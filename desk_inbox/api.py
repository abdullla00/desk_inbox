# Copyright (c) 2026, Abdulla and contributors
# License: MIT. See LICENSE

from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import cint
from pypika import Order


DEFAULT_LIMIT = 20


@frappe.whitelist()
def get_inbox(limit: int | str | None = None) -> dict:
	"""Return Assigned / Pending me / Waiting on others for the Desktop Inbox."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	limit = cint(limit) or DEFAULT_LIMIT
	limit = min(max(limit, 1), 50)

	return {
		"assigned": _get_assigned(limit),
		"pending_me": _get_pending_me(limit),
		"waiting_others": _get_waiting_others(limit),
	}


@frappe.whitelist()
def mark_todo_done(name: str) -> dict:
	"""Close a ToDo allocated to the current user."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if not name:
		frappe.throw(_("ToDo name is required"))

	todo = frappe.get_doc("ToDo", name)
	if todo.allocated_to != frappe.session.user and frappe.session.user != "Administrator":
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	todo.status = "Closed"
	todo.save(ignore_permissions=True)
	return {"name": todo.name, "status": todo.status}


def _get_assigned(limit: int) -> dict:
	filters = {
		"allocated_to": frappe.session.user,
		"status": "Open",
	}
	count = frappe.db.count("ToDo", filters)
	rows = frappe.get_list(
		"ToDo",
		filters=filters,
		fields=[
			"name",
			"description",
			"status",
			"modified",
			"reference_type",
			"reference_name",
			"priority",
			"date",
		],
		order_by="modified desc",
		limit=limit,
	)

	items = []
	for row in rows:
		open_doctype = row.reference_type or "ToDo"
		open_name = row.reference_name or row.name
		if row.reference_type and row.reference_name:
			if not frappe.has_permission(row.reference_type, "read", row.reference_name):
				continue
		title = (row.description or "").strip() or row.reference_name or row.name
		if len(title) > 80:
			title = title[:77] + "…"
		items.append(
			{
				"doctype": open_doctype,
				"name": open_name,
				"todo_name": row.name,
				"title": title,
				"status": row.status,
				"modified": str(row.modified) if row.modified else None,
				"meta": row.priority,
				"kind": "assigned",
			}
		)

	return {"count": count, "items": items}


def _get_pending_me(limit: int) -> dict:
	"""Open Workflow Actions the current user can act on (respects WA permissions)."""
	filters = {"status": "Open"}
	# Fetch a wider page; get_list applies Workflow Action permission query.
	rows = frappe.get_list(
		"Workflow Action",
		filters=filters,
		fields=[
			"name",
			"reference_doctype",
			"reference_name",
			"workflow_state",
			"status",
			"modified",
		],
		order_by="modified desc",
		limit=200,
	)

	items = []
	for row in rows:
		if not row.reference_doctype or not row.reference_name:
			continue
		# WA permission already scopes this list. Prefer a real title when the
		# user can read the doc; otherwise fall back to the document name.
		can_read = frappe.has_permission(row.reference_doctype, "read", row.reference_name)
		title = (
			_doc_title(row.reference_doctype, row.reference_name)
			if can_read
			else row.reference_name
		)
		items.append(
			{
				"doctype": row.reference_doctype,
				"name": row.reference_name,
				"workflow_action": row.name,
				"title": title,
				"status": row.workflow_state or row.status,
				"modified": str(row.modified) if row.modified else None,
				"kind": "pending_me",
			}
		)

	return {"count": len(items), "items": items[:limit]}


def _get_waiting_others(limit: int) -> dict:
	"""
	Open Workflow Actions on documents owned by the user, where the user
	cannot act (not in permitted roles). Uses ignore_permissions for the WA
	query because core WA permissions only expose actions the user can take.
	"""
	user = frappe.session.user
	roles = set(frappe.get_roles(user))

	WA = DocType("Workflow Action")
	WAPR = DocType("Workflow Action Permitted Role")

	# All open actions with their permitted roles
	open_actions = (
		frappe.qb.from_(WA)
		.select(
			WA.name,
			WA.reference_doctype,
			WA.reference_name,
			WA.workflow_state,
			WA.status,
			WA.modified,
		)
		.where(WA.status == "Open")
		.orderby(WA.modified, order=Order.desc)
	).run(as_dict=True)

	if not open_actions:
		return {"count": 0, "items": []}

	action_names = [a.name for a in open_actions]
	role_rows = (
		frappe.qb.from_(WAPR)
		.select(WAPR.parent, WAPR.role)
		.where(WAPR.parent.isin(action_names))
	).run(as_dict=True)

	roles_by_action: dict[str, set[str]] = {}
	for rr in role_rows:
		roles_by_action.setdefault(rr.parent, set()).add(rr.role)

	# Group by doctype for owner lookups
	by_doctype: dict[str, list[str]] = {}
	for action in open_actions:
		if not action.reference_doctype or not action.reference_name:
			continue
		by_doctype.setdefault(action.reference_doctype, []).append(action.reference_name)

	owners: dict[tuple[str, str], str] = {}
	for doctype, names in by_doctype.items():
		unique_names = list(set(names))
		# Chunk to avoid huge IN clauses
		for i in range(0, len(unique_names), 100):
			chunk = unique_names[i : i + 100]
			try:
				rows = frappe.get_all(
					doctype,
					filters={"name": ("in", chunk)},
					fields=["name", "owner"],
					ignore_permissions=True,
				)
			except Exception:
				continue
			for r in rows:
				owners[(doctype, r.name)] = r.owner

	items = []
	full_count = 0
	for action in open_actions:
		key = (action.reference_doctype, action.reference_name)
		if owners.get(key) != user:
			continue
		permitted = roles_by_action.get(action.name, set())
		# User can act via permitted roles → not "waiting on others"
		if permitted and not permitted.isdisjoint(roles):
			continue
		if not frappe.has_permission(action.reference_doctype, "read", action.reference_name):
			continue

		full_count += 1
		if len(items) < limit:
			items.append(
				{
					"doctype": action.reference_doctype,
					"name": action.reference_name,
					"workflow_action": action.name,
					"title": _doc_title(action.reference_doctype, action.reference_name),
					"status": action.workflow_state or action.status,
					"modified": str(action.modified) if action.modified else None,
					"kind": "waiting_others",
				}
			)

	return {"count": full_count, "items": items}


def _doc_title(doctype: str, name: str) -> str:
	"""Best-effort display title for a referenced document."""
	try:
		meta = frappe.get_meta(doctype)
		title_field = meta.get_title_field()
		if title_field and title_field != "name":
			value = frappe.db.get_value(doctype, name, title_field)
			if value:
				return str(value)
	except Exception:
		pass
	return name
