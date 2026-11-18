"""Corrections (spec §6.8): correct an exchange, forgive, record an opening, reverse a fact.

No fact is edited. Undo is a ``REVERSAL`` entry and/or a ``revocation`` row, and whatever
settled a released line goes with it: its allocations (re-made by ``consume_credits``), its
small-difference ADJUSTMENTs (R26), its FORGIVEs (R28: forgive again once re-charged) and
the write-offs of the receipts involved (R27). A PERSON's opening is an open item or a credit
(R29), released the same way (``release_opening``) when it is reversed or replaced.
The caller owns the transaction; every function validates before its first write.
"""
from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import date, datetime

from ..domain import Movement
from ..money import format_minor
from ..store.receivables_repo import MAX_LINE_POSITION, ReceivablesRepository
from .allocation import OpenLine
from .funding import FundingSplit, funding_day, reverse_funding, split_funding, write_eur_charges
from .ledger import (
    DEBT_CURRENCIES, LineInput, ValidationError, charge_usd_lines, new_lines, reverse_entry,
    validate_lines,
)
from .model import (
    OWNER, Counterparty, CounterpartyKind, EntryKind, Exchange, ExchangeLine, Funding,
    LedgerEntry, Opening, PendingItem, PendingKind, ReceiptKind,
)
from .pending import PendingQueue
from .receipts import (
    consume_credits, release_charges, release_opening, reverse_receipt_adjustments,
)

Touched = list[tuple[str, str]]  # (payer id, currency) whose credits are applied again

_FACT_REF = re.compile(r"([CFRE])(\d{1,9})", re.IGNORECASE | re.ASCII)
_EXCHANGE_TARGET = re.compile(r"\s*(C\d{1,9})\s*:\s*(.+?)\s*", re.IGNORECASE | re.ASCII)
_DEBTORS = (CounterpartyKind.PERSON, CounterpartyKind.FUND)


def _id() -> str:
    return uuid.uuid4().hex


def _settle(repo: ReceivablesRepository, conn, ws: str, touched: Touched,
            queue: PendingQueue | None, now: datetime) -> None:
    """The automatic rule again for every payer whose lines or credits changed."""
    for payer, cur in dict.fromkeys(touched):
        consume_credits(repo, conn, ws, payer, cur, queue=queue, now=now)


def _write(repo: ReceivablesRepository, conn, ws: str, cp_id: str, cur: str, amount: int,
           kind: EntryKind, source_ref: str, note: str, now: datetime,
           basis: str | None = None) -> LedgerEntry:
    entry = LedgerEntry(_id(), ws, repo.next_number(conn, ws, "E"), cp_id, cur, amount, kind,
                        now.date(), source_ref, note, basis)
    repo.insert_entry(conn, entry)
    return entry


def _one(repo: ReceivablesRepository, conn, ws: str, label: str, field: str) -> Counterparty:
    found = [cp for cp in repo.find_by_alias(conn, ws, label) if cp.kind in _DEBTORS]
    if len(found) != 1:
        raise ValidationError(field)
    return found[0]


# --- correct an exchange ------------------------------------------------------------
def correct_exchange(repo: ReceivablesRepository, conn, ws: str, exchange_id: str,
                     lines: Sequence[LineInput], total_usd_minor: int | None, reason: str,
                     now: datetime, *, queue: PendingQueue) -> Exchange:
    """Writes version n+1 of the lines with REVERSALs of the old charges and new charges (E11).

    ``total_usd_minor`` ``None`` lets the total follow the new lines; a given total must equal
    their sum. A paid exchange keeps its funding and EUR: shares and EUR charges are recomputed
    for every exchange of that funding (the implied rate changes for all of them). Refused
    below what was already applied to a payer (§6.8 limit) and while a line is forgiven.
    ``queue`` is required (R30): re-applied credits close their small differences with a notice.
    Returns the exchange; its header total stays the registration figure.
    """
    ex = repo.exchange_by_id(conn, ws, exchange_id)
    if ex is None:
        raise ValidationError("exchange")
    if not lines:
        raise ValidationError("lines")
    if len(lines) > MAX_LINE_POSITION + 1:
        raise ValidationError("lines", {"max": str(MAX_LINE_POSITION + 1)})
    if any(ln.usd_minor <= 0 for ln in lines):
        raise ValidationError("usd")
    resolved = validate_lines(repo, conn, ws, lines)
    total = sum(ln.usd_minor for ln in lines)
    if total_usd_minor is not None and total_usd_minor != total:
        raise ValidationError("lines_total", {"total": format_minor(total_usd_minor, "USD"),
                                              "sum": format_minor(total, "USD")})
    old = repo.current_lines(conn, ex.id)
    gifts = repo.effective_entries_for_refs(conn, ws, [ln.id for ln in old], (EntryKind.FORGIVE,))
    if gifts:  # the new lines get new ids: reverse the forgiveness first, then forgive again
        raise ValidationError("forgiven", {"entry": f"E{gifts[0].number}"})
    new = new_lines(ex.id, max(ln.version for ln in old) + 1, resolved)
    funding = repo.live_funding_for_exchange(conn, ex.id)
    split, day = None, None
    if funding is not None:  # exchange_ids are stored in exchange-number order
        funded = [ln for eid in funding.exchange_ids
                  for ln in (new if eid == ex.id else repo.current_lines(conn, eid))]
        split = split_funding(repo, conn, ws, funding.eur_minor, funded)
        day = funding_day(repo, conn, ws, funding)
    _check_collected(repo, conn, ws, old, new, split)

    repo.insert_lines(conn, ws, ex.id, new)
    old_charges = [*repo.effective_charges_for_exchange(conn, ws, ex.id, "USD"),
                   *repo.effective_charges_for_exchange(conn, ws, ex.id, "EUR")]
    touched = release_charges(repo, conn, ws, old_charges, reason, now)
    touched += charge_usd_lines(repo, conn, ws, new, ex.delivered_on)
    if funding is not None:
        touched += _recharge(repo, conn, ws, funding, split, day, reason, now)
    _settle(repo, conn, ws, touched, queue, now)
    return ex


def _check_collected(repo: ReceivablesRepository, conn, ws: str, old: Sequence[ExchangeLine],
                     new: Sequence[ExchangeLine], split: FundingSplit | None) -> None:
    """Per payer and currency: what is applied to the old lines must fit the new debt (an
    unfunded EUR line owes nothing yet; OWNER lines are never a debt, R15)."""
    eur = {ln.id: amount for ln, amount in split.charges} if split else {}
    debt: dict[tuple[str, str], int] = {}
    for ln in new:
        if ln.payer_id != OWNER:
            key = (ln.payer_id, ln.debt_currency)
            debt[key] = debt.get(key, 0) + (
                ln.usd_minor if ln.debt_currency == "USD" else eur.get(ln.id, 0))
    by_id = {ln.id: ln for ln in old}
    applied: dict[tuple[str, str], int] = {}
    for a in repo.live_allocations_for_lines(conn, ws, list(by_id)):
        key = (by_id[a.line_id].payer_id, by_id[a.line_id].debt_currency)
        applied[key] = applied.get(key, 0) + a.amount_minor
    for (payer, cur), got in applied.items():
        owed = debt.get((payer, cur), 0)
        if got > owed:
            cp = repo.get_counterparty(conn, ws, payer)
            raise ValidationError("below_collected", {
                "payer": cp.label if cp else payer, "currency": cur,
                "collected": format_minor(got, cur), "new": format_minor(owed, cur)})


def _recharge(repo: ReceivablesRepository, conn, ws: str, funding: Funding, split: FundingSplit,
              day: date, reason: str, now: datetime) -> Touched:
    """New shares and EUR charges for the whole funding. Lines that keep their ids (the other
    exchanges) are released and charged again only when their EUR figure changes."""
    repo.replace_funding_shares(conn, ws, funding.id, split.shares, reason, now)
    target = {ln.id: amount for ln, amount in split.charges}
    current: dict[str, list[LedgerEntry]] = {}
    for eid in funding.exchange_ids:
        for entry in repo.effective_charges_for_exchange(conn, ws, eid, "EUR"):
            current.setdefault(entry.source_ref, []).append(entry)
    stale = [e for line_id, entries in current.items()
             if sum(x.amount_minor for x in entries) != target.get(line_id, 0) for e in entries]
    touched = release_charges(repo, conn, ws, stale, reason, now)
    released = {e.source_ref for e in stale}
    charges = [(ln, amount) for ln, amount in split.charges
               if ln.id not in current or ln.id in released]
    return touched + [(p, "EUR") for p in write_eur_charges(repo, conn, ws, charges, day)]


# --- forgive ------------------------------------------------------------------------
def forgive(repo: ReceivablesRepository, conn, ws: str, target_ref: str,
            amount_minor: int | None, reason: str, now: datetime) -> LedgerEntry:
    """Turns what is owed into a gift: FORGIVE entries (negative) sourced to the open items
    they settle, oldest first (a PERSON's opening first, R29), so open items stay consistent
    with the balance.

    ``target_ref`` is ``C<n>:<payer label>`` (the payer's open lines on that exchange, in the
    one currency still open there) or a counterparty label (its open items in the one currency
    it owes). What can be forgiven is min(Σ outstanding, balance): a FORGIVE never makes a
    balance negative, so it never creates a credit (R30). ``None`` forgives all of it; more is
    refused. Several items give several entries; the first one is returned.
    """
    cp, cur, lines = _forgive_target(repo, conn, ws, target_ref)
    owed = min(sum(ol.outstanding_minor for ol in lines),
               max(0, repo.balance(conn, ws, cp.id, cur)))
    if owed <= 0:
        raise ValidationError("outstanding")
    amount = owed if amount_minor is None else amount_minor
    if not 0 < amount <= owed:
        raise ValidationError("amount", {"outstanding": format_minor(owed, cur),
                                         "amount": format_minor(amount, cur)})
    parts: list[tuple[str, int]] = []
    left = amount
    for ol in lines:  # amount <= Σ outstanding: the items take all of it
        take = min(left, ol.outstanding_minor)
        if take > 0:
            parts.append((ol.line_id, take))
            left -= take
    written = [_write(repo, conn, ws, cp.id, cur, -part, EntryKind.FORGIVE, ref, reason, now)
               for ref, part in parts]
    return written[0]


def _forgive_target(repo: ReceivablesRepository, conn, ws: str,
                    target_ref: str) -> tuple[Counterparty, str, list[OpenLine]]:
    m = _EXCHANGE_TARGET.fullmatch(target_ref)
    if m:
        ex = repo.exchange_by_ref(conn, ws, m[1])
        if ex is None:
            raise ValidationError("exchange")
        cp = _one(repo, conn, ws, m[2], "payer")
        mine = [ln for ln in repo.current_lines(conn, ex.id) if ln.payer_id == cp.id]
        if not mine:
            raise ValidationError("payer")
        ids = {ln.id for ln in mine}
        open_by_cur: dict[str, list[OpenLine]] = {}  # only currencies still open there count
        for cur in sorted({ln.debt_currency for ln in mine}):
            found = [ol for ol in repo.open_lines(conn, ws, cp.id, cur) if ol.line_id in ids]
            if found:
                open_by_cur[cur] = found
        if len(open_by_cur) > 1:
            raise ValidationError("currency", {"currencies": ", ".join(open_by_cur)})
        if not open_by_cur:
            raise ValidationError("outstanding")
        cur, found = open_by_cur.popitem()
        return cp, cur, found
    cp = _one(repo, conn, ws, target_ref, "counterparty")
    owed = {cur: bal for (cid, cur), bal in repo.balances(conn, ws).items()
            if cid == cp.id and bal > 0}
    if len(owed) > 1:
        raise ValidationError("currency", {"currencies": ", ".join(sorted(owed))})
    if not owed:
        raise ValidationError("outstanding")
    cur, _ = owed.popitem()
    return cp, cur, repo.open_lines(conn, ws, cp.id, cur)


# --- openings -----------------------------------------------------------------------
def _openings(repo: ReceivablesRepository, conn, ws: str, cp_id: str,
              currency: str | None = None) -> list[LedgerEntry]:
    """Effective OPENING entries of a counterparty (sourced to it), oldest first."""
    return [e for e in repo.effective_entries_for_refs(conn, ws, [cp_id], (EntryKind.OPENING,))
            if currency in (None, e.currency)]


def record_opening(repo: ReceivablesRepository, conn, ws: str, cp_id: str, currency: str,
                   amount_minor: int, basis: Opening, note: str, now: datetime, *,
                   queue: PendingQueue | None = None) -> LedgerEntry:
    """An opening balance stated by the owner, with its provenance in ``note`` (required).

    PERSON: signed as given (positive: they owe you, an open item; negative: a credit, R29).
    FUND: what you hold, stored negative. Replaces any effective opening in that currency
    (``release_opening`` + new entry) and sets the counterparty's ``opening`` to ``basis``
    (``APPROXIMATE`` or ``CONFIRMED``). For a PERSON the credits are applied again
    (``consume_credits``); a small EUR difference is closed only when ``queue`` is given.
    """
    cp = repo.get_counterparty(conn, ws, cp_id)
    if cp is None or cp.kind not in _DEBTORS:
        raise ValidationError("counterparty")
    if currency not in DEBT_CURRENCIES:
        raise ValidationError("currency")
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise ValidationError("amount")
    try:
        basis = Opening(basis)
    except ValueError:
        raise ValidationError("basis") from None
    if basis is Opening.UNKNOWN:
        raise ValidationError("basis")
    if not note or not note.strip():
        raise ValidationError("note")
    for old in _openings(repo, conn, ws, cp_id, currency):
        release_opening(repo, conn, ws, old, "replaced by a new opening", now)
    amount = -amount_minor if cp.kind is CounterpartyKind.FUND else amount_minor
    entry = _write(repo, conn, ws, cp_id, currency, amount, EntryKind.OPENING, cp_id,
                   note.strip(), now, basis.value)
    repo.set_opening(conn, ws, cp_id, basis)
    _settle(repo, conn, ws, [(cp_id, currency)], queue, now)  # PERSON only (consume_credits)
    return entry


# --- reverse ------------------------------------------------------------------------
def reverse(repo: ReceivablesRepository, conn, ws: str, ref: str, reason: str,
            queue: PendingQueue, now: datetime) -> dict:
    """Undoes one fact by its human ref: ``F<n>`` a funding, ``R<n>`` a receipt, ``E<n>`` an
    OPENING/ADJUSTMENT/FORGIVE, ``C<n>`` an exchange without a live funding, and
    ``<label> rule`` (or ``rule:<label>``) the payer rules that send money to that counterparty.
    """
    text = ref.strip()
    m = _FACT_REF.fullmatch(text)
    if m:
        handler = {"F": _reverse_funding, "R": _reverse_receipt, "E": _reverse_entry,
                   "C": _reverse_exchange}[m[1].upper()]
        return handler(repo, conn, ws, text, reason, queue, now)
    low = text.lower()
    label = text[5:] if low.startswith("rule:") else text[:-5] if low.endswith(" rule") else ""
    if not label.strip():
        raise ValidationError("ref")
    return _reverse_rules(repo, conn, ws, label.strip(), reason, now)


def _reverse_funding(repo: ReceivablesRepository, conn, ws: str, ref: str, reason: str,
                     queue: PendingQueue, now: datetime) -> dict:
    funding = repo.funding_by_ref(conn, ws, ref)
    if funding is None:
        raise ValidationError("funding")
    asked = reverse_funding(repo, conn, ws, funding.id, reason, queue, now)
    return {"ok": True, "status": "reversed", "ref": f"F{funding.number}",
            "questions": [p.code for p in asked]}


def _reverse_receipt(repo: ReceivablesRepository, conn, ws: str, ref: str, reason: str,
                     queue: PendingQueue, now: datetime) -> dict:
    """Revokes the receipt with its allocations and movement role, reverses its PAYMENT and
    write-offs, re-applies the payer's credits; a BANK receipt asks EXPLAIN_INCOMING again."""
    rec = repo.receipt_by_ref(conn, ws, ref)
    if rec is None:
        raise ValidationError("receipt")
    payments = repo.effective_entries_for_refs(conn, ws, [rec.id], (EntryKind.PAYMENT,))
    allocations = repo.live_allocations_for_receipt(conn, ws, rec.id)
    mv = repo.movement_current(conn, ws, rec.movement_id) if rec.movement_id else None

    for a in allocations:
        repo.revoke(conn, ws, "allocation", a.id, reason, now)
    reverse_receipt_adjustments(repo, conn, ws, [rec.id], reason, now)
    # a small difference closed on a line this receipt paid assumed this payment
    for adj in repo.effective_adjustments_for_lines(conn, ws, [a.line_id for a in allocations]):
        reverse_entry(repo, conn, ws, adj, reason, now)
    for entry in payments:
        reverse_entry(repo, conn, ws, entry, reason, now)
    if rec.movement_id is not None:
        for role_id in repo.live_role_ids_for_movement(conn, rec.movement_id):
            repo.revoke(conn, ws, "movement_role", role_id, reason, now)
    repo.revoke(conn, ws, "receipt", rec.id, reason, now)
    _settle(repo, conn, ws, [(rec.payer_id, rec.currency)], queue, now)
    out = {"ok": True, "status": "reversed", "ref": f"R{rec.number}"}
    if rec.kind is ReceiptKind.BANK and mv is not None:
        out["question"] = _ask_explain_incoming(repo, conn, ws, mv, queue).code
    return out


def _ask_explain_incoming(repo: ReceivablesRepository, conn, ws: str, mv: Movement,
                          queue: PendingQueue) -> PendingItem:
    """Asks again who sent an incoming payment. Minimal options: the matcher (Task 9) owns
    the full set. The payload names the movement, never an IBAN."""
    root = repo.movement_root(conn, mv.id)
    day = mv.booking_date or mv.value_date
    payload = {"movement_id": root, "booking_date": day.isoformat() if day else None,
               "currency": mv.currency, "amount": format_minor(mv.amount_minor, mv.currency)}
    return queue.add(conn, ws, PendingKind.EXPLAIN_INCOMING, ["OTHER", "NOT_EXCHANGE"], payload,
                     f"EXPLAIN_INCOMING:{root}")


def _reverse_entry(repo: ReceivablesRepository, conn, ws: str, ref: str, reason: str,
                   queue: PendingQueue, now: datetime) -> dict:
    entry = repo.entry_by_ref(conn, ws, ref)
    if entry is None:
        raise ValidationError("entry")
    if entry.kind not in (EntryKind.OPENING, EntryKind.ADJUSTMENT, EntryKind.FORGIVE):
        raise ValidationError("entry", {"kind": entry.kind.value})
    if entry.kind is EntryKind.OPENING:
        rev = release_opening(repo, conn, ws, entry, reason, now)
        cp = repo.get_counterparty(conn, ws, entry.counterparty_id)
        is_fund = cp is not None and cp.kind is CounterpartyKind.FUND
        left = _openings(repo, conn, ws, entry.counterparty_id)
        if left and left[-1].basis:
            basis: Opening | None = Opening(left[-1].basis)
        else:  # nothing stated any more: a fund is UNKNOWN again, a person has no opening
            basis = Opening.UNKNOWN if is_fund else None
        repo.set_opening(conn, ws, entry.counterparty_id, basis)
    else:
        rev = reverse_entry(repo, conn, ws, entry, reason, now)
    _settle(repo, conn, ws, [(entry.counterparty_id, entry.currency)], queue, now)
    return {"ok": True, "status": "reversed", "ref": f"E{entry.number}",
            "reversal_ref": f"E{rev.number}"}


def _reverse_exchange(repo: ReceivablesRepository, conn, ws: str, ref: str, reason: str,
                      queue: PendingQueue, now: datetime) -> dict:
    ex = repo.exchange_by_ref(conn, ws, ref)
    if ex is None:
        raise ValidationError("exchange")
    funding = repo.live_funding_for_exchange(conn, ex.id)
    if funding is not None:  # reverse the funding first (F<n>)
        raise ValidationError("funded", {"funding_ref": f"F{funding.number}"})
    charges = [*repo.effective_charges_for_exchange(conn, ws, ex.id, "USD"),
               *repo.effective_charges_for_exchange(conn, ws, ex.id, "EUR")]

    touched = release_charges(repo, conn, ws, charges, reason, now)  # gifts included (R28)
    repo.revoke(conn, ws, "exchange", ex.id, reason, now)
    _settle(repo, conn, ws, touched, queue, now)
    return {"ok": True, "status": "reversed", "ref": f"C{ex.number}"}


def _reverse_rules(repo: ReceivablesRepository, conn, ws: str, label: str, reason: str,
                   now: datetime) -> dict:
    cp = _one(repo, conn, ws, label, "counterparty")
    rule_ids = repo.live_rule_ids_for_counterparty(conn, ws, cp.id)
    if not rule_ids:
        raise ValidationError("rule")
    for rule_id in rule_ids:
        repo.revoke(conn, ws, "payer_rule", rule_id, reason, now)
    return {"ok": True, "status": "reversed", "rules": len(rule_ids)}
