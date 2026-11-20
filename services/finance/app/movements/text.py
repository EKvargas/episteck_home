"""Text helpers for movement search and display. Pure functions; no database access."""
from __future__ import annotations

import unicodedata

from .. import domain
from ..receivables.explain import _RAILS
from ..receivables.text import description_key
from .model import TEXT_CHARS, WHO_CHARS

OUTGOING_RAILS = ("ZELLE PAYMENT TO ", "ZELLE TO ")


def fold(text: str) -> str:
    """Casefold, drop combining marks after NFKD, collapse spaces."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


def matches(query: str, *fields: str) -> bool:
    """Every word of ``query`` is a literal substring of the fields (accent and case blind)."""
    haystack = fold(" ".join(fields))
    return all(word in haystack for word in fold(query).split())


def _strip_rail(text: str, rails: tuple[str, ...]) -> str | None:
    for rail in rails:
        if text.startswith(rail):
            return text[len(rail):]
    return None


def _drop_markers(text: str) -> str:
    return " ".join(w for w in text.split() if not w.endswith("#"))


def sender_key(name: str, remittance: str) -> str:
    """The sender text without rails or markers and without any length cap."""
    text = description_key(name or remittance)
    for rails in (_RAILS, OUTGOING_RAILS):
        rest = _strip_rail(text, rails)
        if rest is not None:
            text = rest
            break
    return _drop_markers(text)


def display_who(name: str, remittance: str) -> str:
    return sender_key(name, remittance)[:WHO_CHARS].rstrip()


def display_text(remittance: str) -> str:
    kept: list[str] = []
    skip_next = False
    for token in remittance.split():
        if skip_next:
            skip_next = False
            continue
        if token.endswith("#"):
            skip_next = True
            continue
        if any(c.isdigit() for c in token):
            continue
        kept.append(token)
    return " ".join(kept)[:TEXT_CHARS].rstrip()


def zelle_recipient(name: str, remittance: str) -> str | None:
    for text in (description_key(remittance), description_key(name)):
        rest = _strip_rail(text, OUTGOING_RAILS)
        if rest is not None:
            return _drop_markers(rest)
    return None


def same_person(a: str, b: str) -> bool:
    wa, wb = set(a.split()), set(b.split())
    return len(wa) >= 2 and len(wb) >= 2 and (wa <= wb or wb <= wa)


def is_undescribed(mv: domain.Movement) -> bool:
    return not (mv.counterparty_name or "").strip() and not (mv.remittance or "").strip()
