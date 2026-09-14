import frappe
from frappe.model.document import Document


ALLOWED_TYPES = {
    "TASK",
    "APPOINTMENT_PLAN",
    "EXAM_PLAN",
    "DOCUMENT_REFERENCE",
    "EXPENSE_FOLLOW_UP",
    "QUESTION",
    "REMINDER",
}


class CareJourneyItem(Document):
    def validate(self):
        if self.item_type not in ALLOWED_TYPES:
            frappe.throw("Unsupported Care Journey Item type")
        if self.knowledge_status != "USER_CONFIRMED":
            frappe.throw("The pilot accepts only human-confirmed items")
        if self.item_type in {"APPOINTMENT_PLAN", "EXAM_PLAN"} and self.external_reference:
            frappe.throw("Clinical references are not accepted in the synthetic pilot")
