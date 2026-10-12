from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.connectors.base import ConnectorError, ErrorKind
from app.connectors.ecb import ECB_DAILY_URL, EcbRates, parse_daily_xml, refresh_rates
from tests.support import make_repo

SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube>
    <Cube time="2026-10-09">
      <Cube currency="USD" rate="1.0834"/>
      <Cube currency="CHF" rate="0.9512"/>
      <Cube currency="JPY" rate="162.31"/>
    </Cube>
  </Cube>
</gesmes:Envelope>"""


def _mutate(old: bytes, new: bytes) -> bytes:
    assert old in SAMPLE
    return SAMPLE.replace(old, new, 1)


def test_parses_the_daily_feed_into_exact_decimals():
    day, rates = parse_daily_xml(SAMPLE)
    assert day == date(2026, 10, 9)
    assert rates == {"USD": Decimal("1.0834"), "CHF": Decimal("0.9512"), "JPY": Decimal("162.31")}


@pytest.mark.parametrize("payload", [
    SAMPLE.replace(b"<gesmes:Envelope",                      # well-formed XML with an entity
                   b'<!DOCTYPE gesmes:Envelope [<!ENTITY a "aaaa">]>\n<gesmes:Envelope', 1),
    _mutate(b'time="2026-10-09"', b'time="soon"'),          # bad date
    _mutate(b'rate="1.0834"', b'rate="abc"'),               # not a number
    _mutate(b'rate="1.0834"', b'rate="-1"'),                # not positive
    _mutate(b'rate="0.9512"', b'rate="1.1"').replace(b'currency="CHF"', b'currency="USD"'),
    b"not xml at all",
    b"<a/>",
])
def test_anything_unexpected_is_malformed(payload):
    with pytest.raises(ConnectorError) as raised:
        parse_daily_xml(payload)
    assert raised.value.kind is ErrorKind.MALFORMED


def test_fetch_uses_the_documented_daily_feed():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, content=SAMPLE)

    day, rates = EcbRates(transport=httpx.MockTransport(handler)).fetch()
    assert seen["url"] == ECB_DAILY_URL
    assert ECB_DAILY_URL == "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
    assert day == date(2026, 10, 9) and "USD" in rates


def test_fetch_failures_are_typed():
    for response, kind in ((httpx.Response(503), ErrorKind.UNAVAILABLE),
                           (httpx.Response(200, content=b"junk"), ErrorKind.MALFORMED)):
        with pytest.raises(ConnectorError) as raised:
            EcbRates(transport=httpx.MockTransport(lambda r, resp=response: resp)).fetch()
        assert raised.value.kind is kind


def test_refresh_stores_rates_and_is_idempotent(tmp_path):
    repo = make_repo(tmp_path)
    fetcher = EcbRates(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=SAMPLE)))
    assert refresh_rates(repo, fetcher) is True
    assert refresh_rates(repo, fetcher) is True
    assert repo.latest_fx_rates().per_eur["USD"] == Decimal("1.0834")


def test_a_failed_refresh_keeps_old_rates_and_never_raises(tmp_path):
    repo = make_repo(tmp_path)
    repo.store_fx_rates(date(2026, 10, 8), {"USD": Decimal("1.07")})
    broken = EcbRates(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert refresh_rates(repo, broken) is False
    assert repo.latest_fx_rates().per_eur["USD"] == Decimal("1.07")


def test_a_conflicting_rate_for_a_stored_day_is_rejected_without_raising(tmp_path):
    repo = make_repo(tmp_path)
    repo.store_fx_rates(date(2026, 10, 9), {"USD": Decimal("1.05")})
    fetcher = EcbRates(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=SAMPLE)))
    assert refresh_rates(repo, fetcher) is False
    assert repo.latest_fx_rates().per_eur["USD"] == Decimal("1.05")
