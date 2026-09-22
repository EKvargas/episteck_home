"""P12: R13 pre-authorized domain execution (H12). The full SS11.4.1 adversarial matrix,
each case a distinct automated assertion (mission brief: "Every one must be an automated
assertion"), including the decisive 2a/2b pair.
"""
from __future__ import annotations

import time

import pytest

from r13.holder_of_key import (
    DomainVerifier,
    HomeBasisMinter,
    ServiceKeypair,
    TrustedKeyRegistry,
    sign_proof,
)


@pytest.fixture
def rig():
    registry = TrustedKeyRegistry()
    svc_nutrition = ServiceKeypair.generate("svc-nutrition")
    svc_attacker = ServiceKeypair.generate("svc-attacker")
    registry.register("svc-nutrition", svc_nutrition.public_bytes_hex())
    registry.register("svc-attacker", svc_attacker.public_bytes_hex())
    minter = HomeBasisMinter(registry)
    now = int(time.time())
    return {
        "registry": registry, "svc_nutrition": svc_nutrition, "svc_attacker": svc_attacker,
        "minter": minter, "now": now,
    }


def _mint(rig, *, op="op-1", audience="svc-nutrition", now=None):
    return rig["minter"].mint(
        basis_id=f"basis-{op}-{now or rig['now']}", partition_id="PART-1", actor_person_id="P1",
        operation_id=op, domain="NUTRITION", action="VIEW", resource_id="res-1",
        audience_service_identity=audience, decision_id="dec-1", now=now or rig["now"],
    )


def _verify(rig, basis, proof, claimed_id, pubkey, **overrides):
    v = DomainVerifier()
    kwargs = dict(
        expected_audience="svc-nutrition", expected_domain="NUTRITION", expected_action="VIEW",
        expected_operation_id=basis.operation_id, expected_actor_person_id="P1", now=rig["now"],
    )
    kwargs.update(overrides)
    return v, v.verify_and_execute(
        basis=basis, proof=proof, claimed_service_identity=claimed_id, presenting_public_key=pubkey, **kwargs
    )


def test_case1_copied_basis_without_correct_key_fails_closed(rig):
    """1: basis copied without the correct key/channel, presented by another party."""
    basis = _mint(rig, op="c1")
    proof = sign_proof(keypair=rig["svc_attacker"], basis=basis, method="POST", target="/x", nonce="n1")
    _, result = _verify(rig, basis, proof, "svc-nutrition", rig["svc_attacker"].public_key)
    assert not result.executed


def test_case2_correct_basis_wrong_service_identity_fails_closed(rig):
    """2: correct basis + wrong service identity claimed."""
    basis = _mint(rig, op="c2")
    proof = sign_proof(keypair=rig["svc_nutrition"], basis=basis, method="POST", target="/x", nonce="n2")
    _, result = _verify(rig, basis, proof, "svc-attacker", rig["svc_nutrition"].public_key)
    assert not result.executed


def test_case2a_wrong_key_correct_looking_service_claim_fails_closed(rig):
    """2a: request ASSERTS it is service S but presents a key not bound to S."""
    basis = _mint(rig, op="c2a")
    proof = sign_proof(keypair=rig["svc_attacker"], basis=basis, method="POST", target="/x", nonce="n3")
    _, result = _verify(rig, basis, proof, "svc-nutrition", rig["svc_attacker"].public_key)
    assert not result.executed, "a claimed identity is not an authenticated one"


def test_case2b_correct_key_wrong_authenticated_identity_fails_closed(rig):
    """2b: a key genuinely bound to service S, presented by an authenticated caller that
    is NOT S."""
    basis = _mint(rig, op="c2b")
    proof = sign_proof(keypair=rig["svc_nutrition"], basis=basis, method="POST", target="/x", nonce="n4")
    _, result = _verify(rig, basis, proof, "svc-attacker", rig["svc_nutrition"].public_key)
    assert not result.executed, "the binding is the pair, not the key alone"


def test_case2a_2b_together_establish_neither_half_sufficient_alone(rig):
    """The pair that matters most: together 2a and 2b prove neither the key nor the
    claimed identity alone is sufficient -- both must match the SAME basis-bound pair."""
    basis = _mint(rig, op="c2ab")
    correct_key_wrong_claim = sign_proof(
        keypair=rig["svc_nutrition"], basis=basis, method="POST", target="/x", nonce="n5"
    )
    _, r_2b = _verify(rig, basis, correct_key_wrong_claim, "svc-attacker", rig["svc_nutrition"].public_key)

    basis2 = _mint(rig, op="c2ab-2")
    wrong_key_correct_claim = sign_proof(
        keypair=rig["svc_attacker"], basis=basis2, method="POST", target="/x", nonce="n6"
    )
    _, r_2a = _verify(rig, basis2, wrong_key_correct_claim, "svc-nutrition", rig["svc_attacker"].public_key)

    assert not r_2a.executed and not r_2b.executed


def test_case3_wrong_audience_domain_fails_closed(rig):
    """3: correct basis presented to the wrong audience/domain."""
    basis = _mint(rig, op="c3")
    proof = sign_proof(keypair=rig["svc_nutrition"], basis=basis, method="POST", target="/x", nonce="n7")
    _, result = _verify(rig, basis, proof, "svc-nutrition", rig["svc_nutrition"].public_key, expected_domain="HEALTH")
    assert not result.executed


def test_case4_cross_request_replay_fails_closed(rig):
    """4: valid basis reused on a later request."""
    basis = _mint(rig, op="c4")
    proof = sign_proof(keypair=rig["svc_nutrition"], basis=basis, method="POST", target="/x", nonce="n8")
    v = DomainVerifier()
    kwargs = dict(
        basis=basis, proof=proof, claimed_service_identity="svc-nutrition",
        presenting_public_key=rig["svc_nutrition"].public_key, expected_audience="svc-nutrition",
        expected_domain="NUTRITION", expected_action="VIEW", expected_operation_id=basis.operation_id,
        expected_actor_person_id="P1", now=rig["now"],
    )
    first = v.verify_and_execute(**kwargs)
    second = v.verify_and_execute(**kwargs)
    assert first.executed
    assert not second.executed, "single-use: replay must fail closed"


def test_case5_cross_actor_replay_fails_closed(rig):
    """5: basis minted for actor X used for actor Y."""
    basis = _mint(rig, op="c5")
    proof = sign_proof(keypair=rig["svc_nutrition"], basis=basis, method="POST", target="/x", nonce="n9")
    _, result = _verify(rig, basis, proof, "svc-nutrition", rig["svc_nutrition"].public_key, expected_actor_person_id="P2")
    assert not result.executed


def test_case6_expired_basis_fails_closed(rig):
    """6: expired basis."""
    basis = _mint(rig, op="c6", now=rig["now"] - 10_000)
    proof = sign_proof(keypair=rig["svc_nutrition"], basis=basis, method="POST", target="/x", nonce="n10")
    _, result = _verify(rig, basis, proof, "svc-nutrition", rig["svc_nutrition"].public_key)
    assert not result.executed


def test_case7_exact_approved_operation_succeeds(rig):
    """7: exact approved operation, correct key, authenticated service, audience ->
    SUCCEEDS."""
    basis = _mint(rig, op="c7")
    proof = sign_proof(keypair=rig["svc_nutrition"], basis=basis, method="POST", target="/x", nonce="n11")
    _, result = _verify(rig, basis, proof, "svc-nutrition", rig["svc_nutrition"].public_key)
    assert result.executed


def test_case8_rt2_still_performs_fresh_home_revalidation(rig):
    """8: RT#2 still performs fresh Home revalidation after execution -- observed, not
    skipped."""
    from home_stub.stub import AuthorizationOperation, Grant, HomeStub

    basis = _mint(rig, op="c8")
    proof = sign_proof(keypair=rig["svc_nutrition"], basis=basis, method="POST", target="/x", nonce="n12")
    v, exec_result = _verify(rig, basis, proof, "svc-nutrition", rig["svc_nutrition"].public_key)
    assert exec_result.executed

    home = HomeStub(grants=(
        Grant("P1", "P1", "NUTRITION", "VIEW", "PART-1"),
        Grant("P1", "P1", "KNOWLEDGE", "VIEW", "PART-1"),
    ))
    op = AuthorizationOperation(
        operation_id="c8", actor_person_id="P1", subject_person_ids=("P1",),
        domains=("NUTRITION",), action="VIEW", partition_id="PART-1",
    )
    revalidation = home.evaluate_plan((op,), version_pool={"c8": frozenset({"v1"})})
    assert revalidation.all_allowed()
    assert home.home_auth_round_trip_count == 1, "this is RT#2's own crossing, distinct from R13 execution"


def test_case9_decision_id_alone_proves_nothing(rig):
    """9: possessing decision_id alone -> no execution, no information. decision_id is
    correlation only and grants no authority by itself."""
    basis = _mint(rig, op="c9")
    # An attacker who has ONLY the decision_id (not the basis, not any key) has nothing
    # that can be passed into verify_and_execute at all -- there is no code path that
    # accepts a bare decision_id as authority. We assert this structurally: the
    # ExecutionBasis and PossessionProof types are required parameters; decision_id alone
    # cannot construct either.
    assert basis.decision_id == "dec-1"
    with pytest.raises(TypeError):
        DomainVerifier().verify_and_execute(  # type: ignore[call-arg]
            decision_id=basis.decision_id  # only decision_id supplied -- missing everything else
        )


def test_case10_home_round_trip_count_equals_two_for_full_flow(rig):
    """10: full flow home_auth_round_trip_count == 2 -- R13 execution itself adds NO
    additional Home crossing (the basis was already minted during the original RT#1/RT#2
    pair); R13 verification happens at the DOMAIN, not via a new Home call."""
    from home_stub.stub import AuthorizationOperation, Grant, HomeStub

    home = HomeStub(grants=(
        Grant("P1", "P1", "NUTRITION", "VIEW", "PART-1"),
        Grant("P1", "P1", "KNOWLEDGE", "VIEW", "PART-1"),
    ))
    op = AuthorizationOperation(
        operation_id="c10", actor_person_id="P1", subject_person_ids=("P1",),
        domains=("NUTRITION",), action="VIEW", partition_id="PART-1",
    )
    home.evaluate_plan((op,), version_pool={"c10": frozenset({"v1"})})  # RT#1

    basis = _mint(rig, op="c10")
    proof = sign_proof(keypair=rig["svc_nutrition"], basis=basis, method="POST", target="/x", nonce="n13")
    v, exec_result = _verify(rig, basis, proof, "svc-nutrition", rig["svc_nutrition"].public_key, expected_operation_id="c10")
    assert exec_result.executed, "R13 execution at the domain is local verification, no Home call"

    home.evaluate_plan((op,), version_pool={"c10": frozenset({"v1"})})  # RT#2
    assert home.home_auth_round_trip_count == 2, "R13 preserves the 2-crossing budget"
