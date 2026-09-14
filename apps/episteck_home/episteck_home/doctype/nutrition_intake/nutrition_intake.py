import frappe
from frappe.model.document import Document


class NutritionIntake(Document):
    def validate(self):
        if self.status == "AI_PROPOSED":
            frappe.throw("AI proposals belong outside authoritative Nutrition Intake")
