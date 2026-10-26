# Copyright (c) 2026, Abdulla and Contributors
# License: MIT. See LICENSE

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from desk_inbox.api import get_inbox, mark_mention_read, mark_todo_done


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
