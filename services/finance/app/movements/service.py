"""MovementsService: authorize, validate, load, shape. Read only (spec 5.4, 5.6, 5.9-5.10).

Authorization comes first (one Home request, then the OWNER role); nothing is read for a
refused caller. Domain errors are ``{"ok": False, "error": code}``; refusals are the I1
exceptions. The interpretation of movements is computed here at read time from the facts of
the receivables layer; nothing is ever written.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from .. import domain
from ..authz import Authorizer
from ..money import parse_amount
from ..receivables.explain import incoming_key
from ..service import AccessDenied, ViewGrant, authorize_view
from ..store.receivables_repo import ReceivablesRepository
from ..store.repo import FinanceRepository
from .accounts import account_rows
from .help import help_items
from .interpret import family_senders, interpret
from .model import (
    DEFAULT_LIMIT, DEFAULT_LOOKBACK_DAYS, MAX_LIMIT, MAX_MONTHS_BACK, MAX_RANGE_DAYS,
    PAIR_WINDOW_DAYS, TEXT_MAX_CHARS, TEXT_MIN_CHARS, Period, movement_day,
)
from .summary import summarize
from .text import matches
from .views import movement_line

OWNER_ROLE = "OWNER"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERIOD = re.compile(r"^(\d{4})(?:-(\d{2}))?$")


class _Invalid(Exception):
    def __init__(self, code: str, **extra) -> None:
        self.code, self.extra = code, extra


def _fail(error: "_Invalid") -> dict:
    return {"ok": False, "error": error.code, **error.extra}


def _day(value: str) -> date:
    if not isinstance(value, str) or not _DATE.match(value):
        raise _Invalid("bad_date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _Invalid("bad_date") from None


def _period(value: str | None, today: date) -> Period:
    label = today.strftime("%Y-%m") if value is None else value
    found = _PERIOD.match(label) if isinstance(label, str) else None
    if not found:
        raise _Invalid("bad_period")
    year, month = int(found.group(1)), found.group(2)
    try:
        start = date(year, 1 if month is None else int(month), 1)
    except ValueError:
        raise _Invalid("bad_period") from None
    back = today.year * 12 + today.month - 1 - MAX_MONTHS_BACK
    if start > today or start < date(back // 12, back % 12 + 1, 1):
        raise _Invalid("bad_period")  # checked before ``end``: far dates would overflow
    if month is None:
        end = date(year, 12, 31)
    else:
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return Period(start, end, label)


def _amounts(value, currencies) -> dict[str, int]:
    """Minor units per currency in which ``value`` is a valid amount; absolute values."""
    text = value.strip() if isinstance(value, str) else ""
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    found: dict[str, int] = {}
    for currency in currencies:
        try:
            found[currency] = abs(parse_amount(text, currency))
        except (ValueError, TypeError):
            continue
    if not found:
        raise _Invalid("bad_amount")
    return found


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MovementsService:
    def __init__(self, repo: FinanceRepository, authorizer: Authorizer, workspace_id: str, *,
                 description_rules: bool = False,
                 clock: Callable[[], datetime] = _utc_now) -> None:
        self._repo = repo
        self._authorizer = authorizer
        self._ws = workspace_id
        self._rules = description_rules
        self._clock = clock
        self._rx = ReceivablesRepository(repo)

    # ---- public operations -------------------------------------------------------

    def movements(self, delegation: str | None, text: str | None = None,
                  amount: str | None = None, account: str | None = None,
                  direction: str | None = None, since: str | None = None,
                  until: str | None = None, limit: int | None = None) -> dict:
        grant = authorize_view(self._repo, self._authorizer, self._ws, delegation)
        now = self._clock()
        today = now.date()
        with self._rx.read() as conn:
            self._owner_only(conn, grant)
            visible, _hidden = grant.visible(self._repo.list_accounts(self._ws))
            try:
                q = self._query(visible, today, text, amount, account, direction,
                                since, until, limit)
            except _Invalid as error:
                return _fail(error)
            chosen, lo, hi = q["accounts"], q["since"], q["until"]
            interp, rows, helps, history = self._load(conn, visible, lo, hi, today)
        parts: dict[str, list] = {}
        for item in helps:
            if item.funding_ref:
                parts.setdefault(item.funding_ref, []).append(item)
        by_id = {a.id: a for a in visible}
        picked = [(rowid, mv) for rowid, mv in rows
                  if mv.account_id in chosen and lo <= movement_day(mv) <= hi
                  and self._wanted(mv, q)]
        picked.sort(key=lambda r: (movement_day(r[1]), r[0]), reverse=True)
        lines = [movement_line(mv, interp[mv.id], by_id[mv.account_id], today,
                               parts.get(interp[mv.id].ref or "", ()))
                 for _rowid, mv in picked[:q["limit"]]]
        return {"ok": True, "since": lo.isoformat(), "until": hi.isoformat(),
                "total_matches": len(picked), "truncated": len(picked) > q["limit"],
                "movements": lines,
                "accounts": account_rows(self._repo, self._ws,
                                         [by_id[i] for i in sorted(chosen)],
                                         history, now)[0]}

    def summary(self, delegation: str | None, period: str | None = None) -> dict:
        grant = authorize_view(self._repo, self._authorizer, self._ws, delegation)
        now = self._clock()
        today = now.date()
        with self._rx.read() as conn:
            self._owner_only(conn, grant)
            visible, hidden = grant.visible(self._repo.list_accounts(self._ws))
            try:
                span = _period(period, today)
            except _Invalid as error:
                return _fail(error)
            interp, rows, helps, history = self._load(conn, visible, span.start, span.end, today)
        by_id = {a.id: a for a in visible}
        inside = [(mv, interp[mv.id]) for _rowid, mv in rows
                  if span.start <= movement_day(mv) <= span.end]
        result = summarize(span, inside, helps, by_id,
                           sorted({a.currency for a in visible}), today)
        listed, unsynced_empty = account_rows(self._repo, self._ws, visible, history, now)
        reasons = [name for name, applies in (
            ("in_progress", span.start <= today <= span.end),
            ("history_starts_late", unsynced_empty
             or any(a["history_from"] and a["history_from"] > span.start.isoformat()
                    for a in listed)),
            ("account_stale", any(a["stale"] for a in listed)),
            ("hidden_accounts", hidden > 0),
            ("exchanges_without_split", result["exchanges_without_split"]),
        ) if applies]
        return {"ok": True, "period": span.label, "from": span.start.isoformat(),
                "to": span.end.isoformat(), "complete": not reasons,
                "incomplete_reasons": reasons, "currencies": result["currencies"],
                "accounts": listed, "hidden_accounts": hidden}

    # ---- helpers -----------------------------------------------------------------

    def _owner_only(self, conn, grant: ViewGrant) -> None:
        if self._rx.member_role(conn, self._ws, grant.actor) != OWNER_ROLE:
            raise AccessDenied()

    def _query(self, visible, today, text, amount, account, direction, since, until, limit):
        q: dict = {"text": None, "amounts": None, "direction": direction}
        if text is not None:
            if not isinstance(text, str) or not TEXT_MIN_CHARS <= len(text.strip()) <= TEXT_MAX_CHARS:
                raise _Invalid("bad_text")
            q["text"] = text.strip()
        if amount is not None:
            q["amounts"] = _amounts(amount, sorted({a.currency for a in visible}))
        chosen = {a.id for a in visible}
        if account is not None:
            key = str(account).strip().casefold()
            chosen = {a.id for a in visible
                      if key in (a.id.casefold(), a.institution.casefold())}
            if not chosen:
                raise _Invalid("unknown_account", accounts=[
                    {"id": a.id, "institution": a.institution} for a in visible])
        if direction not in (None, "in", "out"):
            raise _Invalid("bad_direction")
        hi = today if until is None else _day(until)
        try:
            lo = hi - timedelta(days=DEFAULT_LOOKBACK_DAYS) if since is None else _day(since)
            # the loader widens both ends by the pairing window: refuse what would overflow
            lo - timedelta(days=PAIR_WINDOW_DAYS), hi + timedelta(days=PAIR_WINDOW_DAYS)
        except OverflowError:
            raise _Invalid("bad_range") from None
        if lo > hi or (hi - lo).days > MAX_RANGE_DAYS:
            raise _Invalid("bad_range")
        if limit is None:
            limit = DEFAULT_LIMIT
        elif type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
            raise _Invalid("bad_limit")
        return {**q, "accounts": chosen, "since": lo, "until": hi, "limit": limit}

    @staticmethod
    def _wanted(mv: domain.Movement, q: dict) -> bool:
        if q["text"] and not matches(q["text"], mv.counterparty_name, mv.remittance):
            return False
        if q["amounts"] is not None and q["amounts"].get(mv.currency) != abs(mv.amount_minor):
            return False
        return (q["direction"] is None or (mv.amount_minor > 0) == (q["direction"] == "in"))

    def _load(self, conn, visible, lo: date, hi: date, today: date):
        """Interpretation of the visible accounts' rows in [lo, hi], widened to pair across
        the edges (the caller filters back). One bulk read per kind of fact."""
        ids = [a.id for a in visible]
        rx, ws = self._rx, self._ws
        wide = timedelta(days=PAIR_WINDOW_DAYS)
        rows = rx.current_movements_between(conn, ws, ids, lo - wide, hi + wide)
        facts = rx.interpretation_facts(conn, ws)
        key_of = lambda mv: incoming_key(rx, mv, self._rules)  # noqa: E731
        usd = [a.id for a in visible if a.currency == "USD"]
        senders = family_senders(rx.current_incoming(conn, ws, usd), facts, key_of)
        interp = interpret(rows, {a.id: a for a in visible}, facts, key_of, senders,
                           today)
        return (interp, rows, help_items(rx, conn, ws, facts), rx.history_from(conn, ws))
