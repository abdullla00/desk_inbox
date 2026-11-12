# Copyright (c) 2026, Abdulla and Contributors
# License: MIT. See LICENSE

"""Install / migrate helpers for Desk Inbox."""

import frappe
from frappe.permissions import update_permission_property


def ensure_workflow_action_report_permission() -> None:
	"""Grant Report on Workflow Action to Desk User.

	Waiting on Others is a Script Report with ref_doctype Workflow Action.
	query_report requires has_permission(ref_doctype, "report"); stock DocPerm
	only gives Desk User read + delete.
	"""
	if not frappe.db.exists("DocType", "Workflow Action"):
		return

	update_permission_property("Workflow Action", "Desk User", 0, "report", 1)
	frappe.clear_cache(doctype="Workflow Action")
