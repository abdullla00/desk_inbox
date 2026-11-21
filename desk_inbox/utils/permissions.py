# Copyright (c) 2026, Abdulla and contributors
# For license information, please see license.txt

import frappe


def check_app_permission():
	"""Apps-screen / Dock visibility for Desk Inbox."""
	if frappe.session.user == "Administrator":
		return True

	user_type = frappe.get_cached_value("User", frappe.session.user, "user_type")
	if user_type == "Website User":
		return False

	for doctype in ("ToDo", "Workflow Action", "Notification Log"):
		if frappe.has_permission(doctype, ptype="read"):
			return True

	return False
