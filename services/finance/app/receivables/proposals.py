"""Proposals: turn tool input into a stored payload and the owner's echo. Nothing here writes.

Amounts enter only through ``parse_amount`` (a plain decimal string: "1.250,50" or "$275" is a
``validation_error`` naming the field) and leave through ``format_minor``. Names resolve
through ``find_by_alias``; zero or several matches raise ``Clarify`` with candidate labels.
Payloads hold ids and minor units (stored in the CONFIRM item, never shown); echoes hold
refs, labels, dates and formatted amounts, never an id, an IBAN or a hash.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..money import format_minor, parse_amount
from ..store.receivables_repo import IGNORE, MAX_LINE_POSITION
from .commands import CommandRefused, Ctx, ignored_movements, item_ref, receipt_rule
from .corrections import forgive_preview
from .explain import incoming_key, sender_text
from .fx import implied_rate, rate_text
from .ledger import DEBT_CURRENCIES, LineInput, ValidationError, validate_lines
from .model import (
    CASH_ABROAD, HIGH_VALUE_USD_MINOR, OWNER, Counterparty, CounterpartyKind, EntryKind,
    MovementRoleKind, Opening, PendingKind, ReceiptKind,
)
from .text import normalize_alias

PAYERS = (CounterpartyKind.PERSON, CounterpartyKind.FUND)
ANY_KIND = tuple(CounterpartyKind)
OWNER_WORDS = frozenset({"owner", "mio", "mia", "yo", "tuyo", "dueno"})
PLAIN = {"expected": "a plain decimal such as 1250.50"}
_EXCHANGE_TARGET = re.compile(r"\s*(C\d{1,9})\s*:\s*(.+?)\s*", re.IGNORECASE | re.ASCII)
_FACT = re.compile(r"[CFRE]\d{1,9}", re.IGNORECASE | re.ASCII)
_PENDING = re.compile(r"P\d{1,9}", re.IGNORECASE | re.ASCII)
_UNDO = re.compile(r"U[0-9a-f]{10}", re.IGNORECASE | re.ASCII)


class Clarify(Exception):
    """A name matched no counterparty, or several: ask which one (``candidates`` = labels)."""

    def __init__(self, field: str, candidates: list[str]) -> None:
        super().__init__(field)
        self.field = field
        self.candidates = candidates


@dataclass(frozen=True)
class Proposal:
    command: str
    payload: dict
    echo: dict
    high_value: bool = False
    duplicate_of: str | None = None  # a natural duplicate (the same VES reference)


# --- small parsers -------------------------------------------------------------------
def text(value, field: str, *, required: bool = True) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValidationError(field)
        return None
    if not isinstance(value, str):
        raise ValidationError(field)
    return value.strip()


def money(value, currency: str, field: str) -> int:
    if not isinstance(value, str):  # a float is never read as money
        raise ValidationError(field, PLAIN)
    try:
        return parse_amount(value, currency)
    except ValueError:
        raise ValidationError(field, PLAIN) from None


def positive(value, currency: str, field: str) -> int:
    amount = money(value, currency, field)
    if amount <= 0:
        raise ValidationError(field, PLAIN)
    return amount


def currency(value, field: str = "currency", allowed=DEBT_CURRENCIES) -> str:
    code = value.strip().upper() if isinstance(value, str) else None
    if code not in allowed:
        raise ValidationError(field, {"allowed": ", ".join(allowed)})
    return code


def day(value, field: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value.strip())
    except (AttributeError, ValueError):
        raise ValidationError(field, {"expected": "YYYY-MM-DD"}) from None


def counterparty(ctx: Ctx, conn, name, field: str, kinds=PAYERS, *,
                 active: bool = True) -> Counterparty:
    """The one counterparty whose alias is ``name`` (case, accents and spaces ignored)."""
    query = name if isinstance(name, str) else ""
    allowed = [cp for cp in ctx.repo.list_counterparties(conn, ctx.ws)
               if cp.kind in kinds and (not active or cp.status == "ACTIVE")]
    found = [cp for cp in ctx.repo.find_by_alias(conn, ctx.ws, query) if cp in allowed]
    if len(found) == 1:
        return found[0]
    key, names = normalize_alias(query), ctx.repo.alias_names(conn, ctx.ws)
    partial = [cp for cp in allowed if key and (
        key in normalize_alias(cp.label) or any(key in a for a in names.get(cp.id, ())))]
    raise Clarify(field, [cp.label for cp in (found or partial or allowed)])


def _label(ctx: Ctx, conn, cp_id: str) -> str:
    if cp_id == OWNER:
        return "owner"
    cp = ctx.repo.get_counterparty(conn, ctx.ws, cp_id)
    return cp.label if cp else "?"


def usd_equivalent_is_high(ctx: Ctx, conn, amount_minor: int, cur: str, on: date) -> bool:
    """≥ HIGH_VALUE_USD_MINOR in USD, EUR converted at the ECB rate of that day (or the last
    one before it); with no rate it counts as high."""
    if cur == "USD":
        return amount_minor >= HIGH_VALUE_USD_MINOR
    rate = ctx.repo.usd_per_eur_on(conn, on)  # USD per EUR
    return rate is None or Decimal(amount_minor) * rate >= HIGH_VALUE_USD_MINOR


# --- exchanges -----------------------------------------------------------------------
def _line_inputs(ctx: Ctx, conn, lines) -> list[LineInput]:
    if not isinstance(lines, list) or not lines:
        raise ValidationError("lines")
    if len(lines) > MAX_LINE_POSITION + 1:
        raise ValidationError("lines", {"max": str(MAX_LINE_POSITION + 1)})
    out = []
    for i, ln in enumerate(lines):
        f = f"lines[{i}]"
        if not isinstance(ln, dict):
            raise ValidationError(f)
        name = text(ln.get("payer"), f"{f}.payer")
        payer = OWNER if normalize_alias(name) in OWNER_WORDS else \
            counterparty(ctx, conn, name, f"{f}.payer").id
        usd = positive(ln.get("usd"), "USD", f"{f}.usd")
        debt = ln.get("debt_currency")
        eur = ln.get("eur")
        out.append(LineInput(
            payer, usd, None if debt is None else currency(debt, f"{f}.debt_currency"),
            text(ln.get("beneficiary"), f"{f}.beneficiary", required=False),
            None if eur is None else positive(eur, "EUR", f"{f}.eur")))
    return out


def _resolved_lines(ctx: Ctx, conn, lines) -> tuple[list[dict], list[dict]]:
    """(payload lines, echo lines) after ``validate_lines``; the payload keeps the resolved
    debt currency so the "yes" records exactly what the echo showed."""
    payload, echo = [], []
    for ln, cur in validate_lines(ctx.repo, conn, ctx.ws, _line_inputs(ctx, conn, lines)):
        owner = ln.payer_id == OWNER
        payload.append({"payer_id": ln.payer_id, "usd_minor": ln.usd_minor,
                        "debt_currency": None if owner else cur,
                        "beneficiary_note": ln.beneficiary_note,
                        "eur_override_minor": ln.eur_override_minor})
        echo.append(line_echo(ctx, conn, ln.payer_id, ln.usd_minor, None if owner else cur,
                              ln.eur_override_minor, ln.beneficiary_note))
    return payload, echo


def line_echo(ctx: Ctx, conn, payer_id: str, usd: int, cur: str | None, eur: int | None,
              note: str | None) -> dict:
    return {"payer": _label(ctx, conn, payer_id), "usd": format_minor(usd, "USD"),
            "debt_currency": cur, "eur": None if eur is None else format_minor(eur, "EUR"),
            "eur_pending": cur == "EUR" and eur is None, "note": note}


def _usd_total(lines: list[dict]) -> int:
    return sum(ln["usd_minor"] for ln in lines)


def exchange(ctx: Ctx, conn, total_usd, lines, evidence, delivered_on) -> Proposal:
    total = positive(total_usd, "USD", "total_usd")
    if evidence is not None and not isinstance(evidence, dict):
        raise ValidationError("evidence")
    ev = evidence or {}
    payload_lines, echo_lines = _resolved_lines(ctx, conn, lines)
    if _usd_total(payload_lines) != total:
        raise ValidationError("lines_total", {"total": format_minor(total, "USD"),
                                              "sum": format_minor(_usd_total(payload_lines),
                                                                  "USD")})
    partner = _partner(ctx, conn, ev.get("partner"))
    ves = ev.get("ves_amount")
    ves_minor = None if ves is None else positive(ves, "VES", "evidence.ves_amount")
    reference = text(ev.get("ves_reference"), "evidence.ves_reference", required=False)
    ves_hash = ctx.repo.hash_key(reference) if reference else None
    delivered = (day(delivered_on, "delivered_on") or day(ev.get("date"), "evidence.date")
                 or ctx.now.date())
    same = ctx.repo.exchange_by_ves_hash(conn, ctx.ws, ves_hash) if ves_hash else None
    return Proposal("exchange", {
        "partner_id": partner.id, "total_usd_minor": total, "lines": payload_lines,
        "ves_amount_minor": ves_minor, "ves_reference_hash": ves_hash,
        "delivered_on": delivered.isoformat()}, {
        "type": "exchange", "total_usd": format_minor(total, "USD"),
        "delivered_on": delivered.isoformat(), "partner": partner.label,
        "ves": None if ves_minor is None else format_minor(ves_minor, "VES"),
        "lines": echo_lines}, duplicate_of=f"C{same.number}" if same else None)


def _partner(ctx: Ctx, conn, name) -> Counterparty:
    kinds = (CounterpartyKind.EXCHANGE_PARTNER,)
    if name is not None:
        return counterparty(ctx, conn, name, "evidence.partner", kinds)
    partners = [cp for cp in ctx.repo.list_counterparties(conn, ctx.ws)
                if cp.kind in kinds and cp.status == "ACTIVE"]
    if not partners:
        raise ValidationError("partner")
    if len(partners) > 1:
        raise Clarify("evidence.partner", [cp.label for cp in partners])
    return partners[0]


def correction(ctx: Ctx, conn, exchange_ref, lines, total_usd, reason) -> Proposal:
    ex = ctx.repo.exchange_by_ref(conn, ctx.ws, exchange_ref if isinstance(exchange_ref, str)
                                  else "")
    if ex is None:
        raise ValidationError("exchange")
    why = text(reason, "reason")
    total = None if total_usd is None else positive(total_usd, "USD", "total_usd")
    payload_lines, echo_lines = _resolved_lines(ctx, conn, lines)
    new_total = _usd_total(payload_lines)
    if total is not None and total != new_total:
        raise ValidationError("lines_total", {"total": format_minor(total, "USD"),
                                              "sum": format_minor(new_total, "USD")})
    old = ctx.repo.current_lines(conn, ex.id)
    gifts = ctx.repo.effective_entries_for_refs(conn, ctx.ws, [ln.id for ln in old],
                                                (EntryKind.FORGIVE,))
    if gifts:  # reverse the forgiveness first (E<n>), then correct
        raise ValidationError("forgiven", {"entry": f"E{gifts[0].number}"})
    funding = ctx.repo.live_funding_for_exchange(conn, ex.id)
    before = [line_echo(ctx, conn, ln.payer_id, ln.usd_minor,
                        None if ln.payer_id == OWNER else ln.debt_currency,
                        ln.eur_override_minor, ln.beneficiary_note) for ln in old]
    return Proposal("correction", {
        "exchange_id": ex.id, "lines": payload_lines, "total_usd_minor": total, "reason": why}, {
        "type": "correction", "exchange_ref": f"C{ex.number}",
        "delivered_on": ex.delivered_on.isoformat(),
        "funding_ref": f"F{funding.number}" if funding else None, "reason": why,
        "before": {"usd": format_minor(sum(ln.usd_minor for ln in old), "USD"), "lines": before},
        "after": {"usd": format_minor(new_total, "USD"), "lines": echo_lines}})


# --- receipts, held cash, forgiveness, openings ---------------------------------------
def receipt(ctx: Ctx, conn, payer, amount, cur, kind, received_on, description) -> Proposal:
    cur = currency(cur)
    minor = positive(amount, cur, "amount")
    name = kind.strip().upper().replace("-", "_").replace(" ", "_") \
        if isinstance(kind, str) else ""
    if name not in (ReceiptKind.CASH.value, ReceiptKind.IN_KIND.value):  # BANK: the matcher
        raise ValidationError("kind", {"allowed": "CASH, IN_KIND"})
    what = text(description, "description", required=name == ReceiptKind.IN_KIND.value) or ""
    cp = counterparty(ctx, conn, payer, "payer")
    on = day(received_on, "received_on") or ctx.now.date()
    balance = ctx.repo.balance(conn, ctx.ws, cp.id, cur)
    person = cp.kind is CounterpartyKind.PERSON
    return Proposal("receipt", {
        "payer_id": cp.id, "amount_minor": minor, "currency": cur, "kind": name,
        "received_on": on.isoformat(), "description": what}, {
        "type": "receipt", "payer": cp.label, "amount": format_minor(minor, cur),
        "currency": cur, "kind": name, "received_on": on.isoformat(),
        "description": what or None,
        "balance": format_minor(balance, cur) if person else None,
        "balance_after": format_minor(balance - minor, cur) if person else None},
        high_value=usd_equivalent_is_high(ctx, conn, minor, cur, on))


def held_cash(ctx: Ctx, conn, name, amount, cur) -> dict:
    cur = currency(cur)
    minor = money(amount, cur, "amount")
    if minor < 0:
        raise ValidationError("amount", PLAIN)
    cp = counterparty(ctx, conn, name, "counterparty", (CounterpartyKind.PERSON,))
    return {"counterparty_id": cp.id, "currency": cur, "amount_minor": minor}


def forgive(ctx: Ctx, conn, target, amount, reason) -> Proposal:
    raw = text(target, "target")
    m = _EXCHANGE_TARGET.fullmatch(raw)
    name = m[2] if m else raw
    counterparty(ctx, conn, name, "target")  # an exact alias, or ask which one
    ref = f"{m[1].upper()}:{name}" if m else name
    why = text(reason, "reason")
    cur = forgive_preview(ctx.repo, conn, ctx.ws, ref, None)["currency"]
    minor = None if amount is None else positive(amount, cur, "amount")
    preview = forgive_preview(ctx.repo, conn, ctx.ws, ref, minor)
    return Proposal("forgive", {"target_ref": ref, "amount_minor": minor, "reason": why},
                    {"type": "forgive", **preview, "reason": why})


def opening(ctx: Ctx, conn, name, amount, cur, basis, note) -> Proposal:
    cp = counterparty(ctx, conn, name, "counterparty")
    cur = currency(cur)
    minor = money(amount, cur, "amount")
    stated = basis.strip().upper() if isinstance(basis, str) else ""
    if stated not in (Opening.APPROXIMATE.value, Opening.CONFIRMED.value):
        raise ValidationError("basis", {"allowed": "APPROXIMATE, CONFIRMED"})
    why = text(note, "note")
    replaces = [f"E{e.number}" for e in ctx.repo.effective_entries_for_refs(
        conn, ctx.ws, [cp.id], (EntryKind.OPENING,)) if e.currency == cur]
    return Proposal("opening", {
        "counterparty_id": cp.id, "currency": cur, "amount_minor": minor, "basis": stated,
        "note": why}, {
        "type": "opening", "counterparty": cp.label, "currency": cur,
        "amount": format_minor(minor, cur), "basis": stated, "note": why,
        "replaces": replaces})


# --- counterparties ------------------------------------------------------------------
def new_counterparty(ctx: Ctx, conn, label, kind, aliases, pay_currency, settles_to,
                     alert_below) -> Proposal:
    name = text(label, "label")
    try:
        cp_kind = CounterpartyKind(kind.strip().upper() if isinstance(kind, str) else "")
    except ValueError:
        raise ValidationError("kind", {"allowed": ", ".join(k.value for k in ANY_KIND)}) from None
    if aliases is not None and (not isinstance(aliases, list)
                                or not all(isinstance(a, str) for a in aliases)):
        raise ValidationError("aliases")
    names = list(dict.fromkeys([name, *(a.strip() for a in aliases or [])]))
    taken = {a for used in ctx.repo.alias_names(conn, ctx.ws).values() for a in used}
    for alias in names:  # the label is always an alias; an alias is unique in the workspace
        key = normalize_alias(alias)
        if not key or key in taken:
            raise ValidationError("aliases", {"alias": alias})
    person, fund = cp_kind is CounterpartyKind.PERSON, cp_kind is CounterpartyKind.FUND
    pay = None
    if pay_currency is not None:
        if not person:
            raise ValidationError("pay_currency")
        pay = currency(pay_currency, "pay_currency")
    where_id, where = _settles_to(ctx, conn, settles_to) if settles_to is not None else (None,
                                                                                         None)
    if where_id is not None and not (person or fund):
        raise ValidationError("settles_to")
    alert = None
    if alert_below is not None:
        if not fund:
            raise ValidationError("alert_below")
        alert = money(alert_below, "USD", "alert_below")
    return Proposal("counterparty", {
        "label": name, "kind": cp_kind.value, "aliases": names, "pay_currency": pay,
        "settles_to": where_id, "alert_below_minor": alert}, {
        "type": "counterparty", "label": name, "kind": cp_kind.value, "aliases": names,
        "pay_currency": pay, "settles_to": where,
        "alert_below": None if alert is None else format_minor(alert, "USD"),
        "opening": Opening.UNKNOWN.value if fund else None})


def _settles_to(ctx: Ctx, conn, value) -> tuple[str, str]:
    """(stored value, shown name): ``CASH_ABROAD`` or one workspace account named by its
    institution, its currency or both ("Banco Uno", "EUR", "Banco Uno EUR")."""
    wanted = normalize_alias(value) if isinstance(value, str) else ""
    if wanted.replace(" ", "_") == CASH_ABROAD.lower():
        return CASH_ABROAD, CASH_ABROAD
    accounts = [(a.id, f"{a.institution} {a.currency}", a)
                for a in ctx.repo.base.list_accounts(ctx.ws)]
    found = [(aid, shown) for aid, shown, a in accounts
             if wanted and wanted in (normalize_alias(a.institution), a.currency.lower(),
                                      normalize_alias(shown))]
    if len(found) == 1:
        return found[0]
    raise Clarify("settles_to", [shown for _, shown, _ in accounts] + [CASH_ABROAD])


# --- reversal and reallocation ---------------------------------------------------------
def movement_echo(mv) -> dict:
    return {"date": (mv.booking_date or mv.value_date).isoformat(),
            "amount": format_minor(mv.amount_minor, mv.currency), "currency": mv.currency,
            "sender": sender_text(mv.counterparty_name, mv.remittance)}


def reversal(ctx: Ctx, conn, ref, reason) -> Proposal:
    raw, why = text(ref, "ref"), text(reason, "reason")
    if _PENDING.fullmatch(raw):
        return _reopen(ctx, conn, raw.upper(), why)
    if _UNDO.fullmatch(raw):
        return _unignore(ctx, conn, "U" + raw[1:].lower(), why)
    if _FACT.fullmatch(raw):
        return _fact(ctx, conn, raw.upper(), why)
    low = raw.lower()
    label = raw[5:] if low.startswith("rule:") else raw[:-5] if low.endswith(" rule") else None
    if label is None:
        raise ValidationError("ref")
    cp = counterparty(ctx, conn, label.strip(), "ref")
    rules = ctx.repo.live_rule_ids_for_counterparty(conn, ctx.ws, cp.id)
    if not rules:
        raise ValidationError("rule")
    return Proposal("reverse", {"target": "fact", "ref": f"rule:{label.strip()}", "reason": why},
                    {"type": "reverse", "ref": f"{cp.label} rule", "what": "rule",
                     "counterparty": cp.label, "rules": len(rules), "reason": why},
                    high_value=True)


def _fact(ctx: Ctx, conn, ref: str, why: str) -> Proposal:
    repo, echo, high = ctx.repo, {"type": "reverse", "ref": ref, "reason": why}, False
    if ref[0] == "C":
        ex = repo.exchange_by_ref(conn, ctx.ws, ref)
        if ex is None:
            raise ValidationError("exchange")
        funding = repo.live_funding_for_exchange(conn, ex.id)
        if funding is not None:  # reverse the funding first
            raise ValidationError("funded", {"funding_ref": f"F{funding.number}"})
        usd = sum(ln.usd_minor for ln in repo.current_lines(conn, ex.id))
        echo.update(what="exchange", delivered_on=ex.delivered_on.isoformat(),
                    usd=format_minor(usd, "USD"))
    elif ref[0] == "F":
        f = repo.funding_by_ref(conn, ctx.ws, ref)
        if f is None:
            raise ValidationError("funding")
        exchanges = [repo.exchange_by_id(conn, ctx.ws, eid) for eid in f.exchange_ids]
        usd = sum(ln.usd_minor for eid in f.exchange_ids for ln in repo.current_lines(conn, eid))
        echo.update(what="funding", exchanges=[f"C{ex.number}" for ex in exchanges if ex],
                    eur=format_minor(f.eur_minor, "EUR"), usd=format_minor(usd, "USD"),
                    rate=rate_text(implied_rate(f.eur_minor, usd)))
        high = True
    elif ref[0] == "R":
        rec = repo.receipt_by_ref(conn, ctx.ws, ref)
        if rec is None:
            raise ValidationError("receipt")
        echo.update(what="receipt", receipt_kind=rec.kind.value,
                    payer=_label(ctx, conn, rec.payer_id), currency=rec.currency,
                    amount=format_minor(rec.amount_minor, rec.currency),
                    received_on=rec.received_on.isoformat(),
                    rule=receipt_rule(repo, conn, ctx.ws, ref) is not None)
        high = rec.kind is ReceiptKind.BANK
    else:
        entry = repo.entry_by_ref(conn, ctx.ws, ref)
        if entry is None or entry.kind not in (EntryKind.OPENING, EntryKind.ADJUSTMENT,
                                               EntryKind.FORGIVE):
            raise ValidationError("entry", {"kind": entry.kind.value} if entry else {})
        echo.update(what="entry", entry_kind=entry.kind.value,
                    counterparty=_label(ctx, conn, entry.counterparty_id),
                    currency=entry.currency,
                    amount=format_minor(entry.amount_minor, entry.currency))
    return Proposal("reverse", {"target": "fact", "ref": ref, "reason": why}, echo,
                    high_value=high)


def _reopen(ctx: Ctx, conn, code: str, why: str) -> Proposal:
    """Undo the owner's answer to EXPLAIN_INCOMING ``P<n>`` (refusals as ``reopen_explain``)."""
    repo = ctx.repo
    item = repo.pending_by_code(conn, ctx.ws, code)
    if item is None or item.kind is not PendingKind.EXPLAIN_INCOMING:
        raise CommandRefused({"ok": False, "error": "unknown_pending"})
    if item.resolved_at is None:
        raise CommandRefused({"ok": False, "error": "not_resolved"})
    mv = repo.movement_current(conn, ctx.ws, item.payload.get("movement_id") or "")
    if mv is None or mv.amount_minor <= 0:
        raise CommandRefused({"ok": False, "error": "unknown_movement"})
    if repo.live_funding_for_movement(conn, mv.id) is not None:
        raise CommandRefused({"ok": False, "error": "already_linked"})
    rec = repo.live_receipt_for_movement(conn, mv.id)
    key = incoming_key(repo, mv, True)
    rule = bool(key) and repo.rule_for(conn, ctx.ws, key) == (rec.payer_id if rec else IGNORE)
    return Proposal("reverse", {"target": "reopen", "code": item.code, "reason": why}, {
        "type": "reverse", "ref": item.code, "what": "answer", "movement": movement_echo(mv),
        "receipt_ref": f"R{rec.number}" if rec else None,
        "not_exchange": repo.movement_role(conn, mv.id) is MovementRoleKind.NOT_EXCHANGE,
        "rule": rule, "reason": why}, high_value=rec is not None or rule)


def _unignore(ctx: Ctx, conn, token: str, why: str) -> Proposal:
    match = next((mv for t, _, mv in ignored_movements(ctx.repo, conn, ctx.ws, ctx.now)
                  if t == token), None)
    if match is None:
        raise ValidationError("ref")
    key = incoming_key(ctx.repo, match, True)
    rule = bool(key) and ctx.repo.rule_for(conn, ctx.ws, key) == IGNORE
    return Proposal("reverse", {"target": "unignore", "undo_ref": token, "reason": why}, {
        "type": "reverse", "ref": token, "what": "not_exchange",
        "movement": movement_echo(match), "rule": rule, "reason": why}, high_value=rule)


def reallocation(ctx: Ctx, conn, receipt_ref, allocations) -> Proposal:
    repo = ctx.repo
    rec = repo.receipt_by_ref(conn, ctx.ws, receipt_ref if isinstance(receipt_ref, str) else "")
    payer = repo.get_counterparty(conn, ctx.ws, rec.payer_id) if rec else None
    if rec is None or payer is None or payer.kind is not CounterpartyKind.PERSON:
        raise ValidationError("receipt")
    if not isinstance(allocations, list) or not allocations:
        raise ValidationError("allocations")
    cur = rec.currency
    current = repo.live_allocations_for_receipt(conn, ctx.ws, rec.id)
    free = {ol.line_id: ol.outstanding_minor
            for ol in repo.open_lines(conn, ctx.ws, payer.id, cur)}
    for a in current:  # what each item owes once this receipt's allocations are undone
        free[a.line_id] = free.get(a.line_id, 0) + a.amount_minor
    parts: list[list] = []
    after = []
    for i, item in enumerate(allocations):
        f = f"allocations[{i}]"
        if not isinstance(item, dict):
            raise ValidationError(f)
        name = text(item.get("exchange"), f"{f}.exchange")
        ids = _items(ctx, conn, rec, name)
        if not ids:
            raise ValidationError(f"{f}.exchange", {"item": name})
        amount = positive(item.get("amount"), cur, f"{f}.amount")
        shown = item_ref(repo, conn, ctx.ws, ids[0])
        room = sum(free.get(x, 0) for x in ids)
        if amount > room:
            raise ValidationError(f"{f}.amount", {"item": shown, "outstanding":
                                                  format_minor(room, cur),
                                                  "amount": format_minor(amount, cur)})
        left = amount
        for x in ids:  # a payer's several lines on one exchange fill in position order
            take = min(left, free.get(x, 0))
            if take > 0:
                parts.append([x, take])
                free[x] -= take
                left -= take
        after.append({"item": shown, "amount": format_minor(amount, cur)})
    total = sum(p[1] for p in parts)
    if total > rec.amount_minor:
        raise ValidationError("allocations", {"amount": format_minor(rec.amount_minor, cur),
                                              "total": format_minor(total, cur)})
    return Proposal("reallocate", {"receipt_id": rec.id, "parts": parts}, {
        "type": "reallocate", "receipt_ref": f"R{rec.number}", "payer": payer.label,
        "currency": cur, "amount": format_minor(rec.amount_minor, cur),
        "before": [{"item": item_ref(repo, conn, ctx.ws, a.line_id),
                    "amount": format_minor(a.amount_minor, cur)} for a in current],
        "after": after})


def _items(ctx: Ctx, conn, rec, name: str) -> list[str]:
    """Open-item ids of the receipt's payer and currency named ``C<n>`` or ``opening``/``E<n>``."""
    repo = ctx.repo
    if normalize_alias(name) == "opening" or name.upper().startswith("E"):
        return [e.id for e in repo.effective_entries_for_refs(conn, ctx.ws, [rec.payer_id],
                                                              (EntryKind.OPENING,))
                if e.currency == rec.currency and e.amount_minor > 0
                and (name.upper() == f"E{e.number}" or normalize_alias(name) == "opening")]
    ex = repo.exchange_by_ref(conn, ctx.ws, name)
    if ex is None:
        return []
    return [ln.id for ln in repo.current_lines(conn, ex.id)
            if ln.payer_id == rec.payer_id and ln.debt_currency == rec.currency]
