from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app import domain
from app.overview import FxRates, compute_overview, observation_kind
from tests.support import make_account, make_balance

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
FRESH = NOW - timedelta(hours=2)


def _conn(status=domain.ConnectionStatus.OK, consent=None, provider=domain.Provider.SIMPLEFIN):
    return domain.Connection("conn-1", "ws-1", provider, "PSN-1", status, consent)


def _run(accounts, obs, conn=None, rates=None, valuation=None):
    observations = {o.account_id: o for o in obs}
    return compute_overview(
        accounts, {a.id: observations.get(a.id) for a in accounts},
        {"conn-1": conn or _conn()}, NOW, rates, valuation)


def _subtotal(result, currency, liquidity):
    return next(s for s in result["subtotals"]
                if s["currency"] == currency and s["liquidity"] == liquidity)


def _walk(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _walk(v)
    else:
        yield value


def test_subtotals_are_per_currency_and_liquidity_never_mixed():
    accounts = [
        make_account(aid="a1", currency="EUR"),
        make_account(aid="a2", currency="EUR"),
        make_account(aid="a3", currency="USD"),
        make_account(aid="a4", currency="EUR", liquidity=domain.Liquidity.INVESTED),
    ]
    obs = [make_balance("o1", aid="a1", amount=10000, as_of=FRESH),
           make_balance("o2", aid="a2", amount=2550, as_of=FRESH),
           make_balance("o3", aid="a3", amount=7000, currency="USD", as_of=FRESH),
           make_balance("o4", aid="a4", amount=900, as_of=FRESH)]
    result = _run(accounts, obs)
    assert _subtotal(result, "EUR", "AVAILABLE")["amount_minor"] == 12550
    assert _subtotal(result, "EUR", "AVAILABLE")["amount"] == "125.50"
    assert _subtotal(result, "USD", "AVAILABLE")["amount_minor"] == 7000
    assert _subtotal(result, "EUR", "INVESTED")["amount_minor"] == 900
    assert len(result["subtotals"]) == 3
    assert "total" not in result  # no cross-currency grand total anywhere


def test_each_account_row_states_institution_source_and_dates():
    result = _run([make_account()], [make_balance(as_of=FRESH, observed_at=NOW)])
    row = result["accounts"][0]
    assert row["institution"] == "Bank"
    assert row["source"] == "SIMPLEFIN"
    assert row["as_of"] == FRESH.isoformat()
    assert row["observed_at"] == NOW.isoformat()
    assert row["status"] == "FRESH"


def test_stale_account_keeps_its_last_amount_and_date_and_taints_the_subtotal():
    old = NOW - timedelta(days=2)
    result = _run([make_account()], [make_balance(amount=4200, as_of=old)])
    row = result["accounts"][0]
    assert row["status"] == "STALE"
    assert row["amount_minor"] == 4200
    assert row["as_of"] == old.isoformat()
    assert _subtotal(result, "EUR", "AVAILABLE")["includes_stale"] is True


def test_account_without_any_observation_is_listed_and_never_shown_as_zero():
    result = _run([make_account(aid="a1"), make_account(aid="a2")],
                  [make_balance(aid="a1", amount=100, as_of=FRESH)])
    nodata = next(r for r in result["accounts"] if r["id"] == "a2")
    assert nodata["status"] == "NO_DATA"
    assert nodata["amount_minor"] is None and nodata["amount"] is None
    assert _subtotal(result, "EUR", "AVAILABLE")["account_count"] == 1
    assert _subtotal(result, "EUR", "AVAILABLE")["amount_minor"] == 100


def test_account_with_no_data_at_all_produces_no_subtotal_row():
    result = _run([make_account()], [])
    assert result["subtotals"] == []


def test_consent_expiring_within_seven_days_is_reauth_due():
    conn = _conn(consent=NOW + timedelta(days=3))
    result = _run([make_account()], [make_balance(as_of=FRESH)], conn)
    assert result["accounts"][0]["status"] == "REAUTH_DUE"


def test_expired_consent_or_reauth_required_connection_needs_reauthorization():
    for conn in (_conn(consent=NOW - timedelta(hours=1)),
                 _conn(status=domain.ConnectionStatus.REAUTH_REQUIRED)):
        result = _run([make_account()], [make_balance(amount=777, as_of=FRESH)], conn)
        row = result["accounts"][0]
        assert row["status"] == "REAUTH_REQUIRED"
        assert row["amount_minor"] == 777  # the last known figure is still shown


def test_distant_consent_expiry_stays_fresh():
    conn = _conn(consent=NOW + timedelta(days=60))
    assert _run([make_account()], [make_balance(as_of=FRESH)], conn)["accounts"][0]["status"] == "FRESH"


def test_preferred_kind_is_booked_unless_the_account_says_otherwise():
    assert observation_kind(make_account()) is domain.BalanceKind.BOOKED
    avail = make_account(preferred_balance_kind=domain.BalanceKind.AVAILABLE)
    assert observation_kind(avail) is domain.BalanceKind.AVAILABLE


def test_authority_selects_the_observation_kind_and_never_movements():
    snap = make_account(balance_authority=domain.BalanceAuthority.EVIDENCE_SNAPSHOT)
    ledger = make_account(balance_authority=domain.BalanceAuthority.LEDGER)
    assert observation_kind(snap) is domain.BalanceKind.VALUATION
    assert observation_kind(ledger) is None  # ledger-derived balances are not in I1


def test_ledger_authority_account_is_no_data_even_with_a_provider_observation():
    ledger = make_account(balance_authority=domain.BalanceAuthority.LEDGER)
    result = _run([ledger], [make_balance(amount=999, as_of=FRESH)])
    assert result["accounts"][0]["status"] == "NO_DATA"


# --- valuation (A12) ---------------------------------------------------------------
RATES = FxRates(date(2026, 10, 9), {"USD": Decimal("1.08"), "CHF": Decimal("0.95")})


def test_no_valuation_unless_requested():
    assert _run([make_account()], [make_balance(as_of=FRESH)], rates=RATES)["valuation"] is None


def test_valuation_is_explicit_dated_and_converts_with_ecb_rates():
    accounts = [make_account(aid="a1"), make_account(aid="a2", currency="USD")]
    obs = [make_balance("o1", aid="a1", amount=10000, as_of=FRESH),
           make_balance("o2", aid="a2", amount=10800, currency="USD", as_of=FRESH)]
    val = _run(accounts, obs, rates=RATES, valuation="EUR")["valuation"]
    assert val["currency"] == "EUR"
    assert val["amount_minor"] == 20000 and val["amount"] == "200.00"
    assert val["rate_date"] == "2026-10-09"
    assert "informational" in val["basis"].lower()
    assert val["unvalued"] == []


def test_ves_is_never_valued_even_if_a_rate_exists():
    rates = FxRates(date(2026, 10, 9), {"USD": Decimal("1.08"), "VES": Decimal("40")})
    accounts = [make_account(aid="a1", currency="VES")]
    val = _run(accounts, [make_balance(aid="a1", amount=500000, currency="VES", as_of=FRESH)],
               rates=rates, valuation="EUR")["valuation"]
    assert val["unvalued"] == ["VES"]
    assert val["amount_minor"] == 0


def test_currency_without_a_rate_is_unvalued_not_guessed():
    accounts = [make_account(aid="a1", currency="GBP")]
    val = _run(accounts, [make_balance(aid="a1", currency="GBP", as_of=FRESH)],
               rates=RATES, valuation="EUR")["valuation"]
    assert val["unvalued"] == ["GBP"]


def test_rounding_is_half_even_to_the_minor_unit_at_the_end_only():
    accounts = [make_account(aid="a1", currency="USD")]
    rates = FxRates(date(2026, 10, 9), {"USD": Decimal("3")})
    val = _run(accounts, [make_balance(aid="a1", amount=100, currency="USD", as_of=FRESH)],
               rates=rates, valuation="EUR")["valuation"]
    assert val["amount_minor"] == 33


def test_old_rates_are_flagged():
    rates = FxRates(date(2026, 10, 1), {"USD": Decimal("1.08")})
    val = _run([make_account()], [make_balance(as_of=FRESH)], rates=rates, valuation="EUR")["valuation"]
    assert val["stale_rates"] is True
    assert _run([make_account()], [make_balance(as_of=FRESH)], rates=RATES,
                valuation="EUR")["valuation"]["stale_rates"] is False


def test_missing_rates_are_reported_instead_of_an_invented_total():
    accounts = [make_account(aid="a1", currency="USD")]
    val = _run(accounts, [make_balance(aid="a1", currency="USD", as_of=FRESH)],
               rates=None, valuation="EUR")["valuation"]
    assert val["unvalued"] == ["USD"] and val["rate_date"] is None


def test_only_eur_valuation_is_supported():
    with pytest.raises(ValueError):
        _run([make_account()], [make_balance(as_of=FRESH)], rates=RATES, valuation="USD")


def test_output_never_contains_a_float():
    accounts = [make_account(aid="a1", currency="USD")]
    result = _run(accounts, [make_balance(aid="a1", currency="USD", as_of=FRESH)],
                  rates=RATES, valuation="EUR")
    assert not any(isinstance(v, float) for v in _walk(result))
