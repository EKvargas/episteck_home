"""The per-period summary of the owner's own money (spec 5.4). Pure: no database access."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from .. import domain
from .model import EXCLUDED_GROUPS, TOP_SPENDING, HelpItem, Interpretation, Kind, Period
from .text import is_undescribed
from .views import flow, money, movement_line


def summarize(period: Period, rows: Sequence[tuple[domain.Movement, Interpretation]],
              helps: Sequence[HelpItem], accounts: Mapping[str, domain.Account],
              currencies: Sequence[str], today: date) -> dict:
    helps = [h for h in helps if period.start <= h.day <= period.end]
    codes = sorted({*currencies, *(h.currency for h in helps)})
    blocks = [_block(cur, [r for r in rows if r[0].currency == cur],
                     [h for h in helps if h.currency == cur], accounts, today)
              for cur in codes]
    # an outgoing payment to the partner with no live funding: either unrecognised by I2 or
    # waiting on its LINK_FUNDING question (an outgoing UNCLEAR is always that question)
    without_split = any(
        mv.status is domain.MovementStatus.BOOKED and mv.amount_minor < 0
        and ((ip.kind is Kind.EXCHANGE and ip.funding_id is None) or ip.kind is Kind.UNCLEAR)
        for mv, ip in rows)
    return {"currencies": blocks, "exchanges_without_split": without_split}


def _block(cur: str, rows, helps, accounts, today: date) -> dict:
    booked = [(mv, ip) for mv, ip in rows if mv.status is domain.MovementStatus.BOOKED]

    def of(kind: Kind) -> list[domain.Movement]:
        return [mv for mv, ip in booked if ip.kind is kind]

    def help_sum(source: str) -> int:
        return sum(h.amount_minor for h in helps if h.source == source)

    own = of(Kind.OWN)
    income = sum(mv.amount_minor for mv in own if mv.amount_minor > 0)
    bank = -sum(mv.amount_minor for mv in own if mv.amount_minor < 0)
    zelle = -sum(mv.amount_minor for mv in of(Kind.FAMILY_HELP))
    ex_own, ex_help, forgiven = (help_sum(s) for s in ("exchange_own", "exchange_help", "forgiven"))
    spending = bank + zelle + ex_own + ex_help + forgiven
    family = zelle + ex_help + forgiven

    people: dict[str, int] = {}
    for mv, ip in booked:
        if ip.kind is Kind.FAMILY_HELP and ip.about:
            people[ip.about] = people.get(ip.about, 0) - mv.amount_minor
    for h in helps:
        if h.source in ("exchange_help", "forgiven") and h.about:
            people[h.about] = people.get(h.about, 0) + h.amount_minor
    by_person = [{"about": name, **money(total, cur)}
                 for name, total in sorted(people.items(), key=lambda kv: (-kv[1], kv[0]))
                 if total != 0]

    interp = {mv.id: ip for mv, ip in booked}
    debits = sorted((mv for mv in own if mv.amount_minor < 0),
                    key=lambda mv: (mv.amount_minor, mv.id))[:TOP_SPENDING]
    return {
        "currency": cur,
        "income": money(income, cur),
        "spending": {**money(spending, cur), "bank": money(bank, cur),
                     "zelle_help": money(zelle, cur), "exchange_own": money(ex_own, cur),
                     "exchange_help": money(ex_help, cur), "forgiven": money(forgiven, cur)},
        "family_help": {**money(family, cur), "by_person": by_person},
        "net": money(income - spending, cur),
        "excluded": {group: flow(of(kind), cur) for kind, group in EXCLUDED_GROUPS.items()},
        "unclear": flow(of(Kind.UNCLEAR), cur),
        "pending_bank": flow([mv for mv, _ in rows
                              if mv.status is domain.MovementStatus.PENDING], cur),
        "undescribed": flow([mv for mv in own if is_undescribed(mv)], cur),
        "top_spending": [movement_line(mv, interp[mv.id], accounts[mv.account_id], today)
                         for mv in debits],
    }
