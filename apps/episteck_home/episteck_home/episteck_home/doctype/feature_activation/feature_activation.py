"""Feature Activation: is a feature ACTIVE or PAUSED for a Person or a Circle.

Not an authorization. Access to data is decided by ``can_access`` / ConsentGrant;
this only records whether a feature is switched on for a scope. See ADR-0012.
"""
import frappe
from frappe.model.document import Document

SCOPE_TYPES = ("Person", "Circle")
STATES = ("ACTIVE", "PAUSED")


class FeatureActivation(Document):
    def validate(self) -> None:
        self.feature = (self.feature or "").strip()
        if not self.feature:
            frappe.throw("feature is required", frappe.ValidationError)
        if self.scope_type not in SCOPE_TYPES:
            frappe.throw("invalid scope type", frappe.ValidationError)
        if self.state not in STATES:
            frappe.throw("invalid state", frappe.ValidationError)
        if not self.scope or not frappe.db.exists(self.scope_type, self.scope):
            frappe.throw("scope does not exist", frappe.ValidationError)
        self._reject_duplicate()
        self._stamp_transition()

    def _reject_duplicate(self) -> None:
        duplicates = frappe.get_all(
            "Feature Activation",
            filters={
                "feature": self.feature,
                "scope_type": self.scope_type,
                "scope": self.scope,
                "name": ["!=", self.name],
            },
            fields=["name"],
            limit_page_length=1,
        )
        if duplicates:
            frappe.throw(
                "feature already configured for this scope", frappe.DuplicateEntryError
            )

    def _stamp_transition(self) -> None:
        before = self.get_doc_before_save()
        previous = before.state if before else None
        if self.state == "ACTIVE" and previous != "ACTIVE":
            self.activated_at = frappe.utils.now()
            self.deactivated_at = None
        elif self.state == "PAUSED" and previous == "ACTIVE":
            self.deactivated_at = frappe.utils.now()
