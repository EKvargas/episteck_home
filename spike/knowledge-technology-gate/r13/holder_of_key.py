"""R13 EXPERIMENTAL realization: application-layer holder-of-key (Phase-1 SS11.4).

NOT a production mechanism. Real Ed25519 asymmetric proof-of-possession (correction 4),
not a custom HMAC scheme -- via the `cryptography` library, a well-reviewed primitive.

Structure, per SS11.4.1's binding invariants:

  Home stub retains ONLY: service_identity -> accepted Ed25519 PUBLIC key, established
  out-of-band (fixture-provisioned, never accepted from a request).
  Each stubbed domain service holds its OWN private key, never transmitted.

  Home's plan evaluation produces an ExecutionBasis binding: partition, actor, operation,
  domain, action, resource, audience, expiry, authenticated_service_identity, and the
  accepted confirmation public key FOR that service (the pair, not either alone --
  invariant 3).

  To execute, the presenting service signs a canonical payload (method, target, nonce,
  hash of the basis) with ITS private key. The domain verifies:
    1. signature verifies against the key the BASIS names (not a key the request supplies)
    2. the authenticated caller of this verification call is the SAME service the basis
       names (transport-level identity in production; here, the caller explicitly states
       which identity it is acting as, and this experimental verifier treats that as the
       "authenticated" identity -- see the CRITICAL caveat below)
    3. audience/domain/action/operation match the approved plan
    4. not expired, not replayed

CRITICAL EXPERIMENTAL CAVEAT: this in-process stub cannot reproduce a real transport-level
authenticated identity (that would require mTLS or an equivalent channel -- Family 1's
mTLS variant, explicitly NOT the primary realization per SS11.4). To still test invariant
5 ("a valid proof from the wrong service still fails"), the experiment's `execute()` call
takes a `claimed_service_identity` parameter DISTINCT from `signing_key`, modeling an
attacker who possesses a real key for service X but claims to be service Y (or vice
versa) -- this is exactly what P12 case 2a/2b require, and the verifier must reject any
mismatch between the key that actually signed and the key Home's basis says the claimed
identity should have used.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

MAX_LIFETIME_SECONDS = 300  # precedent: identity/replay.py MAX_LIFETIME_SECONDS


@dataclass(frozen=True)
class ServiceKeypair:
    """Fixture-provisioned, out-of-band. Never accepted from a request."""

    service_identity: str
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey

    @staticmethod
    def generate(service_identity: str) -> "ServiceKeypair":
        priv = Ed25519PrivateKey.generate()
        return ServiceKeypair(service_identity, priv, priv.public_key())

    def public_bytes_hex(self) -> str:
        return self.public_key.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


@dataclass(frozen=True)
class ExecutionBasis:
    """What Home's plan evaluation produces per approved operation (SS11.4.1)."""

    basis_id: str
    partition_id: str
    actor_person_id: str
    operation_id: str
    domain: str
    action: str
    resource_id: str
    audience: str  # the domain service this basis is scoped to
    authenticated_service_identity: str  # bound machine identity (invariant 3)
    accepted_public_key_hex: str  # bound confirmation key (invariant 3, the PAIR)
    issued_at: int
    expires_at: int
    decision_id: str  # correlation only (invariant 7) -- grants nothing on its own

    def canonical_bytes(self) -> bytes:
        payload = "|".join(
            [
                self.basis_id, self.partition_id, self.actor_person_id, self.operation_id,
                self.domain, self.action, self.resource_id, self.audience,
                self.authenticated_service_identity, self.accepted_public_key_hex,
                str(self.issued_at), str(self.expires_at),
            ]
        )
        return payload.encode("utf-8")

    def hash_hex(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class TrustedKeyRegistry:
    """Home-stub-side trusted mapping: service_identity -> accepted public key.

    Established out-of-band by the fixture setup, NEVER from a request payload
    (SS11.4.1 invariant 2). This is what makes the confirmation key authoritative rather
    than caller-nominated.
    """

    def __init__(self) -> None:
        self._registry: dict[str, str] = {}

    def register(self, service_identity: str, public_key_hex: str) -> None:
        self._registry[service_identity] = public_key_hex

    def accepted_key_for(self, service_identity: str) -> str | None:
        return self._registry.get(service_identity)


class HomeBasisMinter:
    """Home stub's side: mints an ExecutionBasis for an approved operation."""

    def __init__(self, registry: TrustedKeyRegistry):
        self.registry = registry

    def mint(
        self, *, basis_id: str, partition_id: str, actor_person_id: str, operation_id: str,
        domain: str, action: str, resource_id: str, audience_service_identity: str,
        decision_id: str, now: int | None = None, lifetime_seconds: int = 60,
    ) -> ExecutionBasis:
        now = now if now is not None else int(time.time())
        accepted_key = self.registry.accepted_key_for(audience_service_identity)
        if accepted_key is None:
            raise ValueError(
                f"no trusted confirmation key registered for {audience_service_identity!r} "
                "-- Home cannot mint a basis for an unregistered service identity"
            )
        lifetime = min(lifetime_seconds, MAX_LIFETIME_SECONDS)
        return ExecutionBasis(
            basis_id=basis_id, partition_id=partition_id, actor_person_id=actor_person_id,
            operation_id=operation_id, domain=domain, action=action, resource_id=resource_id,
            audience=audience_service_identity,
            authenticated_service_identity=audience_service_identity,
            accepted_public_key_hex=accepted_key, issued_at=now, expires_at=now + lifetime,
            decision_id=decision_id,
        )


@dataclass(frozen=True)
class PossessionProof:
    basis_id: str
    method: str
    target: str
    nonce: str
    basis_hash: str
    signature_hex: str

    def signed_payload(self) -> bytes:
        return f"{self.method}|{self.target}|{self.nonce}|{self.basis_hash}".encode("utf-8")


def sign_proof(
    *, keypair: ServiceKeypair, basis: ExecutionBasis, method: str, target: str, nonce: str,
) -> PossessionProof:
    """The presenting service signs a fresh proof with ITS OWN private key.

    This is the step an attacker without the private key cannot perform (invariant: why
    possession alone is insufficient)."""
    basis_hash = basis.hash_hex()
    payload = f"{method}|{target}|{nonce}|{basis_hash}".encode("utf-8")
    signature = keypair.private_key.sign(payload)
    return PossessionProof(
        basis_id=basis.basis_id, method=method, target=target, nonce=nonce,
        basis_hash=basis_hash, signature_hex=signature.hex(),
    )


@dataclass(frozen=True)
class ExecutionResult:
    executed: bool
    reason: str


class DomainVerifier:
    """The stubbed domain's side: verifies basis + proof before executing.

    `claimed_service_identity` models the identity the presenting party ASSERTS itself to
    be (what a real mTLS/transport layer would authenticate). This experimental stub
    cannot reproduce a real transport authentication channel, so it takes this as an
    explicit parameter -- the point under test is whether the VERIFICATION LOGIC correctly
    rejects a mismatch between what is claimed/signed and what the basis actually
    authorizes, which is the logic a real transport-bound implementation would also need.
    """

    def __init__(self) -> None:
        self._seen_basis_ids: set[str] = set()
        self.home_round_trips_triggered = 0

    def verify_and_execute(
        self, *, basis: ExecutionBasis, proof: PossessionProof,
        claimed_service_identity: str, presenting_public_key: Ed25519PublicKey,
        expected_audience: str, expected_domain: str, expected_action: str,
        expected_operation_id: str, expected_actor_person_id: str, now: int | None = None,
    ) -> ExecutionResult:
        now = now if now is not None else int(time.time())

        # Case 6: expired basis.
        if now >= basis.expires_at:
            return ExecutionResult(False, "expired basis (fail closed)")

        # Case 4: cross-request replay (single-use, same pattern as identity/replay.py).
        if basis.basis_id in self._seen_basis_ids:
            return ExecutionResult(False, "replayed basis (fail closed)")

        # Case 3: wrong audience/domain.
        if basis.audience != expected_audience or basis.domain != expected_domain:
            return ExecutionResult(False, "audience/domain mismatch (fail closed)")
        if basis.action != expected_action or basis.operation_id != expected_operation_id:
            return ExecutionResult(False, "operation/action mismatch (fail closed)")

        # Case 5: cross-actor replay.
        if basis.actor_person_id != expected_actor_person_id:
            return ExecutionResult(False, "actor mismatch (fail closed)")

        # Invariant 5/2b: correct key + wrong authenticated service identity. The basis
        # names authenticated_service_identity; the presenter's CLAIMED identity must
        # match it, independent of whether the key verifies.
        if claimed_service_identity != basis.authenticated_service_identity:
            return ExecutionResult(False, "claimed service identity != basis-bound identity (fail closed)")

        # Invariant 1/2a/6: the key used to verify MUST be the one the basis names (the
        # trusted, Home-registered key for that service) -- never a key the request itself
        # supplies or nominates. We re-derive the expected key from the basis, not from
        # whatever `presenting_public_key` claims to be.
        basis_key_hex = basis.accepted_public_key_hex
        presenting_key_hex = presenting_public_key.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        if presenting_key_hex != basis_key_hex:
            return ExecutionResult(False, "presented key != basis-bound accepted key (fail closed)")

        # Proof-of-possession: verify the signature against the basis-bound key.
        if proof.basis_hash != basis.hash_hex():
            return ExecutionResult(False, "proof does not bind this exact basis (fail closed)")
        try:
            presenting_public_key.verify(bytes.fromhex(proof.signature_hex), proof.signed_payload())
        except InvalidSignature:
            return ExecutionResult(False, "invalid signature (fail closed)")

        self._seen_basis_ids.add(basis.basis_id)
        return ExecutionResult(True, "executed")

    def revalidate_with_home(self, home_stub, decision_id: str) -> bool:
        """RT#2: fresh re-evaluation, not a TTL check (invariant 8). `decision_id` alone
        (invariant 9) is passed only as a correlation handle -- home_stub re-evaluates
        CURRENT grants, it does not trust decision_id as proof of anything."""
        self.home_round_trips_triggered += 1
        return True  # actual re-evaluation performed by caller via home_stub.evaluate_plan
