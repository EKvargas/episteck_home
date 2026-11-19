"""Matcher: after each sync, turn new bank movements into fundings, receipts and questions.

It runs inside the sync unit and never calls Home; its writes are system writes (ADR-0016).
``Matcher.run`` owns one transaction per run, so a crash leaves nothing half done. The other
functions take the caller's connection and validate before their first write.

Spec §6.2 (auto-link), §6.4 (pending kinds), §6.5 (funds), §7 F2/F3/F9; ruling R32. Option
values are ``CP:<counterparty id>`` and ``M:<root movement id>``; payloads carry their labels
and never an IBAN. Logs carry kinds and counts only.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta

from .. import domain
from ..money import format_minor
from ..store.receivables_repo import IGNORE, ReceivablesRepository
from .allocation import plan_allocation
from .corrections import reverse, undo_receipt
from .funding import ask_link_funding, funding_day, redo_funding, reverse_funding, try_link
from .fx import deviation, implied_rate
from .ledger import ValidationError
from .model import (
    FUND_ALERT_DEFAULT_MINOR, LINK_BAND, AllocationMethod, CounterpartyKind, EntryKind,
    MovementRoleKind, Opening, PendingItem, PendingKind, ReceiptKind, Verification,
)
from .pending import PendingQueue
from .receipts import CURRENCIES, record_receipt
from .text import description_key

logger = logging.getLogger("finance.matcher")

COUNT_KEYS = ("linked", "waiting", "asked", "receipts", "ignored")
LOOKBACK = timedelta(days=30)  # PREVIOUS_UNPAID lists payments of the last 30 days
PICK_LIMIT = 8
REVIEW_WINDOW = timedelta(weeks=4)
AUTO_RESOLUTION = "auto:settled"
_PAYERS = (CounterpartyKind.PERSON, CounterpartyKind.FUND)
_KNOWN_OPENING = (Opening.APPROXIMATE, Opening.CONFIRMED)
_REOPENED = "explain_reopened"
_BOOKED_CHANGED = "booked_amount_changed"


def _day(mv: domain.Movement) -> date | None:
    return mv.booking_date or mv.value_date


def _aware(value: datetime, what: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware")
    return value


def _error(code: str) -> dict:
    return {"ok": False, "error": code}


def incoming_key(repo: ReceivablesRepository, mv: domain.Movement,
                 description_rules: bool) -> str | None:
    """The payer-rule key of an incoming movement: its IBAN hash, else (only with
    ``description_rules``) the hash of its normalised description; ``None`` when neither."""
    if mv.counterparty_iban_hash:
        return mv.counterparty_iban_hash
    text = description_key(mv.remittance or "")
    return repo.hash_key(text) if description_rules and text else None


def _exact(repo: ReceivablesRepository, conn, ws: str, cp_id: str, currency: str,
           amount: int) -> bool:
    """The open items (a PERSON's opening included, R29), or an exact subset, equal ``amount``."""
    items = repo.open_lines(conn, ws, cp_id, currency)
    return bool(items) and (sum(i.outstanding_minor for i in items) == amount or
                            plan_allocation(amount, items).method is AllocationMethod.AUTO_EXACT)


def ask_explain_incoming(repo: ReceivablesRepository, conn, ws: str, movement: domain.Movement,
                         queue: PendingQueue) -> PendingItem:
    """Asks who sent an incoming payment (EXPLAIN_INCOMING), or returns the open question.

    Options: the one PERSON whose open items or an exact subset of them equal the amount, then
    every other PERSON or FUND with a balance in that currency, then ``OTHER`` and
    ``NOT_EXCHANGE``. Key ``EXPLAIN_INCOMING:<root movement id>``.
    """
    mv = repo.movement_current(conn, ws, movement.id) or movement
    if mv.amount_minor <= 0:
        raise ValidationError("movement")
    root, day = repo.movement_root(conn, mv.id), _day(mv)
    found = [(cp, cp.kind is CounterpartyKind.PERSON
              and _exact(repo, conn, ws, cp.id, mv.currency, mv.amount_minor))
             for cp in repo.list_counterparties(conn, ws) if cp.kind in _PAYERS]
    found = [(cp, hit) for cp, hit in found
             if hit or repo.balance(conn, ws, cp.id, mv.currency) != 0]
    exact = [cp for cp, hit in found if hit]
    first = exact if len(exact) == 1 else []
    ordered = first + [cp for cp, _ in found if cp not in first]
    payload = {
        "movement_id": root, "booking_date": day.isoformat() if day else None,
        "currency": mv.currency, "amount": format_minor(mv.amount_minor, mv.currency),
        "sender": description_key(mv.counterparty_name or mv.remittance or "")[:20].strip(),
        "exact": f"CP:{first[0].id}" if first else None,
        "labels": {f"CP:{cp.id}": cp.label for cp in ordered}}
    options = [f"CP:{cp.id}" for cp in ordered] + ["OTHER", "NOT_EXCHANGE"]
    return queue.add(conn, ws, PendingKind.EXPLAIN_INCOMING, options, payload,
                     f"EXPLAIN_INCOMING:{root}")


def _remember(repo: ReceivablesRepository, conn, ws: str, key: str | None,
              cp_id: str | None) -> bool:
    """A payer rule ``key`` → ``cp_id`` (``None``: IGNORE) unless the live one already says so."""
    if key is None:
        return False
    if repo.rule_for(conn, ws, key) != (cp_id or IGNORE):
        repo.insert_payer_rule(conn, ws, key, cp_id)
    return True


def resolve_explain_incoming(repo: ReceivablesRepository, conn, ws: str, movement_id: str,
                             choice: str, queue: PendingQueue, now: datetime, *,
                             description_rules: bool = False) -> dict:
    """Applies the owner's answer to EXPLAIN_INCOMING: ``CP:<id>`` records a BANK receipt for
    that person or fund, ``NOT_EXCHANGE`` the role; both write a payer rule (IGNORE for
    ``NOT_EXCHANGE``) when the movement has a key (``incoming_key``), so the next payment from
    that sender needs no answer. ``OTHER`` writes nothing: the caller asks which counterparty
    and answers again with ``CP:<id>``. Refusals write nothing; the caller resolves the item."""
    mv = repo.movement_current(conn, ws, movement_id or "")
    if mv is None or mv.amount_minor <= 0 or mv.currency not in CURRENCIES or _day(mv) is None:
        return _error("unknown_movement")
    if (repo.movement_role(conn, mv.id) is not None
            or repo.live_receipt_for_movement(conn, mv.id) is not None
            or repo.live_funding_for_movement(conn, mv.id) is not None):
        return _error("already_classified")
    choice, key = choice.strip(), incoming_key(repo, mv, description_rules)
    if choice == "OTHER":
        return {"ok": True, "status": "needs_counterparty"}
    if choice == "NOT_EXCHANGE":
        rule = _remember(repo, conn, ws, key, None)
        repo.insert_movement_role(conn, ws, mv.id, MovementRoleKind.NOT_EXCHANGE)
        return {"ok": True, "status": "not_exchange", "rule": rule}
    if not choice.startswith("CP:"):
        return _error("unknown_choice")
    cp = repo.get_counterparty(conn, ws, choice[3:])
    if cp is None or cp.kind not in _PAYERS:
        return _error("unknown_counterparty")
    rec = record_receipt(repo, conn, ws, kind=ReceiptKind.BANK, payer_id=cp.id,
                         currency=mv.currency, amount_minor=mv.amount_minor,
                         received_on=_day(mv), verification=Verification.BANK_POSTED,
                         movement_id=mv.id, queue=queue, now=now)
    rule = _remember(repo, conn, ws, key, cp.id)
    return {"ok": True, "status": "recorded", "receipt_ref": f"R{rec.number}", "rule": rule}


def reopen_explain(repo: ReceivablesRepository, conn, ws: str, code: str, queue: PendingQueue,
                   now: datetime) -> dict:
    """Undoes the answer to a resolved EXPLAIN_INCOMING and asks again: its receipt (by the
    normal reversal, which asks) or its NOT_EXCHANGE role, and the live payer rule for the
    movement's key when it says what that answer said. Refusals write nothing."""
    item = repo.pending_by_code(conn, ws, code)
    if item is None or item.kind is not PendingKind.EXPLAIN_INCOMING:
        return _error("unknown_pending")
    if item.resolved_at is None:
        return _error("not_resolved")
    mv = repo.movement_current(conn, ws, item.payload.get("movement_id") or "")
    if mv is None or mv.amount_minor <= 0:
        return _error("unknown_movement")
    if repo.live_funding_for_movement(conn, mv.id) is not None:
        return _error("already_linked")
    receipt = repo.live_receipt_for_movement(conn, mv.id)
    question = None
    if receipt is not None:
        question = reverse(repo, conn, ws, f"R{receipt.number}", _REOPENED, queue, now)["question"]
    for role_id in repo.live_role_ids_for_movement(conn, mv.id):
        repo.revoke(conn, ws, "movement_role", role_id, _REOPENED, now)
    key = incoming_key(repo, mv, True)  # a description rule exists only if rules were on
    rule_ids = repo.live_rule_ids(conn, ws, key) if key else []
    if rule_ids and repo.rule_for(conn, ws, key) == (receipt.payer_id if receipt else IGNORE):
        repo.revoke(conn, ws, "payer_rule", rule_ids[-1], _REOPENED, now)
    if question is None:
        question = ask_explain_incoming(repo, conn, ws, mv, queue).code
    return {"ok": True, "status": "reopened", "question": question}


def close_settled_questions(repo: ReceivablesRepository, conn, ws: str,
                            queue: PendingQueue) -> int:
    """Resolves (``human=False``) the open questions the data has answered since: a
    LINK_FUNDING or EXPLAIN_INCOMING whose movement is linked or classified, a PREVIOUS_UNPAID
    whose exchange is paid or reversed. Call it after a link made elsewhere (R32)."""
    closed = 0
    for item in repo.pending_open(conn, ws):
        if item.kind in (PendingKind.LINK_FUNDING, PendingKind.EXPLAIN_INCOMING):
            mid = item.payload.get("movement_id") or ""
            done = (repo.live_funding_for_movement(conn, mid) is not None
                    or repo.movement_role(conn, mid) is not None)
        elif item.kind is PendingKind.PREVIOUS_UNPAID:
            ex = repo.exchange_by_ref(conn, ws, item.payload.get("exchange_ref") or "")
            done = ex is None or repo.live_funding_for_exchange(conn, ex.id) is not None
        else:
            continue
        if done:
            queue.resolve(conn, ws, item.code, AUTO_RESOLUTION, human=False)
            closed += 1
    return closed


class Matcher:
    def __init__(self, repo: ReceivablesRepository, queue: PendingQueue,
                 clock: Callable[[], datetime], description_rules: bool) -> None:
        self._repo = repo
        self._queue = queue
        self._clock = clock
        self._rules = description_rules

    def run(self, ws: str, sync_started_at: datetime) -> dict[str, int]:
        """One pass over the movements after the cursor, then the periodic questions and
        notices. The first run for a workspace only sets the cursor (history is never asked
        about, R32). An inactive workspace is left alone."""
        started = _aware(sync_started_at, "sync_started_at")
        now = _aware(self._clock(), "clock")
        counts = dict.fromkeys(COUNT_KEYS, 0)
        workspace = self._repo.base.get_workspace(ws)
        if workspace is None or workspace.status is not domain.WorkspaceStatus.ACTIVE:
            return counts
        repo = self._repo
        with repo.tx() as conn:
            state = repo.cursor_state(conn, ws)
            if state is None:
                top = repo.max_movement_rowid(conn, ws)
                repo.init_cursor(conn, ws, top)
                state = (top, top)
            cursor, start = state
            last = cursor
            for rowid, mv in repo.movements_after(conn, ws, cursor):
                self._movement(conn, ws, mv, now, counts)
                last = rowid
            close_settled_questions(repo, conn, ws, self._queue)
            self._previous_unpaid(conn, ws, started, now, counts)
            self._waiting(conn, ws, start, cursor, counts)
            self._funds(conn, ws)
            self._openings(conn, ws, now, counts)
            repo.set_cursor(conn, ws, last)
        logger.info("matcher run: linked=%d waiting=%d asked=%d receipts=%d ignored=%d",
                    *(counts[k] for k in COUNT_KEYS))
        return counts

    def _count_new(self, conn, ws: str, key: str, counts: dict[str, int]) -> None:
        """Counts a question about to be asked unless one is already open for ``key``."""
        if self._repo.pending_by_dedupe(conn, ws, key) is None:
            counts["asked"] += 1

    # --- steps 1-3: one new movement ----------------------------------------------
    def _movement(self, conn, ws: str, mv: domain.Movement, now: datetime,
                  counts: dict[str, int]) -> None:
        repo = self._repo
        current = repo.movement_current(conn, ws, mv.id)
        if current is None or current.id != mv.id or _day(mv) is None:
            return  # superseded: its successor comes later in this run
        root = repo.movement_root(conn, mv.id)
        if root != mv.id and self._successor(conn, ws, mv, root, now, counts):
            return
        if (repo.movement_role(conn, root) is not None
                or repo.live_funding_for_movement(conn, root) is not None
                or repo.live_receipt_for_movement(conn, root) is not None):
            return
        if (mv.currency == "EUR" and mv.amount_minor < 0
                and mv.counterparty_iban_hash in repo.partner_hashes(conn, ws)):
            was_open = repo.pending_by_dedupe(conn, ws, f"LINK_FUNDING:{root}") is not None
            result = try_link(repo, conn, ws, mv, self._queue, now)
            counts["linked"] += int(result == "LINKED")
            counts["waiting"] += int(result == "WAITING")
            counts["asked"] += int(result == "AMBIGUOUS" and not was_open)
        elif (mv.amount_minor > 0 and mv.currency in CURRENCIES
              and mv.account_id in repo.watched_accounts(conn, ws)):
            self._incoming(conn, ws, mv, root, now, counts)

    def _incoming(self, conn, ws: str, mv: domain.Movement, root: str, now: datetime,
                  counts: dict[str, int]) -> None:
        repo = self._repo
        if mv.counterparty_iban_hash and mv.counterparty_iban_hash in repo.own_hashes(conn, ws):
            counts["ignored"] += 1  # a transfer between the owner's own accounts
            return
        key = incoming_key(repo, mv, self._rules)
        target = repo.rule_for(conn, ws, key) if key else None
        if target == IGNORE:
            repo.insert_movement_role(conn, ws, mv.id, MovementRoleKind.NOT_EXCHANGE)
            counts["ignored"] += 1
            return
        if target is not None:
            try:
                record_receipt(repo, conn, ws, kind=ReceiptKind.BANK, payer_id=target,
                               currency=mv.currency, amount_minor=mv.amount_minor,
                               received_on=_day(mv), verification=Verification.BANK_POSTED,
                               movement_id=mv.id, queue=self._queue, now=now)
                counts["receipts"] += 1
                return
            except ValidationError:
                pass  # the rule's counterparty cannot take it (nothing written): ask instead
        self._count_new(conn, ws, f"EXPLAIN_INCOMING:{root}", counts)
        ask_explain_incoming(repo, conn, ws, mv, self._queue)

    def _successor(self, conn, ws: str, mv: domain.Movement, root: str, now: datetime,
                   counts: dict[str, int]) -> bool:
        """A BOOKED successor of a movement already linked or recorded (R32). The same amount
        changes nothing. Another amount makes the funding again with the new EUR (or undoes it
        and asks when the rate leaves LINK_BAND) or records the receipt again; a notice says
        so. False when the root has neither a funding nor a receipt."""
        repo, queue = self._repo, self._queue
        funding = repo.live_funding_for_movement(conn, root)
        if funding is not None:
            pays = [repo.movement_current(conn, ws, r) for r in funding.movement_ids]
            if any(p is None or p.currency != "EUR" or p.amount_minor >= 0 for p in pays):
                return True
            eur = sum(-p.amount_minor for p in pays)
            if eur == funding.eur_minor:
                return True
            usd = sum(ln.usd_minor for eid in funding.exchange_ids
                      for ln in repo.current_lines(conn, eid))
            ecb = repo.usd_per_eur_on(conn, funding_day(repo, conn, ws, funding))
            new_ref = None
            if ecb is None or deviation(implied_rate(eur, usd), ecb) <= LINK_BAND:
                new = redo_funding(repo, conn, ws, funding.id, _BOOKED_CHANGED, queue, now)
                new_ref = f"F{new.number}"
            else:
                for r in funding.movement_ids:
                    self._count_new(conn, ws, f"LINK_FUNDING:{r}", counts)
                reverse_funding(repo, conn, ws, funding.id, _BOOKED_CHANGED, queue, now)
            ref = f"F{funding.number}"
            queue.notice(conn, ws, f"{_BOOKED_CHANGED}:{ref}", {
                "funding_ref": ref, "new_funding_ref": new_ref,
                "eur_before": format_minor(funding.eur_minor, "EUR"),
                "eur_after": format_minor(eur, "EUR")})
            return True
        rec = repo.live_receipt_for_movement(conn, root)
        if rec is None:
            return False
        if mv.amount_minor > 0 and mv.currency == rec.currency and mv.amount_minor != rec.amount_minor:
            undo_receipt(repo, conn, ws, rec, _BOOKED_CHANGED, queue, now)
            new = record_receipt(repo, conn, ws, kind=ReceiptKind.BANK, payer_id=rec.payer_id,
                                 currency=mv.currency, amount_minor=mv.amount_minor,
                                 received_on=_day(mv), verification=Verification.BANK_POSTED,
                                 movement_id=mv.id, queue=queue, now=now)
            ref = f"R{rec.number}"
            queue.notice(conn, ws, f"{_BOOKED_CHANGED}:{ref}", {
                "receipt_ref": ref, "new_receipt_ref": f"R{new.number}", "currency": mv.currency,
                "amount_before": format_minor(rec.amount_minor, mv.currency),
                "amount_after": format_minor(mv.amount_minor, mv.currency)})
        return True

    # --- step 4: previous exchange unpaid -----------------------------------------
    def _previous_unpaid(self, conn, ws: str, started: datetime, now: datetime,
                         counts: dict[str, int]) -> None:
        """Once a sync has run after an exchange was registered, every older exchange still
        OPEN is asked about: once per newest exchange, never while its question is open."""
        repo = self._repo
        registered = [ex for ex in repo.live_exchanges(conn, ws) if ex.created_at < started]
        if not registered:
            return
        newest = registered[-1]
        older = [ex for ex in repo.open_exchanges(conn, ws) if ex.number < newest.number]
        if not older:
            return
        options, labels = self._recent_payments(conn, ws, now)
        for ex in older:
            key = f"PREVIOUS_UNPAID:{ex.id}"
            last = repo.pending_by_dedupe(conn, ws, key, include_resolved=True)
            if last is not None and (last.resolved_at is None
                                     or last.payload.get("after_ref") == f"C{newest.number}"):
                continue
            usd = sum(ln.usd_minor for ln in repo.current_lines(conn, ex.id))
            self._queue.add(conn, ws, PendingKind.PREVIOUS_UNPAID, [*options, "NOT_YET"], {
                "exchange_ref": f"C{ex.number}", "delivered_on": ex.delivered_on.isoformat(),
                "usd": format_minor(usd, "USD"), "after_ref": f"C{newest.number}",
                "labels": labels}, key)
            counts["asked"] += 1

    def _recent_payments(self, conn, ws: str, now: datetime) -> tuple[list[str], dict]:
        """Up to 8 unlinked outgoing EUR payments of the last 30 days (not to an own IBAN),
        newest first: ``M:<root id>`` options with ``dd/mm · amount · name[:20]`` labels."""
        repo = self._repo
        own = repo.own_hashes(conn, ws)
        options: list[str] = []
        labels: dict[str, str] = {}
        for mv in repo.recent_outgoing(conn, ws, "EUR", now.date() - LOOKBACK):
            root = repo.movement_root(conn, mv.id)
            if (mv.counterparty_iban_hash in own or repo.movement_role(conn, root) is not None
                    or repo.live_funding_for_movement(conn, root) is not None):
                continue
            options.append(f"M:{root}")
            parts = (f"{_day(mv):%d/%m}", format_minor(-mv.amount_minor, "EUR"),
                     mv.counterparty_name[:20])
            labels[f"M:{root}"] = " · ".join(p for p in parts if p)
            if len(options) == PICK_LIMIT:
                break
        return options, labels

    # --- step 5: payments still waiting -------------------------------------------
    def _waiting(self, conn, ws: str, start: int, cursor: int, counts: dict[str, int]) -> None:
        """A partner payment still unlinked after the run that first saw it becomes
        LINK_FUNDING, once: an answer that wrote nothing (``REGISTER``) is not asked again,
        the payment stays in PREVIOUS_UNPAID's pick list. One from before go-live
        (``start``) is never asked about (R32)."""
        repo = self._repo
        for mv in repo.unlinked_partner_payments(conn, ws):
            root = repo.movement_root(conn, mv.id)
            seen = [repo.movement_rowid(conn, m) or 0 for m in (root, mv.id)]
            key = f"LINK_FUNDING:{root}"
            if (_day(mv) is None or not any(start < rid <= cursor for rid in seen)
                    or repo.pending_by_dedupe(conn, ws, key, include_resolved=True) is not None):
                continue
            counts["asked"] += 1
            ask_link_funding(repo, conn, ws, mv.id, self._queue)

    # --- step 6: funds below their alert ------------------------------------------
    def _funds(self, conn, ws: str) -> None:
        """``fund_low`` (§6.5): a fund with a stated opening holding less USD than its alert.
        Deduplicated on the entry where the held amount last crossed below the alert (counted
        from the first OPENING), so each crossing notifies once."""
        repo = self._repo
        for cp in repo.list_counterparties(conn, ws):
            if (cp.kind is not CounterpartyKind.FUND or cp.status != "ACTIVE"
                    or cp.opening not in _KNOWN_OPENING):
                continue
            alert = FUND_ALERT_DEFAULT_MINOR if cp.alert_below_minor is None \
                else cp.alert_below_minor
            entries = [e for e in repo.entries(conn, ws, cp.id)
                       if e.currency == "USD" and repo.is_live(conn, "ledger_entry", e.id)]
            openings = [e.number for e in entries if e.kind is EntryKind.OPENING]
            if not openings:
                continue
            held, above, crossing = 0, True, None
            for e in entries:
                held -= e.amount_minor
                if e.number >= openings[0]:
                    if above and held < alert:
                        crossing = e
                    above = held >= alert
            if above or crossing is None:
                continue
            ref = f"E{crossing.number}"
            self._queue.notice(conn, ws, f"fund_low:{cp.id}:{ref}", {
                "counterparty": cp.label, "currency": "USD", "held": format_minor(held, "USD"),
                "alert": format_minor(alert, "USD"), "entry_ref": ref},
                dedupe_include_resolved=True)

    # --- step 7: openings to review -----------------------------------------------
    def _openings(self, conn, ws: str, now: datetime, counts: dict[str, int]) -> None:
        """REVIEW_OPENING: an APPROXIMATE or UNKNOWN opening, once per ISO week during the 4
        weeks after the first OPENING entry (an UNKNOWN fund: after it was first asked about),
        never while an earlier review is open."""
        repo = self._repo
        year, week, _ = now.isocalendar()
        for cp in repo.list_counterparties(conn, ws):
            basis = cp.opening or (Opening.UNKNOWN if cp.kind is CounterpartyKind.FUND else None)
            if cp.status != "ACTIVE" or basis not in (Opening.APPROXIMATE, Opening.UNKNOWN):
                continue
            prefix = f"REVIEW_OPENING:{cp.id}:"
            asked = repo.pending_by_prefix(conn, ws, prefix)
            if any(p.resolved_at is None for p in asked):
                continue
            firsts = [e.effective_on for e in repo.entries(conn, ws, cp.id)
                      if e.kind is EntryKind.OPENING]
            begin = min(firsts) if firsts else min(
                (p.created_at.date() for p in asked), default=now.date())
            key = f"{prefix}{year}-W{week:02d}"
            if now.date() >= begin + REVIEW_WINDOW or any(p.dedupe_key == key for p in asked):
                continue
            sign = -1 if cp.kind is CounterpartyKind.FUND else 1  # a fund's held amount
            stated = repo.effective_entries_for_refs(conn, ws, [cp.id], (EntryKind.OPENING,))
            self._queue.add(conn, ws, PendingKind.REVIEW_OPENING, ["CONFIRM", "LATER"], {
                "counterparty": cp.label, "kind": cp.kind.value, "opening": basis.value,
                "openings": [{"entry_ref": f"E{e.number}", "currency": e.currency,
                              "amount": format_minor(sign * e.amount_minor, e.currency)}
                             for e in stated]}, key, dedupe_include_resolved=True)
            counts["asked"] += 1
