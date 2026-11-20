"""Read-time interpretation of movements (spec 5.1 rules 1-10) and transfer pairing (5.2).

Pure logic over data already loaded: no database access.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date

from .. import domain
from ..receivables.model import CounterpartyKind, MovementRoleKind
from ..store.receivables_repo import IGNORE
from .model import (
    PAIR_WINDOW_DAYS, Interpretation, InterpretationFacts, Kind, is_stale_pending,
    movement_day,
)
from .text import same_person, sender_key, zelle_recipient

_ROLE_KIND = {
    MovementRoleKind.FUND_DEPOSIT: Kind.FUND,
    MovementRoleKind.EXCHANGE_FUNDING: Kind.EXCHANGE,
    MovementRoleKind.RECEIVABLE_PAYMENT: Kind.FAMILY,
    MovementRoleKind.PARTNER_SIDE: Kind.PARTNER_FAVOR,
}
_COUNTERPARTY_KIND = {
    CounterpartyKind.PERSON: Kind.FAMILY,
    CounterpartyKind.EXCHANGE_PARTNER: Kind.PARTNER_FAVOR,
    CounterpartyKind.FUND: Kind.FUND,
}


def family_senders(incoming: Sequence[domain.Movement], facts: InterpretationFacts,
                   key_of: Callable[[domain.Movement], str | None]) -> dict[str, str]:
    """``sender_key`` (uncapped) of each sender known to be family -> its PERSON label."""
    senders: dict[str, str] = {}
    for mv in incoming:
        person = None
        receipt = facts.receipts.get(facts.root(mv.id))
        if receipt is not None:
            person = facts.counterparties.get(receipt.payer_id)
        else:
            key = key_of(mv)
            target = facts.rules.get(key) if key else None
            if target is not None and target != IGNORE:
                person = facts.counterparties.get(target)
        if person is None or person.kind is not CounterpartyKind.PERSON:
            continue
        who = sender_key(mv.counterparty_name, mv.remittance)
        if who:
            senders.setdefault(who, person.label)
    return senders


def pair_transfers(candidates: Sequence[tuple[int, domain.Movement]], today: date) -> set[str]:
    """Ids of movements that pair one to one as transfers between own accounts."""
    items: list[tuple[int, domain.Movement, date]] = []
    for rowid, mv in candidates:
        day = movement_day(mv)
        if day is None or mv.amount_minor == 0:
            continue
        if is_stale_pending(mv, today):
            continue
        items.append((rowid, mv, day))
    pairs: list[tuple[int, int, int, str, str]] = []
    groups: dict[tuple[str, int], list[tuple[int, domain.Movement, date]]] = {}
    for item in items:  # only equal-and-opposite amounts in one currency can pair
        groups.setdefault((item[1].currency, abs(item[1].amount_minor)), []).append(item)
    for group in groups.values():
        for i, (ra, a, da) in enumerate(group):
            for rb, b, db in group[i + 1:]:
                if (a.amount_minor == -b.amount_minor and a.account_id != b.account_id
                        and abs((da - db).days) <= PAIR_WINDOW_DAYS):
                    pairs.append((abs((da - db).days), min(ra, rb), max(ra, rb), a.id, b.id))
    paired: set[str] = set()
    for _gap, _lo, _hi, id_a, id_b in sorted(pairs):
        if id_a in paired or id_b in paired:
            continue
        paired.update((id_a, id_b))
    return paired


def interpret(rows: Sequence[tuple[int, domain.Movement]],
              accounts: Mapping[str, domain.Account], facts: InterpretationFacts,
              key_of: Callable[[domain.Movement], str | None], senders: Mapping[str, str],
              today: date) -> dict[str, Interpretation]:
    out: dict[str, Interpretation] = {}
    own: list[tuple[int, domain.Movement]] = []
    for rowid, mv in rows:
        result = _rules_1_to_8(mv, accounts, facts, key_of, senders)
        if result is None:
            own.append((rowid, mv))
        else:
            out[mv.id] = result
    paired = pair_transfers(own, today)
    for _rowid, mv in own:
        out[mv.id] = Interpretation(Kind.OWN_TRANSFER if mv.id in paired else Kind.OWN)
    return out


def _rules_1_to_8(mv, accounts, facts, key_of, senders) -> Interpretation | None:
    root = facts.root(mv.id)
    funding = facts.fundings.get(root)
    if funding is not None:  # 1
        return Interpretation(Kind.EXCHANGE, ref=f"F{funding.number}", funding_id=funding.id)
    receipt = facts.receipts.get(root)
    if receipt is not None:  # 2
        payer = facts.counterparties.get(receipt.payer_id)
        is_fund = payer is not None and payer.kind is CounterpartyKind.FUND
        return Interpretation(Kind.FUND if is_fund else Kind.FAMILY,
                              about=payer.label if payer else None, ref=f"R{receipt.number}")
    role = facts.roles.get(root)
    if role in _ROLE_KIND:  # 3
        return Interpretation(_ROLE_KIND[role])
    code = facts.questions.get(root)
    if code is not None:  # 4
        return Interpretation(Kind.UNCLEAR, ref=code)
    iban = mv.counterparty_iban_hash
    if iban and iban in facts.partner_hashes:  # 5
        return Interpretation(Kind.EXCHANGE)
    if iban and iban in facts.own_hashes:  # 6
        return Interpretation(Kind.OWN_TRANSFER)
    if mv.amount_minor > 0 and role is not MovementRoleKind.NOT_EXCHANGE:  # 7
        key = key_of(mv)
        target = facts.rules.get(key) if key else None
        cp = facts.counterparties.get(target) if target and target != IGNORE else None
        if cp is not None:
            return Interpretation(_COUNTERPARTY_KIND[cp.kind], about=cp.label)
    account = accounts.get(mv.account_id)
    if account is not None and account.currency == "USD" and mv.amount_minor < 0:  # 8
        recipient = zelle_recipient(mv.counterparty_name, mv.remittance)
        label = _closest_sender(recipient, senders) if recipient else None
        if label is not None:
            return Interpretation(Kind.FAMILY_HELP, about=label)
    return None


def _closest_sender(recipient: str, senders: Mapping[str, str]) -> str | None:
    """The label of the sender naming the same person: an exact word-set match first, then
    the largest word overlap, then the first listed."""
    words = set(recipient.split())
    best: tuple[int, int] | None = None
    label = None
    for who, who_label in senders.items():
        if not same_person(recipient, who):
            continue
        other = set(who.split())
        score = (int(other == words), len(other & words))
        if best is None or score > best:
            best, label = score, who_label
    return label
