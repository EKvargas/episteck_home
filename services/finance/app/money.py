"""Money as integer minor units plus an ISO 4217 currency. Never float.

``Decimal`` exists only here, at the I/O edge. Providers send amounts as strings; we
convert once and carry ``int`` everywhere else. An amount with more decimals than the
currency allows is an error, never a silent rounding of a bank figure.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# ISO 4217 minor-unit exponents for the currencies this service may meet. Unknown
# currencies are a hard error rather than a guessed exponent.
EXPONENTS: dict[str, int] = {
    "EUR": 2, "USD": 2, "GBP": 2, "CHF": 2, "CAD": 2, "AUD": 2, "SEK": 2, "NOK": 2,
    "DKK": 2, "PLN": 2, "CZK": 2, "VES": 2, "MXN": 2, "BRL": 2, "COP": 2,
    "JPY": 0, "HUF": 2, "KRW": 0, "BHD": 3, "KWD": 3,
}

_PLAIN_DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")


class UnknownCurrency(ValueError):
    """The currency has no known minor-unit exponent."""


def exponent(currency: str) -> int:
    try:
        return EXPONENTS[currency]
    except KeyError:
        raise UnknownCurrency(currency) from None


def parse_amount(value: str, currency: str) -> int:
    """Parse a plain decimal string ("1234.50", "-0.05") into minor units."""
    if not isinstance(value, str):
        raise TypeError("amount must be a string; floats are not accepted")
    exp = exponent(currency)
    text = value.strip()
    if not _PLAIN_DECIMAL.match(text):
        raise ValueError("amount is not a plain decimal string")
    try:
        number = Decimal(text)
    except InvalidOperation:  # pragma: no cover - guarded by the regex
        raise ValueError("amount is not a plain decimal string") from None
    scaled = number * (Decimal(10) ** exp)
    if scaled != scaled.to_integral_value():
        raise ValueError("amount has more decimals than the currency allows")
    return int(scaled)


def format_minor(minor: int, currency: str) -> str:
    """Render minor units as a plain decimal string without losing precision."""
    exp = exponent(currency)
    sign = "-" if minor < 0 else ""
    digits = str(abs(minor))
    if exp == 0:
        return f"{sign}{digits}"
    digits = digits.rjust(exp + 1, "0")
    return f"{sign}{digits[:-exp]}.{digits[-exp:]}"
