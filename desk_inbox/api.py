# Copyright (c) 2026, Abdulla and contributors
# License: MIT. See LICENSE

from __future__ import annotations

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import mark_as_read
from frappe.query_builder import DocType
from frappe.utils import cint, getdate, strip_html, today
from pypika import Order


DEFAULT_LIMIT = 20
REPORT_WAITING_LIMIT = 500
ALLOWED_SORT_BY = frozenset({"modified", "creation", "title"})
ALLOWED_SORT_ORDER = frozenset({"asc", "desc"})
DEFAULT_SORT_BY = "modified"
DEFAULT_SORT_ORDER = "desc"


@frappe.whitelist()
def get_inbox(
	limit: int | str | None = None,
	sort_by: str | None = None,
	sort_order: str | None = None,
) -> dict:
	"""Return Assigned / Pending me / Waiting on others / Mentions for the Desktop Inbox."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	limit = cint(limit) or DEFAULT_LIMIT
	limit = min(max(limit, 1), 50)
	sort_by, sort_order = _normalize_sort(sort_by, sort_order)

	return {
		"assigned": _get_assigned(limit, sort_by, sort_order),
		"pending_me": _get_pending_me(limit, sort_by, sort_order),
		"waiting_others": get_waiting_others_bucket(limit, sort_by, sort_order),
		"mentions": _get_mentions(limit, sort_by, sort_order),
		"sort_by": sort_by,
		"sort_order": sort_order,
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


@frappe.whitelist()
def mark_mention_read(name: str) -> dict:
	"""Mark a Mention Notification Log as read for the current user."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if not name:
		frappe.throw(_("Notification Log name is required"))

	row = frappe.db.get_value(
		"Notification Log",
		name,
		["name", "for_user", "type", "read"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Not found"), frappe.DoesNotExistError)

	if row.for_user != frappe.session.user:
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if row.type != "Mention":
		frappe.throw(_("Not a mention"), frappe.ValidationError)

	if not cint(row.read):
		mark_as_read(name)

	return {"name": name, "read": 1}


def _normalize_sort(sort_by: str | None, sort_order: str | None) -> tuple[str, str]:
	by = (sort_by or DEFAULT_SORT_BY).strip().lower()
	order = (sort_order or DEFAULT_SORT_ORDER).strip().lower()
	if by not in ALLOWED_SORT_BY:
		by = DEFAULT_SORT_BY
	if order not in ALLOWED_SORT_ORDER:
		order = DEFAULT_SORT_ORDER
	return by, order


def _sort_key(item: dict, sort_by: str) -> str:
	"""Stable string key for client-visible fields."""
	if sort_by == "title":
		return (item.get("title") or "").casefold()
	if sort_by == "creation":
		return item.get("creation") or ""
	return item.get("modified") or ""


def _sort_items(items: list[dict], sort_by: str, sort_order: str) -> list[dict]:
	reverse = sort_order == "desc"
	return sorted(items, key=lambda item: _sort_key(item, sort_by), reverse=reverse)


def _clip_title(text: str) -> str:
	title = (text or "").strip()
	if len(title) > 80:
		return title[:77] + "…"
	return title


def _get_assigned(limit: int, sort_by: str, sort_order: str) -> dict:
	"""
	Open ToDos for the current user:
	- allocated_to = me (always), or
	- owned by me with no allocatee, only once past due date.
	Overdue is still flagged for UI, but SortSelector order is not overridden.
	"""
	user = frappe.session.user
	today_date = getdate(today())

	rows = frappe.get_list(
		"ToDo",
		filters={"status": "Open"},
		or_filters=[
			["allocated_to", "=", user],
			["owner", "=", user],
		],
		fields=[
			"name",
			"description",
			"status",
			"modified",
			"creation",
			"reference_type",
			"reference_name",
			"priority",
			"date",
			"allocated_to",
			"owner",
		],
		order_by="modified desc",
		limit=200,
	)

	items = []
	for row in rows:
		allocated = row.allocated_to or ""
		is_allocated_to_me = allocated == user
		is_personal_unallocated = row.owner == user and not allocated
		due = getdate(row.date) if row.date else None
		overdue = bool(due and due < today_date)

		# Personal unallocated todos only appear once overdue
		if not is_allocated_to_me and not (is_personal_unallocated and overdue):
			continue

		open_doctype = row.reference_type or "ToDo"
		open_name = row.reference_name or row.name
		if row.reference_type and row.reference_name:
			if not frappe.has_permission(row.reference_type, "read", row.reference_name):
				continue
		title = _clip_title((strip_html(row.description or "") or "") or row.reference_name or row.name)
		items.append(
			{
				"doctype": open_doctype,
				"name": open_name,
				"todo_name": row.name,
				"title": title,
				"status": _("Overdue") if overdue else row.status,
				"modified": str(row.modified) if row.modified else None,
				"creation": str(row.creation) if row.creation else None,
				"meta": row.priority,
				"overdue": overdue,
				"kind": "assigned",
			}
		)

	items = _sort_items(items, sort_by, sort_order)
	return {"count": len(items), "items": items[:limit]}


def _get_pending_me(limit: int, sort_by: str, sort_order: str) -> dict:
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
			"creation",
		],
		order_by="modified desc",
		limit=200,
	)

	items = []
	for row in rows:
		if not row.reference_doctype or not row.reference_name:
			continue
		items.append(
			{
				"doctype": row.reference_doctype,
				"name": row.reference_name,
				"workflow_action": row.name,
				"title": _(row.reference_doctype),
				"status": row.workflow_state or row.status,
				"modified": str(row.modified) if row.modified else None,
				"creation": str(row.creation) if row.creation else None,
				"kind": "pending_me",
			}
		)

	items = _sort_items(items, sort_by, sort_order)
	return {"count": len(items), "items": items[:limit]}


def get_waiting_others_bucket(
	limit: int = DEFAULT_LIMIT,
	sort_by: str = DEFAULT_SORT_BY,
	sort_order: str = DEFAULT_SORT_ORDER,
) -> dict:
	"""
	Open Workflow Actions on documents owned by the user, where the user
	cannot act (not in permitted roles). Shared by Desktop Inbox + Script Report.
	Uses ignore_permissions for the WA query because core WA permissions only
	expose actions the user can take.
	"""
	sort_by, sort_order = _normalize_sort(sort_by, sort_order)
	limit = cint(limit) or DEFAULT_LIMIT
	limit = min(max(limit, 1), REPORT_WAITING_LIMIT)

	user = frappe.session.user
	roles = set(frappe.get_roles(user))

	# Actions the user can already take (same permission surface as Pending).
	# Exclude these so Pending ∩ Waiting is always empty — even when a WA has
	# no Permitted Role rows (role check alone would mis-classify them).
	pending_action_names = set(
		frappe.get_list(
			"Workflow Action",
			filters={"status": "Open"},
			pluck="name",
			limit=REPORT_WAITING_LIMIT,
		)
	)

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
			WA.creation,
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
	for action in open_actions:
		key = (action.reference_doctype, action.reference_name)
		if owners.get(key) != user:
			continue
		# Already actionable in Pending → never Waiting
		if action.name in pending_action_names:
			continue
		permitted = roles_by_action.get(action.name, set())
		# User can act via permitted roles → not "waiting on others"
		if permitted and not permitted.isdisjoint(roles):
			continue
		if not frappe.has_permission(action.reference_doctype, "read", action.reference_name):
			continue

		items.append(
			{
				"doctype": action.reference_doctype,
				"name": action.reference_name,
				"workflow_action": action.name,
				"title": _(action.reference_doctype),
				"status": action.workflow_state or action.status,
				"modified": str(action.modified) if action.modified else None,
				"creation": str(action.creation) if action.creation else None,
				"kind": "waiting_others",
			}
		)

	items = _sort_items(items, sort_by, sort_order)
	return {"count": len(items), "items": items[:limit]}


def _get_mentions(limit: int, sort_by: str, sort_order: str) -> dict:
	"""Unread Mention Notification Logs for the current user only."""
	filters = {
		"for_user": frappe.session.user,
		"type": "Mention",
		"read": 0,
	}
	count = frappe.db.count("Notification Log", filters)
	# Pull a wider page so title/creation sorts are correct before limit.
	rows = frappe.get_list(
		"Notification Log",
		filters=filters,
		fields=[
			"name",
			"subject",
			"document_type",
			"document_name",
			"from_user",
			"creation",
			"modified",
		],
		order_by="creation desc",
		limit=200,
	)

	items = []
	for row in rows:
		if not row.document_type or not row.document_name:
			continue
		if not frappe.has_permission(row.document_type, "read", row.document_name):
			continue

		title = _clip_title((strip_html(row.subject or "") or "") or f"{row.document_type} {row.document_name}")

		from_label = None
		if row.from_user:
			from_label = frappe.db.get_value("User", row.from_user, "full_name") or row.from_user

		items.append(
			{
				"doctype": row.document_type,
				"name": row.document_name,
				"notification_log": row.name,
				"title": title,
				"status": from_label,
				"modified": str(row.modified) if row.modified else None,
				"creation": str(row.creation) if row.creation else None,
				"kind": "mentions",
			}
		)

	items = _sort_items(items, sort_by, sort_order)
	return {"count": count, "items": items[:limit]}
