"""Narrow record-level access for the synthetic Care Journey pilot.

Frappe roles remain a coarse gate.  This module is the second gate: an item is
visible only to its creator or the one explicitly named recipient.  A Household
relationship or an assignment never grants broader access.
"""

import frappe


def care_journey_item_query(user: str | None = None) -> str:
    user = user or frappe.session.user
    escaped_user = frappe.db.escape(user)
    return f"(`tabCare Journey Item`.owner = {escaped_user} OR `tabCare Journey Item`.shared_with_user = {escaped_user})"


def has_care_journey_item_permission(doc, user: str | None = None, permission_type=None) -> bool:
    user = user or frappe.session.user
    return user == doc.owner or user == doc.shared_with_user
