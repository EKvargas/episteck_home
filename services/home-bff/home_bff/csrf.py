"""CSRF guard for state-changing browser routes (H5).

The BFF cookie is ``SameSite=Lax``, which already blocks cross-site POST, but the grant
and revoke routes act with the user's authority over 90 days, so they get two more
independent checks:

1. **Fetch metadata / Origin** — ``Sec-Fetch-Site``, when sent, must be ``same-origin``.
   A real browser form POST under ``Referrer-Policy: no-referrer`` sends
   ``Origin: null`` *together with* ``Sec-Fetch-Site: same-origin``, so ``null`` is
   accepted only with that proof. A concrete ``Origin`` must equal this BFF's own
   origin. With neither a matching Origin nor same-origin fetch metadata -> reject.
2. **Token** — a stateless per-session value, ``HMAC(HMAC(secret, label), session_id)``,
   rendered into the page's form. A different session or secret yields a different token.

Everything fails closed: any missing piece is a rejection.
"""
from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlsplit

_KEY_LABEL = b"episteck-bff-csrf-key-v1"


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _key(secret: str) -> bytes:
    return hmac.new(secret.encode(), _KEY_LABEL, hashlib.sha256).digest()


def token_for(session_id: str, secret: str) -> str:
    return hmac.new(_key(secret), session_id.encode(), hashlib.sha256).hexdigest()


def verify(
    *,
    session_id: str,
    secret: str,
    presented: str | None,
    origin: str | None,
    sec_fetch_site: str | None,
    expected_origin: str,
) -> bool:
    if sec_fetch_site is not None and sec_fetch_site != "same-origin":
        return False
    if origin is not None and origin != "null" and origin != expected_origin:
        return False
    if (origin is None or origin == "null") and sec_fetch_site != "same-origin":
        return False
    if not presented:
        return False
    return hmac.compare_digest(presented, token_for(session_id, secret))
