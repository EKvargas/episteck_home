"""Exact FX arithmetic with ``Fraction``. Never floats."""
from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Sequence


def implied_rate(eur_minor: int, usd_minor: int) -> Fraction:
    """EUR per USD."""
    if eur_minor <= 0 or usd_minor <= 0:
        raise ValueError("amounts must be positive")
    return Fraction(eur_minor, usd_minor)


def split_largest_remainder(total_minor: int, weights: Sequence[int]) -> list[int]:
    """Split ``total_minor`` proportionally; sums exactly; remainder ties go to the earlier index."""
    if not weights:
        raise ValueError("weights must not be empty")
    if any(w < 0 for w in weights):
        raise ValueError("weights must not be negative")
    wsum = sum(weights)
    if wsum == 0:
        raise ValueError("weights must not sum to zero")
    if total_minor < 0:
        raise ValueError("total must not be negative")
    shares = [total_minor * w // wsum for w in weights]
    rems = [total_minor * w % wsum for w in weights]
    left = total_minor - sum(shares)
    order = sorted(range(len(weights)), key=lambda i: (-rems[i], i))
    for i in order[:left]:
        shares[i] += 1
    return shares


def deviation(implied: Fraction, usd_per_eur: Decimal) -> Fraction:
    return abs(implied * Fraction(usd_per_eur) - 1)


def rate_text(rate: Fraction) -> str:
    """4 decimals, ROUND_HALF_EVEN (``round`` on a Fraction rounds half to even)."""
    scaled = round(rate * 10000)
    sign = "-" if scaled < 0 else ""
    whole, frac = divmod(abs(scaled), 10000)
    return f"{sign}{whole}.{frac:04d}"
