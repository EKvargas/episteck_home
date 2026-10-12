from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app import domain
from tests.support import make_account, make_repo, seed_connection, seed_workspace


@pytest.fixture
def repo(tmp_path):
    r = make_repo(tmp_path)
    seed_workspace(r)
    return r


def test_fx_rates_round_trip_as_exact_decimals(repo):
    repo.store_fx_rates(date(2026, 10, 9), {"USD": Decimal("1.0834"), "CHF": Decimal("0.9512")})
    rates = repo.latest_fx_rates()
    assert rates.date == date(2026, 10, 9)
    assert rates.per_eur["USD"] == Decimal("1.0834")


def test_storing_the_same_rate_twice_is_a_no_op_and_a_different_rate_is_an_error(repo):
    repo.store_fx_rates(date(2026, 10, 9), {"USD": Decimal("1.08")})
    repo.store_fx_rates(date(2026, 10, 9), {"USD": Decimal("1.08")})
    with pytest.raises(ValueError):
        repo.store_fx_rates(date(2026, 10, 9), {"USD": Decimal("1.09")})


def test_latest_rates_pick_the_newest_date_and_none_when_empty(repo):
    assert repo.latest_fx_rates() is None
    repo.store_fx_rates(date(2026, 10, 8), {"USD": Decimal("1.07")})
    repo.store_fx_rates(date(2026, 10, 9), {"USD": Decimal("1.08")})
    assert repo.latest_fx_rates().date == date(2026, 10, 9)


def test_workspace_scope_exposes_only_status_and_distinct_owner_ids(repo):
    seed_connection(repo)
    repo.add_account(make_account(aid="a1", owner_person_ids=("PSN-2", "PSN-1")))
    repo.add_account(make_account(aid="a2", owner_person_ids=("PSN-1",), provider_account_ref="r2"))
    scope = repo.workspace_scope("ws-1")
    assert scope.status is domain.WorkspaceStatus.ACTIVE
    assert scope.owner_person_ids == ("PSN-1", "PSN-2")
    assert repo.workspace_scope("nope") is None


def test_list_connections_is_workspace_scoped(repo):
    seed_connection(repo)
    seed_workspace(repo, ws="ws-2", owner="PSN-2")
    assert [c.id for c in repo.list_connections("ws-1")] == ["conn-1"]
    assert repo.list_connections("ws-2") == []
