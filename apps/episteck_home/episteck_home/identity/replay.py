"""Shared, atomic replay enforcement for delegation tokens (G1.6).

WHY THIS MODULE EXISTS
----------------------
``delegation.verify()`` accepts a ``seen_token_ids`` set so replay semantics can be
tested in isolation. That parameter is a **test seam, not production enforcement**:
a Python set lives in one worker's memory, so with four gunicorn workers a replayed
token simply lands on a different worker and succeeds. Live validation confirmed
exactly that — the same ``jti`` was accepted twice.

Production enforcement has to be a single claim, shared by every worker, that cannot
be split into check-then-write. This module is that claim.

THE PRIMITIVE
-------------
``frappe.cache()`` is a redis-py client (``RedisWrapper(Redis)``), so it exposes
``SET key value NX EX ttl`` as ``set(..., nx=True, ex=ttl)``. Redis executes that as
one command: exactly one caller can create the key, every other gets ``None``. There
is no read-modify-write window for two concurrent requests to race through.

    first use      -> set(...) returns True   -> claimed, continue
    second use     -> set(...) returns None   -> replay, DENY
    cache down     -> raises                  -> DENY (fail closed)

KEY SHAPE
---------
Keys are site-scoped and hashed:

    episteck:delegation:replay:<db_name>:<sha256(issuer|audience|jti)>

* Site-scoped because Redis is shared across every site on this bench, and raw
  ``.set()`` bypasses Frappe's own ``make_key`` prefixing. Without the site in the
  key, one site could consume another's token ids.
* Hashed so nothing meaningful survives a ``KEYS *`` during Redis inspection. A
  ``jti`` is random and carries no identity, but the composed value is still request
  material, and an opaque namespace costs nothing.

No Person id, User, session id, or token ever appears in a key.
"""
from __future__ import annotations

import hashlib

import frappe

KEY_PREFIX = "episteck:delegation:replay"

# A claim only has to outlive the window in which its token is still acceptable.
# Past ``exp`` the verifier rejects on expiry anyway, so a longer-lived key would
# guard nothing and only grow the keyspace. The buffer covers the verifier's own
# clock-skew tolerance, so a token accepted at the very edge of that tolerance
# cannot outlive its claim.
SKEW_BUFFER_SECONDS = 60
MIN_TTL_SECONDS = 1


class ReplayStoreUnavailable(RuntimeError):
    """The replay store could not be reached or gave an indeterminate answer.

    Raised rather than returned so a caller cannot accidentally treat an outage as
    "not a replay". Availability of this store is part of the trust boundary.
    """


def replay_key(issuer: str, audience: str, token_id: str) -> str:
    """Opaque, site-scoped key for one delegation's single-use claim."""
    digest = hashlib.sha256(
        f"{issuer}|{audience}|{token_id}".encode("utf-8")
    ).hexdigest()
    site = frappe.conf.get("db_name") or "unknown-site"
    return f"{KEY_PREFIX}:{site}:{digest}"


def ttl_for(expires_at: int, now: int) -> int:
    """Seconds the claim must outlive the token's own acceptance window."""
    return max(MIN_TTL_SECONDS, expires_at - now + SKEW_BUFFER_SECONDS)


def claim(issuer: str, audience: str, token_id: str, *, ttl_seconds: int) -> bool:
    """Atomically claim a token id. True on first use, False on replay.

    Raises ``ReplayStoreUnavailable`` when the store cannot answer, so the caller
    denies rather than guessing.
    """
    if not issuer or not audience or not token_id:
        raise ReplayStoreUnavailable("incomplete replay identity")
    if ttl_seconds < MIN_TTL_SECONDS:
        ttl_seconds = MIN_TTL_SECONDS

    key = replay_key(issuer, audience, token_id)
    try:
        cache = frappe.cache()
        # SET key 1 NX EX ttl — one Redis command, no race.
        result = cache.set(key, b"1", nx=True, ex=ttl_seconds)
    except Exception as error:  # connection, timeout, auth, anything
        # Deliberately no message from `error`: a redis exception can quote the key.
        raise ReplayStoreUnavailable(type(error).__name__) from None

    if result is True:
        return True
    if result is None or result is False:
        # Redis returns nil when NX found the key present. That is a replay.
        return False
    # An unrecognised truthy value means we cannot tell. Fail closed.
    raise ReplayStoreUnavailable("indeterminate replay claim")
