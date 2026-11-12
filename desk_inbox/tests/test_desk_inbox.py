# Copyright (c) 2026, Abdulla and Contributors
# License: MIT. See LICENSE

import json
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import frappe
from frappe.desk.doctype.sidebar.sidebar import resolve_sidebar
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, cint, nowdate

from desk_inbox.api import get_inbox, get_waiting_others_bucket, mark_mention_read, mark_todo_done
from desk_inbox.desk_inbox.report.waiting_on_others.waiting_on_others import execute as waiting_report_execute
from desk_inbox.setup import ensure_workflow_action_report_permission

SESSION_USER_SENTINEL = "__session_user__"
DESK_INBOX_SHELL = "Desk Inbox"
VIEW_ALL_SIDEBAR_LABEL = {
	"assigned": "Assigned to me",
	"pending_me": "Pending my action",
	"waiting_others": "Waiting on others",
	"mentions": "Mentions",
}


def _rewrite_session_user_filters(filters_str: str, user: str) -> str | None:
	"""Mirror desk_inbox.js patch_desk_inbox_sidebar_filters."""
	if not filters_str or SESSION_USER_SENTINEL not in filters_str:
		return filters_str
	parsed = json.loads(filters_str)
	for row in parsed:
		if isinstance(row, list) and len(row) > 3 and row[3] == SESSION_USER_SENTINEL:
			row[3] = user
	return json.dumps(parsed)


def _filters_as_route_options(filters_str: str | None) -> dict | None:
	"""Mirror frappe.ui.sidebar_item filters_as_options for '=' filters."""
	if not filters_str:
		return None
	arr = json.loads(filters_str)
	obj = {a[1]: [a[2], a[3]] for a in arr}
	flat = {}
	for key, value in obj.items():
		flat[key] = value[1] if isinstance(value, list) and value[0] == "=" else json.dumps(value)
	return flat


def _shell_slug(name: str) -> str:
	"""Mirror frappe.router.shell_slug."""
	return name.lower().replace("&", " and ").strip().replace(" ", "-")


def _doctype_slug(name: str) -> str:
	"""Mirror frappe.router.slug for DocType names."""
	return name.lower().replace(" ", "-")


def _in_shell(path: str, shell: str) -> str:
	"""Mirror sidebar_item.js in_shell()."""
	if not shell or not path.startswith("/desk/"):
		return path
	rest = path[len("/desk/") :]
	query = ""
	if "?" in rest:
		rest, query = rest.split("?", 1)
		query = "?" + query
	slug = _shell_slug(shell)
	if rest == slug or rest.startswith(slug + "/"):
		return path
	return f"/desk/{slug}/{rest}{query}"


def _view_all_path_for_item(item: dict, user: str) -> str:
	"""Mirror get_route(item, false, Desk Inbox) after sentinel rewrite."""
	filters = _rewrite_session_user_filters(item.get("filters"), user)
	if item.get("link_type") == "Report":
		report = item.get("report") or {}
		report_type = report.get("report_type") or ""
		if report_type in ("Query Report", "Script Report"):
			path = f"/desk/query-report/{item['link_to']}"
		else:
			path = f"/desk/report/{item['link_to']}"
	else:
		opts = _filters_as_route_options(filters) or {}
		route = f"{_doctype_slug(item['link_to'])}/view/list"
		if opts:
			query = "&".join(f"{quote(str(k))}={quote(str(v))}" for k, v in opts.items())
			route = f"{route}?{query}"
		path = f"/desk/{route}"
	return _in_shell(path, DESK_INBOX_SHELL)


class TestDeskInbox(FrappeTestCase):
	def test_get_inbox_assigned_and_mark_done(self):
		user = frappe.session.user
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "Desk Inbox unit test todo",
				"allocated_to": user,
				"status": "Open",
				"date": nowdate(),
			}
		).insert(ignore_permissions=True)

		data = get_inbox(20)
		self.assertIn("assigned", data)
		names = [i.get("todo_name") for i in data["assigned"]["items"]]
		self.assertIn(todo.name, names)

		mark_todo_done(todo.name)
		todo.reload()
		self.assertEqual(todo.status, "Closed")

	def test_mentions_only_for_mentioned_user_and_vanish_on_read(self):
		user = frappe.session.user
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "Desk Inbox mention target",
				"allocated_to": user,
				"status": "Open",
				"date": nowdate(),
			}
		).insert(ignore_permissions=True)

		nlog = frappe.get_doc(
			{
				"doctype": "Notification Log",
				"type": "Mention",
				"for_user": user,
				"from_user": "Administrator",
				"document_type": "ToDo",
				"document_name": todo.name,
				"subject": f"Mentioned you on ToDo {todo.name}",
				"read": 0,
			}
		).insert(ignore_permissions=True)

		data = get_inbox(20)
		self.assertIn("mentions", data)
		log_names = [i.get("notification_log") for i in data["mentions"]["items"]]
		self.assertIn(nlog.name, log_names)

		other = "Guest"
		frappe.set_user(other)
		with self.assertRaises(frappe.PermissionError):
			get_inbox(20)
		frappe.set_user(user)

		mark_mention_read(nlog.name)
		nlog.reload()
		self.assertEqual(nlog.read, 1)

		data_after = get_inbox(20)
		log_names_after = [i.get("notification_log") for i in data_after["mentions"]["items"]]
		self.assertNotIn(nlog.name, log_names_after)

	def test_mark_mention_read_rejects_other_user(self):
		user = frappe.session.user
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "Desk Inbox mention permission target",
				"allocated_to": user,
				"status": "Open",
				"date": nowdate(),
			}
		).insert(ignore_permissions=True)

		# Create a mention owned by a different system user if available
		other_users = frappe.get_all(
			"User",
			filters={
				"enabled": 1,
				"user_type": "System User",
				"name": ("not in", [user, "Guest", "Administrator"]),
			},
			pluck="name",
			limit=1,
		)
		if not other_users:
			self.skipTest("No alternate system user for permission test")

		other = other_users[0]
		nlog = frappe.get_doc(
			{
				"doctype": "Notification Log",
				"type": "Mention",
				"for_user": other,
				"from_user": user,
				"document_type": "ToDo",
				"document_name": todo.name,
				"subject": "Private mention for other user",
				"read": 0,
			}
		).insert(ignore_permissions=True)

		# Current user must not see other's mention in inbox
		data = get_inbox(20)
		log_names = [i.get("notification_log") for i in data["mentions"]["items"]]
		self.assertNotIn(nlog.name, log_names)

		with self.assertRaises(frappe.PermissionError):
			mark_mention_read(nlog.name)

	def test_personal_unallocated_overdue_shows_in_assigned(self):
		user = frappe.session.user
		past = add_days(nowdate(), -2)

		# Owned by me, no allocatee, past due → must appear as Overdue
		overdue = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "Personal overdue smoke todo",
				"status": "Open",
				"date": past,
			}
		).insert(ignore_permissions=True)
		self.assertFalse(overdue.allocated_to)
		self.assertEqual(overdue.owner, user)

		# Owned by me, no allocatee, due today → must NOT appear yet
		not_due = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "Personal not-yet-due smoke todo",
				"status": "Open",
				"date": nowdate(),
			}
		).insert(ignore_permissions=True)

		# Allocated to me and past due → appears with overdue flag
		allocated_overdue = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "Allocated overdue smoke todo",
				"allocated_to": user,
				"status": "Open",
				"date": past,
			}
		).insert(ignore_permissions=True)

		data = get_inbox(50)
		by_name = {i.get("todo_name"): i for i in data["assigned"]["items"]}

		self.assertIn(overdue.name, by_name)
		self.assertTrue(by_name[overdue.name].get("overdue"))
		self.assertEqual(by_name[overdue.name].get("status"), "Overdue")

		self.assertNotIn(not_due.name, by_name)

		self.assertIn(allocated_overdue.name, by_name)
		self.assertTrue(by_name[allocated_overdue.name].get("overdue"))

	def test_waiting_on_others_report_matches_bucket_helper(self):
		bucket = get_waiting_others_bucket(limit=50, sort_by="modified", sort_order="desc")
		columns, data = waiting_report_execute()
		self.assertTrue(columns)
		self.assertIsInstance(data, list)
		bucket_items = bucket.get("items") or []
		self.assertEqual(len(data), len(bucket_items))
		if bucket_items:
			self.assertEqual(data[0].get("reference_name"), bucket_items[0].get("name"))
			self.assertEqual(data[0].get("workflow_action"), bucket_items[0].get("workflow_action"))

	def test_pending_and_waiting_do_not_overlap(self):
		data = get_inbox(50)
		pending = {i.get("workflow_action") for i in data["pending_me"]["items"]}
		waiting = {i.get("workflow_action") for i in data["waiting_others"]["items"]}
		self.assertFalse(pending & waiting)

	def test_assigned_sort_by_title_ignores_overdue_pin(self):
		user = frappe.session.user
		past = add_days(nowdate(), -1)

		alpha = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "AAA non-overdue sort probe",
				"allocated_to": user,
				"status": "Open",
				"date": nowdate(),
			}
		).insert(ignore_permissions=True)
		zebra = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "ZZZ non-overdue sort probe",
				"allocated_to": user,
				"status": "Open",
				"date": nowdate(),
			}
		).insert(ignore_permissions=True)
		overdue_z = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "ZZZ overdue sort probe",
				"allocated_to": user,
				"status": "Open",
				"date": past,
			}
		).insert(ignore_permissions=True)
		overdue_a = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "AAA overdue sort probe",
				"allocated_to": user,
				"status": "Open",
				"date": past,
			}
		).insert(ignore_permissions=True)

		data = get_inbox(50, sort_by="title", sort_order="asc")
		self.assertEqual(data.get("sort_by"), "title")
		self.assertEqual(data.get("sort_order"), "asc")

		probe_names = {alpha.name, zebra.name, overdue_z.name, overdue_a.name}
		ordered = [
			i.get("todo_name")
			for i in data["assigned"]["items"]
			if i.get("todo_name") in probe_names
		]
		# Pure title asc — overdue label does not reorder alphabet
		# AAA non… < AAA overdue… < ZZZ non… < ZZZ overdue…
		self.assertEqual(
			ordered,
			[alpha.name, overdue_a.name, zebra.name, overdue_z.name],
		)

		for item in data["assigned"]["items"]:
			if item.get("todo_name") in probe_names:
				self.assertTrue(item.get("creation"))
				self.assertTrue(item.get("modified"))

	def test_desk_inbox_sidebar_ships_four_view_all_targets(self):
		self.assertTrue(frappe.db.exists("Sidebar", "Desk Inbox"))
		sb = frappe.get_doc("Sidebar", "Desk Inbox")
		self.assertEqual(sb.standard, 1)
		self.assertEqual(sb.module, "Desk Inbox")
		self.assertEqual(
			[i.label for i in sb.items],
			["Assigned to me", "Pending my action", "Waiting on others", "Mentions"],
		)
		self.assertEqual(sb.items[0].link_type, "DocType")
		self.assertEqual(sb.items[0].link_to, "ToDo")
		self.assertEqual(sb.items[1].link_type, "DocType")
		self.assertEqual(sb.items[1].link_to, "Workflow Action")
		self.assertEqual(sb.items[2].link_type, "Report")
		self.assertEqual(sb.items[2].link_to, "Waiting on Others")
		self.assertEqual(sb.items[3].link_type, "DocType")
		self.assertEqual(sb.items[3].link_to, "Notification Log")

		path = (
			Path(frappe.get_app_path("desk_inbox"))
			/ "desk_inbox"
			/ "sidebar"
			/ "desk_inbox"
			/ "desk_inbox.json"
		)
		self.assertTrue(path.exists(), f"missing sidebar fixture {path}")
		file_labels = [i["label"] for i in json.loads(path.read_text())["items"]]
		self.assertEqual(file_labels, [i.label for i in sb.items])

	def test_sidebar_session_user_filters_resolve_and_query(self):
		user = frappe.session.user
		sb = frappe.get_doc("Sidebar", "Desk Inbox")
		assigned = next(i for i in sb.items if i.label == "Assigned to me")
		mentions = next(i for i in sb.items if i.label == "Mentions")
		pending = next(i for i in sb.items if i.label == "Pending my action")

		self.assertIn(SESSION_USER_SENTINEL, assigned.filters or "")
		self.assertIn(SESSION_USER_SENTINEL, mentions.filters or "")

		assigned_opts = _filters_as_route_options(_rewrite_session_user_filters(assigned.filters, user))
		mention_opts = _filters_as_route_options(_rewrite_session_user_filters(mentions.filters, user))
		pending_opts = _filters_as_route_options(_rewrite_session_user_filters(pending.filters, user))

		self.assertEqual(assigned_opts, {"allocated_to": user, "status": "Open"})
		self.assertEqual(pending_opts, {"status": "Open"})
		self.assertEqual(mention_opts, {"type": "Mention", "read": 0, "for_user": user})

		# Route options must be valid list filters (no sentinel left)
		frappe.get_list("ToDo", filters=assigned_opts, limit=1)
		frappe.get_list("Workflow Action", filters=pending_opts, limit=1)
		frappe.get_list("Notification Log", filters=mention_opts, limit=1)

		resolved = resolve_sidebar("Desk Inbox", user)
		self.assertIsNotNone(resolved)
		waiting = next(i for i in resolved.items if i.get("label") == "Waiting on others")
		self.assertEqual(waiting.get("report", {}).get("report_type"), "Script Report")
		self.assertEqual(waiting.get("report", {}).get("ref_doctype"), "Workflow Action")

	def test_desk_user_can_get_report_on_workflow_action(self):
		"""Waiting on Others needs report perm on Workflow Action."""
		ensure_workflow_action_report_permission()
		row = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": "Workflow Action", "role": "Desk User", "permlevel": 0},
			["read", "report"],
			as_dict=True,
		)
		self.assertTrue(row, "Custom DocPerm for Desk User missing")
		self.assertEqual(cint(row.report), 1)

	def test_view_all_routes_open_inside_desk_inbox_shell(self):
		"""View all must match sidebar links under /desk/desk-inbox/…"""
		user = frappe.session.user
		resolved = resolve_sidebar(DESK_INBOX_SHELL, user)
		self.assertIsNotNone(resolved)
		by_label = {i.get("label"): i for i in resolved.items}
		shell_prefix = f"/desk/{_shell_slug(DESK_INBOX_SHELL)}/"

		paths = {}
		for key, label in VIEW_ALL_SIDEBAR_LABEL.items():
			self.assertIn(label, by_label, f"sidebar missing {label}")
			item = by_label[label]
			path = _view_all_path_for_item(item, user)
			paths[key] = path
			self.assertTrue(path.startswith(shell_prefix), path)
			self.assertNotIn(SESSION_USER_SENTINEL, path)

		assigned = urlparse(paths["assigned"])
		assigned_qs = {k: v[0] for k, v in parse_qs(assigned.query).items()}
		self.assertIn("/todo/", assigned.path)
		self.assertEqual(assigned_qs.get("allocated_to"), user)
		self.assertEqual(assigned_qs.get("status"), "Open")

		pending = urlparse(paths["pending_me"])
		pending_qs = {k: v[0] for k, v in parse_qs(pending.query).items()}
		self.assertIn("/workflow-action/", pending.path)
		self.assertEqual(pending_qs.get("status"), "Open")

		self.assertIn("/query-report/Waiting on Others", paths["waiting_others"])
		self.assertNotIn("?", paths["waiting_others"])
		self.assertTrue(by_label["Waiting on others"].get("report"), "report meta required for get_route")

		mentions = urlparse(paths["mentions"])
		mentions_qs = {k: v[0] for k, v in parse_qs(mentions.query).items()}
		self.assertIn("/notification-log/", mentions.path)
		self.assertEqual(mentions_qs.get("type"), "Mention")
		self.assertEqual(mentions_qs.get("read"), "0")
		self.assertEqual(mentions_qs.get("for_user"), user)

		js = (Path(frappe.get_app_path("desk_inbox")) / "public" / "js" / "desk_inbox.js").read_text()
		self.assertIn("DESK_INBOX_SHELL", js)
		self.assertIn("open_view_all", js)
		self.assertIn("get_route(item, false, DESK_INBOX_SHELL)", js)
		for label in VIEW_ALL_SIDEBAR_LABEL.values():
			self.assertIn(f'"{label}"', js)
