"""R13-B secondary local transport-identity experiment (correction 7).

`classify_r13()` records R13-B (machine/transport-identity binding) as UNKNOWN because the
in-process verifier takes `claimed_service_identity` as a caller-supplied string. This
suite exercises the SECONDARY local mTLS experiment that addresses exactly that gap: the
identity is derived from a VERIFIED TLS peer certificate, so it cannot be nominated by the
caller. The adversarial matrix here mirrors the P12 spirit at the transport layer:

  * honest service  -> admitted, identity read from its verified peer cert
  * rogue service    -> a cert CLAIMING the honest identity but signed by an untrusted CA is
                        rejected at the transport before any identity is accepted
  * composition      -> the transport-derived identity feeds the SAME
                        DomainVerifier.verify_and_execute (R13-A holder-of-key), so the two
                        halves compose; a transport-authenticated caller presenting the
                        wrong Ed25519 key still fails closed.

Scope: a single-host loopback experiment, throwaway ephemeral CA, selects no technology.
It demonstrates the mechanism locally; it is not evidence about production infrastructure.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from r13.holder_of_key import (
    DomainVerifier,
    HomeBasisMinter,
    R13ClaimVerdict,
    ServiceKeypair,
    TrustedKeyRegistry,
    sign_proof,
)
from r13.transport_identity import (
    EphemeralServiceCA,
    RogueCA,
    TransportIdentityServer,
    classify_r13b_transport,
    connect_as,
)


@pytest.fixture
def workdir():
    # mkdtemp + best-effort cleanup: Windows can hold a transient lock on the freshly
    # written PEM files, and TemporaryDirectory's unconditional rmtree can raise on exit.
    import shutil

    td = Path(tempfile.mkdtemp(prefix="r13-transport-"))
    try:
        yield td
    finally:
        shutil.rmtree(td, ignore_errors=True)


def _run_client_against_server(ca, issued, workdir, label):
    """Start a one-shot server, connect one client, return (server_result, client_outcome)."""
    server = TransportIdentityServer(ca)
    try:
        t = server.serve_one()
        client_outcome = connect_as(ca, issued, server.port, workdir, label)
        t.join(timeout=5)
        return server.result(), client_outcome
    finally:
        server.close()


def test_honest_service_identity_is_read_from_verified_peer_cert(workdir):
    """An honest service issued a cert for `svc-nutrition` connects, and the SERVER reads
    exactly that identity from the verified peer certificate -- not from any request body."""
    ca = EphemeralServiceCA(workdir)
    issued = ca.issue("svc-nutrition")
    server_result, _client = _run_client_against_server(ca, issued, workdir, "honest")
    assert server_result.handshake_ok, server_result.detail
    assert server_result.transport_identity == "svc-nutrition"


def test_rogue_cert_claiming_identity_is_rejected_at_transport(workdir):
    """A rogue CA mints a cert whose Common Name CLAIMS `svc-nutrition`, but the server
    does not trust that CA. The handshake must be rejected at the transport BEFORE any
    identity is accepted -- a forged name is not an authenticated identity. The server-side
    result is authoritative (a rejected client sees a reset on some platforms, not an
    SSLError)."""
    honest_ca = EphemeralServiceCA(workdir)
    rogue_ca = RogueCA(workdir / "rogue")
    rogue_issued = rogue_ca.issue("svc-nutrition")  # claims the real name, wrong trust root

    server = TransportIdentityServer(honest_ca)  # trusts only the honest CA
    try:
        t = server.serve_one()
        # Present the rogue client cert to the honest server; the rogue client trusts its
        # own CA for the server side so it attempts the handshake.
        connect_as(rogue_ca, rogue_issued, server.port, workdir, "rogue")
        t.join(timeout=5)
        result = server.result()
    finally:
        server.close()

    assert not result.handshake_ok, "an untrusted client cert must not complete the handshake"
    assert result.transport_identity is None
    assert "rejected at transport" in result.detail


def test_transport_identity_composes_with_ed25519_holder_of_key(workdir):
    """The transport-derived identity feeds the SAME holder-of-key verifier (R13-A). A
    caller authenticated by the transport as `svc-nutrition` and presenting the correct
    Ed25519 key executes; the same authenticated caller presenting the WRONG key still
    fails closed. This shows the two halves compose rather than substitute."""
    ca = EphemeralServiceCA(workdir)
    issued = ca.issue("svc-nutrition")
    server_result, _client = _run_client_against_server(ca, issued, workdir, "compose")
    assert server_result.handshake_ok
    transport_id = server_result.transport_identity
    assert transport_id == "svc-nutrition"

    # R13-A machinery, now fed the TRANSPORT-derived identity instead of a caller string.
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

    def verify(basis, proof, pubkey):
        return DomainVerifier().verify_and_execute(
            basis=basis, proof=proof,
            claimed_service_identity=transport_id,  # transport-authenticated, not caller-claimed
            presenting_public_key=pubkey, expected_audience="svc-nutrition",
            expected_domain="NUTRITION", expected_action="VIEW",
            expected_operation_id=basis.operation_id, expected_actor_person_id="P1", now=now,
        )

    b_ok = mint("ok")
    p_ok = sign_proof(keypair=svc, basis=b_ok, method="POST", target="/x", nonce="n-ok")
    assert verify(b_ok, p_ok, svc.public_key).executed, "transport-auth + correct key executes"

    b_bad = mint("bad")
    p_bad = sign_proof(keypair=attacker, basis=b_bad, method="POST", target="/x", nonce="n-bad")
    assert not verify(b_bad, p_bad, attacker.public_key).executed, (
        "transport auth does not excuse a wrong Ed25519 key -- the halves compose"
    )


def test_classify_r13b_transport_pass_only_on_full_adversarial_evidence(workdir):
    """The transport experiment classifies PASS only when BOTH the honest identity was
    transport-derived AND the rogue was rejected. Partial evidence stays UNKNOWN."""
    ca = EphemeralServiceCA(workdir)
    honest = ca.issue("svc-nutrition")
    honest_result, _ = _run_client_against_server(ca, honest, workdir, "cls-honest")

    rogue_ca = RogueCA(workdir / "rogue2")
    rogue_issued = rogue_ca.issue("svc-nutrition")
    server = TransportIdentityServer(ca)
    try:
        t = server.serve_one()
        connect_as(rogue_ca, rogue_issued, server.port, workdir, "cls-rogue")
        t.join(timeout=5)
        rogue_result = server.result()
    finally:
        server.close()

    outcome = classify_r13b_transport(
        honest_identity=honest_result.transport_identity,
        honest_ok=honest_result.handshake_ok,
        rogue_rejected=not rogue_result.handshake_ok,
    )
    assert outcome.verdict == R13ClaimVerdict.PASS
    assert outcome.limit, "even a local PASS must state it is a secondary local experiment"
    assert "SECONDARY LOCAL EXPERIMENT" in outcome.limit

    # Partial evidence (rogue not rejected) must NOT be a pass.
    partial = classify_r13b_transport(
        honest_identity="svc-nutrition", honest_ok=True, rogue_rejected=False
    )
    assert partial.verdict == R13ClaimVerdict.UNKNOWN


def test_classify_r13b_verdicts_are_closed_set(workdir):
    """Both outcomes are members of the shared closed set (correction 12)."""
    allowed = set(R13ClaimVerdict)
    a = classify_r13b_transport(honest_identity="svc-nutrition", honest_ok=True, rogue_rejected=True)
    b = classify_r13b_transport(honest_identity=None, honest_ok=False, rogue_rejected=False)
    assert a.verdict in allowed and b.verdict in allowed
