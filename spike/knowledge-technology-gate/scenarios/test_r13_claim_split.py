"""R13 two-claim split (correction 6, Product Architect review of PR #33).

The first spike wiring reported R13 as a single "PASS" with the transport-identity caveat
buried in prose -- a "PASS with caveat" the closed-set classification rule (correction 12)
forbids. R13 actually asserts two separable things, and this in-process experiment can
prove only one of them:

  R13-A  Cryptographic non-bearer proof-of-possession -- PASS. Fully demonstrated in
         process by the P12 adversarial matrix (real Ed25519, self-contained).
  R13-B  Machine / transport-identity binding -- UNKNOWN / INSUFFICIENT EVIDENCE. The
         verifier takes `claimed_service_identity` as a caller-supplied parameter rather
         than deriving it from a real mTLS / transport-authenticated channel, so this
         experiment cannot establish it (the correction-7 secondary mTLS experiment is
         required). Not a failure, not a silent pass.

These tests assert the SPLIT itself is honest: two independent closed-set claims, the
crypto half PASS, the transport half UNKNOWN, and never one collapsed verdict. They also
cross-check that R13-A's PASS is backed by the executable P12 evidence (a valid proof
executes; a wrong-key proof and a wrong-claimed-identity proof both fail closed), so the
classification is not an unbacked assertion.
"""
from __future__ import annotations

import time

from r13.holder_of_key import (
    DomainVerifier,
    HomeBasisMinter,
    R13ClaimVerdict,
    ServiceKeypair,
    TrustedKeyRegistry,
    classify_r13,
    sign_proof,
)


def test_r13_is_two_independent_claims_not_one_blended_verdict():
    """R13 is reported as exactly two claims, R13-A and R13-B, each with its own
    closed-set verdict -- never a single 'PASS with caveat'."""
    result = classify_r13()
    ids = [c.claim_id for c in result.claims]
    assert ids == ["R13-A", "R13-B"], f"expected exactly the two-claim split, got {ids}"

    verdicts = {c.claim_id: c.verdict for c in result.claims}
    assert verdicts["R13-A"] == R13ClaimVerdict.PASS
    assert verdicts["R13-B"] == R13ClaimVerdict.UNKNOWN, (
        "the transport/machine-identity binding must stay UNKNOWN -- an in-process "
        "caller-supplied identity cannot establish it (correction 6)"
    )
    # The unproven half is UNKNOWN, categorically NOT a pass -- guards against a future
    # regression that re-collapses the split into a single passing verdict.
    assert verdicts["R13-B"] != R13ClaimVerdict.PASS


def test_r13_verdicts_are_closed_set_members():
    """Every claim verdict is one of the five closed-set classifications (correction 12)."""
    allowed = set(R13ClaimVerdict)
    for c in classify_r13().claims:
        assert c.verdict in allowed, f"{c.claim_id} verdict {c.verdict!r} not in closed set"


def test_r13_b_names_the_exact_evidence_boundary():
    """R13-B's limit must name the concrete reason it cannot be proven in process -- the
    caller-supplied `claimed_service_identity` parameter and the need for a real mTLS/
    transport channel -- so the report states what is missing, not a vague hedge."""
    r13_b = next(c for c in classify_r13().claims if c.claim_id == "R13-B")
    assert "claimed_service_identity" in r13_b.limit
    assert "mTLS" in r13_b.limit or "transport" in r13_b.limit
    assert r13_b.limit, "an UNKNOWN claim must state the boundary of its evidence"


def test_r13_a_pass_is_backed_by_executable_p12_evidence():
    """R13-A's PASS is not an unbacked label: the crypto proof-of-possession really does
    execute for a valid basis+proof and really does fail closed for a wrong-key proof and
    a wrong-claimed-identity proof (the P12 matrix is the full suite; this is a compact
    cross-check that the classified PASS reflects real behavior)."""
    registry = TrustedKeyRegistry()
    svc = ServiceKeypair.generate("svc-nutrition")
    attacker = ServiceKeypair.generate("svc-attacker")
    registry.register("svc-nutrition", svc.public_bytes_hex())
    registry.register("svc-attacker", attacker.public_bytes_hex())
    minter = HomeBasisMinter(registry)
    now = int(time.time())

    def mint(op):
        return minter.mint(
            basis_id=f"b-{op}", partition_id="PART-1", actor_person_id="P1", operation_id=op,
            domain="NUTRITION", action="VIEW", resource_id="res-1",
            audience_service_identity="svc-nutrition", decision_id="dec-1", now=now,
        )

    def verify(basis, proof, claimed_id, pubkey):
        return DomainVerifier().verify_and_execute(
            basis=basis, proof=proof, claimed_service_identity=claimed_id,
            presenting_public_key=pubkey, expected_audience="svc-nutrition",
            expected_domain="NUTRITION", expected_action="VIEW",
            expected_operation_id=basis.operation_id, expected_actor_person_id="P1", now=now,
        )

    # Valid path -> executes (case 7).
    b_ok = mint("ok")
    p_ok = sign_proof(keypair=svc, basis=b_ok, method="POST", target="/x", nonce="n-ok")
    assert verify(b_ok, p_ok, "svc-nutrition", svc.public_key).executed

    # Wrong key, correct-looking claim -> fails closed (case 2a).
    b_2a = mint("2a")
    p_2a = sign_proof(keypair=attacker, basis=b_2a, method="POST", target="/x", nonce="n-2a")
    assert not verify(b_2a, p_2a, "svc-nutrition", attacker.public_key).executed

    # Correct key, wrong claimed identity -> fails closed (case 2b).
    b_2b = mint("2b")
    p_2b = sign_proof(keypair=svc, basis=b_2b, method="POST", target="/x", nonce="n-2b")
    assert not verify(b_2b, p_2b, "svc-attacker", svc.public_key).executed
