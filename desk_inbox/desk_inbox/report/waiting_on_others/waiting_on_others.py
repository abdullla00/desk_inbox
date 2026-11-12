# Copyright (c) 2026, Abdulla and contributors
# License: MIT. See LICENSE

from __future__ import annotations

from frappe import _

from desk_inbox.api import REPORT_WAITING_LIMIT, get_waiting_others_bucket


def execute(filters=None):
	"""Same Waiting-on-others truth as the Desktop Inbox panel."""
	bucket = get_waiting_others_bucket(
		limit=REPORT_WAITING_LIMIT,
		sort_by="modified",
		sort_order="desc",
	)

	columns = [
		{
			"label": _("Document Type"),
			"fieldname": "reference_doctype",
			"fieldtype": "Link",
			"options": "DocType",
			"width": 160,
		},
		{
			"label": _("Document"),
			"fieldname": "reference_name",
			"fieldtype": "Dynamic Link",
			"options": "reference_doctype",
			"width": 220,
		},
		{
			"label": _("State"),
			"fieldname": "workflow_state",
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"label": _("Last Updated"),
			"fieldname": "modified",
			"fieldtype": "Datetime",
			"width": 160,
		},
		{
			"label": _("Workflow Action"),
			"fieldname": "workflow_action",
			"fieldtype": "Link",
			"options": "Workflow Action",
			"width": 160,
		},
	]

	data = []
	for item in bucket.get("items") or []:
		data.append(
			{
				"reference_doctype": item.get("doctype"),
				"reference_name": item.get("name"),
				"workflow_state": item.get("status"),
				"modified": item.get("modified"),
				"workflow_action": item.get("workflow_action"),
			}
		)

	return columns, data
