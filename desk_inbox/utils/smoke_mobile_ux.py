# Copyright (c) 2026, Abdulla and contributors
# For license information, please see license.txt

"""Smoke checks for Desk Inbox v16.60 mobile UX. Run:
bench --site frappe16 execute desk_inbox.utils.smoke_mobile_ux.run
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import frappe


def run() -> dict:
	errors: list[str] = []
	checks: dict = {}

	app_path = Path(frappe.get_app_path("desk_inbox"))
	app_root = app_path.parent

	# 1) pyproject pin
	pyproject = app_root / "pyproject.toml"
	with open(pyproject, "rb") as handle:
		data = tomllib.load(handle)
	dep = (data.get("tool") or {}).get("bench") or {}
	frappe_dep = (dep.get("frappe-dependencies") or {}).get("frappe") or ""
	checks["frappe_dependency"] = frappe_dep
	if "16.60" not in str(frappe_dep):
		errors.append(f"pyproject frappe pin missing 16.60: {frappe_dep}")

	# 2) CSS: mobile-nav clearance + touch rows + header stack
	css = (app_path / "public" / "css" / "desk_inbox.css").read_text(encoding="utf-8")
	checks["css_mobile_nav_clearance"] = "has-mobile-nav.desktop-page" in css and (
		"--desk-mobile-nav-height" in css
	)
	checks["css_touch_row_44"] = "--di-row-h: 44px" in css
	checks["css_header_stack"] = (
		"@media (max-width: 479px)" in css and "flex-direction: column" in css
	)
	if not checks["css_mobile_nav_clearance"]:
		errors.append("desk_inbox.css missing body.has-mobile-nav.desktop-page clearance")
	if not checks["css_touch_row_44"]:
		errors.append("desk_inbox.css missing --di-row-h: 44px for phones")
	if not checks["css_header_stack"]:
		errors.append("desk_inbox.css missing header stack under 480px")

	# 3) Mount still on desktop_screen (Desktop Icons inherits setup)
	js = (app_path / "public" / "js" / "desk_inbox.js").read_text(encoding="utf-8")
	checks["js_desktop_screen_mount"] = 'on("desktop_screen"' in js or "on('desktop_screen'" in js
	checks["js_desktop_wrapper"] = ".desktop-wrapper" in js
	if not checks["js_desktop_screen_mount"]:
		errors.append("desk_inbox.js missing desktop_screen mount")
	if not checks["js_desktop_wrapper"]:
		errors.append("desk_inbox.js missing .desktop-wrapper mount target")

	# 4) Apps screen + home + logo
	hooks = (app_path / "hooks.py").read_text(encoding="utf-8")
	checks["hooks_app_home"] = 'app_home = "/desk/desk-inbox"' in hooks
	checks["hooks_apps_screen"] = "add_to_apps_screen" in hooks
	checks["hooks_permission"] = "desk_inbox.utils.permissions.check_app_permission" in hooks
	logo = app_path / "public" / "images" / "desk-inbox-logo.svg"
	checks["logo_exists"] = logo.is_file()
	if not checks["hooks_app_home"]:
		errors.append("hooks.py missing app_home /desk/desk-inbox")
	if not checks["hooks_apps_screen"]:
		errors.append("hooks.py missing add_to_apps_screen")
	if not checks["hooks_permission"]:
		errors.append("hooks.py missing check_app_permission")
	if not checks["logo_exists"]:
		errors.append("missing public/images/desk-inbox-logo.svg")

	# 5) CleanShot screenshot must be gone
	cleanshot = list(app_path.glob("CleanShot*")) + list(app_root.glob("**/CleanShot*"))
	checks["cleanshot_removed"] = len(cleanshot) == 0
	if cleanshot:
		errors.append(f"CleanShot asset still present: {cleanshot[0]}")

	# 6) Permission helper importable
	try:
		from desk_inbox.utils.permissions import check_app_permission

		checks["permission_callable"] = callable(check_app_permission)
	except Exception as exc:
		checks["permission_callable"] = False
		errors.append(f"permissions import failed: {exc}")

	# 7) Installed frappe version
	try:
		ver = getattr(frappe, "__version__", "") or ""
		checks["installed_frappe_version"] = ver
		parts = [int(p) for p in ver.split(".")[:3]]
		if parts < [16, 60, 0]:
			errors.append(f"installed frappe {ver} < 16.60.0")
	except Exception as exc:
		errors.append(f"could not read frappe version: {exc}")

	# 8) Runtime: app installed + hooks live
	checks["app_installed"] = "desk_inbox" in frappe.get_installed_apps()
	if not checks["app_installed"]:
		errors.append("desk_inbox not installed on this site")

	live_apps = frappe.get_hooks("add_to_apps_screen", app_name="desk_inbox") or []
	live_home = frappe.get_hooks("app_home", app_name="desk_inbox") or []
	checks["live_apps_screen"] = bool(live_apps) and live_apps[0].get("route") == "/desk/desk-inbox"
	checks["live_app_home"] = "/desk/desk-inbox" in live_home
	if not checks["live_apps_screen"]:
		errors.append(f"live add_to_apps_screen missing/wrong: {live_apps}")
	if not checks["live_app_home"]:
		errors.append(f"live app_home missing/wrong: {live_home}")

	# 9) Permission + inbox API
	try:
		from desk_inbox.utils.permissions import check_app_permission
		from desk_inbox.api import get_inbox

		checks["permission_admin"] = bool(check_app_permission())
		if not checks["permission_admin"]:
			errors.append("check_app_permission() false for current user")

		inbox = get_inbox(limit=2)
		buckets = ("assigned", "pending_me", "waiting_others", "mentions")
		checks["inbox_buckets"] = all(
			isinstance(inbox.get(k), dict) and "count" in inbox[k] and "items" in inbox[k]
			for k in buckets
		)
		checks["inbox_counts"] = {k: inbox[k].get("count") for k in buckets}
		if not checks["inbox_buckets"]:
			errors.append("get_inbox missing expected bucket shape")
	except Exception as exc:
		errors.append(f"permission/inbox runtime failed: {exc}")

	# 10) Sidebar shell (View all destinations)
	try:
		from frappe.desk.doctype.sidebar.sidebar import resolve_sidebar

		sidebar = resolve_sidebar("Desk Inbox", frappe.session.user)
		labels = [i.get("label") for i in (sidebar.items if sidebar else [])]
		expected = {
			"Assigned to me",
			"Pending my action",
			"Waiting on others",
			"Mentions",
		}
		checks["sidebar_labels"] = labels
		checks["sidebar_complete"] = expected.issubset(set(labels))
		if not checks["sidebar_complete"]:
			errors.append(f"Desk Inbox sidebar missing items: {expected - set(labels)}")
	except Exception as exc:
		errors.append(f"sidebar resolve failed: {exc}")

	# 11) Dock entry
	try:
		dock_ok = bool(frappe.db.exists("Dock", "desk_inbox"))
		checks["dock_exists"] = dock_ok
		if dock_ok:
			dock = frappe.get_doc("Dock", "desk_inbox")
			checks["dock_links_sidebar"] = any(
				(i.link_type == "Sidebar" and i.link_to == "Desk Inbox") for i in dock.items
			)
			if not checks["dock_links_sidebar"]:
				errors.append("Dock desk_inbox does not link Sidebar Desk Inbox")
		else:
			errors.append("Dock desk_inbox missing")
	except Exception as exc:
		errors.append(f"dock check failed: {exc}")

	# 12) Linked assets under sites/assets
	bench_assets = Path(frappe.utils.get_bench_path()) / "sites" / "assets" / "desk_inbox"
	checks["asset_css"] = (bench_assets / "css" / "desk_inbox.css").is_file()
	checks["asset_js"] = (bench_assets / "js" / "desk_inbox.js").is_file()
	checks["asset_logo"] = (bench_assets / "images" / "desk-inbox-logo.svg").is_file()
	for key, label in (
		("asset_css", "css/desk_inbox.css"),
		("asset_js", "js/desk_inbox.js"),
		("asset_logo", "images/desk-inbox-logo.svg"),
	):
		if not checks[key]:
			errors.append(f"missing linked asset: {label}")

	# 13) Permission matrix: Website User must be denied
	try:
		from desk_inbox.utils.permissions import check_app_permission

		wu = frappe.db.get_value("User", {"user_type": "Website User", "enabled": 1}, "name")
		checks["website_user_sample"] = wu
		if wu:
			prev = frappe.session.user
			frappe.set_user(wu)
			denied = check_app_permission() is False
			frappe.set_user(prev)
			checks["website_user_denied"] = denied
			if not denied:
				errors.append(f"Website User {wu} unexpectedly allowed desk_inbox")
		else:
			checks["website_user_denied"] = None
	except Exception as exc:
		errors.append(f"permission matrix failed: {exc}")

	ok = not errors
	print("SMOKE_DESK_INBOX_MOBILE_RESULT", json.dumps({"ok": ok, "error_count": len(errors)}, indent=2))
	for err in errors:
		print("ERROR:", err)
	if ok:
		print("ALL_DESK_INBOX_MOBILE_CHECKS_PASSED")
	return {"ok": ok, "checks": checks, "errors": errors}
