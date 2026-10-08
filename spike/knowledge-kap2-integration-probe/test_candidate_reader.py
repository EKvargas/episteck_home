"""Disposable reader truth table; database integration runs on the marked Frappe site."""

from episteck_home.probes.kap2_frappe import _candidate_decision


def test_permissive_authority_requires_matching_commit():
    assert not _candidate_decision("ACTIVE", 7, {7: ("PENDING", "ACTIVE")}, True)
    assert _candidate_decision("ACTIVE", 7, {7: ("COMMIT", "ACTIVE")}, True)
    assert not _candidate_decision("ACTIVE", 7, {7: ("COMMIT", "REVOKED")}, True)
    assert not _candidate_decision("ACTIVE", 7, {7: ("COMMIT", "ACTIVE")}, False)


def test_revocation_and_restored_revision_deny():
    assert not _candidate_decision("REVOKED", 8, {8: ("PENDING", "REVOKED")}, True)
    assert not _candidate_decision("REVOKED", 8, {8: ("COMMIT", "REVOKED")}, True)
    assert not _candidate_decision("ACTIVE", 7, {7: ("COMMIT", "ACTIVE"), 8: ("COMMIT", "REVOKED")}, True)
