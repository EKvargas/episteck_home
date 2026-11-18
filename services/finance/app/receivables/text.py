"""Text keys for alias matching and bank-description grouping."""
from __future__ import annotations

import unicodedata


def normalize_alias(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    folded = " ".join(stripped.casefold().split())
    start, end = 0, len(folded)
    while start < end and unicodedata.category(folded[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(folded[end - 1]).startswith("P"):
        end -= 1
    return folded[start:end].strip()


def description_key(text: str) -> str:
    """Upper case; drop digit-bearing tokens and the token right after one ending in ``#``."""
    kept: list[str] = []
    skip_next = False
    for token in text.upper().split():
        if skip_next:
            skip_next = False
            continue
        if token.endswith("#"):
            skip_next = True
        if any(c.isdigit() for c in token):
            continue
        kept.append(token)
    return " ".join(kept)
