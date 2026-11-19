"""Read views: exchanges, a receivables view for one counterparty, pending items, history.

Rows name facts by ref (``C<n>``, ``F<n>``, ``R<n>``, ``E<n>``, ``P<n>``) with dates and
current-line totals, never by id, IBAN or hash. Option values that hold an id (``CP:``,
``M:``) are shown as a stable opaque token derived from the value (``choice_token``), never
by position, so a refreshed question cannot turn a tap into another option (R44).
"""
from __future__ import annotations

import re
from collections.abc import Callable

from ..money import format_minor, parse_amount
from ..store.receivables_repo import ReceivablesRepository
from .commands import Ctx, allocation_rows, ignored_movements, item_ref
from .fx import implied_rate, rate_text
from .ledger import ValidationError
from .model import (
    OWNER, Counterparty, CounterpartyKind, EntryKind, Exchange, LedgerEntry, PendingItem,
    PendingKind,
)
from .proposals import ANY_KIND, counterparty, day, movement_echo, text
from .text import normalize_alias

PRIVATE_OPTIONS = ("CP:", "M:")
# text_key is a dedupe key ("fund_low:<counterparty id>:E<n>"): shown as its first part only
HIDDEN_PAYLOAD = frozenset({"movement_id", "labels", "exact", "text_key"})
_REF = re.compile(r"([CFREP])(\d{1,9})", re.IGNORECASE | re.ASCII)


def names(ctx: Ctx, conn) -> dict[str, str]:
    out = {cp.id: cp.label for cp in ctx.repo.list_counterparties(conn, ctx.ws)}
    out[OWNER] = "owner"
    return out


# --- receivables and exchanges -------------------------------------------------------
def _subtotals(rows: list[dict]) -> dict[str, str]:
    sums: dict[str, int] = {}
    for r in rows:
        minor = parse_amount(r["amount"], r["currency"]) if r["amount"] is not None else 0
        if minor > 0:  # a fund the owner is advancing is not held for anyone
            sums[r["currency"]] = sums.get(r["currency"], 0) + minor
    return {c: format_minor(v, c) for c, v in sorted(sums.items())}


def for_counterparty(view: dict, cp: Counterparty) -> dict:
    """The receivables view narrowed to one counterparty, subtotals recomputed."""
    def mine(rows):
        return [r for r in rows if r["counterparty"] == cp.label]

    owed, held = mine(view["owed_to_you"]), mine(view["held_for_others"])
    partner = cp.kind is CounterpartyKind.EXCHANGE_PARTNER
    return {**view, "counterparty": cp.label, "owed_to_you": owed, "held_for_others": held,
            "to_fix": mine(view["to_fix"]),
            "owed_to_partner": view["owed_to_partner"] if partner else None,
            "subtotals": {"owed_to_you": _subtotals(owed), "held_for_others": _subtotals(held)}}


def exchange_row(ctx: Ctx, conn, ex: Exchange, labels: dict[str, str]) -> dict:
    repo = ctx.repo
    current = repo.current_lines(conn, ex.id)
    funding = repo.live_funding_for_exchange(conn, ex.id)
    eur: dict[str, int] = {}
    rate = None
    if funding is not None:
        for e in repo.effective_charges_for_exchange(conn, ctx.ws, ex.id, "EUR"):
            eur[e.source_ref] = eur.get(e.source_ref, 0) + e.amount_minor
        usd = sum(ln.usd_minor for eid in funding.exchange_ids
                  for ln in repo.current_lines(conn, eid))
        rate = rate_text(implied_rate(funding.eur_minor, usd))
    return {
        "exchange_ref": f"C{ex.number}", "delivered_on": ex.delivered_on.isoformat(),
        "status": "PAID" if funding else "OPEN",
        "usd": format_minor(sum(ln.usd_minor for ln in current), "USD"),
        "ves": None if ex.ves_amount_minor is None else format_minor(ex.ves_amount_minor, "VES"),
        "funding_ref": f"F{funding.number}" if funding else None, "rate": rate,
        "lines": [{"payer": labels.get(ln.payer_id, "?"), "usd": format_minor(ln.usd_minor, "USD"),
                   "debt_currency": None if ln.payer_id == OWNER else ln.debt_currency,
                   "eur": format_minor(eur[ln.id], "EUR") if ln.id in eur else None,
                   "note": ln.beneficiary_note} for ln in current]}


def exchanges(ctx: Ctx, conn, status, since) -> dict:
    want = status.strip().upper() if isinstance(status, str) else status
    if want not in (None, "OPEN", "PAID"):
        raise ValidationError("status", {"allowed": "OPEN, PAID"})
    start = day(since, "since")
    labels = names(ctx, conn)
    rows = [exchange_row(ctx, conn, ex, labels) for ex in ctx.repo.live_exchanges(conn, ctx.ws)
            if start is None or ex.delivered_on >= start]
    return {"ok": True, "as_of": ctx.now.date().isoformat(),
            "exchanges": [r for r in rows if want is None or r["status"] == want]}


# --- pending -------------------------------------------------------------------------
def choice_token(repo: ReceivablesRepository, value: str) -> str:
    """A private option's public handle: ``O`` + 8 hex of the keyed hash of its value. The
    same value keeps its token when the question is refreshed; it never reveals the id."""
    return "O" + repo.hash_key(f"choice:{value}")[:8].lower()


def choice(value: str, token: Callable[[str], str]) -> str:
    """What an owner taps or types for an option: the token of a private value, else the value."""
    return token(value) if value.startswith(PRIVATE_OPTIONS) else value


def public_resolution(resolution: str | None) -> str | None:
    if resolution and resolution.startswith(PRIVATE_OPTIONS):
        return "answered"
    return resolution


def render_pending(item: PendingItem, token: Callable[[str], str]) -> dict:
    labels = item.payload.get("labels") or {}
    options = []
    for n, value in enumerate(item.options, 1):
        private = value.startswith(PRIVATE_OPTIONS)
        options.append({"n": n, "choice": choice(value, token),
                        "label": labels.get(value) or (f"option {n}" if private else value)})
    out = {"code": item.code, "kind": item.kind.value, "requires_answer": item.requires_answer,
           "created_at": item.created_at.isoformat(), "delivered": item.delivered_at is not None,
           "options": options}
    if item.kind is PendingKind.CONFIRM:
        p = item.payload
        out.update(command=p["command"], status=p["status"], echo=p["echo"],
                   high_value=p["high_value"])
        return out
    out["details"] = {k: v for k, v in item.payload.items() if k not in HIDDEN_PAYLOAD}
    if item.kind is PendingKind.INFO:
        out["notice"] = str(item.payload.get("text_key", "")).split(":")[0]
    exact = item.payload.get("exact")
    if exact in item.options:
        out["suggested"] = item.options.index(exact) + 1
    return out


# --- history -------------------------------------------------------------------------
def _entry_rows(ctx: Ctx, conn, entries: list[LedgerEntry], labels: dict[str, str],
                context: list[LedgerEntry] | None = None) -> list[dict]:
    repo, pool = ctx.repo, context if context is not None else entries
    numbers = {e.id: e.number for e in pool}
    undone = {e.reverses_id for e in pool if e.kind is EntryKind.REVERSAL
              and repo.is_live(conn, "ledger_entry", e.id)}
    rows = []
    for e in entries:
        target = numbers.get(e.reverses_id) if e.reverses_id else None
        if e.reverses_id and target is None:
            found = repo.entry_by_id(conn, ctx.ws, e.reverses_id)
            target = found.number if found else None
        rows.append({
            "ref": f"E{e.number}", "entry_kind": e.kind.value,
            "counterparty": labels.get(e.counterparty_id, "?"), "currency": e.currency,
            "amount": format_minor(e.amount_minor, e.currency),
            "date": e.effective_on.isoformat(), "note": e.note or None,
            "reverses": f"E{target}" if target else None,
            "undone": e.id in undone or not repo.is_live(conn, "ledger_entry", e.id)})
    return rows


def explain(ctx: Ctx, conn, ref) -> dict:
    raw = text(ref, "ref")
    if normalize_alias(raw) in ("ignored", "ignorados"):
        return {"ok": True, "ref": "ignored", "movements": [
            {"undo_ref": token, **movement_echo(mv)}
            for token, _, mv in ignored_movements(ctx.repo, conn, ctx.ws, ctx.now)]}
    m = _REF.fullmatch(raw)
    if m is None:
        return _counterparty(ctx, conn, raw)
    handler = {"C": _exchange, "F": _funding, "R": _receipt, "E": _entry,
               "P": _pending}[m[1].upper()]
    return handler(ctx, conn, raw.upper())


def _exchange(ctx: Ctx, conn, ref: str) -> dict:
    repo = ctx.repo
    ex = repo.exchange_by_ref(conn, ctx.ws, ref, include_revoked=True)
    if ex is None:
        raise ValidationError("ref")
    labels = names(ctx, conn)
    fundings = [{"ref": f"F{f.number}", "live": repo.is_live(conn, "funding", f.id)}
                for f in repo.fundings_for_exchange(conn, ctx.ws, ex.id)]
    every = repo.exchange_lines(conn, ex.id)
    versions: dict[int, list[dict]] = {}
    for ln in every:
        versions.setdefault(ln.version, []).append({
            "payer": labels.get(ln.payer_id, "?"), "usd": format_minor(ln.usd_minor, "USD"),
            "debt_currency": None if ln.payer_id == OWNER else ln.debt_currency,
            "note": ln.beneficiary_note})
    live = repo.is_live(conn, "exchange", ex.id)
    current = repo.current_lines(conn, ex.id)
    return {
        "ok": True, "ref": f"C{ex.number}", "kind": "exchange",
        "status": "REVERSED" if not live else "PAID" if any(f["live"] for f in fundings)
        else "OPEN",
        "delivered_on": ex.delivered_on.isoformat(),
        "registered_usd": format_minor(ex.total_usd_minor, "USD"),
        "usd": format_minor(sum(ln.usd_minor for ln in current), "USD"),
        "ves": None if ex.ves_amount_minor is None else format_minor(ex.ves_amount_minor, "VES"),
        "versions": [{"version": v, "lines": rows} for v, rows in sorted(versions.items())],
        "fundings": fundings,
        "entries": _entry_rows(ctx, conn, repo.entries_by_sources(
            conn, ctx.ws, [ln.id for ln in every]), labels)}


def _funding(ctx: Ctx, conn, ref: str) -> dict:
    repo = ctx.repo
    f = repo.funding_by_ref(conn, ctx.ws, ref, include_revoked=True)
    if f is None:
        raise ValidationError("ref")
    labels = names(ctx, conn)
    exchanges_ = [repo.exchange_by_id(conn, ctx.ws, eid, include_revoked=True)
                  for eid in f.exchange_ids]
    usd = sum(ln.usd_minor for eid in f.exchange_ids for ln in repo.current_lines(conn, eid))
    payments = []
    for root in f.movement_ids:
        mv = repo.movement_current(conn, ctx.ws, root)
        if mv is not None:
            payments.append({"date": (mv.booking_date or mv.value_date).isoformat(),
                             "eur": format_minor(-mv.amount_minor, "EUR")})
    return {"ok": True, "ref": f"F{f.number}", "kind": "funding",
            "live": repo.is_live(conn, "funding", f.id), "eur": format_minor(f.eur_minor, "EUR"),
            "usd": format_minor(usd, "USD"), "rate": rate_text(implied_rate(f.eur_minor, usd)),
            "exchanges": [f"C{ex.number}" for ex in exchanges_ if ex], "payments": payments,
            "shares": [{"payer": labels.get(payer, "?"), "eur": format_minor(eur, "EUR")}
                       for payer, eur in repo.funding_shares(conn, f.id).items()]}


def _receipt(ctx: Ctx, conn, ref: str) -> dict:
    repo = ctx.repo
    rec = repo.receipt_by_ref(conn, ctx.ws, ref, include_revoked=True)
    if rec is None:
        raise ValidationError("ref")
    return {"ok": True, "ref": f"R{rec.number}", "kind": "receipt",
            "receipt_kind": rec.kind.value, "payer": names(ctx, conn).get(rec.payer_id, "?"),
            "currency": rec.currency, "amount": format_minor(rec.amount_minor, rec.currency),
            "received_on": rec.received_on.isoformat(), "verification": rec.verification.value,
            "description": rec.description or None,
            "live": repo.is_live(conn, "receipt", rec.id),
            "allocations": allocation_rows(repo, conn, ctx.ws, rec)}


def _entry(ctx: Ctx, conn, ref: str) -> dict:
    repo = ctx.repo
    e = repo.entry_by_ref(conn, ctx.ws, ref, include_undone=True)
    if e is None:
        raise ValidationError("ref")
    history = repo.entries(conn, ctx.ws, e.counterparty_id)
    [row] = _entry_rows(ctx, conn, [e], names(ctx, conn), history)
    by = [x for x in history if x.reverses_id == e.id]
    source = None
    if e.kind is not EntryKind.OPENING:
        source = item_ref(repo, conn, ctx.ws, e.source_ref)
        rec = None if source else repo.receipt_by_id(conn, ctx.ws, e.source_ref)
        source = source or (f"R{rec.number}" if rec else None)
    return {"ok": True, **row, "kind": "entry", "basis": e.basis, "source": source,
            "reversed_by": f"E{by[-1].number}" if by else None}


def _pending(ctx: Ctx, conn, ref: str) -> dict:
    item = ctx.repo.pending_by_code(conn, ctx.ws, ref)
    if item is None:
        raise ValidationError("ref")
    pending = render_pending(item, lambda value: choice_token(ctx.repo, value))
    return {"ok": True, "ref": item.code, "kind": "pending", "pending": pending,
            "resolution": public_resolution(item.resolution),
            "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None}


def _counterparty(ctx: Ctx, conn, name: str) -> dict:
    cp = counterparty(ctx, conn, name, "ref", ANY_KIND, active=False)
    entries = ctx.repo.entries(conn, ctx.ws, cp.id)
    balances = {cur: format_minor(bal, cur)
                for (cid, cur), bal in sorted(ctx.repo.balances(conn, ctx.ws).items())
                if cid == cp.id and bal != 0}
    return {"ok": True, "ref": cp.label, "kind": "counterparty",
            "counterparty_kind": cp.kind.value, "status": cp.status,
            "opening": cp.opening.value if cp.opening else None, "balances": balances,
            "entries": _entry_rows(ctx, conn, entries, names(ctx, conn))}
