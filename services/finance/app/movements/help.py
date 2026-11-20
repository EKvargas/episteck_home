"""Family help and the owner's own part of exchanges (spec 5.3), computed from I2 data.

Read only. ``help_items`` covers every period; ``summarize`` filters by ``day``.
"""
from __future__ import annotations

from .. import domain
from ..receivables.fx import split_largest_remainder
from ..receivables.model import OWNER, EntryKind, Funding
from ..receivables.text import normalize_alias
from ..store.receivables_repo import ReceivablesRepository
from .model import HelpItem, InterpretationFacts, movement_day


def help_items(rx: ReceivablesRepository, conn, ws: str,
               facts: InterpretationFacts) -> list[HelpItem]:
    items: list[HelpItem] = []
    seen: set[str] = set()
    for funding in sorted(facts.fundings.values(), key=lambda f: f.number):
        if funding.id not in seen:
            seen.add(funding.id)
            items.extend(_exchange_parts(rx, conn, ws, facts, funding))
    items.extend(_forgiven(rx, conn, ws, facts))
    return items


def _exchange_parts(rx, conn, ws: str, facts: InterpretationFacts,
                    funding: Funding) -> list[HelpItem]:
    owner_share = rx.funding_shares(conn, funding.id).get(OWNER, 0)
    if owner_share == 0:
        return []
    day = None
    for root in funding.movement_ids:
        mv = rx.movement_current(conn, ws, root)
        if mv is None or mv.status is not domain.MovementStatus.BOOKED:
            return []  # wait until every payment is booked
        d = movement_day(mv)
        if d is None:
            return []
        day = d if day is None or d > day else day
    if day is None:
        return []
    exchanges = [ex for ex in (rx.exchange_by_id(conn, ws, eid) for eid in funding.exchange_ids)
                 if ex is not None]
    lines = [ln for ex in sorted(exchanges, key=lambda e: e.number)
             for ln in rx.current_lines(conn, ex.id) if ln.payer_id == OWNER]
    if not lines:
        return []
    parts = split_largest_remainder(owner_share, [ln.usd_minor for ln in lines])
    ref = f"F{funding.number}"
    out: list[HelpItem] = []
    for ln, amount in zip(lines, parts):
        note = (ln.beneficiary_note or "").strip()
        if note:
            person = facts.counterparties.get(facts.person_names.get(normalize_alias(note), ""))
            out.append(HelpItem("exchange_help", "EUR", amount, day,
                                person.label if person else note, ref))
        else:
            out.append(HelpItem("exchange_own", "EUR", amount, day, None, ref))
    return out


def _forgiven(rx, conn, ws: str, facts: InterpretationFacts) -> list[HelpItem]:
    out: list[HelpItem] = []
    for entry in rx.forgive_history(conn, ws):
        if entry.kind not in (EntryKind.FORGIVE, EntryKind.REVERSAL):
            continue
        cp = facts.counterparties.get(entry.counterparty_id)
        out.append(HelpItem("forgiven", entry.currency, -entry.amount_minor, entry.effective_on,
                            cp.label if cp else None, None))
    return out
