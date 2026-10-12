"""Behaviour every connector must share. Subclass as ``Test<Name>Contract`` and implement
``make(scenario)`` returning ``(connector, account_ref)``.

Scenarios: ok | auth | rate_limited | unavailable | malformed.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from app import domain
from app.connectors.base import ConnectorError, ErrorKind, RawBalance, RawMovement


class ConnectorContract:
    def make(self, scenario: str):  # pragma: no cover - interface
        raise NotImplementedError

    def test_balances_are_int_minor_units_with_aware_dates(self):
        connector, ref = self.make("ok")
        balances = connector.fetch_balances(ref)
        assert balances and all(isinstance(b, RawBalance) for b in balances)
        for b in balances:
            assert type(b.amount_minor) is int
            assert len(b.currency) == 3 and b.currency.isupper()
            assert isinstance(b.kind, domain.BalanceKind)
            assert isinstance(b.as_of, datetime) and b.as_of.tzinfo is not None

    def test_movements_have_int_amounts_and_a_status(self):
        connector, ref = self.make("ok")
        movements = connector.fetch_movements(ref, None)
        assert movements and all(isinstance(m, RawMovement) for m in movements)
        for m in movements:
            assert type(m.amount_minor) is int
            assert isinstance(m.status, domain.MovementStatus)
            assert m.booking_date is None or isinstance(m.booking_date, date)

    @pytest.mark.parametrize("scenario,kind", [
        ("auth", ErrorKind.AUTH_REQUIRED),
        ("rate_limited", ErrorKind.RATE_LIMITED),
        ("unavailable", ErrorKind.UNAVAILABLE),
        ("malformed", ErrorKind.MALFORMED),
    ])
    def test_failures_map_to_a_typed_error_for_balances_and_movements(self, scenario, kind):
        for call in ("balances", "movements"):
            connector, ref = self.make(scenario)
            with pytest.raises(ConnectorError) as raised:
                if call == "balances":
                    connector.fetch_balances(ref)
                else:
                    connector.fetch_movements(ref, None)
            assert raised.value.kind is kind

    def test_errors_never_carry_secrets_or_raw_payloads(self):
        connector, ref = self.make("auth")
        with pytest.raises(ConnectorError) as raised:
            connector.fetch_balances(ref)
        text = f"{raised.value!s} {raised.value!r}"
        assert "pass" not in text.lower() and "secret" not in text.lower()
