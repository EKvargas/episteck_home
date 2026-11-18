"""Funding: link partner payments (EUR out) to exchanges; fix the rate and the EUR shares.

The caller owns the transaction. A funding stores ROOT movement ids, so a PENDING payment and
its BOOKED successor are one payment; amounts come from the latest version. Nothing here
resolves a pending item: the service does that once the owner's choice has been applied.
OWNER lines carry ``debt_currency`` "USD" only as a placeholder and are never charged.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from .. import domain
from ..money import format_minor
from ..store.receivables_repo import ReceivablesRepository
from .fx import deviation, implied_rate, rate_text, split_largest_remainder
from .ledger import ValidationError
from .model import (
    LINK_BAND, NOTICE_BAND, OWNER, CounterpartyKind, EntryKind, Exchange, ExchangeLine, Funding,
    LedgerEntry, MovementRoleKind, PendingItem, PendingKind,
)
from .pending import PendingQueue

LinkResult = Literal["LINKED", "WAITING", "AMBIGUOUS", "ALREADY_LINKED"]


class AlreadyLinked(Exception):
    """A movement or an exchange already belongs to a live funding."""


def _id() -> str:
    return uuid.uuid4().hex


def _error(code: str) -> dict:
    return {"ok": False, "error": code}


def consume_credits(repo: ReceivablesRepository, conn, ws: str, payer_id: str,
                    currency: str) -> None:
    """Seam: Task 7 applies the payer's receipt credits FIFO to open lines. No-op for now."""


def _day(mv: domain.Movement) -> date:
    """The movement date is its booking date (value date only if the bank gave none)."""
    day = mv.booking_date or mv.value_date
    if day is None:
        raise ValidationError("movement")
    return day


def _payment(repo: ReceivablesRepository, conn, ws: str,
             movement_id: str | None) -> domain.Movement | None:
    """The latest version of an outgoing EUR movement of this workspace, else ``None``."""
    mv = repo.movement_current(conn, ws, movement_id or "")
    if mv is None or mv.currency != "EUR" or mv.amount_minor >= 0:
        return None
    return mv


def _usd(repo: ReceivablesRepository, conn, ex: Exchange) -> int:
    return sum(ln.usd_minor for ln in repo.current_lines(conn, ex.id))


def _candidates(repo: ReceivablesRepository, conn, ws: str, day: date) -> list[Exchange]:
    return [ex for ex in repo.open_exchanges(conn, ws) if ex.delivered_on <= day]


def _compatible(repo: ReceivablesRepository, conn, ws: str, eur: int,
                day: date) -> list[Exchange]:
    """Rules 1-2: open exchanges delivered by ``day`` whose rate with ``eur`` is within
    LINK_BAND of the ECB rate. With no ECB rate, every candidate is compatible."""
    ecb = repo.usd_per_eur_on(conn, day)
    return [ex for ex in _candidates(repo, conn, ws, day)
            if ecb is None or deviation(implied_rate(eur, _usd(repo, conn, ex)), ecb) <= LINK_BAND]


def _charges_eur(repo: ReceivablesRepository, conn, ws: str, ln: ExchangeLine) -> bool:
    if ln.payer_id == OWNER or ln.debt_currency != "EUR":
        return False
    payer = repo.get_counterparty(conn, ws, ln.payer_id)
    return payer is not None and payer.kind is CounterpartyKind.PERSON


def create_funding(repo: ReceivablesRepository, conn, ws: str, movement_ids: Sequence[str],
                   exchange_ids: Sequence[str], queue: PendingQueue, now: datetime) -> Funding:
    payments: dict[str, domain.Movement] = {}
    for mid in movement_ids:
        mv = _payment(repo, conn, ws, mid)
        if mv is None:
            raise ValidationError("movement")
        if repo.live_funding_for_movement(conn, mv.id) is not None:
            raise AlreadyLinked()
        payments.setdefault(repo.movement_root(conn, mv.id), mv)
    open_by_id = {ex.id: ex for ex in repo.open_exchanges(conn, ws)}
    exchanges: list[Exchange] = []
    for eid in dict.fromkeys(exchange_ids):
        if eid not in open_by_id:
            if repo.live_funding_for_exchange(conn, eid) is not None:
                raise AlreadyLinked()
            raise ValidationError("exchange")
        exchanges.append(open_by_id[eid])
    if not payments or not exchanges:
        raise ValidationError("funding")
    exchanges.sort(key=lambda ex: ex.number)

    lines = [ln for ex in exchanges for ln in repo.current_lines(conn, ex.id)]
    eur = sum(-mv.amount_minor for mv in payments.values())
    usd = sum(ln.usd_minor for ln in lines)
    rate = implied_rate(eur, usd)
    splits = split_largest_remainder(eur, [ln.usd_minor for ln in lines])
    shares: dict[str, int] = {}
    for ln, part in zip(lines, splits):
        shares[ln.payer_id] = shares.get(ln.payer_id, 0) + part
    day = max(_day(mv) for mv in payments.values())
    funding = Funding(_id(), ws, repo.next_number(conn, ws, "F"), tuple(payments),
                      tuple(ex.id for ex in exchanges), eur, usd, now)
    repo.insert_funding(conn, funding, shares)

    charged: list[str] = []
    for ln, part in zip(lines, splits):
        amount = ln.eur_override_minor if ln.eur_override_minor is not None else part
        if amount > 0 and _charges_eur(repo, conn, ws, ln):
            repo.insert_entry(conn, LedgerEntry(
                _id(), ws, repo.next_number(conn, ws, "E"), ln.payer_id, "EUR", amount,
                EntryKind.CHARGE, day, ln.id))
            charged.append(ln.payer_id)
    for root in payments:
        repo.insert_movement_role(conn, ws, root, MovementRoleKind.EXCHANGE_FUNDING)
    for payer in dict.fromkeys(charged):
        consume_credits(repo, conn, ws, payer, "EUR")
    _notify(conn, ws, funding, exchanges, rate, repo.usd_per_eur_on(conn, day), queue)
    return funding


def _notify(conn, ws: str, funding: Funding, exchanges: Sequence[Exchange], rate: Fraction,
            ecb: Decimal | None, queue: PendingQueue) -> None:
    ref = f"F{funding.number}"
    payload = {"funding_ref": ref, "exchange_refs": [f"C{ex.number}" for ex in exchanges],
               "rate": rate_text(rate), "eur": format_minor(funding.eur_minor, "EUR"),
               "usd": format_minor(funding.usd_minor, "USD")}
    queue.notice(conn, ws, f"funding_closed:{ref}", payload)
    if ecb is not None and deviation(rate, ecb) > NOTICE_BAND:
        queue.notice(conn, ws, f"rate_outlier:{ref}",
                     {**payload, "reference_rate": rate_text(1 / Fraction(ecb))})


def try_link(repo: ReceivablesRepository, conn, ws: str, movement: domain.Movement,
             queue: PendingQueue, now: datetime) -> LinkResult:
    """Spec §6.2 rules 1-5 for an outgoing EUR payment to a known partner IBAN.

    ``ALREADY_LINKED`` also covers a payment the owner already classified (any live role).
    A pool of unlinked partner payments that fits more than one exchange keeps waiting.
    """
    mv = _payment(repo, conn, ws, movement.id)
    if mv is None:
        raise ValidationError("movement")
    if (repo.live_funding_for_movement(conn, mv.id) is not None
            or repo.movement_role(conn, mv.id) is not None):
        return "ALREADY_LINKED"
    compatible = _compatible(repo, conn, ws, -mv.amount_minor, _day(mv))
    if len(compatible) == 1:
        create_funding(repo, conn, ws, [mv.id], [compatible[0].id], queue, now)
        return "LINKED"
    if compatible:
        ask_link_funding(repo, conn, ws, mv.id, queue)
        return "AMBIGUOUS"
    root, day = repo.movement_root(conn, mv.id), _day(mv)
    unlinked = [p for p in repo.unlinked_partner_payments(conn, ws)
                if repo.movement_root(conn, p.id) != root]
    ecb = repo.usd_per_eur_on(conn, day)
    fits: list[tuple[Exchange, list[domain.Movement]]] = []
    for ex in _candidates(repo, conn, ws, day):
        # only payments from the delivery up to this payment can belong to this exchange (R19)
        pool = sorted([mv, *(p for p in unlinked if ex.delivered_on <= _day(p) <= day)],
                      key=_day)
        if len(pool) < 2:
            continue
        eur = sum(-p.amount_minor for p in pool)
        if ecb is None or deviation(implied_rate(eur, _usd(repo, conn, ex)), ecb) <= LINK_BAND:
            fits.append((ex, pool))
    if len(fits) == 1:
        ex, pool = fits[0]
        create_funding(repo, conn, ws, [p.id for p in pool], [ex.id], queue, now)
        return "LINKED"
    return "WAITING"


def ask_link_funding(repo: ReceivablesRepository, conn, ws: str, movement_id: str,
                     queue: PendingQueue) -> PendingItem:
    """Raises the LINK_FUNDING question for a payment (or returns the open one).

    One button per open exchange delivered on or before the payment, ``ALL`` when there are
    several, ``ADD_TO:C<n>`` for the latest paid exchange delivered by then, then
    ``REGISTER`` and ``NOT_EXCHANGE``.
    """
    mv = _payment(repo, conn, ws, movement_id)
    if mv is None:
        raise ValidationError("movement")
    root, day = repo.movement_root(conn, mv.id), _day(mv)
    refs = [f"C{ex.number}" for ex in _candidates(repo, conn, ws, day)]
    options = refs + (["ALL"] if len(refs) > 1 else [])
    paid = repo.latest_funded_exchange(conn, ws, day)
    if paid is not None:
        options.append(f"ADD_TO:C{paid.number}")
    payload = {"movement_id": root, "booking_date": day.isoformat(),
               "eur": format_minor(-mv.amount_minor, "EUR"), "candidates": refs}
    return queue.add(conn, ws, PendingKind.LINK_FUNDING, [*options, "REGISTER", "NOT_EXCHANGE"],
                     payload, f"LINK_FUNDING:{root}")


def link_choice(repo: ReceivablesRepository, conn, ws: str, movement_id: str | None,
                choice: str, queue: PendingQueue, now: datetime, *,
                exchange_ref: str | None = None) -> dict:
    """Applies the owner's answer to LINK_FUNDING (``C<n>``, ``ALL``, ``ADD_TO:C<n>``,
    ``REGISTER``, ``NOT_EXCHANGE``) or PREVIOUS_UNPAID (``M:<movement id>`` with
    ``exchange_ref``, ``NOT_YET``). An already linked movement is refused with no writes."""
    choice = choice.strip()
    if choice == "NOT_YET":
        return {"ok": True, "status": "not_yet"}
    picked = choice.startswith("M:")
    mv = _payment(repo, conn, ws, choice[2:] if picked else movement_id)
    if mv is None:
        return _error("unknown_movement")
    if repo.live_funding_for_movement(conn, mv.id) is not None:
        return _error("already_linked")
    if repo.movement_role(conn, mv.id) is not None:
        return _error("already_classified")
    if choice == "REGISTER":
        return {"ok": True, "status": "needs_exchange"}
    if choice == "NOT_EXCHANGE":
        repo.insert_movement_role(conn, ws, mv.id, MovementRoleKind.NOT_EXCHANGE)
        return {"ok": True, "status": "not_exchange"}

    movements = [mv.id]
    if choice == "ALL":
        exchanges = _candidates(repo, conn, ws, _day(mv))
        if not exchanges:
            return _error("no_open_exchange")
        exchange_ids, partner_id = [ex.id for ex in exchanges], exchanges[0].partner_id
    elif choice.startswith("ADD_TO:"):
        ex = repo.exchange_by_ref(conn, ws, choice[len("ADD_TO:"):])
        old = repo.live_funding_for_exchange(conn, ex.id) if ex is not None else None
        if old is None:
            return _error("exchange_not_paid")
        _undo(repo, conn, ws, old, "add_to", now)
        movements = [*old.movement_ids, mv.id]
        exchange_ids, partner_id = list(old.exchange_ids), ex.partner_id
    else:
        ref = (exchange_ref or "") if picked else choice
        ex = repo.exchange_by_ref(conn, ws, ref)
        if ex is None:
            return _error("unknown_exchange" if picked or ref[:1] in ("C", "c")
                          else "unknown_choice")
        if repo.live_funding_for_exchange(conn, ex.id) is not None:
            return _error("exchange_already_paid")
        exchange_ids, partner_id = [ex.id], ex.partner_id
    funding = create_funding(repo, conn, ws, movements, exchange_ids, queue, now)
    iban = mv.counterparty_iban_hash
    if iban and iban not in repo.partner_hashes(conn, ws):
        repo.add_partner_identifier(conn, ws, iban, partner_id)  # the owner picked it (§6.4)
    return {"ok": True, "status": "linked", "funding_ref": f"F{funding.number}"}


def _undo(repo: ReceivablesRepository, conn, ws: str, funding: Funding, reason: str,
          now: datetime) -> list[str]:
    """Revokes a live funding with its shares and roles, reverses its EUR charges and revokes
    the allocations on those lines. Returns the payers whose charges were reversed."""
    payers: list[str] = []
    for eid in funding.exchange_ids:
        for entry in repo.effective_charges_for_exchange(conn, ws, eid, "EUR"):
            repo.insert_entry(conn, LedgerEntry(
                _id(), ws, repo.next_number(conn, ws, "E"), entry.counterparty_id, "EUR",
                -entry.amount_minor, EntryKind.REVERSAL, now.date(), entry.source_ref, reason,
                reverses_id=entry.id))
            for aid in repo.live_allocation_ids_for_line(conn, ws, entry.source_ref):
                repo.revoke(conn, ws, "allocation", aid, reason, now)
            payers.append(entry.counterparty_id)
    repo.replace_funding_shares(conn, ws, funding.id, {}, reason, now)  # revokes, adds none
    for root in funding.movement_ids:
        for role_id in repo.live_role_ids_for_movement(conn, root):
            repo.revoke(conn, ws, "movement_role", role_id, reason, now)
    repo.revoke(conn, ws, "funding", funding.id, reason, now)
    return list(dict.fromkeys(payers))


def reverse_funding(repo: ReceivablesRepository, conn, ws: str, funding_id: str, reason: str,
                    queue: PendingQueue, now: datetime) -> list[PendingItem]:
    """Undoes a live funding and asks LINK_FUNDING again for each of its payments (a new
    question even if an earlier one was resolved). Returns those questions."""
    funding = repo.funding_by_id(conn, ws, funding_id)
    if funding is None:
        raise ValidationError("funding")
    for payer in _undo(repo, conn, ws, funding, reason, now):
        consume_credits(repo, conn, ws, payer, "EUR")
    return [ask_link_funding(repo, conn, ws, root, queue) for root in funding.movement_ids]
