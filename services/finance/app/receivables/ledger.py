"""Record an exchange and read the receivables view. Money is ``int`` minor units."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from ..money import format_minor
from ..store.receivables_repo import MAX_LINE_POSITION, ReceivablesRepository
from .model import (
    CASH_ABROAD, OWNER, CounterpartyKind, EntryKind, Exchange, ExchangeLine, LedgerEntry,
    Opening,
)

DEBT_CURRENCIES = ("USD", "EUR")


@dataclass(frozen=True)
class LineInput:
    payer_id: str
    usd_minor: int
    debt_currency: str | None = None
    beneficiary_note: str | None = None
    eur_override_minor: int | None = None


@dataclass(frozen=True)
class Evidence:
    """``ves_reference_hash`` is the keyed hash of the reference when the caller already
    hashed it (a proposal stores only the hash, §6.9); it wins over ``ves_reference``."""

    ves_amount_minor: int | None
    ves_reference: str | None
    delivered_on: date | None
    ves_reference_hash: str | None = None


class ValidationError(Exception):
    def __init__(self, field: str, detail: dict[str, str] | None = None) -> None:
        super().__init__(field)
        self.field = field
        self.detail = detail or {}


def _id() -> str:
    return uuid.uuid4().hex


def _usd(minor: int) -> str:
    return format_minor(minor, "USD")


def validate_lines(repo: ReceivablesRepository, conn, ws: str,
                   lines: Sequence[LineInput]) -> list[tuple[LineInput, str]]:
    """Resolves each line's debt currency and rejects inconsistent EUR overrides (R17).

    Reused by every writer of lines. An override is a positive EUR figure on a PERSON line
    whose debt is EUR: it is refused on OWNER/FUND lines, with an explicit USD debt, or when
    not positive. With an override and no explicit debt currency the debt is EUR. An explicit
    EUR debt on a FUND line is refused rather than coerced.
    """
    resolved: list[tuple[LineInput, str]] = []
    for ln in lines:
        ov = ln.eur_override_minor
        bad = {"override": format_minor(ov, "EUR"), "usd": _usd(ln.usd_minor)} if ov is not None else {}
        if ln.payer_id == OWNER:
            if ov is not None:
                raise ValidationError("eur_override", bad)
            # Not a debt: stored in USD (the column is NOT NULL) and never charged.
            resolved.append((ln, "USD"))
            continue
        payer = repo.get_counterparty(conn, ws, ln.payer_id)
        if (payer is None or payer.status != "ACTIVE"
                or payer.kind not in (CounterpartyKind.PERSON, CounterpartyKind.FUND)):
            raise ValidationError("payer")
        if payer.kind is CounterpartyKind.FUND:
            if ln.debt_currency not in (None, "USD"):
                raise ValidationError("debt_currency")
            if ov is not None:
                raise ValidationError("eur_override", bad)
            cur = "USD"
        else:
            if ov is not None and (ov <= 0 or ln.debt_currency == "USD"):
                raise ValidationError("eur_override", bad)
            cur = ln.debt_currency or ("EUR" if ov is not None
                                       else payer.pay_currency or "USD")
        if cur not in DEBT_CURRENCIES:
            raise ValidationError("debt_currency")
        resolved.append((ln, cur))
    return resolved


def record_exchange(repo: ReceivablesRepository, conn, ws: str, *, partner_id: str,
                    total_usd_minor: int, lines: Sequence[LineInput],
                    evidence: Evidence | None, now: datetime) -> Exchange:
    partner = repo.get_counterparty(conn, ws, partner_id)
    if partner is None or partner.kind is not CounterpartyKind.EXCHANGE_PARTNER:
        raise ValidationError("partner")
    if total_usd_minor <= 0 or any(ln.usd_minor <= 0 for ln in lines):
        raise ValidationError("usd")
    if len(lines) > MAX_LINE_POSITION + 1:
        raise ValidationError("lines", {"max": str(MAX_LINE_POSITION + 1)})

    resolved = validate_lines(repo, conn, ws, lines)

    total_lines = sum(ln.usd_minor for ln in lines)
    if total_lines != total_usd_minor:
        raise ValidationError("lines_total", {"total": _usd(total_usd_minor),
                                              "sum": _usd(total_lines)})

    ev = evidence or Evidence(None, None, None)
    delivered = ev.delivered_on or now.date()
    ves_hash = ev.ves_reference_hash or (repo.hash_key(ev.ves_reference) if ev.ves_reference
                                         else None)
    ex = Exchange(
        _id(), ws, repo.next_number(conn, ws, "C"), partner_id, total_usd_minor, delivered, now,
        ev.ves_amount_minor, ves_hash)
    ex_lines = new_lines(ex.id, 1, resolved)
    repo.insert_exchange(conn, ex, ex_lines)
    from .receipts import consume_credits  # lazy: receipts imports ValidationError from here

    for payer, cur in charge_usd_lines(repo, conn, ws, ex_lines, delivered):
        consume_credits(repo, conn, ws, payer, cur)  # what they paid ahead pays it (R30)
    return ex


def new_lines(exchange_id: str, version: int,
              resolved: Sequence[tuple[LineInput, str]]) -> list[ExchangeLine]:
    """One version of an exchange's lines from ``validate_lines`` output, in input order."""
    return [ExchangeLine(_id(), exchange_id, version, pos, ln.payer_id, ln.usd_minor, cur,
                         ln.beneficiary_note, ln.eur_override_minor)
            for pos, (ln, cur) in enumerate(resolved)]


def charge_usd_lines(repo: ReceivablesRepository, conn, ws: str, lines: Sequence[ExchangeLine],
                     day: date) -> list[tuple[str, str]]:
    """A USD CHARGE per USD line (PERSON or FUND), never for OWNER (R15). EUR lines are
    charged only once the exchange is funded. Returns the (payer, "USD") pairs charged."""
    charged: list[tuple[str, str]] = []
    for el in lines:
        if el.payer_id == OWNER or el.debt_currency != "USD":
            continue
        # source_ref = line id: open_lines joins CHARGEs to lines on it.
        repo.insert_entry(conn, LedgerEntry(
            _id(), ws, repo.next_number(conn, ws, "E"), el.payer_id, "USD", el.usd_minor,
            EntryKind.CHARGE, day, el.id))
        charged.append((el.payer_id, "USD"))
    return list(dict.fromkeys(charged))


def reverse_entry(repo: ReceivablesRepository, conn, ws: str, entry: LedgerEntry, reason: str,
                  now: datetime) -> LedgerEntry:
    """Writes the ``REVERSAL`` that undoes one effective entry (same party, currency and
    source; the negated amount). The repository refuses a double undo."""
    rev = LedgerEntry(_id(), ws, repo.next_number(conn, ws, "E"), entry.counterparty_id,
                      entry.currency, -entry.amount_minor, EntryKind.REVERSAL, now.date(),
                      entry.source_ref, reason, reverses_id=entry.id)
    repo.insert_entry(conn, rev)
    return rev


def _where(accounts: dict[str, str], settles_to: str | None) -> str | None:
    if settles_to is None:
        return None
    if settles_to == CASH_ABROAD:
        return CASH_ABROAD
    return accounts.get(settles_to)


def receivables_view(repo: ReceivablesRepository, conn, ws: str, now: datetime) -> dict:
    from .receipts import held_cash_shown  # lazy: receipts imports ValidationError from here

    accounts = {r["id"]: r["institution"] for r in conn.execute(
        "SELECT id, institution FROM account WHERE workspace_id=?", (ws,))}
    cps = {c.id: c for c in repo.list_counterparties(conn, ws)}
    order = {cid: i for i, cid in enumerate(cps)}
    balances = repo.balances(conn, ws)

    owed: list[dict] = []
    held: list[dict] = []
    owed_sub: dict[str, int] = {}
    held_sub: dict[str, int] = {}

    for (cp_id, cur), bal in sorted(balances.items(),
                                    key=lambda kv: (order.get(kv[0][0], len(order)), kv[0][1])):
        cp = cps.get(cp_id)
        if cp is None or cp.kind is not CounterpartyKind.PERSON or bal == 0:
            continue
        opening = cp.opening.value if cp.opening else None
        if bal > 0:
            lines = []
            openings = {e.id: e for e in repo.effective_entries_for_refs(
                conn, ws, [cp_id], (EntryKind.OPENING,))}
            for ol in repo.open_lines(conn, ws, cp_id, cur):
                if ol.is_opening:  # the opening is an open item with no exchange (R29)
                    op = openings.get(ol.line_id)
                    if op is not None:
                        lines.append({
                            "exchange_ref": None, "entry_ref": f"E{op.number}",
                            "delivered_on": op.effective_on.isoformat(), "usd": None,
                            "debt": format_minor(op.amount_minor, cur),
                            "outstanding": format_minor(ol.outstanding_minor, cur),
                            "currency": cur})
                    continue
                found = repo.line_with_exchange(conn, ws, ol.line_id)
                if found is None:
                    continue
                el, ex = found
                lines.append({
                    "exchange_ref": f"C{ex.number}", "entry_ref": None,
                    "delivered_on": ex.delivered_on.isoformat(), "usd": _usd(el.usd_minor),
                    "debt": format_minor(repo.line_charged(conn, ws, ol.line_id), cur),
                    "outstanding": format_minor(ol.outstanding_minor, cur), "currency": cur})
            shown = held_cash_shown(repo, conn, ws, cp_id, cur)
            owed.append({
                "counterparty": cp.label, "currency": cur, "amount": format_minor(bal, cur),
                "where": _where(accounts, cp.settles_to),
                "held_cash": None if shown is None else format_minor(shown, cur),
                "opening": opening, "lines": lines})
            owed_sub[cur] = owed_sub.get(cur, 0) + bal
        else:
            held.append({
                "counterparty": cp.label, "kind": "PREPAYMENT", "currency": cur,
                "amount": format_minor(-bal, cur), "opening": opening, "since": None,
                "out_since": None, "in_since": None,
                "account": _where(accounts, cp.settles_to)})
            held_sub[cur] = held_sub.get(cur, 0) - bal

    # Every fund row with a balance or flows, whatever its status; an ACTIVE fund always
    # shows its USD row. A negative amount means the owner is advancing the fund (R18).
    for cp in cps.values():
        if cp.kind is not CounterpartyKind.FUND:
            continue
        currencies = {cur for (cid, cur) in balances if cid == cp.id}
        if cp.status == "ACTIVE":
            currencies.add("USD")
        for cur in sorted(currencies):
            bal = balances.get((cp.id, cur), 0)
            out, inn, since = repo.flows_since_creation(conn, ws, cp.id, cur)
            if not (bal or out or inn or (cp.status == "ACTIVE" and cur == "USD")):
                continue
            unknown = cp.opening in (None, Opening.UNKNOWN)
            held.append({
                "counterparty": cp.label, "kind": "FUND", "currency": cur,
                "amount": None if unknown else format_minor(-bal, cur),
                "opening": (cp.opening or Opening.UNKNOWN).value,
                "since": since.isoformat() if since else None,
                "out_since": format_minor(out, cur) if unknown else None,
                "in_since": format_minor(inn, cur) if unknown else None,
                "account": _where(accounts, cp.settles_to)})
            if not unknown and bal < 0:
                held_sub[cur] = held_sub.get(cur, 0) - bal

    to_fix: list[dict] = []
    partner_ex: list[dict] = []
    partner_total = 0
    for ex in repo.open_exchanges(conn, ws):
        current = repo.current_lines(conn, ex.id)
        ex_total = sum(el.usd_minor for el in current)  # corrections add line versions
        partner_total += ex_total
        partner_ex.append({"exchange_ref": f"C{ex.number}",
                           "delivered_on": ex.delivered_on.isoformat(),
                           "usd": _usd(ex_total)})
        for el in current:
            payer = cps.get(el.payer_id)
            if el.debt_currency == "EUR" and payer is not None:
                to_fix.append({"counterparty": payer.label, "exchange_ref": f"C{ex.number}",
                               "usd": _usd(el.usd_minor)})

    return {
        "as_of": now.date().isoformat(),
        "owed_to_you": owed,
        "to_fix": to_fix,
        "held_for_others": held,
        "owed_to_partner": {"currency": "USD", "amount": _usd(partner_total),
                            "exchanges": partner_ex},
        "subtotals": {
            "owed_to_you": {c: format_minor(v, c) for c, v in sorted(owed_sub.items())},
            "held_for_others": {c: format_minor(v, c) for c, v in sorted(held_sub.items())}},
        "interventions_this_month": repo.interventions_in_month(conn, ws, now.year, now.month),
    }
