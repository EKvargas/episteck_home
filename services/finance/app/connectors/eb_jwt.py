"""Enable Banking application JWT (RS256, signed with the application's private key).

Header ``typ=JWT, alg=RS256, kid=<application id>``; claims ``iss=enablebanking.com``,
``aud=api.enablebanking.com``, ``iat``, ``exp`` (maximum lifetime 24 h; we use 1 h). Only
RS256 is accepted by the API. The key is loaded once from a mode-600 file by the caller
and is never printed.
"""
from __future__ import annotations

import time
from collections.abc import Callable

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "enablebanking.com"
AUDIENCE = "api.enablebanking.com"
MAX_TTL_SECONDS = 86400
REFRESH_MARGIN_SECONDS = 300


class JwtSigner:
    def __init__(self, application_id: str, private_key_pem: bytes, *, ttl_seconds: int = 3600,
                 clock: Callable[[], float] = time.time) -> None:
        if not 0 < ttl_seconds <= MAX_TTL_SECONDS:
            raise ValueError("ttl must be between 1 second and 24 hours")
        try:
            key = serialization.load_pem_private_key(private_key_pem, password=None)
        except (ValueError, TypeError):
            raise ValueError("private key is not a valid unencrypted PEM") from None
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError("private key must be RSA")
        self._application_id = application_id
        self._key = key
        self._ttl = ttl_seconds
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0

    def __repr__(self) -> str:
        return f"<JwtSigner kid={self._application_id}>"

    def token(self) -> str:
        now = self._clock()
        if self._token is None or now >= self._expires_at - REFRESH_MARGIN_SECONDS:
            issued = int(now)
            self._token = jwt.encode(
                {"iss": ISSUER, "aud": AUDIENCE, "iat": issued, "exp": issued + self._ttl},
                self._key, algorithm="RS256",
                headers={"typ": "JWT", "kid": self._application_id})
            self._expires_at = issued + self._ttl
        return self._token
