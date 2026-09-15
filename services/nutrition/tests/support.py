from app.home_control.client import AccessDecision


class AllowAllAuthorizer:
    def check_access(self, actor, subject, domain, action):
        return AccessDecision(True, "test allow")


class DenyAllAuthorizer:
    def check_access(self, actor, subject, domain, action):
        return AccessDecision(False, "test deny")
