"""Overview read model: pure, no I/O.

Rules (proposal §6.8):
* one balance authority per account; a total is the latest observation of that
  authority, never a sum of movements;
* a stale or unauthorised-for-now account keeps its last figure and date, and an account
  with no observation is listed as NO_DATA, never as zero;
* currencies are never summed together; subtotals are keyed by (currency, liquidity);
* a EUR valuation exists only when requested, is dated, and never includes VES.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from . import domain
from .money import exponent, format_minor

REAUTH_WARNING = timedelta(days=7)
RATES_STALE_AFTER_DAYS = 5
NEVER_VALUED = frozenset({"VES"})
VALUATION_BASIS = "ECB euro reference rates (informational, not a transaction rate)"

FRESH, STALE = "FRESH", "STALE"
REAUTH_DUE, REAUTH_REQUIRED, NO_DATA = "REAUTH_DUE", "REAUTH_REQUIRED", "NO_DATA"
_TAINTED = {STALE, REAUTH_REQUIRED}


@dataclass(frozen=True)
class FxRates:
    """ECB reference rates: units of foreign currency per 1 EUR, as of ``date``."""

    date: date
    per_eur: Mapping[str, Decimal]


def observation_kind(account: domain.Account) -> domain.BalanceKind | None:
    """Which stored observation kind is this account's balance? None: not derivable in I1."""
    authority = account.balance_authority
    if authority is domain.BalanceAuthority.PROVIDER:
        return account.preferred_balance_kind
    if authority is domain.BalanceAuthority.EVIDENCE_SNAPSHOT:
        return domain.BalanceKind.VALUATION
    return None  # LEDGER-derived balances arrive with the ledger (not I1)


def _status(account: domain.Account, obs: domain.BalanceObservation | None,
            conn: domain.Connection | None, now: datetime) -> str:
    if obs is None or observation_kind(account) is None:
        return NO_DATA
    if conn is not None:
        expired = conn.consent_expires_at is not None and conn.consent_expires_at <= now
        if conn.status is domain.ConnectionStatus.REAUTH_REQUIRED or expired:
            return REAUTH_REQUIRED
        soon = (conn.consent_expires_at is not None
                and conn.consent_expires_at - now <= REAUTH_WARNING)
        if conn.status is domain.ConnectionStatus.REAUTH_DUE or soon:
            return REAUTH_DUE
    if now - obs.as_of > timedelta(hours=account.freshness_sla_hours):
        return STALE
    return FRESH


def _valuation(rows: Sequence[dict], rates: FxRates | None, now: datetime) -> dict:
    total = Decimal(0)
    unvalued: set[str] = set()
    for row in rows:
        if row["amount_minor"] is None:
            continue
        currency = row["currency"]
        units = Decimal(row["amount_minor"]) / (Decimal(10) ** exponent(currency))
        if currency == "EUR":
            total += units
        elif currency in NEVER_VALUED or rates is None or currency not in rates.per_eur:
            unvalued.add(currency)
        else:
            total += units / rates.per_eur[currency]
    minor = int((total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)) * 100)
    return {
        "currency": "EUR",
        "amount_minor": minor,
        "amount": format_minor(minor, "EUR"),
        "rate_date": rates.date.isoformat() if rates else None,
        "stale_rates": bool(rates and (now.date() - rates.date).days > RATES_STALE_AFTER_DAYS),
        "basis": VALUATION_BASIS,
        "unvalued": sorted(unvalued),
    }


def compute_overview(
    accounts: Sequence[domain.Account],
    observations: Mapping[str, domain.BalanceObservation | None],
    connections: Mapping[str, domain.Connection],
    now: datetime,
    rates: FxRates | None = None,
    valuation_currency: str | None = None,
) -> dict:
    if valuation_currency not in (None, "EUR"):
        raise ValueError("only EUR valuation is supported")
    rows: list[dict] = []
    groups: dict[tuple[str, str], dict] = {}
    for account in accounts:
        obs = observations.get(account.id)
        conn = connections.get(account.connection_id or "")
        status = _status(account, obs, conn, now)
        has_figure = status != NO_DATA
        row = {
            "id": account.id,
            "institution": account.institution,
            "type": account.type.value,
            "currency": account.currency,
            "liquidity": account.liquidity.value,
            "amount_minor": obs.amount_minor if has_figure else None,
            "amount": format_minor(obs.amount_minor, account.currency) if has_figure else None,
            "as_of": obs.as_of.isoformat() if has_figure else None,
            "observed_at": obs.observed_at.isoformat() if has_figure else None,
            "source": conn.provider.value if conn else account.balance_authority.value,
            "status": status,
            "stale": status in _TAINTED,
        }
        rows.append(row)
        if not has_figure:
            continue
        group = groups.setdefault(
            (account.currency, account.liquidity.value),
            {"currency": account.currency, "liquidity": account.liquidity.value,
             "amount_minor": 0, "account_count": 0, "includes_stale": False})
        group["amount_minor"] += obs.amount_minor
        group["account_count"] += 1
        group["includes_stale"] = group["includes_stale"] or row["stale"]
    subtotals = []
    for key in sorted(groups):
        group = groups[key]
        group["amount"] = format_minor(group["amount_minor"], group["currency"])
        subtotals.append(group)
    return {
        "as_of": now.isoformat(),
        "accounts": rows,
        "subtotals": subtotals,
        "valuation": _valuation(rows, rates, now) if valuation_currency else None,
    }
