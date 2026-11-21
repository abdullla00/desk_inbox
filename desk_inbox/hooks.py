app_name = "desk_inbox"
app_title = "Desk Inbox"
app_publisher = "Abdulla"
app_description = "Desktop Inbox panels for assignments and workflow actions"
app_email = "abdullla210@gmail.com"
app_license = "mit"

app_logo_url = "/assets/desk_inbox/images/desk-inbox-logo.svg"
app_home = "/desk/desk-inbox"

add_to_apps_screen = [
	{
		"name": "desk_inbox",
		"logo": "/assets/desk_inbox/images/desk-inbox-logo.svg",
		"title": "Desk Inbox",
		"route": app_home,
		"has_permission": "desk_inbox.utils.permissions.check_app_permission",
	}
]

app_include_css = "/assets/desk_inbox/css/desk_inbox.css"
app_include_js = "/assets/desk_inbox/js/desk_inbox.js"

after_install = "desk_inbox.setup.ensure_workflow_action_report_permission"
