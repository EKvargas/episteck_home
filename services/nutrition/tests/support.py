"""Test doubles for the Home authorization boundary (G1.6 contract).

An authorizer now has TWO responsibilities, mirroring the real client:
  * ``resolve_actor(delegation)`` — Home decides who the human is
  * ``check_access(actor, subject, domain, action, delegation)`` — Home decides access

Nutrition never accepts an asserted actor, so every double resolves one from the
delegated session.
"""
from app.home_control.client import AccessDecision

# The delegated human session used across Nutrition tests.
SESSION = "test-delegation-token"
ACTOR = "PSN-ACTOR"


class AllowAllAuthorizer:
    def resolve_actor(self, delegation):
        return ACTOR if delegation else None

    def check_access(self, actor, subject, domain, action, delegation=None):
        return AccessDecision(True, "test allow")


class DenyAllAuthorizer:
    def resolve_actor(self, delegation):
        return ACTOR if delegation else None

    def check_access(self, actor, subject, domain, action, delegation=None):
        return AccessDecision(False, "test deny")


class RecordingAuthorizer:
    """Captures the exact (actor, subject, domain, action) Home was asked about."""

    def __init__(self, allow: bool = True, actor: str = ACTOR):
        self.allow = allow
        self.actor = actor
        self.calls: list[tuple] = []
        self.resolutions: list[str | None] = []

    def resolve_actor(self, delegation):
        self.resolutions.append(delegation)
        return self.actor if delegation else None

    def check_access(self, actor, subject, domain, action, delegation=None):
        self.calls.append((actor, subject, domain, action))
        return AccessDecision(self.allow, "recorded")


class UnresolvableActorAuthorizer:
    """Home cannot resolve the session (revoked, expired, unknown, unreachable)."""

    def resolve_actor(self, delegation):
        return None

    def check_access(self, actor, subject, domain, action, delegation=None):
        raise AssertionError("check_access must not be reached without an actor")
