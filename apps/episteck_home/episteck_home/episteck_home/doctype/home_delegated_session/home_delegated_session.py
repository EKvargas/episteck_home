import frappe
from frappe.model.document import Document


class HomeDelegatedSession(Document):
    """A server-side human session. Never holds a Person id."""

    def revoke(self) -> None:
        self.status = "Revoked"
        self.revoked_at = frappe.utils.now()
        self.save(ignore_permissions=True)
