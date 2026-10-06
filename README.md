# Desk Inbox

A Frappe app that adds an **Inbox** work strip under the Desktop icon grid — assignments and workflow actions in one place.

## Panels

| Panel | Shows |
| --- | --- |
| **Assigned to me** | Open ToDos allocated to you |
| **Pending my action** | Open Workflow Actions you can act on |
| **Waiting on others** | Open Workflow Actions on docs you own, waiting on someone else |

## Requirements

- Frappe **v16**
- Desk Desktop page (`/app/desktop`)

## Install

```bash
# From your bench
cd apps
git clone https://github.com/abdullla00/desk_inbox.git
cd ..
bench pip install -e apps/desk_inbox
bench --site <site-name> install-app desk_inbox
bench build --app desk_inbox
bench --site <site-name> clear-cache
```

Or with get-app:

```bash
bench get-app https://github.com/abdullla00/desk_inbox.git
bench --site <site-name> install-app desk_inbox
bench build --app desk_inbox
```

Open **Desktop** and hard-refresh. Inbox appears below the module icons.

## Features

- Three-column work strip (stacks on small screens)
- Scrollable lists with pinned headers / “View all”
- Auto-refresh every 60s while Desktop is open
- Hidden during Desktop icon edit mode
- Responsive breakpoints for desktop, tablet, and phone

## API

Whitelisted methods (session user):

- `desk_inbox.api.get_inbox` — returns assigned / pending_me / waiting_others

## License

MIT — see [license.txt](license.txt).
