"""EXPLAIN_INCOMING: who sent an incoming payment (spec §6.4, §7 F3).

The question and its options live here so that the matcher and the corrections (a reversed
BANK receipt asks again) share them without importing each other. The caller owns the
transaction. Payloads never carry an IBAN or a hash.
"""
from __future__ import annotations

from .. import domain
from ..money import format_minor
from ..store.receivables_repo import ReceivablesRepository
from .allocation import plan_allocation
from .ledger import ValidationError
from .model import AllocationMethod, CounterpartyKind, PendingItem, PendingKind
from .pending import PendingQueue
from .text import description_key

PAYERS = (CounterpartyKind.PERSON, CounterpartyKind.FUND)
SENDER_CHARS = 40
# Leading payment-rail words of a bank description; the sender's name follows them.
_RAILS = ("ZELLE PAYMENT FROM ", "ZELLE FROM ", "ONLINE BANKING TRANSFER FROM ",
          "ONLINE TRANSFER FROM ", "TRANSFER FROM ")


def incoming_key(repo: ReceivablesRepository, mv: domain.Movement,
                 description_rules: bool) -> str | None:
    """The payer-rule key of an incoming movement: its IBAN hash, else (only with
    ``description_rules``) the hash of its normalised description; ``None`` when neither."""
    if mv.counterparty_iban_hash:
        return mv.counterparty_iban_hash
    text = description_key(mv.remittance or "")
    return repo.hash_key(text) if description_rules and text else None


def sender_text(counterparty_name: str, remittance: str) -> str:
    """Who sent it, for the owner: the counterparty name, else the description, upper case,
    without digit-bearing tokens (``description_key``: so never an IBAN), a leading payment
    rail ("ZELLE FROM") or reference markers ("CONF#"); at most 40 characters."""
    text = description_key(counterparty_name or remittance or "")
    for rail in _RAILS:
        if text.startswith(rail):
            text = text[len(rail):]
            break
    words = [w for w in text.split() if not w.endswith("#")]
    return " ".join(words)[:SENDER_CHARS].rstrip()


def _exact(repo: ReceivablesRepository, conn, ws: str, cp_id: str, currency: str,
           amount: int) -> bool:
    """The open items (a PERSON's opening included, R29), or an exact subset, equal ``amount``."""
    items = repo.open_lines(conn, ws, cp_id, currency)
    return bool(items) and (sum(i.outstanding_minor for i in items) == amount or
                            plan_allocation(amount, items).method is AllocationMethod.AUTO_EXACT)


def explain_question(repo: ReceivablesRepository, conn, ws: str,
                     mv: domain.Movement) -> tuple[list[str], dict]:
    """Options and payload for an incoming movement (its current version).

    Options: the one PERSON whose open items or an exact subset of them equal the amount, then
    every other PERSON or FUND with a balance in that currency, then ``OTHER`` and
    ``NOT_EXCHANGE``. Option values are ``CP:<counterparty id>``; ``labels`` names them.
    """
    root, day = repo.movement_root(conn, mv.id), mv.booking_date or mv.value_date
    found = [(cp, cp.kind is CounterpartyKind.PERSON
              and _exact(repo, conn, ws, cp.id, mv.currency, mv.amount_minor))
             for cp in repo.list_counterparties(conn, ws) if cp.kind in PAYERS]
    found = [(cp, hit) for cp, hit in found
             if hit or repo.balance(conn, ws, cp.id, mv.currency) != 0]
    exact = [cp for cp, hit in found if hit]
    first = exact if len(exact) == 1 else []
    ordered = first + [cp for cp, _ in found if cp not in first]
    payload = {
        "movement_id": root, "booking_date": day.isoformat() if day else None,
        "currency": mv.currency, "amount": format_minor(mv.amount_minor, mv.currency),
        "sender": sender_text(mv.counterparty_name, mv.remittance),
        "exact": f"CP:{first[0].id}" if first else None,
        "labels": {f"CP:{cp.id}": cp.label for cp in ordered}}
    return [f"CP:{cp.id}" for cp in ordered] + ["OTHER", "NOT_EXCHANGE"], payload


def ask_explain_incoming(repo: ReceivablesRepository, conn, ws: str, movement: domain.Movement,
                         queue: PendingQueue) -> PendingItem:
    """Asks who sent an incoming payment (key ``EXPLAIN_INCOMING:<root movement id>``).

    An open question for the same movement is returned instead, its options and payload
    refreshed when they changed (a BOOKED successor with another amount, other balances).
    Raises ``ValidationError("movement")`` for a movement that is not incoming.
    """
    mv = repo.movement_current(conn, ws, movement.id) or movement
    if mv.amount_minor <= 0:
        raise ValidationError("movement")
    options, payload = explain_question(repo, conn, ws, mv)
    key = f"EXPLAIN_INCOMING:{payload['movement_id']}"
    current = repo.pending_by_dedupe(conn, ws, key)
    if current is None:
        return queue.add(conn, ws, PendingKind.EXPLAIN_INCOMING, options, payload, key)
    if (current.options, current.payload) != (tuple(options), payload):
        repo.refresh_pending(conn, ws, current.code, options, payload)
        return repo.pending_by_code(conn, ws, current.code)
    return current
