"""Fail-closed authorization invariants (Stage G1.5 section E + N). Pure, no Frappe."""
from episteck_home.policy.access import can_access, Grant

A, B = "person-A", "person-B"

def g(actor=A, subject=B, domain="NUTRITION", actions=("VIEW",), state="ACTIVE", vf=None, vu=None):
    return Grant(actor, subject, domain, frozenset(actions), state, vf, vu)

# self-access
def test_self_access_allowed():
    assert can_access(A, A, "NUTRITION", "VIEW", grants=None).allow is True

# membership / care != authorization  (no grant => deny, regardless of any relationship)
def test_no_grant_denies():
    assert can_access(A, B, "NUTRITION", "VIEW", grants=[]).allow is False
    assert can_access(A, B, "NUTRITION", "VIEW", grants=None).allow is False

# a nutrition grant permits nutrition only
def test_nutrition_grant_allows_nutrition():
    assert can_access(A, B, "NUTRITION", "VIEW", grants=[g(domain="NUTRITION")]).allow is True

def test_one_domain_never_implies_another():
    grants=[g(domain="HEALTH", actions=("VIEW",))]
    assert can_access(A, B, "NUTRITION", "VIEW", grants=grants).allow is False  # health != nutrition
    grants2=[g(domain="NUTRITION", actions=("VIEW",))]
    assert can_access(A, B, "MIND", "VIEW", grants=grants2).allow is False       # nutrition != mind
    assert can_access(A, B, "KNOWLEDGE", "VIEW", grants=grants2).allow is False   # nutrition != knowledge

# action scoping
def test_view_grant_does_not_permit_update():
    grants=[g(actions=("VIEW",))]
    assert can_access(A, B, "NUTRITION", "VIEW", grants=grants).allow is True
    assert can_access(A, B, "NUTRITION", "UPDATE", grants=grants).allow is False

def test_manage_implies_lesser():
    grants=[g(actions=("MANAGE",))]
    for act in ("VIEW","CREATE","UPDATE","MANAGE"):
        assert can_access(A, B, "NUTRITION", act, grants=grants).allow is True

# revoked / expired / unknown -> deny
def test_revoked_denies():
    assert can_access(A, B, "NUTRITION", "VIEW", grants=[g(state="REVOKED")]).allow is False

def test_expired_denies():
    grants=[g(vu="2020-01-01T00:00:00Z")]
    assert can_access(A, B, "NUTRITION", "VIEW", grants=grants, now="2026-09-15T00:00:00Z").allow is False

def test_not_yet_valid_denies():
    grants=[g(vf="2099-01-01T00:00:00Z")]
    assert can_access(A, B, "NUTRITION", "VIEW", grants=grants, now="2026-09-15T00:00:00Z").allow is False

def test_unknown_domain_or_action_denies():
    assert can_access(A, B, "TELEPATHY", "VIEW", grants=[g(domain="TELEPATHY")]).allow is False
    assert can_access(A, B, "NUTRITION", "DESTROY", grants=[g(actions=("DESTROY",))]).allow is False
    assert can_access(None, B, "NUTRITION", "VIEW", grants=None).allow is False   # missing actor
    assert can_access(A, None, "NUTRITION", "VIEW", grants=None).allow is False   # missing subject

# grant for a different actor/subject pair does not leak
def test_grant_scoped_to_pair():
    grants=[Grant("person-C", B, "NUTRITION", frozenset({"VIEW"}), "ACTIVE")]
    assert can_access(A, B, "NUTRITION", "VIEW", grants=grants).allow is False  # A is not the grantee
