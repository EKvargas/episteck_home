"""Effects of the receivables commands: one per command type (spec §8.1).

An effect runs inside ``FinanceRepository.run_command``, so its writes and the ``command_log``
row commit in ONE transaction and an exception leaves neither (E14). Payloads hold ids and
minor units that ``proposals`` validated; the domain functions validate again because the
data may have changed between the proposal and the owner's "yes". A refusal that must leave
no trace raises ``CommandRefused``. Results carry refs, labels and formatted amounts only.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .. import domain
from ..money import format_minor
from ..store.receivables_repo import IGNORE, ReceivablesRepository
from .corrections import correct_exchange, forgive_all, record_opening, reverse
from .explain import ask_explain_incoming, incoming_key
from .ledger import Evidence, LineInput, ValidationError, record_exchange
from .matcher import close_settled_questions, reopen_explain, unhide
from .model import (
    Counterparty, CounterpartyKind, MovementRoleKind, Opening, Receipt, ReceiptKind,
    Verification,
)
from .pending import PendingQueue
from .receipts import held_cash_shown, mark_held_cash, reallocate, record_receipt

IGNORED_LOOKBACK = timedelta(days=60)


class CommandRefused(Exception):
    """A refusal to return as is; raising it rolls the transaction back (nothing logged)."""

    def __init__(self, result: dict) -> None:
        super().__init__(result.get("error", "refused"))
        self.result = result


@dataclass(frozen=True)
class Ctx:
    repo: ReceivablesRepository
    ws: str
    queue: PendingQueue
    now: datetime
    description_rules: bool = False


# --- refs instead of ids -------------------------------------------------------------
def item_ref(repo: ReceivablesRepository, conn, ws: str, item_id: str) -> str | None:
    """An open item's public name: ``C<n>`` for an exchange line, ``E<n>`` for an opening."""
    found = repo.line_with_exchange(conn, ws, item_id)
    if found is not None:
        return f"C{found[1].number}"
    entry = repo.entry_by_id(conn, ws, item_id)
    return f"E{entry.number}" if entry else None


def allocation_rows(repo: ReceivablesRepository, conn, ws: str, rec: Receipt) -> list[dict]:
    return [{"item": item_ref(repo, conn, ws, a.line_id),
             "amount": format_minor(a.amount_minor, rec.currency), "method": a.method.value}
            for a in repo.live_allocations_for_receipt(conn, ws, rec.id)]


def undo_token(repo: ReceivablesRepository, root: str) -> str:
    """Opaque, stable handle of a movement the owner may un-ignore (never its id)."""
    return "U" + repo.hash_key(f"undo:{root}")[:10]


def ignored_movements(repo: ReceivablesRepository, conn, ws: str,
                      now: datetime) -> list[tuple[str, str, domain.Movement]]:
    """Incoming movements with a live NOT_EXCHANGE role from the last 60 days, newest first,
    as ``(undo token, root id, current movement)``."""
    since = now.date() - IGNORED_LOOKBACK
    found = []
    for root in repo.roots_with_role(conn, ws, MovementRoleKind.NOT_EXCHANGE):
        mv = repo.movement_current(conn, ws, root)
        day = (mv.booking_date or mv.value_date) if mv else None
        if mv is not None and mv.amount_minor > 0 and day is not None and day >= since:
            found.append((undo_token(repo, root), root, mv))
    return sorted(found, key=lambda t: t[2].booking_date or t[2].value_date, reverse=True)


def receipt_rule(repo: ReceivablesRepository, conn, ws: str, ref: str) -> str | None:
    """The payer-rule key behind a live BANK receipt ``R<n>``: the live rule for its movement
    still names its payer. ``None`` otherwise."""
    rec = repo.receipt_by_ref(conn, ws, ref)
    if rec is None or rec.kind is not ReceiptKind.BANK or rec.movement_id is None:
        return None
    mv = repo.movement_current(conn, ws, rec.movement_id)
    key = incoming_key(repo, mv, True) if mv else None  # True: as reopen_explain does
    return key if key and repo.rule_for(conn, ws, key) == rec.payer_id else None


def _revoke_rules(ctx: Ctx, conn, key: str, target: str, reason: str) -> int:
    """Revokes the newest live rules for ``key`` while they still say ``target``."""
    count = 0
    while ctx.repo.rule_for(conn, ctx.ws, key) == target:
        ctx.repo.revoke(conn, ctx.ws, "payer_rule", ctx.repo.live_rule_ids(conn, ctx.ws, key)[-1],
                        reason, ctx.now)
        count += 1
    return count


# --- effects -------------------------------------------------------------------------
def _lines(raw: list[dict]) -> list[LineInput]:
    return [LineInput(ln["payer_id"], ln["usd_minor"], ln["debt_currency"],
                      ln["beneficiary_note"], ln["eur_override_minor"]) for ln in raw]


def _exchange(ctx: Ctx, conn, p: dict) -> dict:
    ev = Evidence(p["ves_amount_minor"], None, date.fromisoformat(p["delivered_on"]),
                  ves_reference_hash=p["ves_reference_hash"])
    ex = record_exchange(ctx.repo, conn, ctx.ws, partner_id=p["partner_id"],
                         total_usd_minor=p["total_usd_minor"], lines=_lines(p["lines"]),
                         evidence=ev, now=ctx.now)
    return {"ok": True, "status": "recorded", "exchange_ref": f"C{ex.number}",
            "delivered_on": ex.delivered_on.isoformat(),
            "usd": format_minor(ex.total_usd_minor, "USD")}


def _receipt(ctx: Ctx, conn, p: dict) -> dict:
    rec = record_receipt(ctx.repo, conn, ctx.ws, kind=ReceiptKind(p["kind"]),
                         payer_id=p["payer_id"], currency=p["currency"],
                         amount_minor=p["amount_minor"],
                         received_on=date.fromisoformat(p["received_on"]),
                         verification=Verification.OWNER_CONFIRMED,
                         description=p["description"], queue=ctx.queue, now=ctx.now)
    return {"ok": True, "status": "recorded", "receipt_ref": f"R{rec.number}",
            "currency": rec.currency, "amount": format_minor(rec.amount_minor, rec.currency)}


def _correction(ctx: Ctx, conn, p: dict) -> dict:
    ex = correct_exchange(ctx.repo, conn, ctx.ws, p["exchange_id"], _lines(p["lines"]),
                          p["total_usd_minor"], p["reason"], ctx.now, queue=ctx.queue)
    usd = sum(ln.usd_minor for ln in ctx.repo.current_lines(conn, ex.id))
    return {"ok": True, "status": "corrected", "exchange_ref": f"C{ex.number}",
            "usd": format_minor(usd, "USD")}


def _forgive(ctx: Ctx, conn, p: dict) -> dict:
    written = forgive_all(ctx.repo, conn, ctx.ws, p["target_ref"], p["amount_minor"],
                          p["reason"], ctx.now)
    cur = written[0].currency
    return {"ok": True, "status": "forgiven", "currency": cur,
            "amount": format_minor(-sum(e.amount_minor for e in written), cur),
            "entries": [f"E{e.number}" for e in written]}


def _opening(ctx: Ctx, conn, p: dict) -> dict:
    entry = record_opening(ctx.repo, conn, ctx.ws, p["counterparty_id"], p["currency"],
                           p["amount_minor"], Opening(p["basis"]), p["note"], ctx.now,
                           queue=ctx.queue)
    return {"ok": True, "status": "recorded", "entry_ref": f"E{entry.number}"}


def _counterparty(ctx: Ctx, conn, p: dict) -> dict:
    kind = CounterpartyKind(p["kind"])
    cp = Counterparty(uuid.uuid4().hex, ctx.ws, kind, p["label"], "ACTIVE", p["pay_currency"],
                      p["settles_to"], Opening.UNKNOWN if kind is CounterpartyKind.FUND else None,
                      p["alert_below_minor"])
    ctx.repo.insert_counterparty(conn, cp, p["aliases"])
    return {"ok": True, "status": "created", "counterparty": cp.label, "kind": kind.value}


def _reverse(ctx: Ctx, conn, p: dict) -> dict:
    target, reason = p["target"], p["reason"]
    if target == "reopen":  # undo the answer to an EXPLAIN_INCOMING
        out = reopen_explain(ctx.repo, conn, ctx.ws, p["code"], ctx.queue, ctx.now)
        if not out["ok"]:
            raise CommandRefused(out)
        return {**out, "ref": p["code"]}
    if target == "unignore":
        return _unignore(ctx, conn, p["undo_ref"], reason)
    key = receipt_rule(ctx.repo, conn, ctx.ws, p["ref"])
    payer = ctx.repo.receipt_by_ref(conn, ctx.ws, p["ref"]).payer_id if key else None
    out = reverse(ctx.repo, conn, ctx.ws, p["ref"], reason, ctx.queue, ctx.now)
    if key:  # the rule that recorded it would record the next one the same way
        out["rules_revoked"] = _revoke_rules(ctx, conn, key, payer, reason)
    return out


def _unignore(ctx: Ctx, conn, token: str, reason: str) -> dict:
    """Undoes a NOT_EXCHANGE role (and the IGNORE rule that wrote it, with the other roles
    that rule wrote on its own, R36) and asks EXPLAIN_INCOMING again."""
    repo = ctx.repo
    match = next(((root, mv) for t, root, mv in ignored_movements(repo, conn, ctx.ws, ctx.now)
                  if t == token), None)
    if match is None:
        raise ValidationError("ref")
    root, mv = match
    for role_id in repo.live_role_ids_for_movement(conn, root):
        repo.revoke(conn, ctx.ws, "movement_role", role_id, reason, ctx.now)
    key = incoming_key(repo, mv, True)
    revoked = _revoke_rules(ctx, conn, key, IGNORE, reason) if key else 0
    question = ask_explain_incoming(repo, conn, ctx.ws, mv, ctx.queue).code
    also = unhide(repo, conn, ctx.ws, key, mv.id, ctx.queue, ctx.now) if revoked else []
    return {"ok": True, "status": "reopened", "question": question, "also_asked": also,
            "rules_revoked": revoked}


def _reallocate(ctx: Ctx, conn, p: dict) -> dict:
    repo = ctx.repo
    try:
        reallocate(repo, conn, ctx.ws, p["receipt_id"], [tuple(x) for x in p["parts"]], ctx.now)
    except ValidationError as exc:  # name the item, never the line id
        detail = dict(exc.detail)
        if "line" in detail:
            detail["item"] = item_ref(repo, conn, ctx.ws, detail.pop("line"))
        field = "allocations" if exc.field == "parts" else exc.field
        raise ValidationError(field, detail) from None
    rec = repo.receipt_by_id(conn, ctx.ws, p["receipt_id"])
    return {"ok": True, "status": "reallocated", "receipt_ref": f"R{rec.number}",
            "allocations": allocation_rows(repo, conn, ctx.ws, rec)}


def _held_cash(ctx: Ctx, conn, p: dict) -> dict:
    cur = p["currency"]
    mark_held_cash(ctx.repo, conn, ctx.ws, p["counterparty_id"], cur, p["amount_minor"], ctx.now)
    shown = held_cash_shown(ctx.repo, conn, ctx.ws, p["counterparty_id"], cur)
    cp = ctx.repo.get_counterparty(conn, ctx.ws, p["counterparty_id"])
    return {"ok": True, "status": "recorded", "counterparty": cp.label, "currency": cur,
            "amount": format_minor(p["amount_minor"], cur),
            "shown": None if shown is None else format_minor(shown, cur)}


EFFECTS: dict[str, Callable[[Ctx, object, dict], dict]] = {
    "exchange": _exchange, "receipt": _receipt, "correction": _correction,
    "forgive": _forgive, "opening": _opening, "counterparty": _counterparty,
    "reverse": _reverse, "reallocate": _reallocate, "held_cash": _held_cash,
}


def execute(ctx: Ctx, conn, command: str, payload: dict) -> dict:
    """Runs one command's effect, then closes the questions it may have answered (R32)."""
    result = EFFECTS[command](ctx, conn, payload)
    close_settled_questions(ctx.repo, conn, ctx.ws, ctx.queue)
    return result
