from __future__ import annotations

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.connectors.eb_jwt import JwtSigner


@pytest.fixture(scope="module")
def keys():
    """A throwaway RSA key generated in memory; never read from or written to a fixture file."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    return pem, private.public_key()


class Clock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def _decode(token, public_key):
    return jwt.decode(token, public_key, algorithms=["RS256"], audience="api.enablebanking.com",
                      options={"verify_exp": False, "verify_iat": False})


def test_header_and_claims_follow_the_enable_banking_contract(keys):
    pem, public = keys
    token = JwtSigner("app-123", pem, clock=Clock()).token()
    header = jwt.get_unverified_header(token)
    assert header["typ"] == "JWT" and header["alg"] == "RS256" and header["kid"] == "app-123"
    claims = _decode(token, public)
    assert claims["iss"] == "enablebanking.com" and claims["aud"] == "api.enablebanking.com"
    assert claims["exp"] - claims["iat"] == 3600  # well under the 24 h maximum


def test_ttl_above_the_documented_maximum_is_refused(keys):
    pem, _ = keys
    with pytest.raises(ValueError):
        JwtSigner("a", pem, ttl_seconds=86401)
    with pytest.raises(ValueError):
        JwtSigner("a", pem, ttl_seconds=0)


def test_token_is_reused_until_close_to_expiry_then_refreshed(keys):
    pem, _ = keys
    clock = Clock()
    signer = JwtSigner("a", pem, clock=clock)
    first = signer.token()
    clock.now += 1800
    assert signer.token() == first
    clock.now += 1500  # 5 minutes left: refresh
    assert signer.token() != first


def test_an_invalid_key_fails_at_construction_without_echoing_it():
    with pytest.raises(ValueError) as raised:
        JwtSigner("a", b"-----BEGIN PRIVATE KEY-----\nnot-a-key\n-----END PRIVATE KEY-----")
    assert "not-a-key" not in str(raised.value)


def test_repr_and_str_never_show_key_material(keys):
    pem, _ = keys
    signer = JwtSigner("app-123", pem)
    text = repr(signer) + str(signer)
    assert "PRIVATE KEY" not in text and "app-123" in text


def test_a_public_key_or_non_rsa_key_is_refused(keys):
    pem, public = keys
    public_pem = public.public_bytes(serialization.Encoding.PEM,
                                     serialization.PublicFormat.SubjectPublicKeyInfo)
    with pytest.raises(ValueError):
        JwtSigner("a", public_pem)
