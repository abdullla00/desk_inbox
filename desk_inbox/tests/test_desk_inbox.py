# Copyright (c) 2026, Abdulla and Contributors
# License: MIT. See LICENSE

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from desk_inbox.api import get_inbox, mark_todo_done


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
