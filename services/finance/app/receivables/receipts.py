"""Receipts: money received from a person or a fund, its allocation to exchange lines, credits.

The caller owns the transaction and every function validates before its first write. The
balance never depends on allocations (they only explain which exchanges a receipt paid), so
allocation never asks the owner anything. A receipt from a FUND is a deposit, not a payment of
a debt: it gets no allocations. EUR differences of at most ``EUR_ADJUST_TOLERANCE_MINOR`` are
closed with an ``ADJUSTMENT`` (EUR only).
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime

from ..money import format_minor
from ..store.receivables_repo import DuplicateReceipt, ReceivablesRepository, _receipt
from .allocation import plan_allocation
from .ledger import ValidationError
from .model import (
    EUR_ADJUST_TOLERANCE_MINOR, Allocation, AllocationMethod, CounterpartyKind, EntryKind,
    LedgerEntry, MovementRoleKind, Receipt, ReceiptKind, Verification,
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
        if repo.movement_current(conn, ws, movement_id) is None:
            raise ValidationError("movement")
        existing = repo.live_receipt_for_movement(conn, movement_id)
        if existing is not None:
            raise DuplicateReceipt(repo.movement_root(conn, movement_id), existing.id)
    return payer


def _entry(repo: ReceivablesRepository, conn, ws: str, payer_id: str, currency: str,
           amount: int, kind: EntryKind, day: date, source_ref: str) -> None:
    repo.insert_entry(conn, LedgerEntry(
        _id(), ws, repo.next_number(conn, ws, "E"), payer_id, currency, amount, kind, day,
        source_ref))


def _settled_ref(repo: ReceivablesRepository, conn, ws: str, payer_id: str, currency: str,
                 balance: int, fallback: str) -> str:
    """What a small difference closes: the open line holding a residual the payer still owes,
    or the receipt holding a remainder we hold of theirs."""
    if balance > 0:
        lines = repo.open_lines(conn, ws, payer_id, currency)
        fits = [ln for ln in lines if ln.outstanding_minor >= balance]
        if fits:
            return min(fits, key=lambda ln: (ln.outstanding_minor, -ln.order)).line_id
        if lines:
            return max(lines, key=lambda ln: ln.order).line_id
    else:
        rems = repo.receipt_remainders(conn, ws, payer_id, currency)
        fits = [r for r, left in rems if left >= -balance]
        if fits:
            return fits[-1].id
        if rems:
            return rems[-1][0].id
    return fallback


def _close_small_difference(repo: ReceivablesRepository, conn, ws: str, payer_id: str,
                            currency: str, ref: str, day: date, queue: PendingQueue) -> None:
    """EUR only: a balance of at most 1,00 either way is closed by an ADJUSTMENT whose
    ``source_ref`` names the line (residual owed) or receipt (credit held) it settles."""
    balance = repo.balance(conn, ws, payer_id, currency)
    if currency != "EUR" or balance == 0 or abs(balance) > EUR_ADJUST_TOLERANCE_MINOR:
        return
    target = _settled_ref(repo, conn, ws, payer_id, currency, balance, ref)
    _entry(repo, conn, ws, payer_id, currency, -balance, EntryKind.ADJUSTMENT, day, target)
    queue.notice(conn, ws, f"small_difference_closed:{ref}", {
        "ref": ref, "currency": currency, "amount": format_minor(-balance, currency)})


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
    if is_fund:
        _notice_applied(repo, conn, ws, receipt, (), amount_minor, queue)
        return receipt

    plan = plan_allocation(amount_minor, repo.open_lines(conn, ws, payer_id, currency))
    for line_id, part in plan.parts:
        repo.insert_allocation(conn, Allocation(_id(), ws, receipt.id, line_id, part,
                                                plan.method))
    _notice_applied(repo, conn, ws, receipt, plan.parts, plan.remainder_minor, queue)
    if balance_before > 0:
        _close_small_difference(repo, conn, ws, payer_id, currency, receipt.id, received_on,
                                queue)
    return receipt


def _notice_applied(repo: ReceivablesRepository, conn, ws: str, receipt: Receipt,
                    parts: Sequence[tuple[str, int]], credit: int, queue: PendingQueue) -> None:
    covered: dict[str, list] = {}
    for line_id, part in parts:
        found = repo.line_with_exchange(conn, ws, line_id)
        if found is None:
            continue
        ex = found[1]
        entry = covered.setdefault(f"C{ex.number}", [ex.delivered_on.isoformat(), 0])
        entry[1] += part
    ref = f"R{receipt.number}"
    queue.notice(conn, ws, f"receipt_applied:{ref}", {
        "receipt_ref": ref, "currency": receipt.currency,
        "amount": format_minor(receipt.amount_minor, receipt.currency),
        "exchanges": [
            {"exchange_ref": r, "delivered_on": d, "amount": format_minor(a, receipt.currency)}
            for r, (d, a) in covered.items()],
        "credit": format_minor(credit, receipt.currency)})


def consume_credits(repo: ReceivablesRepository, conn, ws: str, payer_id: str, currency: str,
                    *, queue: PendingQueue | None = None, now: datetime | None = None) -> None:
    """Applies the payer's receipt credits FIFO to its open lines (``AUTO_FIFO``).

    A small EUR difference left by a consumed credit is closed too, but only when both
    ``queue`` and ``now`` are given.
    """
    payer = repo.get_counterparty(conn, ws, payer_id)
    if payer is None or payer.kind is not CounterpartyKind.PERSON:
        return
    lines = [[ln.line_id, ln.outstanding_minor] for ln in repo.open_lines(conn, ws, payer_id,
                                                                          currency)]
    last_receipt: str | None = None
    i = 0
    for rec, credit in repo.receipt_remainders(conn, ws, payer_id, currency):
        while credit > 0 and i < len(lines):
            take = min(credit, lines[i][1])
            repo.insert_allocation(conn, Allocation(_id(), ws, rec.id, lines[i][0], take,
                                                    AllocationMethod.AUTO_FIFO))
            credit -= take
            lines[i][1] -= take
            last_receipt = rec.id
            if lines[i][1] == 0:
                i += 1
        if i >= len(lines):
            break
    if last_receipt is not None and queue is not None and now is not None:
        _close_small_difference(repo, conn, ws, payer_id, currency, last_receipt, now.date(),
                                queue)


def _live_receipt(repo: ReceivablesRepository, conn, ws: str, receipt_id: str) -> Receipt | None:
    row = conn.execute("SELECT * FROM receipt WHERE workspace_id=? AND id=?",
                       (ws, receipt_id)).fetchone()
    if row is None or not repo.is_live(conn, "receipt", receipt_id):
        return None
    return _receipt(row)


def reverse_receipt_adjustments(repo: ReceivablesRepository, conn, ws: str,
                                receipt_ids: Sequence[str], reason: str, now: datetime) -> None:
    """Undoes the credit write-offs (ADJUSTMENTs sourced to a receipt) of these receipts.

    Call it whenever a receipt's live allocations are revoked: the write-off assumed a small
    remainder that no longer exists. If the remainder is small again later,
    ``consume_credits`` applies the rule again.
    """
    for adj in repo.effective_adjustments_for_receipts(conn, ws, receipt_ids):
        repo.insert_entry(conn, LedgerEntry(
            _id(), ws, repo.next_number(conn, ws, "E"), adj.counterparty_id, adj.currency,
            -adj.amount_minor, EntryKind.REVERSAL, now.date(), adj.source_ref, reason,
            reverses_id=adj.id))


def reallocate(repo: ReceivablesRepository, conn, ws: str, receipt_id: str,
               parts: Sequence[tuple[str, int]], now: datetime) -> None:
    """Replaces the receipt's live allocations by ``parts`` (``OWNER``). Nothing is written
    unless every invariant holds."""
    receipt = _live_receipt(repo, conn, ws, receipt_id)
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
