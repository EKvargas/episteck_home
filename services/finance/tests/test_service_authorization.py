"""A6: no authorization means deny, one Home call, no data read. Plus visibility rules."""
from __future__ import annotations

import inspect
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app import domain
from app.authz import SELF
from app.service import (
    AccessDenied, FeatureOff, FinanceService, PolicyUnavailable, SessionInvalid,
)
from tests.support import (
    FakeAuthorizer, SpyRepo, make_account, make_balance, make_repo, seed_connection,
    seed_workspace,
)

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
FRESH = NOW - timedelta(hours=2)
# Everything that carries financial data. The single metadata read allowed before
# authorization (workspace_scope) returns only owner ids and a status.
DATA_READS = {"list_accounts", "latest_balance", "current_movements", "list_connections",
              "latest_fx_rates", "is_member"}


@pytest.fixture
def repo(tmp_path):
    r = make_repo(tmp_path)
    seed_workspace(r)
    seed_connection(r)
    r.add_account(make_account(aid="acc-1"))
    r.record_balance(make_balance("o1", aid="acc-1", amount=123456, as_of=FRESH, observed_at=FRESH))
    return r


def _svc(repo, authorizer=None, workspace="ws-1"):
    spy = SpyRepo(repo)
    authz = authorizer or FakeAuthorizer()
    return FinanceService(spy, authz, workspace, clock=lambda: NOW), spy, authz


def test_no_delegation_is_refused_without_calling_home_or_the_repository(repo):
    svc, spy, authz = _svc(repo)
    with pytest.raises(SessionInvalid):
        svc.overview(None)
    assert authz.calls == [] and spy.calls == []


@pytest.mark.parametrize("mode,error", [
    ("session_invalid", SessionInvalid),
    ("unavailable", PolicyUnavailable),
    ("malformed", PolicyUnavailable),
    ("raise", PolicyUnavailable),
])
def test_every_non_answer_is_refused_with_one_home_call_and_no_data_read(repo, mode, error):
    svc, spy, authz = _svc(repo, FakeAuthorizer(mode=mode))
    with pytest.raises(error):
        svc.overview("deleg")
    assert len(authz.calls) == 1
    assert not set(spy.calls) & DATA_READS


def test_denied_self_view_is_refused_and_reads_nothing(repo):
    svc, spy, authz = _svc(repo, FakeAuthorizer(allow={"SELF": False}))
    with pytest.raises(AccessDenied):
        svc.overview("deleg")
    assert len(authz.calls) == 1
    assert not set(spy.calls) & DATA_READS


def test_requirements_are_self_plus_every_distinct_owner_all_finance_view(repo):
    repo.add_account(make_account(aid="acc-2", owner_person_ids=("PSN-1", "PSN-2"),
                                  provider_account_ref="r2"))
    svc, _, authz = _svc(repo)
    svc.overview("deleg-token")
    delegation, reqs = authz.calls[0]
    assert delegation == "deleg-token"
    assert [r.subject for r in reqs] == [SELF, "PSN-1", "PSN-2"]
    assert {(r.domain, r.action) for r in reqs} == {("FINANCE", "VIEW")}


def test_more_owners_than_a_batch_can_carry_fails_closed_before_calling_home(repo):
    for i in range(2, 10):
        repo.add_account(make_account(aid=f"x{i}", owner_person_ids=(f"PSN-{i}",),
                                      provider_account_ref=f"r{i}"))
    svc, spy, authz = _svc(repo)
    with pytest.raises(PolicyUnavailable):
        svc.overview("deleg")
    assert authz.calls == []
    assert not set(spy.calls) & DATA_READS


def test_actor_who_is_not_a_workspace_member_is_denied_even_if_home_allows(repo):
    svc, spy, _ = _svc(repo, FakeAuthorizer(actor="PSN-77"))
    with pytest.raises(AccessDenied):
        svc.overview("deleg")
    assert not set(spy.calls) & (DATA_READS - {"is_member"})


def test_joint_account_is_hidden_unless_every_owner_is_allowed(repo):
    repo.add_account(make_account(aid="acc-2", owner_person_ids=("PSN-1", "PSN-2"),
                                  provider_account_ref="r2"))
    repo.record_balance(make_balance("o2", aid="acc-2", amount=50000, as_of=FRESH))
    svc, _, _ = _svc(repo, FakeAuthorizer(allow={"SELF": True, "PSN-1": True, "PSN-2": False}))
    result = svc.overview("deleg")
    assert [a["id"] for a in result["accounts"]] == ["acc-1"]
    assert result["hidden_accounts"] == 1
    assert result["subtotals"][0]["amount_minor"] == 123456
    assert "PSN-2" not in repr(result) and "acc-2" not in repr(result)


def test_joint_account_is_visible_when_every_owner_is_allowed(repo):
    repo.add_account(make_account(aid="acc-2", owner_person_ids=("PSN-1", "PSN-2"),
                                  provider_account_ref="r2"))
    repo.record_balance(make_balance("o2", aid="acc-2", amount=50000, as_of=FRESH))
    svc, _, _ = _svc(repo, FakeAuthorizer(allow={"SELF": True, "PSN-1": True, "PSN-2": True}))
    result = svc.overview("deleg")
    assert result["hidden_accounts"] == 0
    assert result["subtotals"][0]["amount_minor"] == 173456


def test_own_accounts_are_recognised_through_the_actor_id_home_returned(repo):
    # Home allowed SELF only: the actor's own accounts need no separate PSN entry.
    svc, _, _ = _svc(repo, FakeAuthorizer(actor="PSN-1", allow={"SELF": True}))
    assert len(svc.overview("deleg")["accounts"]) == 1


def test_inactive_workspace_is_feature_off_only_after_authorization(repo):
    with repo.connection() as conn:
        conn.execute("UPDATE workspace SET status='PAUSED'")
    svc, spy, _ = _svc(repo)
    with pytest.raises(FeatureOff):
        svc.overview("deleg")
    assert not set(spy.calls) & {"list_accounts", "latest_balance", "latest_fx_rates"}
    denied, _, _ = _svc(repo, FakeAuthorizer(allow={"SELF": False}))
    with pytest.raises(AccessDenied):  # an unauthorised caller learns nothing about status
        denied.overview("deleg")


def test_no_method_accepts_an_actor_workspace_or_sql():
    params = set(inspect.signature(FinanceService.overview).parameters) - {"self"}
    assert params == {"delegation", "valuation_currency"}


def test_two_observation_kinds_of_one_account_count_once_using_the_preferred_kind(repo):
    repo.record_balance(make_balance("o9", aid="acc-1", amount=99999,
                                     kind=domain.BalanceKind.AVAILABLE, as_of=FRESH))
    result = _svc(repo)[0].overview("deleg")
    assert result["subtotals"][0]["amount_minor"] == 123456
    assert result["subtotals"][0]["account_count"] == 1


def test_valuation_uses_stored_ecb_rates_when_requested(repo):
    repo.add_account(make_account(aid="acc-usd", currency="USD", provider_account_ref="u"))
    repo.record_balance(make_balance("ou", aid="acc-usd", amount=10800, currency="USD", as_of=FRESH))
    repo.store_fx_rates(date(2026, 10, 9), {"USD": Decimal("1.08")})
    result = _svc(repo)[0].overview("deleg", valuation_currency="EUR")
    assert result["valuation"]["rate_date"] == "2026-10-09"
    assert result["valuation"]["amount_minor"] == 123456 + 10000


def test_no_valuation_block_unless_requested(repo):
    assert _svc(repo)[0].overview("deleg")["valuation"] is None
