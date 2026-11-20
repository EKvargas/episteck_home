"""Shapes money, flows and movement lines for the finance tools (spec 5.6).

No id, IBAN, hash or provider id ever leaves through these functions.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from .. import domain
from ..money import format_minor
from .model import HelpItem, Interpretation, Kind, is_stale_pending, movement_day
from .text import display_text, display_who


def money(minor: int, currency: str) -> dict:
    return {"amount_minor": minor, "amount": format_minor(minor, currency)}


def flow(movements: Iterable[domain.Movement], currency: str) -> dict:
    count = total_in = total_out = 0
    for mv in movements:
        count += 1
        if mv.amount_minor > 0:
            total_in += mv.amount_minor
        else:
            total_out -= mv.amount_minor
    return {"count": count, "in": money(total_in, currency), "out": money(total_out, currency)}


def movement_line(mv: domain.Movement, interp: Interpretation, account: domain.Account,
                  today: date, parts: Sequence[HelpItem] = ()) -> dict:
    day = movement_day(mv)
    line = {
        "date": day.isoformat() if day else None,
        "account": {"id": account.id, "institution": account.institution},
        "amount_minor": mv.amount_minor,
        "amount": format_minor(mv.amount_minor, mv.currency),
        "currency": mv.currency,
        "status": mv.status.value,
        "stale_pending": is_stale_pending(mv, today),
        "who": display_who(mv.counterparty_name, mv.remittance),
        "text": display_text(mv.remittance),
        "kind": interp.kind.value,
        "about": interp.about,
        "ref": interp.ref,
    }
    if interp.kind is Kind.EXCHANGE and parts:
        own = [p for p in parts if p.source == "exchange_own"]
        line["own_part"] = (money(sum(p.amount_minor for p in own), own[0].currency)
                            if own else None)
        line["help"] = [{"about": p.about, **money(p.amount_minor, p.currency)}
                        for p in parts if p.source == "exchange_help"]
    return line
