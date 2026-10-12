"""ECB euro foreign exchange reference rates (daily XML feed).

Published around 16:00 CET on working days. The ECB states the rates are for information
only and discourages transaction use, which is why Finance only uses them for an explicit,
dated valuation line. (The SDMX data-api route was not reachable when this was written, so
the documented XML feed is used.)
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from ..store.repo import FinanceRepository
from .base import ConnectorError, ErrorKind

logger = logging.getLogger("finance.ecb")

ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_NS = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"


def parse_daily_xml(data: bytes) -> tuple[date, dict[str, Decimal]]:
    # ElementTree expands entities; the feed never needs a DTD, so any is refused.
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ConnectorError(ErrorKind.MALFORMED)
    try:
        root = ET.fromstring(data)
        day_cube = next((c for c in root.iter(f"{_NS}Cube") if "time" in c.attrib), None)
        if day_cube is None:
            raise ConnectorError(ErrorKind.MALFORMED)
        day = date.fromisoformat(day_cube.attrib["time"])
        rates: dict[str, Decimal] = {}
        for cube in day_cube.findall(f"{_NS}Cube"):
            currency, rate = cube.attrib["currency"], Decimal(cube.attrib["rate"])
            if currency in rates or rate <= 0 or not rate.is_finite():
                raise ConnectorError(ErrorKind.MALFORMED)
            rates[currency] = rate
    except (ET.ParseError, ValueError, KeyError, InvalidOperation):
        raise ConnectorError(ErrorKind.MALFORMED) from None
    if not rates:
        raise ConnectorError(ErrorKind.MALFORMED)
    return day, rates


class EcbRates:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(transport=transport, timeout=20.0)

    def fetch(self) -> tuple[date, dict[str, Decimal]]:
        try:
            response = self._client.get(ECB_DAILY_URL)
        except httpx.HTTPError:
            raise ConnectorError(ErrorKind.UNAVAILABLE) from None
        if response.status_code != 200:
            raise ConnectorError(ErrorKind.UNAVAILABLE)
        return parse_daily_xml(response.content)


def refresh_rates(repo: FinanceRepository, fetcher: EcbRates) -> bool:
    """Store today's rates. Never raises into the sync: old rates simply stay."""
    try:
        day, rates = fetcher.fetch()
        repo.store_fx_rates(day, rates)
    except ConnectorError as error:
        logger.warning("ecb refresh failed: %s", error.kind.value)
        return False
    except ValueError:
        logger.warning("ecb refresh rejected: conflicting rate for a stored day")
        return False
    return True
