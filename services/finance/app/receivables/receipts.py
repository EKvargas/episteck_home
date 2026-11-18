"""Receipts: money received from a person or a fund, its allocation to open items, credits.

The caller owns the transaction and every function validates before its first write. The
balance never depends on allocations (they only explain which exchanges a receipt paid), so
allocation never asks the owner anything. A receipt from a FUND is a deposit, not a payment of
a debt: it gets no allocations. EUR differences of at most ``EUR_ADJUST_TOLERANCE_MINOR`` are
closed with an ``ADJUSTMENT`` (EUR only).

Open items and credits (R29): a PERSON's open items are its exchange lines plus a positive
OPENING, the oldest item; its credits are its receipt remainders plus a negative OPENING, the
oldest credit (``repo.open_lines`` / ``repo.credit_sources``). For every PERSON and currency,
Σ outstanding of the open items − Σ remaining credits = the balance.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime

from ..money import format_minor
from ..store.receivables_repo import DuplicateReceipt, ReceivablesRepository
from .allocation import plan_allocation
from .ledger import ValidationError, reverse_entry
from .model import (
    EUR_ADJUST_TOLERANCE_MINOR, Allocation, AllocationMethod, Counterparty, CounterpartyKind,
    EntryKind, LedgerEntry, MovementRoleKind, Opening, Receipt, ReceiptKind, Verification,
)
from .pending import PendingQueue

CURRENCIES = ("USD", "EUR")


def _id() -> str:
    return uuid.uuid4().hex


def _payer(repo: ReceivablesRepository, conn, ws: str, payer_id: str):
    payer = repo.get_counterparty(conn, ws, payer_id)
    if payer is None or payer.kind not in (CounterpartyKind.PERSON, CounterpartyKind.FUND):
        raise ValidationError("payer")
    return payer


def _validate(repo: ReceivablesRepository, conn, ws: str, kind: ReceiptKind, payer_id: str,
              currency: str, amount_minor: int, verification: Verification,
              movement_id: str | None, description: str):
    if currency not in CURRENCIES:
        raise ValidationError("currency")
    if amount_minor <= 0:
        raise ValidationError("amount")
    payer = _payer(repo, conn, ws, payer_id)
    expected = Verification.BANK_POSTED if kind is ReceiptKind.BANK else Verification.OWNER_CONFIRMED
    if verification is not expected:
        raise ValidationError("verification")
    if kind is ReceiptKind.BANK and movement_id is None:
        raise ValidationError("movement")
    if kind is ReceiptKind.IN_KIND and not description.strip():
        raise ValidationError("description")
    if movement_id is not None:
        _check_movement(repo, conn, ws, movement_id, currency, amount_minor)
    return payer


def _check_movement(repo: ReceivablesRepository, conn, ws: str, movement_id: str,
                    currency: str, amount_minor: int) -> None:
    """A receipt's bank movement (R30): the current version (BOOKED successor followed) of an
    incoming movement in the receipt's currency and amount, with no live receipt, funding or
    role on its root. Refusals are ``ValidationError("movement")`` with a ``reason``."""
    mv = repo.movement_current(conn, ws, movement_id)
    if mv is None:
        raise ValidationError("movement", {"reason": "unknown"})
    existing = repo.live_receipt_for_movement(conn, movement_id)
    if existing is not None:
        raise DuplicateReceipt(repo.movement_root(conn, movement_id), existing.id)
    if mv.amount_minor <= 0:
        raise ValidationError("movement", {"reason": "outgoing"})
    if mv.currency != currency:
        raise ValidationError("movement", {"reason": "currency", "movement_currency": mv.currency})
    if mv.amount_minor != amount_minor:
        raise ValidationError("movement", {
            "reason": "amount", "movement_amount": format_minor(mv.amount_minor, mv.currency),
            "amount": format_minor(amount_minor, currency)})
    if repo.live_funding_for_movement(conn, movement_id) is not None:
        raise ValidationError("movement", {"reason": "funded"})
    if repo.movement_role(conn, movement_id) is not None:
        raise ValidationError("movement", {"reason": "classified"})


def _entry(repo: ReceivablesRepository, conn, ws: str, payer_id: str, currency: str,
           amount: int, kind: EntryKind, day: date, source_ref: str) -> LedgerEntry:
    entry = LedgerEntry(_id(), ws, repo.next_number(conn, ws, "E"), payer_id, currency, amount,
                        kind, day, source_ref)
    repo.insert_entry(conn, entry)
    return entry


def _settled_ref(repo: ReceivablesRepository, conn, ws: str, payer_id: str, currency: str,
                 balance: int) -> str | None:
    """What a small difference closes: the open item (an exchange line or the opening) holding
    a residual the payer still owes, or the credit (a receipt or a negative opening) holding a
    remainder we hold of theirs. ``None`` when there is none: nothing is closed then, so a
    negative ADJUSTMENT is never sourced to a credit (R29)."""
    if balance > 0:
        lines = repo.open_lines(conn, ws, payer_id, currency)
        fits = [ln for ln in lines if ln.outstanding_minor >= balance]
        if fits:
            return min(fits, key=lambda ln: (ln.outstanding_minor, -ln.order)).line_id
        return max(lines, key=lambda ln: ln.order).line_id if lines else None
    credits = repo.credit_sources(conn, ws, payer_id, currency)
    fits = [source for source, left in credits if left >= -balance]
    if fits:
        return fits[-1]
    return credits[-1][0] if credits else None


def _close_small_difference(repo: ReceivablesRepository, conn, ws: str, payer_id: str,
                            currency: str, day: date, queue: PendingQueue,
                            receipt: Receipt | None) -> None:
    """EUR only: a balance of at most 1,00 either way is closed by an ADJUSTMENT whose
    ``source_ref`` names the item (residual owed) or credit (remainder held) it settles.

    One INFO ``small_difference_closed`` per ADJUSTMENT, keyed by its ``E<n>`` (R30), naming
    the receipt involved (``None`` when an opening's credit was consumed), the absolute amount
    and its ``direction``: ``they_owed`` (a residual they owed) or ``you_held`` (a remainder
    you held)."""
    balance = repo.balance(conn, ws, payer_id, currency)
    if currency != "EUR" or balance == 0 or abs(balance) > EUR_ADJUST_TOLERANCE_MINOR:
        return
    target = _settled_ref(repo, conn, ws, payer_id, currency, balance)
    if target is None:
        return
    adj = _entry(repo, conn, ws, payer_id, currency, -balance, EntryKind.ADJUSTMENT, day, target)
    ref = f"E{adj.number}"
    queue.notice(conn, ws, f"small_difference_closed:{ref}", {
        "entry_ref": ref, "receipt_ref": f"R{receipt.number}" if receipt else None,
        "currency": currency, "amount": format_minor(abs(balance), currency),
        "direction": "they_owed" if balance > 0 else "you_held"})


def record_receipt(repo: ReceivablesRepository, conn, ws: str, *, kind: ReceiptKind,
                   payer_id: str, currency: str, amount_minor: int, received_on: date,
                   verification: Verification, movement_id: str | None = None,
                   description: str = "", queue: PendingQueue, now: datetime) -> Receipt:
    payer = _validate(repo, conn, ws, kind, payer_id, currency, amount_minor, verification,
                      movement_id, description)
    balance_before = repo.balance(conn, ws, payer_id, currency)
    receipt = Receipt(_id(), ws, repo.next_number(conn, ws, "R"), kind, payer_id, currency,
                      amount_minor, received_on, verification, movement_id,
                      description.strip())
    repo.insert_receipt(conn, receipt)
    _entry(repo, conn, ws, payer_id, currency, -amount_minor, EntryKind.PAYMENT, received_on,
           receipt.id)
    is_fund = payer.kind is CounterpartyKind.FUND
    if movement_id is not None:
        repo.insert_movement_role(
            conn, ws, movement_id,
            MovementRoleKind.FUND_DEPOSIT if is_fund else MovementRoleKind.RECEIVABLE_PAYMENT)
    parts: Sequence[tuple[str, int]] = ()
    if not is_fund:
        plan = plan_allocation(amount_minor, repo.open_lines(conn, ws, payer_id, currency))
        for line_id, part in plan.parts:
            repo.insert_allocation(conn, Allocation(_id(), ws, receipt.id, line_id, part,
                                                    plan.method))
        parts = plan.parts
        if balance_before > 0:
            _close_small_difference(repo, conn, ws, payer_id, currency, received_on, queue,
                                    receipt)
    _notice_applied(repo, conn, ws, receipt, payer, parts, queue)
    return receipt


def _notice_applied(repo: ReceivablesRepository, conn, ws: str, receipt: Receipt,
                    payer: Counterparty, parts: Sequence[tuple[str, int]],
                    queue: PendingQueue) -> None:
    """INFO ``receipt_applied``, written after any small-difference closure (R30): the
    exchanges the receipt paid, the opening if it paid that (``{"entry_ref", "amount"}``), the
    payer's signed ``balance_after`` and ``credit`` = max(0, −balance_after). A fund whose
    opening is unknown gets no figures (spec §6.5)."""
    cur = receipt.currency
    openings = {e.id: e for e in repo.effective_entries_for_refs(conn, ws, [payer.id],
                                                                  (EntryKind.OPENING,))}
    covered: dict[str, list] = {}
    opening = None
    for line_id, part in parts:
        if line_id in openings:
            opening = {"entry_ref": f"E{openings[line_id].number}",
                       "amount": format_minor(part, cur)}
            continue
        found = repo.line_with_exchange(conn, ws, line_id)
        if found is None:
            continue
        ex = found[1]
        entry = covered.setdefault(f"C{ex.number}", [ex.delivered_on.isoformat(), 0])
        entry[1] += part
    unknown = payer.kind is CounterpartyKind.FUND and payer.opening in (None, Opening.UNKNOWN)
    balance = repo.balance(conn, ws, payer.id, cur)
    ref = f"R{receipt.number}"
    queue.notice(conn, ws, f"receipt_applied:{ref}", {
        "receipt_ref": ref, "currency": cur, "amount": format_minor(receipt.amount_minor, cur),
        "exchanges": [{"exchange_ref": r, "delivered_on": d, "amount": format_minor(a, cur)}
                      for r, (d, a) in covered.items()],
        "opening": opening,
        "balance_after": None if unknown else format_minor(balance, cur),
        "credit": None if unknown else format_minor(max(0, -balance), cur)})


def consume_credits(repo: ReceivablesRepository, conn, ws: str, payer_id: str, currency: str,
                    *, queue: PendingQueue | None = None, now: datetime | None = None) -> None:
    """Applies the payer's credits (``repo.credit_sources``: an opening credit, then receipt
    remainders) FIFO to its open items (the opening item first), ``AUTO_FIFO``.

    A small EUR difference left by a consumed credit is closed too, but only when both
    ``queue`` and ``now`` are given.
    """
    payer = repo.get_counterparty(conn, ws, payer_id)
    if payer is None or payer.kind is not CounterpartyKind.PERSON:
        return
    lines = [[ln.line_id, ln.outstanding_minor] for ln in repo.open_lines(conn, ws, payer_id,
                                                                          currency)]
    last_source: str | None = None
    i = 0
    for source, credit in repo.credit_sources(conn, ws, payer_id, currency):
        while credit > 0 and i < len(lines):
            take = min(credit, lines[i][1])
            repo.insert_allocation(conn, Allocation(_id(), ws, source, lines[i][0], take,
                                                    AllocationMethod.AUTO_FIFO))
            credit -= take
            lines[i][1] -= take
            last_source = source
            if lines[i][1] == 0:
                i += 1
        if i >= len(lines):
            break
    if last_source is not None and queue is not None and now is not None:
        _close_small_difference(repo, conn, ws, payer_id, currency, now.date(), queue,
                                repo.receipt_by_id(conn, ws, last_source))


def reverse_receipt_adjustments(repo: ReceivablesRepository, conn, ws: str,
                                receipt_ids: Sequence[str], reason: str, now: datetime) -> None:
    """Undoes the credit write-offs (ADJUSTMENTs sourced to a receipt) of these receipts.

    Call it whenever a receipt's live allocations are revoked: the write-off assumed a small
    remainder that no longer exists. If the remainder is small again later,
    ``consume_credits`` applies the rule again.
    """
    for adj in repo.effective_adjustments_for_receipts(conn, ws, receipt_ids):
        reverse_entry(repo, conn, ws, adj, reason, now)


def release_charges(repo: ReceivablesRepository, conn, ws: str, charges: Sequence[LedgerEntry],
                    reason: str, now: datetime) -> list[tuple[str, str]]:
    """Undoes effective CHARGEs together with what settled their lines.

    In one step: a ``REVERSAL`` of each charge and of the settlements sourced to its line
    (small-difference ADJUSTMENTs, R26, and FORGIVEs, R28: a gift on an un-charged line would
    show as a credit; the owner forgives again once it is charged again), revocation of the
    line's live allocations and reversal of those receipts' write-offs (R27). Returns the
    (payer, currency) pairs touched; the caller re-runs ``consume_credits`` for them.
    """
    lines = list(dict.fromkeys(e.source_ref for e in charges))
    for entry in charges:
        reverse_entry(repo, conn, ws, entry, reason, now)
    allocations = repo.live_allocations_for_lines(conn, ws, lines)
    for a in allocations:
        repo.revoke(conn, ws, "allocation", a.id, reason, now)
    for settled in repo.effective_settlements_for_lines(conn, ws, lines):
        reverse_entry(repo, conn, ws, settled, reason, now)
    reverse_receipt_adjustments(repo, conn, ws, [a.receipt_id for a in allocations], reason, now)
    return list(dict.fromkeys((e.counterparty_id, e.currency) for e in charges))


def release_opening(repo: ReceivablesRepository, conn, ws: str, opening: LedgerEntry,
                    reason: str, now: datetime) -> LedgerEntry:
    """Undoes an effective OPENING with what hangs on it, as ``release_charges`` does for a
    line (R29).

    In one step: its ``REVERSAL``; the REVERSAL of the settlements sourced to it (small
    differences and FORGIVEs of a positive opening, the write-off of a negative one); the
    revocation of its live allocations either way (receipts that paid it, lines it paid as a
    credit); the write-offs of those receipts (R27) and the small differences closed on the
    lines it paid (as a receipt reversal does). Returns the REVERSAL; the caller re-runs
    ``consume_credits`` for the opening's party and currency.
    """
    rev = reverse_entry(repo, conn, ws, opening, reason, now)
    paid_by = repo.live_allocations_for_lines(conn, ws, [opening.id])
    paid = repo.live_allocations_for_receipt(conn, ws, opening.id)
    for a in (*paid_by, *paid):
        repo.revoke(conn, ws, "allocation", a.id, reason, now)
    for settled in repo.effective_settlements_for_lines(conn, ws, [opening.id]):
        reverse_entry(repo, conn, ws, settled, reason, now)
    reverse_receipt_adjustments(repo, conn, ws, [a.receipt_id for a in paid_by], reason, now)
    for adj in repo.effective_adjustments_for_lines(conn, ws, [a.line_id for a in paid]):
        reverse_entry(repo, conn, ws, adj, reason, now)
    return rev


def reallocate(repo: ReceivablesRepository, conn, ws: str, receipt_id: str,
               parts: Sequence[tuple[str, int]], now: datetime) -> None:
    """Replaces the receipt's live allocations by ``parts`` (``OWNER``). Nothing is written
    unless every invariant holds. A PERSON's opening item may be a part (R29)."""
    receipt = repo.receipt_by_id(conn, ws, receipt_id)
    if receipt is None:
        raise ValidationError("receipt")
    payer = _payer(repo, conn, ws, receipt.payer_id)
    if payer.kind is CounterpartyKind.FUND:
        raise ValidationError("receipt")
    current = conn.execute(
        "SELECT a.id, a.line_id, a.amount_minor FROM allocation a WHERE a.receipt_id=? AND "
        "NOT EXISTS (SELECT 1 FROM revocation r WHERE r.table_name='allocation' "
        "AND r.target_id=a.id) ORDER BY a.rowid", (receipt_id,)).fetchall()
    free: dict[str, int] = {ln.line_id: ln.outstanding_minor
                            for ln in repo.open_lines(conn, ws, receipt.payer_id,
                                                      receipt.currency)}
    for row in current:  # what the lines owe once this receipt's allocations are revoked
        free[row["line_id"]] = free.get(row["line_id"], 0) + row["amount_minor"]

    def fmt(minor: int) -> str:
        return format_minor(minor, receipt.currency)

    totals: dict[str, int] = {}
    for line_id, part in parts:
        if part <= 0:
            raise ValidationError("parts", {"part": fmt(part)})
        totals[line_id] = totals.get(line_id, 0) + part
    for line_id, part in totals.items():
        outstanding = free.get(line_id, 0)
        if outstanding <= 0:
            raise ValidationError("parts", {"line": line_id})
        if part > outstanding:
            raise ValidationError("parts", {"line": line_id, "outstanding": fmt(outstanding),
                                            "part": fmt(part)})
    total = sum(totals.values())
    if total > receipt.amount_minor:
        raise ValidationError("parts", {"amount": fmt(receipt.amount_minor), "part": fmt(total)})

    reverse_receipt_adjustments(repo, conn, ws, [receipt_id], "reallocated", now)
    for row in current:
        repo.revoke(conn, ws, "allocation", row["id"], "reallocated", now)
    for line_id, part in totals.items():
        repo.insert_allocation(conn, Allocation(_id(), ws, receipt_id, line_id, part,
                                                AllocationMethod.OWNER))


def mark_held_cash(repo: ReceivablesRepository, conn, ws: str, cp_id: str, currency: str,
                   amount_minor: int, now: datetime) -> None:
    """The owner states how much of what a person owes is held in cash abroad."""
    cp = repo.get_counterparty(conn, ws, cp_id)
    if cp is None or cp.kind is not CounterpartyKind.PERSON:
        raise ValidationError("counterparty")
    if currency not in CURRENCIES:
        raise ValidationError("currency")
    if amount_minor < 0:
        raise ValidationError("amount")
    repo.insert_held_cash(conn, ws, cp_id, currency, amount_minor, now.date())


def held_cash_shown(repo: ReceivablesRepository, conn, ws: str, cp_id: str,
                    currency: str) -> int | None:
    """min(stated - live CASH receipts dated strictly after the statement day, balance), floored at 0.

    ``None`` when no statement exists. Display only: it never changes a balance.
    """
    stated = repo.latest_held_cash(conn, ws, cp_id, currency)
    if stated is None:
        return None
    amount, stated_on = stated
    cash = conn.execute(
        "SELECT COALESCE(SUM(r.amount_minor),0) AS s FROM receipt r WHERE r.workspace_id=? "
        "AND r.payer_id=? AND r.currency=? AND r.kind='CASH' AND r.received_on>? AND "
        "NOT EXISTS (SELECT 1 FROM revocation v WHERE v.table_name='receipt' AND v.target_id=r.id)",
        (ws, cp_id, currency, stated_on.isoformat())).fetchone()["s"]
    return max(0, min(amount - cash, repo.balance(conn, ws, cp_id, currency)))
