"""ReceivablesService: one Home request per call, then a read, a proposal or an answer.

* Every public method takes the delegation first and authorizes ONCE through the
  ``Authorizer`` port: reads with ``Requirement(SELF, "VIEW")``, writes with
  ``Requirement(SELF, "CREATE")``. The actor Home returns must hold role OWNER in this
  workspace and the workspace must be ACTIVE. Any non-answer raises the I1 refusal
  (``SessionInvalid``, ``AccessDenied``, ``PolicyUnavailable``, ``FeatureOff``) and nothing is
  read or written.
* Two phases (spec §8.1): a proposal writes only a CONFIRM pending item. Its command key is
  the sha256 of the command type, its canonical payload and the UTC date (a command already
  completed that day makes a new proposal a ``possible_duplicate``); the open CONFIRM is
  found by the same content without the date, and without dates filled in by default, so an
  agent retry across midnight returns it (m1). ``resolve(code, "yes")`` runs the STORED
  payload through ``FinanceRepository.run_command`` with the human actor and this process's
  machine caller and channel: "yes" executes exactly what the echo showed (R42), and a
  possible duplicate runs only on an explicit "Es otro" (R43). The MCP process (Telegram via
  Hermes) and the REST process (web) each build their own service: ``MCP_CALLER`` /
  ``API_CALLER``. A REST ``Idempotency-Key`` is a proposal's ``client_key``.
* A tap means exactly the option the owner saw: private options are stable tokens, and a
  number is refused once the options changed since they were delivered (R44).
* Domain refusals come back as ``{"ok": False, "error": <code>, ...}``; any other exception
  as ``{"ok": False, "error": "internal_error"}`` with nothing committed.
* Logs carry kinds and counts only: never labels, amounts, exception messages or
  ``ValidationError.detail``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .. import domain
from ..authz import ANSWERED, SELF, SESSION_INVALID, Authorizer, Requirement
from ..service import AccessDenied, FeatureOff, PolicyUnavailable, SessionInvalid
from ..store.receivables_repo import (
    AlreadyRevoked, DuplicateAlias, DuplicateReceipt, ReceivablesRepository,
)
from ..store.repo import FinanceRepository, IdempotencyConflict
from . import commands, proposals, views
from .commands import CommandRefused, Ctx, changed
from .corrections import record_opening
from .funding import AlreadyLinked, ask_link_funding, link_choice
from .ledger import ValidationError, receivables_view
from .matcher import ask_previous_unpaid, close_settled_questions, resolve_explain_incoming
from .model import CounterpartyKind, EntryKind, Opening, PendingItem, PendingKind
from .pending import AlreadyResolved, PendingQueue, UnknownPending
from .proposals import Clarify, Proposal
from .text import normalize_alias

logger = logging.getLogger("finance.receivables")

OWNER_ROLE = "OWNER"
SNOOZE = timedelta(days=7)
CLIENT_KEY_CHARS = 200
CONFIRM_OPTIONS = ("yes", "correct", "cancel")
DUPLICATE_OPTIONS = ("other", "same")  # [Es otro] [Es el mismo]
SUPERSEDED = "superseded"  # an old echo replaced by its re-proposal (R63)
# answers the data overtook (m3): the item resolves as "stale" and is asked again if relevant
STALE_LINK = frozenset({"exchange_already_paid", "unknown_exchange", "already_linked",
                        "already_classified", "unknown_movement", "exchange_not_paid",
                        "no_open_exchange"})
STALE_EXPLAIN = frozenset({"already_classified", "unknown_movement"})
_CLOSE_WORDS = {"no": "cancel", "cancel": "cancel", "cancelar": "cancel",
                "correct": "correct", "corregir": "correct"}
_CONFIRM_WORDS = {"yes": "yes", "y": "yes", "si": "yes", "ok": "yes", "confirm": "yes",
                  "confirmar": "yes", **_CLOSE_WORDS}
_DUPLICATE_WORDS = {"other": "yes", "otro": "yes", "es otro": "yes",  # never "yes" (R43)
                    "same": "same", "mismo": "same", "es el mismo": "same", **_CLOSE_WORDS}
_CONFIRM_STATUS = {"cancel": "cancelled", "correct": "needs_correction", "same": "not_recorded"}
_REVIEW_WORDS = {"confirm": "CONFIRM", "confirmar": "CONFIRM", "yes": "CONFIRM", "si": "CONFIRM",
                 "later": "LATER", "mas tarde": "LATER", "luego": "LATER"}
_RESULT_REFS = ("exchange_ref", "receipt_ref", "entry_ref", "ref", "counterparty")


@dataclass(frozen=True)
class Caller:
    """Who runs the command for the human: ``command_log.machine_caller`` and ``channel``."""

    machine: str
    channel: str


MCP_CALLER = Caller("finance-mcp", "telegram")
API_CALLER = Caller("finance-api", "web")


def content_key(command: str, payload: dict, now: datetime | None) -> str:
    """sha256 of the command, its canonical payload and the UTC date of ``now`` (none: undated)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    day = "" if now is None else now.astimezone(timezone.utc).date().isoformat()
    return hashlib.sha256(f"{command}\n{canonical}\n{day}".encode()).hexdigest()


def lookup_key(p: Proposal) -> str:
    """The open-CONFIRM key: undated, and blind to dates filled in by default (m1)."""
    stated = {k: None if k in p.defaults else v for k, v in p.payload.items()}
    return content_key(p.command, stated, None)


def _client_handle(value) -> str:
    """A REST Idempotency-Key as part of a ``command_log`` key (hashed, never stored raw)."""
    raw = proposals.text(value, "client_key")
    if len(raw) > CLIENT_KEY_CHARS:
        raise ValidationError("client_key", {"max": str(CLIENT_KEY_CHARS)})
    return hashlib.sha256(raw.encode()).hexdigest()


def _result_ref(result: dict) -> str | None:
    for key in _RESULT_REFS:
        if result.get(key):
            return result[key]
    return (result.get("entries") or [None])[0]


def _current_defaults(item: PendingItem, p: Proposal, now: datetime) -> bool:
    """The stored CONFIRM's dates that were filled in by default are within 1 day of today
    (UTC), so "yes" would not record a stale date (R49)."""
    today = now.astimezone(timezone.utc).date()
    for key in p.defaults:
        try:
            stored = datetime.fromisoformat(str(item.payload["payload"][key])).date()
        except (KeyError, TypeError, ValueError):
            return False
        if abs((stored - today).days) > 1:
            return False
    return True


def _confirm_view(item: PendingItem) -> dict:
    p = item.payload
    return {"ok": True, "status": p["status"], "code": item.code, "echo": p["echo"],
            "high_value": p["high_value"], "options": list(item.options)}


def _unknown(item: PendingItem, token: Callable[[str], str],
             reason: str | None = None) -> CommandRefused:
    out = {"ok": False, "error": "unknown_choice"}
    if reason:
        out["reason"] = reason
    out["expected"] = [views.choice(o, token) for o in item.options]
    return CommandRefused(out)


def _choose(item: PendingItem, choice: str, token: Callable[[str], str]) -> str:
    """The option an answer means: its value or token ("C3", "O1a2b3c4d"), its label, a word
    for a CONFIRM / REVIEW_OPENING ("sí", "Es otro", "más tarde"), or its number ("2") while
    the options are still the ones the owner was shown (R44). A possible duplicate takes no
    number and no "yes": only "Es otro" records it (R43). Else ``unknown_choice``."""
    if item.kind is PendingKind.INFO:
        return "dismissed"
    raw = choice.strip()
    duplicate = (item.kind is PendingKind.CONFIRM
                 and item.payload.get("status") == "possible_duplicate")
    if raw.isascii() and raw.isdigit():
        if item.numbers_unsafe(views.PRIVATE_OPTIONS):
            raise _unknown(item, token, "options_changed")
        n = int(raw)
        if duplicate or not 1 <= n <= len(item.options):
            raise _unknown(item, token)
        raw = item.options[n - 1]
    word = normalize_alias(raw)
    if item.kind is PendingKind.CONFIRM:
        found = (_DUPLICATE_WORDS if duplicate else _CONFIRM_WORDS).get(word)
    elif item.kind is PendingKind.REVIEW_OPENING:
        found = _REVIEW_WORDS.get(word)
    else:
        found = next((o for o in item.options
                      if raw == o or raw.upper() == views.choice(o, token).upper()), None)
        labels = item.payload.get("labels") or {}
        found = found or next((o for o, label in labels.items()
                               if o in item.options and word == normalize_alias(label)), None)
    if found is None:
        raise _unknown(item, token)
    return found


class ReceivablesService:
    def __init__(self, repo: FinanceRepository, authorizer: Authorizer, workspace_id: str,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc), *,
                 caller: Caller = MCP_CALLER, description_rules: bool = False) -> None:
        self._base = repo
        self._rx = ReceivablesRepository(repo)
        self._authorizer = authorizer
        self._ws = workspace_id
        self._clock = clock
        self._caller = caller
        self._rules = description_rules
        self._queue = PendingQueue(self._rx, clock)

    # --- authorization ---------------------------------------------------------------
    def _authorize(self, delegation: str | None, action: str) -> str:
        if not delegation:
            raise SessionInvalid()
        try:
            batch = self._authorizer.authorize(delegation, [Requirement(SELF, action)])
        except Exception:
            logger.warning("receivables authorization not granted: authorizer_error")
            raise PolicyUnavailable() from None
        if batch.outcome == SESSION_INVALID:
            raise SessionInvalid()
        if batch.outcome != ANSWERED:
            raise PolicyUnavailable()
        if not batch.is_allowed(SELF, action):
            raise AccessDenied()
        actor = batch.actor_person_id
        with self._rx.read() as conn:
            role = self._rx.member_role(conn, self._ws, actor) if actor else None
        if role != OWNER_ROLE:
            raise AccessDenied()
        workspace = self._base.get_workspace(self._ws)
        if workspace is None or workspace.status is not domain.WorkspaceStatus.ACTIVE:
            raise FeatureOff()
        return actor

    def _ctx(self) -> Ctx:
        return Ctx(self._rx, self._ws, self._queue, self._clock(), self._rules)

    def _token(self, value: str) -> str:
        return views.choice_token(self._rx, value)

    def _guard(self, call: Callable[[], dict]) -> dict:
        """Domain refusals become result dicts; any other exception (nothing committed)
        becomes ``internal_error``, logged by its type only."""
        try:
            return call()
        except CommandRefused as exc:
            result = exc.result
        except Clarify as exc:
            result = {"ok": False, "error": "clarification_needed", "field": exc.field,
                      "candidates": exc.candidates}
        except ValidationError as exc:
            result = {"ok": False, "error": "validation_error", "field": exc.field,
                      "detail": exc.detail}
        except DuplicateAlias as exc:
            result = {"ok": False, "error": "validation_error", "field": "aliases",
                      "detail": {"alias": exc.alias}}
        except DuplicateReceipt:
            result = {"ok": False, "error": "validation_error", "field": "movement",
                      "detail": {"reason": "recorded"}}
        except AlreadyRevoked:
            result = {"ok": False, "error": "validation_error", "field": "ref",
                      "detail": {"reason": "already_undone"}}
        except IdempotencyConflict:
            result = {"ok": False, "error": "idempotency_conflict"}
        except UnknownPending:
            result = {"ok": False, "error": "unknown_pending"}
        except AlreadyResolved as exc:
            result = {"ok": False, "error": "already_resolved",
                      "resolution": views.public_resolution(exc.resolution)}
        except AlreadyLinked:
            result = {"ok": False, "error": "already_linked"}
        except Exception as exc:  # never str(exc): it may hold labels or figures
            logger.error("receivables call failed: %s", type(exc).__name__)
            return {"ok": False, "error": "internal_error"}
        logger.info("receivables refused: error=%s field=%s", result["error"],
                    result.get("field"))
        return result

    def _run(self, actor: str, key: str, command: str, payload: dict,
             effect: Callable[[object], dict]) -> dict:
        return self._base.run_command(self._ws, key, command, payload, effect,
                                      human_actor=actor, machine_caller=self._caller.machine,
                                      channel=self._caller.channel)

    # --- reads -------------------------------------------------------------------------
    def receivables(self, delegation: str | None, counterparty: str | None = None) -> dict:
        self._authorize(delegation, "VIEW")

        def read() -> dict:
            ctx = self._ctx()
            with self._rx.read() as conn:
                view = {"ok": True, **receivables_view(self._rx, conn, self._ws, ctx.now)}
                if counterparty is None:
                    return view
                cp = proposals.counterparty(ctx, conn, counterparty, "counterparty",
                                            proposals.ANY_KIND, active=False)
            return views.for_counterparty(view, cp)
        return self._guard(read)

    def exchanges(self, delegation: str | None, status: str | None = None,
                  since: str | None = None) -> dict:
        self._authorize(delegation, "VIEW")

        def read() -> dict:
            with self._rx.read() as conn:
                return views.exchanges(self._ctx(), conn, status, since)
        return self._guard(read)

    def pending(self, delegation: str | None, for_delivery: bool = False) -> dict:
        """Open items; ``for_delivery`` returns those due now and marks them delivered (F9)."""
        self._authorize(delegation, "VIEW")

        def read() -> dict:
            now = self._clock()
            if for_delivery:
                with self._rx.tx() as conn:
                    items = self._queue.for_delivery(conn, self._ws)
            else:
                with self._rx.tx() as conn:  # showing private options binds them (R49)
                    items = self._queue.open_items(conn, self._ws)
                    for i in items:
                        self._rx.bind_shown(conn, self._ws, i.code)
            logger.info("receivables pending: items=%d delivery=%s", len(items),
                        bool(for_delivery))
            return {"ok": True, "as_of": now.isoformat(),
                    "items": [views.render_pending(i, self._token) for i in items]}
        return self._guard(read)

    def explain(self, delegation: str | None, ref: str) -> dict:
        self._authorize(delegation, "VIEW")

        def read() -> dict:
            with self._rx.tx() as conn:  # explaining a P-code shows its options: bind them
                out = views.explain(self._ctx(), conn, ref)
                if out.get("kind") == "pending" and out["resolved_at"] is None:
                    self._rx.bind_shown(conn, self._ws, out["ref"])
                return out
        return self._guard(read)

    # --- proposals (two-phase) -----------------------------------------------------------
    def propose_exchange(self, delegation: str | None, total_usd: str, lines: list[dict],
                         evidence: dict | None = None, delivered_on: str | None = None, *,
                         client_key: str | None = None) -> dict:
        actor = self._authorize(delegation, "CREATE")
        return self._propose(actor, lambda ctx, conn: proposals.exchange(
            ctx, conn, total_usd, lines, evidence, delivered_on), client_key)

    def propose_receipt(self, delegation: str | None, payer: str, amount: str, currency: str,
                        kind: str, received_on: str | None = None,
                        description: str | None = None, *,
                        client_key: str | None = None) -> dict:
        actor = self._authorize(delegation, "CREATE")
        return self._propose(actor, lambda ctx, conn: proposals.receipt(
            ctx, conn, payer, amount, currency, kind, received_on, description), client_key)

    def propose_correction(self, delegation: str | None, exchange_ref: str, lines: list[dict],
                           total_usd: str | None = None, reason: str | None = None, *,
                           client_key: str | None = None) -> dict:
        actor = self._authorize(delegation, "CREATE")
        return self._propose(actor, lambda ctx, conn: proposals.correction(
            ctx, conn, exchange_ref, lines, total_usd, reason), client_key)

    def propose_forgive(self, delegation: str | None, target: str, amount: str | None = None,
                        reason: str | None = None, *, client_key: str | None = None) -> dict:
        actor = self._authorize(delegation, "CREATE")
        return self._propose(actor, lambda ctx, conn: proposals.forgive(
            ctx, conn, target, amount, reason), client_key)

    def propose_opening(self, delegation: str | None, counterparty: str, amount: str,
                        currency: str, basis: str, note: str, *,
                        client_key: str | None = None) -> dict:
        actor = self._authorize(delegation, "CREATE")
        return self._propose(actor, lambda ctx, conn: proposals.opening(
            ctx, conn, counterparty, amount, currency, basis, note), client_key)

    def propose_counterparty(self, delegation: str | None, label: str, kind: str,
                             aliases: list[str] | None = None, pay_currency: str | None = None,
                             settles_to: str | None = None, alert_below: str | None = None, *,
                             client_key: str | None = None) -> dict:
        actor = self._authorize(delegation, "CREATE")
        return self._propose(actor, lambda ctx, conn: proposals.new_counterparty(
            ctx, conn, label, kind, aliases, pay_currency, settles_to, alert_below), client_key)

    def propose_reverse(self, delegation: str | None, ref: str, reason: str, *,
                        client_key: str | None = None) -> dict:
        actor = self._authorize(delegation, "CREATE")
        return self._propose(actor, lambda ctx, conn: proposals.reversal(ctx, conn, ref, reason),
                             client_key)

    def propose_reallocate(self, delegation: str | None, receipt_ref: str,
                           allocations: list[dict], *, client_key: str | None = None) -> dict:
        actor = self._authorize(delegation, "CREATE")
        return self._propose(actor, lambda ctx, conn: proposals.reallocation(
            ctx, conn, receipt_ref, allocations), client_key)

    def _propose(self, actor: str, prepare: Callable[[Ctx, object], Proposal],
                 client_key: str | None) -> dict:
        """One CONFIRM, or the open one for the same content. With ``client_key`` the answer
        is also stored under that key: the same key with other content is
        ``idempotency_conflict``."""
        def run() -> dict:
            ctx = self._ctx()
            if client_key is None:
                with self._rx.tx() as conn:
                    return self._open_confirm(ctx, conn, prepare(ctx, conn))
            handle = _client_handle(client_key)
            with self._rx.read() as conn:
                p = prepare(ctx, conn)
            return self._run(actor, f"propose:{handle}", "propose",
                             {"command": p.command, "content": lookup_key(p)},
                             lambda conn: self._open_confirm(ctx, conn, p))
        return self._guard(run)

    def _open_confirm(self, ctx: Ctx, conn, p: Proposal) -> dict:
        """A command already completed with this key today, an exchange with the same VES
        reference, or an open exchange CONFIRM with it, makes the proposal a
        ``possible_duplicate`` whose payload carries a nonce ([Es otro]). An open CONFIRM for
        the same content whose defaulted date is stale is resolved ``superseded`` (no
        intervention) and replaced by this one, so only one of them can record (R63)."""
        key = content_key(p.command, p.payload, ctx.now)
        dedupe = f"CONFIRM:{lookup_key(p)}"
        item = self._rx.pending_by_dedupe(conn, self._ws, dedupe)
        if item is not None and not _current_defaults(item, p, ctx.now):
            self._queue.resolve(conn, self._ws, item.code, SUPERSEDED, human=False)
            logger.info("receivables proposal superseded: command=%s", p.command)
            item = None
        if item is None:
            done = self._rx.command_result(conn, self._ws, key)
            duplicate_of = p.duplicate_of or self._open_ves_confirm(conn, p)
            repeated = done is not None or duplicate_of is not None
            status = "possible_duplicate" if repeated else "confirmation_required"
            echo = p.echo if not repeated else {
                **p.echo, "duplicate_of": duplicate_of or _result_ref(done)}
            item = self._queue.add(
                conn, self._ws, PendingKind.CONFIRM,
                DUPLICATE_OPTIONS if repeated else CONFIRM_OPTIONS,
                {"command": p.command, "payload": p.payload, "key": key,
                 "nonce": uuid.uuid4().hex[:12] if repeated else None,
                 "status": status, "echo": echo, "high_value": p.high_value}, dedupe)
            # the proposal's answer shows it: the cron only re-sends it if unanswered
            self._rx.mark_pending_delivered(conn, self._ws, item.code, ctx.now, resolve=False)
            logger.info("receivables proposal: command=%s status=%s", p.command, status)
        return _confirm_view(item)

    def _open_ves_confirm(self, conn, p: Proposal) -> str | None:
        """The code of an open exchange CONFIRM with the same VES reference (R43)."""
        h = p.payload.get("ves_reference_hash") if p.command == "exchange" else None
        if not h:
            return None
        return next((i.code for i in self._rx.pending_open(conn, self._ws)
                     if i.kind is PendingKind.CONFIRM and i.payload.get("command") == "exchange"
                     and i.payload["payload"].get("ves_reference_hash") == h), None)

    # --- direct (level 1) ----------------------------------------------------------------
    def mark_held_cash(self, delegation: str | None, counterparty: str, amount: str,
                       currency: str, *, client_key: str | None = None) -> dict:
        """Display only (F5): no confirmation; audited in ``command_log``. Each statement is
        new (the latest wins), so its key carries a nonce: repeating one is harmless. With
        ``client_key`` a retry returns the stored result instead."""
        actor = self._authorize(delegation, "CREATE")

        def run() -> dict:
            ctx = self._ctx()
            with self._rx.read() as conn:
                payload = proposals.held_cash(ctx, conn, counterparty, amount, currency)
            if client_key is None:
                key = f"{content_key('held_cash', payload, ctx.now)}:{uuid.uuid4().hex[:12]}"
            else:
                key = f"held_cash:{_client_handle(client_key)}"
            return self._run(actor, key, "held_cash", payload,
                             lambda conn: commands.execute(ctx, conn, "held_cash", payload))
        return self._guard(run)

    def resolve(self, delegation: str | None, code: str, choice: str,
                details: dict | None = None) -> dict:
        """Answers a pending item by code. Idempotent by (code, choice): the same answer again
        returns the stored result; another answer to a resolved item is ``already_resolved``.
        ``details``: ``counterparty`` (an EXPLAIN_INCOMING ``OTHER``), ``remember`` (False:
        an EXPLAIN_INCOMING answer writes no payer rule)."""
        actor = self._authorize(delegation, "CREATE")
        return self._guard(lambda: self._resolve(actor, code, choice, details))

    def _resolve(self, actor: str, code, choice, details) -> dict:
        code_text = proposals.text(code, "code")
        choice_text = proposals.text(choice, "choice")
        if details is not None and not isinstance(details, dict):
            raise ValidationError("details")
        proposals.known_keys(details or {}, proposals.DETAIL_KEYS, "details")
        remember = (details or {}).get("remember", True)
        if not isinstance(remember, bool):
            raise ValidationError("details", {"remember": "true or false"})
        ctx = self._ctx()
        with self._rx.read() as conn:
            item = self._queue.get(conn, self._ws, code_text)
            if item is None:
                raise CommandRefused({"ok": False, "error": "unknown_pending"})
            value = _choose(item, choice_text, self._token)
            named = (details or {}).get("counterparty")
            if item.kind is PendingKind.EXPLAIN_INCOMING and value == "OTHER" and named:
                value = "CP:" + proposals.counterparty(ctx, conn, named, "counterparty").id
        if item.kind is PendingKind.EXPLAIN_INCOMING:
            return self._explain(ctx, actor, item, value, remember)
        handler = {
            PendingKind.CONFIRM: self._confirm, PendingKind.LINK_FUNDING: self._link,
            PendingKind.PREVIOUS_UNPAID: self._link, PendingKind.REVIEW_OPENING: self._review,
            PendingKind.INFO: self._info,
        }[item.kind]
        return handler(ctx, actor, item, value)

    def _answer(self, actor: str, item: PendingItem, value: str,
                effect: Callable[[object], dict], extra: dict | None = None) -> dict:
        return self._run(actor, f"resolve:{item.code}:{value}", "resolve",
                         {"code": item.code, "choice": value, **(extra or {})}, effect)

    def _still_open(self, conn, item: PendingItem) -> None:
        current = self._queue.get(conn, self._ws, item.code)
        if current.resolved_at is not None:
            raise AlreadyResolved(current.resolution)

    def _confirm(self, ctx: Ctx, actor: str, item: PendingItem, value: str) -> dict:
        stored = item.payload
        if value == "yes":  # the STORED payload, never one the model sends again
            key = stored["key"] + (f":{stored['nonce']}" if stored.get("nonce") else "")

            def effect(conn) -> dict:
                self._queue.resolve(conn, self._ws, item.code, "yes", human=True)
                if not stored.get("nonce"):
                    self._no_ves_duplicate(conn, stored)
                return commands.execute(ctx, conn, stored["command"], stored["payload"])

            out = self._run(actor, key, stored["command"], stored["payload"], effect)
            logger.info("receivables command: command=%s", stored["command"])
            return out

        def close(conn) -> dict:
            self._queue.resolve(conn, self._ws, item.code, value, human=True)
            return {"ok": True, "status": _CONFIRM_STATUS[value], "code": item.code}
        return self._answer(actor, item, value, close)

    def _no_ves_duplicate(self, conn, stored: dict) -> None:
        """At "yes", an exchange whose VES reference a live exchange already has is a
        ``possible_duplicate``; the CONFIRM stays open (R43)."""
        h = stored["payload"].get("ves_reference_hash") if stored["command"] == "exchange" \
            else None
        same = self._rx.exchange_by_ves_hash(conn, self._ws, h) if h else None
        if same is not None:
            raise CommandRefused({"ok": False, "error": "possible_duplicate",
                                  "duplicate_of": f"C{same.number}"})

    def _link(self, ctx: Ctx, actor: str, item: PendingItem, value: str) -> dict:
        """LINK_FUNDING / PREVIOUS_UNPAID. A stale answer (the exchange was paid or reversed,
        the payment linked or classified meanwhile) resolves the item and asks again with
        fresh options."""
        rx, ws, queue = self._rx, self._ws, self._queue

        def effect(conn) -> dict:
            self._still_open(conn, item)
            if item.kind is PendingKind.LINK_FUNDING:
                out = link_choice(rx, conn, ws, item.payload.get("movement_id"), value, queue,
                                  ctx.now)
            else:
                out = link_choice(rx, conn, ws, None, value, queue, ctx.now,
                                  exchange_ref=item.payload.get("exchange_ref"))
            if not out["ok"]:
                if out["error"] in STALE_LINK:
                    return self._stale(ctx, conn, item, value)
                raise CommandRefused(out)
            queue.resolve(conn, ws, item.code, value, human=True)
            close_settled_questions(rx, conn, ws, queue)
            return {**out, "code": item.code}
        return self._answer(actor, item, value, effect)

    def _stale(self, ctx: Ctx, conn, item: PendingItem, value: str) -> dict:
        """Resolves the item as "stale" (no intervention). A PREVIOUS_UNPAID whose exchange is
        still unpaid is asked again; a payment still unlinked gets LINK_FUNDING again."""
        rx, ws, queue = self._rx, self._ws, self._queue
        queue.resolve(conn, ws, item.code, "stale", human=False)
        if item.kind is PendingKind.PREVIOUS_UNPAID:
            ex = rx.exchange_by_ref(conn, ws, item.payload.get("exchange_ref") or "")
            if ex is not None and rx.live_funding_for_exchange(conn, ex.id) is None:
                after = item.payload.get("after_ref") or f"C{ex.number}"
                return {"ok": True, "status": "asked_again",
                        "code": ask_previous_unpaid(rx, conn, ws, ex, after, queue, ctx.now).code}
            movement = value[2:] if value.startswith("M:") else None
        else:
            movement = item.payload.get("movement_id")
        mv = rx.movement_current(conn, ws, movement) if movement else None
        if (mv is not None and mv.currency == "EUR" and mv.amount_minor < 0
                and rx.live_funding_for_movement(conn, mv.id) is None
                and rx.movement_role(conn, mv.id) is None):
            return {"ok": True, "status": "asked_again",
                    "code": ask_link_funding(rx, conn, ws, mv.id, queue).code}
        close_settled_questions(rx, conn, ws, queue)
        return {"ok": True, "status": "already_settled"}

    def _explain(self, ctx: Ctx, actor: str, item: PendingItem, value: str,
                 remember: bool) -> dict:
        if value == "OTHER":  # writes nothing: the owner names the counterparty next
            if item.resolved_at is not None:
                raise AlreadyResolved(item.resolution)
            return {"ok": True, "status": "needs_counterparty", "code": item.code}
        rx, ws, queue = self._rx, self._ws, self._queue

        def effect(conn) -> dict:
            self._still_open(conn, item)
            out = resolve_explain_incoming(rx, conn, ws, item.payload.get("movement_id") or "",
                                           value, queue, ctx.now,
                                           description_rules=self._rules, remember=remember)
            if not out["ok"]:
                if out["error"] in STALE_EXPLAIN:  # classified or gone meanwhile (m3)
                    queue.resolve(conn, ws, item.code, "stale", human=False)
                    close_settled_questions(rx, conn, ws, queue)
                    return {"ok": True, "status": "already_settled"}
                raise CommandRefused(out)
            queue.resolve(conn, ws, item.code, value, human=True)
            close_settled_questions(rx, conn, ws, queue)
            return {**out, "code": item.code}
        return self._answer(actor, item, value, effect, None if remember else {"remember": False})

    def _review(self, ctx: Ctx, actor: str, item: PendingItem, value: str) -> dict:
        """REVIEW_OPENING: CONFIRM re-records the APPROXIMATE openings it showed as CONFIRMED
        (REVERSAL + new OPENING, same amount and note) and refuses ``changed`` when they are
        no longer the effective ones (m4) and closes the question as stale so the matcher asks again (R49); an UNKNOWN fund needs an amount (nothing written);
        LATER snoozes the question for 7 days."""
        rx, ws, queue = self._rx, self._ws, self._queue
        if value == "LATER":
            until = ctx.now + SNOOZE
            with rx.tx() as conn:
                self._still_open(conn, item)
                queue.snooze(conn, ws, item.code, until)
            return {"ok": True, "status": "snoozed", "until": until.date().isoformat(),
                    "code": item.code}
        cp_id = item.dedupe_key.split(":")[1]  # REVIEW_OPENING:<counterparty id>:<ISO week>
        shown = sorted(str(o.get("entry_ref")) for o in item.payload.get("openings") or []
                       if isinstance(o, dict))

        def stated(conn) -> list:
            return rx.effective_entries_for_refs(conn, ws, [cp_id], (EntryKind.OPENING,))

        if item.resolved_at is None:  # a repeated answer gets the stored result below
            with rx.read() as conn:
                cp, entries = rx.get_counterparty(conn, ws, cp_id), stated(conn)
            if sorted(f"E{e.number}" for e in entries) != shown:
                with rx.tx() as conn:  # close it, so the matcher asks again with today's figures
                    if queue.get(conn, ws, item.code).resolved_at is None:
                        queue.resolve(conn, ws, item.code, "stale", human=False)
                raise CommandRefused({"ok": False, "error": "validation_error",
                                      "field": "target",
                                      "detail": {"reason": "changed", "question": "stale"}})
            if cp is None or cp.opening in (None, Opening.UNKNOWN) or not entries:
                return {"ok": True, "status": "needs_amount", "code": item.code}

        def effect(conn) -> dict:
            self._still_open(conn, item)
            current, entries = rx.get_counterparty(conn, ws, cp_id), stated(conn)
            if sorted(f"E{e.number}" for e in entries) != shown:
                raise changed()
            written = []
            if current.opening is Opening.APPROXIMATE:
                latest = {e.currency: e for e in entries}
                for e in latest.values():  # a fund's opening is stated as what it holds
                    held = -e.amount_minor if current.kind is CounterpartyKind.FUND \
                        else e.amount_minor
                    new = record_opening(rx, conn, ws, cp_id, e.currency, held,
                                         Opening.CONFIRMED, e.note, ctx.now, queue=queue)
                    written.append(f"E{new.number}")
            queue.resolve(conn, ws, item.code, "CONFIRM", human=True)
            close_settled_questions(rx, conn, ws, queue)
            return {"ok": True, "status": "confirmed", "code": item.code, "entries": written}
        return self._answer(actor, item, "CONFIRM", effect)

    def _info(self, ctx: Ctx, actor: str, item: PendingItem, value: str) -> dict:
        """Dismissing a notice is idempotent, also once its delivery resolved it (m7)."""
        done = {"ok": True, "status": "dismissed", "code": item.code}
        if item.resolved_at is not None:
            return done

        def effect(conn) -> dict:
            if self._queue.get(conn, self._ws, item.code).resolved_at is None:
                self._queue.resolve(conn, self._ws, item.code, "dismissed", human=False)
            return done
        return self._answer(actor, item, "dismissed", effect)
