"""Test doubles for the Home authorization boundary (G1.6 contract).

An authorizer has exactly ONE responsibility, mirroring the real client:

    check_access(subject, domain, action, delegation) -> AccessDecision

It takes no actor. Home derives the human server-side from the caller's machine
credential plus the delegation, so Nutrition has no actor value to assert or forward.

A previous revision also resolved the actor via ``whoami`` first. Delegations are
single-use, so that second call was replay-denied in production; the doubles here
would have hidden it, because a double has no replay store. Every double now counts
its calls so a test can assert the one-call contract directly.
"""
from app.home_control.client import AccessDecision

# The delegated human session used across Nutrition tests.
SESSION = "test-delegation-token"
ACTOR = "PSN-ACTOR"


class _CountingAuthorizer:
    """Base double. Counts delegated Home calls and the tokens they used.

    ``home_calls`` is what proves the single-use contract: one person-sensitive
    operation must produce exactly one delegated request.
    """

    def __init__(self):
        self.home_calls = 0
        self.delegations: list[str | None] = []

    def _record(self, delegation):
        self.home_calls += 1
        self.delegations.append(delegation)


class AllowAllAuthorizer(_CountingAuthorizer):
    """Allows anything — but only for a present session, as the real client does.

    The real ``HomeControlPlaneClient`` returns a denial without touching the network
    when the delegation is missing. A double that allowed anyway would let a
    missing-session bug pass unnoticed.
    """

    def check_access(self, subject, domain, action, delegation=None):
        self._record(delegation)
        if not delegation:
            return AccessDecision(
                False, "no authenticated human session (fail closed)"
            )
        return AccessDecision(True, "test allow")


class DenyAllAuthorizer(_CountingAuthorizer):
    def check_access(self, subject, domain, action, delegation=None):
        self._record(delegation)
        return AccessDecision(False, "test deny")


class RecordingAuthorizer(_CountingAuthorizer):
    """Captures the exact (subject, domain, action) Home was asked about."""

    def __init__(self, allow: bool = True):
        super().__init__()
        self.allow = allow
        self.calls: list[tuple] = []

    def check_access(self, subject, domain, action, delegation=None):
        self._record(delegation)
        self.calls.append((subject, domain, action))
        return AccessDecision(self.allow, "recorded")


class UnresolvableSessionAuthorizer(_CountingAuthorizer):
    """Home refuses the session: revoked, expired, replayed, or unreachable.

    The real client returns a denial rather than raising, so the service must treat
    "no decision" and "deny" identically.
    """

    def __init__(self, reason: str = "no authenticated human session (fail closed)"):
        super().__init__()
        self.reason = reason

    def check_access(self, subject, domain, action, delegation=None):
        self._record(delegation)
        return AccessDecision(False, self.reason)


# Retained under the old name so existing imports keep working; the behaviour is the
# same denial, expressed through the single-call contract.
UnresolvableActorAuthorizer = UnresolvableSessionAuthorizer
