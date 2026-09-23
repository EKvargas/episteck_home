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

Because of that caveat, R13 is NOT one verdict. `classify_r13()` (bottom of this module)
splits it into two independent closed-set claims per correction 6: R13-A (cryptographic
non-bearer proof-of-possession) is PASS -- fully provable in process by the P12 matrix;
R13-B (machine/transport-identity binding) is UNKNOWN / INSUFFICIENT EVIDENCE for THIS
IN-PROCESS experiment -- because `claimed_service_identity` is a caller-supplied parameter,
not a transport-authenticated channel, this experiment cannot establish it. The two are
never collapsed into a single "PASS with caveat."

The correction-7 companion `r13/transport_identity.py` addresses the R13-B gap in a
SEPARATE, secondary, single-host local mTLS experiment (Family 1 variant, explicitly NOT
the primary realization): there the service identity is derived from a VERIFIED TLS peer
certificate rather than a caller string, and a rogue certificate claiming the identity is
rejected at the transport. Its outcome is classified independently by
`transport_identity.classify_r13b_transport()`; it does NOT overwrite the in-process R13-B
UNKNOWN below (that stays honest about its own instrumentation), and it selects no
technology.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum

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


# ---------------------------------------------------------------------------
# R13 result split (correction 6, Product Architect review of PR #33)
# ---------------------------------------------------------------------------
# The first spike wiring reported R13 as a single "PASS" with the transport caveat buried
# in prose. That collapsed two genuinely distinct claims into one verdict -- exactly the
# "PASS with caveat" the closed-set classification rule (correction 12) forbids. R13
# actually asserts TWO separable things, and this experiment can prove only one of them in
# process. They are recorded as two independent closed-set results here so the report can
# never present the unproven half as passing.
#
#   R13-A  Cryptographic non-bearer proof-of-possession.
#          Claim: authority to execute is bound to POSSESSION OF A PRIVATE KEY, not to
#          mere possession of a token/basis. A copied basis, a forged proof, a replayed
#          proof, an expired basis, or a proof signed by the wrong key all fail closed;
#          only a fresh Ed25519 signature by the exact key Home's basis names (re-derived
#          from the basis, never nominated by the request) executes.
#          Evidence: the full P12 adversarial matrix -- cases 1, 2a/2b, 3, 4, 5, 6 fail
#          closed and case 7 succeeds -- all provable IN PROCESS because the cryptography
#          is real (Ed25519 via `cryptography`) and self-contained. This half is PASS.
#
#   R13-B  Machine / transport-identity binding.
#          Claim: the "authenticated service identity" the basis binds to is the identity
#          a real transport channel (mTLS or equivalent) actually authenticated -- not an
#          identity the caller merely asserts. This experiment CANNOT establish that:
#          `DomainVerifier.verify_and_execute` takes `claimed_service_identity` as an
#          explicit parameter, so in process the "authenticated" identity is stated by the
#          caller, not derived from a bound channel. What IS proven is that the
#          verification LOGIC rejects a mismatch between claimed identity, signing key, and
#          the basis-bound pair (cases 2/2a/2b); what is NOT proven is that a real deployment
#          could not present a claimed identity it does not actually own. That binding needs
#          the correction-7 secondary mTLS experiment (Family 1 variant). This half is
#          UNKNOWN / INSUFFICIENT EVIDENCE -- NOT a failure (nothing shows the property is
#          unattainable), and NOT a pass (nothing shows it holds here). It is genuinely
#          unmeasured with the available in-process instrumentation.


class R13ClaimVerdict(str, Enum):
    """Closed set, identical to backends.instrumentation.BarrierVerdict (correction 12).
    Duplicated as an independent enum only to keep r13/ free of a backends/ import; the
    string VALUES are deliberately identical so the report aggregates them uniformly."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN — INSUFFICIENT EVIDENCE"
    NOT_EXECUTED = "NOT EXECUTED — ENVIRONMENT BLOCKED"
    N_A = "N/A"


@dataclass(frozen=True)
class R13Claim:
    """One of R13's two separable claims, each with its own closed-set verdict."""

    claim_id: str  # "R13-A" | "R13-B"
    title: str
    verdict: R13ClaimVerdict
    evidence: str  # what this experiment actually showed
    limit: str  # the boundary of that evidence (empty for a clean PASS)


@dataclass(frozen=True)
class R13Result:
    """R13 as TWO independent claims -- never one blended verdict (correction 6)."""

    claims: tuple[R13Claim, ...]

    @property
    def overall_note(self) -> str:
        return (
            "R13 is reported as two independent closed-set claims (correction 6): the "
            "cryptographic non-bearer proof-of-possession is demonstrated in process (R13-A "
            "PASS); the machine/transport-identity binding is not establishable in process "
            "because the authenticated identity is a caller-supplied parameter rather than a "
            "transport-authenticated channel (R13-B UNKNOWN / INSUFFICIENT EVIDENCE). The two "
            "are NOT collapsed into a single 'PASS with caveat'."
        )


def classify_r13() -> R13Result:
    """Return R13's two-claim split. Static classification of what THIS in-process
    experiment can and cannot establish -- the P12 adversarial suite is the executable
    evidence backing R13-A; the `claimed_service_identity` parameter in
    `DomainVerifier.verify_and_execute` is the structural reason R13-B stays UNKNOWN. No
    number is fabricated and no technology is selected."""
    return R13Result(
        claims=(
            R13Claim(
                claim_id="R13-A",
                title="Cryptographic non-bearer proof-of-possession (Ed25519 holder-of-key)",
                verdict=R13ClaimVerdict.PASS,
                evidence=(
                    "Full P12 adversarial matrix passes in process: a copied basis without "
                    "the correct key (case 1), a proof signed by the wrong key (2a), a right "
                    "key presented under a wrong authenticated identity (2b), wrong "
                    "audience/domain (3), cross-request replay (4), cross-actor reuse (5) and "
                    "an expired basis (6) all fail closed, while only a fresh signature by the "
                    "exact basis-bound key executes (7). The verifying key is re-derived from "
                    "the basis Home minted, never nominated by the request; the private key is "
                    "never transmitted. Real Ed25519 (`cryptography`), self-contained, so this "
                    "claim needs no external environment."
                ),
                limit="",
            ),
            R13Claim(
                claim_id="R13-B",
                title="Machine / transport-identity binding (authenticated caller identity)",
                verdict=R13ClaimVerdict.UNKNOWN,
                evidence=(
                    "The verification LOGIC correctly rejects any mismatch between the claimed "
                    "identity, the signing key, and the basis-bound (identity, key) pair "
                    "(cases 2/2a/2b) -- the decision logic a transport-bound deployment would "
                    "also run."
                ),
                limit=(
                    "But `DomainVerifier.verify_and_execute` takes `claimed_service_identity` "
                    "as an explicit parameter, so in process the 'authenticated' identity is "
                    "ASSERTED by the caller, not derived from a real mTLS / transport-"
                    "authenticated channel. This IN-PROCESS experiment therefore cannot show "
                    "that a real caller could not present an identity it does not own. The "
                    "correction-7 secondary mTLS (Family 1) experiment in "
                    "`r13/transport_identity.py` addresses this SEPARATELY and LOCALLY (identity "
                    "read from a verified peer certificate; see `classify_r13b_transport()` and "
                    "the `r13b_transport` bench key); it does not change this in-process verdict. "
                    "Recorded UNKNOWN / INSUFFICIENT EVIDENCE, never a failure and never silently "
                    "upgraded to PASS."
                ),
            ),
        )
    )
