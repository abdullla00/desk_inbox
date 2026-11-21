# Desk Inbox

A Frappe app that adds an **Inbox** work strip under the Desktop icon grid — assignments and workflow actions in one place.

## Panels

| Panel | Shows | View all |
| --- | --- | --- |
| **Assigned to me** | Open ToDos allocated to you | List → ToDo (`allocated_to`=me, Open) |
| **Pending my action** | Open Workflow Actions you can act on | List → Workflow Action (Open) |
| **Waiting on others** | Open WAs on docs you own, waiting on someone else | Report → **Waiting on Others** (grants Desk User **Report** on Workflow Action) |
| **Mentions** | Unread @mentions | List → Notification Log (Mention, unread, for you) |

## Module sidebar

Opening the **Desk Inbox** module shows the same four destinations (Assigned → Pending → Waiting report → Mentions). Assigned / Mentions filters resolve to the signed-in user at boot.

**View all** on the Desktop strip opens those same links *inside* the Desk Inbox shell (sidebar stays Desk Inbox), not under ToDo / Workflow / Notifications’ home modules.

## Requirements

- Frappe **v16.60+** (`<17`)
- Desk Desktop page (`/desk/desktop`) and/or Dock → **Desk Inbox**

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

Open **Desktop** and hard-refresh. Inbox appears below the module icons. On phone, use **Dock / Apps → Desk Inbox** (sidebar shell) — the strip clears the v16.60 mobile bottom nav when Desktop is open.

## Features

- Four-column work strip (stacks on small screens)
- Global **SortSelector** (Last Updated / Created On / Title) next to refresh; preference in `localStorage`
- Overdue stays labeled in Assigned, but does not override sort order
- Scrollable preview lists with pinned headers / “View all” (full lists use Framework infinite scroll)
- Auto-refresh every 60s while Desktop is open
- Hidden during Desktop icon edit mode
- Responsive breakpoints for desktop, tablet, and phone (44px touch rows, header stack &lt;480px, mobile-nav clearance)
- Apps screen tile + Dock entry → `/desk/desk-inbox`

## API

Whitelisted methods (session user):

- `desk_inbox.api.get_inbox(limit, sort_by, sort_order)` — returns assigned / pending_me / waiting_others / mentions (`sort_by`: `modified` | `creation` | `title`)

## License

MIT — see [license.txt](license.txt).
