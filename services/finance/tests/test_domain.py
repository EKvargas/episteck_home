from __future__ import annotations

import dataclasses
import typing
from datetime import datetime, timezone

import pytest

from app import domain


def _account(**over):
    base = dict(
        id="acc-1", workspace_id="ws-1", owner_person_ids=("PSN-1",), institution="Sparkasse",
        type=domain.AccountType.CURRENT, currency="EUR", liquidity=domain.Liquidity.AVAILABLE,
        balance_authority=domain.BalanceAuthority.PROVIDER,
        movement_authority=domain.Provider.ENABLE_BANKING,
        preferred_balance_kind=domain.BalanceKind.BOOKED, freshness_sla_hours=36,
        connection_id="conn-1", provider_account_ref="ref-1",
    )
    base.update(over)
    return domain.Account(**base)


def test_account_requires_at_least_one_owner():
    with pytest.raises(ValueError):
        _account(owner_person_ids=())


def test_account_is_frozen():
    account = _account()
    with pytest.raises(dataclasses.FrozenInstanceError):
        account.currency = "USD"  # type: ignore[misc]


def test_enum_values_match_the_proposal_vocabulary():
    assert {e.value for e in domain.Liquidity} == {"AVAILABLE", "INVESTED", "RESTRICTED"}
    assert {e.value for e in domain.MovementStatus} == {"PENDING", "BOOKED"}
    assert {e.value for e in domain.ConnectionStatus} == {
        "OK", "REAUTH_DUE", "REAUTH_REQUIRED", "FAILING", "PAUSED"}


def test_no_domain_dataclass_has_a_float_field():
    for name in ("Workspace", "Account", "Connection", "BalanceObservation", "Movement"):
        cls = getattr(domain, name)
        for field_name, hint in typing.get_type_hints(cls).items():
            assert float not in typing.get_args(hint) and hint is not float, (name, field_name)


def test_balance_observation_amount_must_be_an_int():
    with pytest.raises(TypeError):
        domain.BalanceObservation(
            id="o1", workspace_id="ws-1", account_id="acc-1", amount_minor=1.5,  # type: ignore[arg-type]
            currency="EUR", kind=domain.BalanceKind.BOOKED,
            as_of=datetime(2026, 10, 9, tzinfo=timezone.utc),
            observed_at=datetime(2026, 10, 10, tzinfo=timezone.utc), source_ref="s")
