(() => {
	const REFRESH_MS = 60_000;
	const ROOT_ID = "desk-inbox-root";
	const WIDTH_SYNC_MIN = 1100;
	const RESIZE_DEBOUNCE_MS = 100;
	const DEFAULT_SORT_BY = "modified";
	const DEFAULT_SORT_ORDER = "desc";
	const ALLOWED_SORT_BY = new Set(["modified", "creation", "title"]);
	const ALLOWED_SORT_ORDER = new Set(["asc", "desc"]);
	// Sidebar JSON cannot store a live user; resolve this sentinel at boot.
	const SESSION_USER_SENTINEL = "__session_user__";

	const SORT_OPTIONS = [
		{ fieldname: "modified", label: () => __("Last Updated On") },
		{ fieldname: "creation", label: () => __("Created On") },
		{ fieldname: "title", label: () => __("Title") },
	];

	const DESK_INBOX_SHELL = "Desk Inbox";

	// Must match Sidebar Item labels in desk_inbox/sidebar/desk_inbox/desk_inbox.json
	const VIEW_ALL_SIDEBAR_LABEL = {
		assigned: "Assigned to me",
		pending_me: "Pending my action",
		waiting_others: "Waiting on others",
		mentions: "Mentions",
	};

	const PANEL_DEFS = [
		{
			key: "assigned",
			label: () => __("Assigned to me"),
			className: "desk-inbox-panel--assigned",
			badgeTheme: "blue",
			viewAll: () => ({
				doctype: "ToDo",
				filters: {
					allocated_to: frappe.session.user,
					status: "Open",
				},
			}),
		},
		{
			key: "pending_me",
			label: () => __("Pending my action"),
			className: "desk-inbox-panel--pending",
			badgeTheme: "amber",
			viewAll: () => ({
				doctype: "Workflow Action",
				filters: { status: "Open" },
			}),
		},
		{
			key: "waiting_others",
			label: () => __("Waiting on others"),
			className: "desk-inbox-panel--waiting",
			badgeTheme: "green",
			viewAll: () => ({
				// Exact inbox rule (owner + cannot act) — not expressible as List filters
				route: ["query-report", "Waiting on Others"],
			}),
		},
		{
			key: "mentions",
			label: () => __("Mentions"),
			className: "desk-inbox-panel--mentions",
			badgeTheme: "violet",
			viewAll: () => ({
				doctype: "Notification Log",
				filters: {
					type: "Mention",
					read: 0,
					for_user: frappe.session.user,
				},
			}),
		},
	];

	frappe.desk_inbox = frappe.desk_inbox || {};

	/**
	 * Rewrite Desk Inbox sidebar filters so `__session_user__` becomes the
	 * logged-in user. Mirrors View-all routes for Assigned / Mentions.
	 */
	function patch_desk_inbox_sidebar_filters() {
		const user = frappe.session?.user;
		if (!user || user === "Guest") return;

		const shells = frappe.boot?.module_sidebars;
		if (!shells) return;

		for (const sidebar of Object.values(shells)) {
			if (sidebar?.module !== "Desk Inbox" && sidebar?.name !== "Desk Inbox") {
				continue;
			}
			for (const item of sidebar.items || []) {
				if (!item?.filters || !String(item.filters).includes(SESSION_USER_SENTINEL)) {
					continue;
				}
				try {
					const parsed = JSON.parse(item.filters);
					if (!Array.isArray(parsed)) continue;
					let changed = false;
					for (const row of parsed) {
						if (Array.isArray(row) && row[3] === SESSION_USER_SENTINEL) {
							row[3] = user;
							changed = true;
						}
					}
					if (changed) {
						item.filters = JSON.stringify(parsed);
					}
				} catch (_e) {
					/* ignore bad filter JSON */
				}
			}
		}
	}

	patch_desk_inbox_sidebar_filters();
	if (typeof frappe.ready === "function") {
		frappe.ready(patch_desk_inbox_sidebar_filters);
	}

	function desk_inbox_sidebar() {
		const shells = frappe.boot?.module_sidebars || {};
		return (
			shells[DESK_INBOX_SHELL] ||
			Object.values(shells).find(
				(entry) => entry?.module === DESK_INBOX_SHELL || entry?.name === DESK_INBOX_SHELL
			)
		);
	}

	function sidebar_item_for_panel(key) {
		const label = VIEW_ALL_SIDEBAR_LABEL[key];
		if (!label) return null;
		const sidebar = desk_inbox_sidebar();
		return (sidebar?.items || []).find((item) => item.label === label) || null;
	}

	/**
	 * Open the same destination as the Desk Inbox module sidebar link,
	 * with the Desk Inbox shell so that sidebar stays on screen.
	 */
	function open_view_all(key) {
		patch_desk_inbox_sidebar_filters();

		const item = sidebar_item_for_panel(key);
		if (item && typeof frappe.ui?.sidebar_item?.get_route === "function") {
			const path = frappe.ui.sidebar_item.get_route(item, false, DESK_INBOX_SHELL);
			if (path) {
				frappe.set_route(path);
				return;
			}
		}

		// Fallback if sidebar boot entry is missing (pre-migrate / cache)
		const def = PANEL_DEFS.find((p) => p.key === key);
		if (!def) return;
		const target = def.viewAll();
		const shell = frappe.router.shell_slug(DESK_INBOX_SHELL);
		if (target.route?.length) {
			frappe.set_route(`/desk/${shell}/${target.route.join("/")}`);
			return;
		}
		const opts = target.filters || {};
		frappe.route_options = opts;
		const doctype_slug = frappe.router.slug(target.doctype);
		const query = Object.entries(opts)
			.map(
				([k, v]) =>
					`${encodeURIComponent(k)}=${encodeURIComponent(
						v !== null && typeof v === "object" ? JSON.stringify(v) : String(v)
					)}`
			)
			.join("&");
		const list_path = `/desk/${shell}/${doctype_slug}/view/list${query ? `?${query}` : ""}`;
		frappe.set_route(list_path);
	}

	frappe.desk_inbox.mount = function mount(desktop) {
		if (!frappe.session.user || frappe.session.user === "Guest") return;

		const $wrapper = $(".desktop-wrapper").first();
		const $icons_row = $(".desktop-container").first();
		if (!$wrapper.length || !$icons_row.length) return;

		let $root = $wrapper.find(`#${ROOT_ID}`);
		if (!$root.length) {
			$root = $(build_shell());
			$icons_row.after($root);
			bind_root($root);
			mount_sort_selector($root);
		} else if (!$root.prev().is($icons_row)) {
			$icons_row.after($root);
		}

		if (!frappe.desk_inbox.sort_selector) {
			mount_sort_selector($root);
		}

		frappe.desk_inbox.$root = $root;
		frappe.desk_inbox.desktop = desktop;
		sync_width($root);
		set_edit_visibility(desktop);
		refresh();
		start_timer();
		watch_edit_mode(desktop);
	};

	frappe.desk_inbox.unmount = function unmount() {
		stop_timer();
		if (frappe.desk_inbox._edit_observer) {
			frappe.desk_inbox._edit_observer.disconnect();
			frappe.desk_inbox._edit_observer = null;
		}
		frappe.desk_inbox.sort_selector = null;
		frappe.desk_inbox.$root = null;
	};

	function build_shell() {
		const panels = PANEL_DEFS.map(
			(p) => `
			<section class="desk-inbox-panel ${p.className}" data-panel="${p.key}">
				<div class="desk-inbox-panel__head">
					<span class="desk-inbox-panel__label">${frappe.utils.escape_html(p.label())}</span>
					<span class="es-badge desk-inbox-panel__count" data-size="sm" data-theme="${p.badgeTheme}" data-count data-badge-theme="${p.badgeTheme}">
						<span class="es-badge__label">0</span>
					</span>
				</div>
				<div class="desk-inbox-panel__list-wrap has-more">
					<div class="desk-inbox-panel__list" data-list></div>
				</div>
				<div class="desk-inbox-panel__foot">
					<button
						type="button"
						class="es-button desk-inbox-panel__view-all"
						data-variant="ghost"
						data-size="sm"
						data-view-all="${p.key}"
					>
						<span class="es-button__label">${__("View all")}</span>
					</button>
				</div>
			</section>`
		).join("");

		return `
		<section class="desk-inbox" id="${ROOT_ID}" aria-label="${__("Desk Inbox")}">
			<div class="desk-inbox__header">
				<div class="desk-inbox__title-wrap">
					<nav class="es-breadcrumbs desk-inbox__breadcrumbs" aria-label="${__("Desk Inbox")}">
						<ol>
							<li>
								<span class="es-breadcrumbs__item" aria-current="page">
									<span class="es-breadcrumbs__label desk-inbox__title">${__("Desk Inbox")}</span>
								</span>
							</li>
						</ol>
					</nav>
					<span class="desk-inbox__total filter-label" data-total title="${__(
						"Assigned + pending + mentions"
					)}">0</span>
				</div>
				<div class="desk-inbox__actions filter-section">
					<div class="desk-inbox__sort" data-sort></div>
					<button type="button" class="text-muted btn btn-default icon-btn desk-inbox__refresh" data-refresh title="${__(
						"Reload"
					)}" aria-label="${__("Reload")}">
						${frappe.utils.icon("refresh-cw")}
					</button>
				</div>
			</div>
			<div class="desk-inbox__panels">${panels}</div>
		</section>`;
	}

	function storage_key() {
		return `desk_inbox_sort:${frappe.session.user || "Guest"}`;
	}

	function read_sort_prefs() {
		try {
			const raw = localStorage.getItem(storage_key());
			if (!raw) return { sort_by: DEFAULT_SORT_BY, sort_order: DEFAULT_SORT_ORDER };
			const parsed = JSON.parse(raw);
			const sort_by = ALLOWED_SORT_BY.has(parsed?.sort_by) ? parsed.sort_by : DEFAULT_SORT_BY;
			const sort_order = ALLOWED_SORT_ORDER.has(parsed?.sort_order)
				? parsed.sort_order
				: DEFAULT_SORT_ORDER;
			return { sort_by, sort_order };
		} catch (_e) {
			return { sort_by: DEFAULT_SORT_BY, sort_order: DEFAULT_SORT_ORDER };
		}
	}

	function write_sort_prefs(sort_by, sort_order) {
		try {
			localStorage.setItem(
				storage_key(),
				JSON.stringify({
					sort_by: ALLOWED_SORT_BY.has(sort_by) ? sort_by : DEFAULT_SORT_BY,
					sort_order: ALLOWED_SORT_ORDER.has(sort_order) ? sort_order : DEFAULT_SORT_ORDER,
				})
			);
		} catch (_e) {
			/* private mode / quota — ignore */
		}
	}

	function current_sort() {
		const sel = frappe.desk_inbox.sort_selector;
		if (sel?.sort_by && sel?.sort_order) {
			return {
				sort_by: ALLOWED_SORT_BY.has(sel.sort_by) ? sel.sort_by : DEFAULT_SORT_BY,
				sort_order: ALLOWED_SORT_ORDER.has(sel.sort_order)
					? sel.sort_order
					: DEFAULT_SORT_ORDER,
			};
		}
		return read_sort_prefs();
	}

	function mount_sort_selector($root) {
		const $parent = $root.find("[data-sort]");
		if (!$parent.length || typeof frappe.ui?.SortSelector !== "function") return;

		const prefs = read_sort_prefs();
		const options = SORT_OPTIONS.map((o) => ({
			fieldname: o.fieldname,
			label: o.label(),
		}));
		const sort_by_label =
			options.find((o) => o.fieldname === prefs.sort_by)?.label || __("Last Updated On");

		const selector = new frappe.ui.SortSelector({
			parent: $parent,
			args: {
				options,
				sort_by: prefs.sort_by,
				sort_by_label,
				sort_order: prefs.sort_order,
			},
			change: (sort_by, sort_order) => {
				write_sort_prefs(sort_by, sort_order);
				refresh({ quiet: true });
			},
		});

		// SortSelector skips init of sort_by/sort_order when no doctype meta exists.
		selector.sort_by = prefs.sort_by;
		selector.sort_order = prefs.sort_order;
		selector.set_value(prefs.sort_by, prefs.sort_order);

		frappe.desk_inbox.sort_selector = selector;
	}

	function visible_rows() {
		const w = window.innerWidth;
		if (w < 480) return 3;
		if (w < 1100) return 4;
		return 5;
	}

	function sync_width($root) {
		if (!$root || !$root.length) return;

		// Below 1100px CSS owns width (full bleed). Clear any prior inline max-width.
		if (window.innerWidth < WIDTH_SYNC_MIN) {
			$root.css("max-width", "");
			return;
		}

		// Desktop: match icon-row width exactly (no extra breathing room).
		const $icons = $(".desktop-container .icons").first();
		const width = $icons.outerWidth();
		if (width && width > 200) {
			$root.css("max-width", Math.round(width) + "px");
		}
	}

	function bind_root($root) {
		$root.on("click", "[data-refresh]", (e) => {
			e.preventDefault();
			refresh();
		});

		$root.on("click", "[data-view-all]", (e) => {
			e.preventDefault();
			const key = $(e.currentTarget).attr("data-view-all");
			open_view_all(key);
		});

		$root.on("click", ".desk-inbox-row", (e) => {
			const $row = $(e.currentTarget);
			const doctype = $row.attr("data-doctype");
			const name = $row.attr("data-name");
			const notification_log = $row.attr("data-notification-log");

			if (notification_log) {
				frappe.call({
					method: "desk_inbox.api.mark_mention_read",
					args: { name: notification_log },
					callback: () => refresh({ quiet: true }),
				});
			}

			if (doctype && name) {
				frappe.set_route("Form", doctype, name);
			}
		});
	}

	function refresh(opts = {}) {
		const quiet = !!opts.quiet;
		const $root = frappe.desk_inbox.$root;
		if (!$root || !$root.length) return;
		if (!$(".desktop-wrapper").length) {
			frappe.desk_inbox.unmount();
			return;
		}

		sync_width($root);
		if (!quiet) {
			$root.addClass("is-loading");
		}
		const { sort_by, sort_order } = current_sort();
		frappe.call({
			method: "desk_inbox.api.get_inbox",
			args: { limit: 20, sort_by, sort_order },
			callback: (r) => {
				$root.removeClass("is-loading");
				if (!r.message) return;
				frappe.desk_inbox._sort_by = r.message.sort_by || sort_by;
				render(r.message);
			},
			error: () => {
				$root.removeClass("is-loading");
			},
		});
	}

	function render(data) {
		const $root = frappe.desk_inbox.$root;
		if (!$root) return;

		const assignedCount = data.assigned?.count || 0;
		const pendingCount = data.pending_me?.count || 0;
		const mentionsCount = data.mentions?.count || 0;
		tick_count($root.find("[data-total]"), assignedCount + pendingCount + mentionsCount);

		PANEL_DEFS.forEach((def) => {
			const bucket = data[def.key] || { count: 0, items: [] };
			const $panel = $root.find(`[data-panel="${def.key}"]`);
			tick_count($panel.find("[data-count]"), bucket.count || 0, {
				badgeTheme: def.badgeTheme,
			});
			const $list = $panel.find("[data-list]");
			const $wrap = $panel.find(".desk-inbox-panel__list-wrap");

			const items = bucket.items || [];
			if (!items.length) {
				$list.html(`
					<div class="desk-inbox-empty">
						<div class="desk-inbox-empty__icon">${frappe.utils.icon("check", "sm")}</div>
						<div class="desk-inbox-empty__text">${__("Nothing pending")}</div>
					</div>`);
				$wrap.removeClass("has-more");
				return;
			}

			$list.html(items.map((item) => row_html(item, def.key)).join(""));
			const rows = visible_rows();
			$wrap.toggleClass(
				"has-more",
				items.length > rows || (bucket.count || 0) > items.length
			);
		});
	}

	function tick_count($el, next, opts = {}) {
		if (!$el.length) return;
		const $label = $el.find(".es-badge__label");
		const prev = parseInt(($label.length ? $label.text() : $el.text()), 10) || 0;
		if ($label.length) {
			$label.text(next);
		} else {
			$el.text(next);
		}

		// Espresso badge theme (keep color even at 0 so Mentions stays purple)
		if (opts.badgeTheme) {
			$el.attr("data-theme", opts.badgeTheme);
		}

		if (prev !== next) {
			$el.removeClass("is-ticking");
			// reflow so animation restarts
			void $el[0].offsetWidth;
			$el.addClass("is-ticking");
		}
	}

	function row_when(item) {
		const sort_by = frappe.desk_inbox._sort_by || current_sort().sort_by;
		const stamp =
			sort_by === "creation" ? item.creation || item.modified : item.modified || item.creation;
		if (!stamp) return "";
		return frappe.utils.escape_html(frappe.datetime.prettyDate(stamp, true) || "");
	}

	function row_html(item, panelKey) {
		const title = frappe.utils.escape_html(item.title || item.name || "");
		const when = row_when(item);
		const doctype = frappe.utils.escape_html(item.doctype || "");
		const name = frappe.utils.escape_html(item.name || "");
		const notification_log = frappe.utils.escape_html(item.notification_log || "");
		const status_label = format_status(item.status, panelKey);
		const overdue = !!item.overdue || status_label === __("Overdue");
		const status_html = status_label
			? `<span class="desk-inbox-row__status${
					overdue ? " desk-inbox-row__status--overdue" : ""
			  }">${frappe.utils.escape_html(status_label)}</span>`
			: "";
		const log_attr = notification_log
			? ` data-notification-log="${notification_log}"`
			: "";
		const overdue_class = overdue ? " is-overdue" : "";

		return `
		<div class="desk-inbox-row${overdue_class}" data-doctype="${doctype}" data-name="${name}"${log_attr}>
			<span class="desk-inbox-row__dot" aria-hidden="true"></span>
			<div class="desk-inbox-row__main">
				<div class="desk-inbox-row__line">
					${status_html}<span class="desk-inbox-row__title">${title}</span>
				</div>
			</div>
			<div class="desk-inbox-row__aside">
				${when ? `<span class="desk-inbox-row__when">${when}</span>` : ""}
			</div>
		</div>`;
	}

	function format_status(status, panelKey) {
		if (!status) return "";
		if (panelKey === "assigned" && status === "Open") return "";
		return status;
	}

	function set_edit_visibility(desktop) {
		const $root = frappe.desk_inbox.$root;
		if (!$root) return;
		$root.toggleClass("is-hidden", !!(desktop && desktop.edit_mode));
	}

	function watch_edit_mode() {
		if (frappe.desk_inbox._edit_observer) {
			frappe.desk_inbox._edit_observer.disconnect();
		}
		const el = document.querySelector(".desktop-wrapper");
		if (!el || !window.MutationObserver) return;

		const observer = new MutationObserver(() => {
			const editing =
				el.getAttribute("data-mode") === "Edit" ||
				!!(frappe.pages["desktop"]?.desktop_page?.edit_mode);
			frappe.desk_inbox.$root?.toggleClass("is-hidden", editing);
			if (!editing && !$(".desktop-wrapper #" + ROOT_ID).length) {
				frappe.desk_inbox.mount(frappe.pages["desktop"]?.desktop_page);
			}
		});
		observer.observe(el, { attributes: true, attributeFilter: ["data-mode"] });
		frappe.desk_inbox._edit_observer = observer;
	}

	function start_timer() {
		stop_timer();
		frappe.desk_inbox._timer = setInterval(() => {
			if (frappe.get_route_str() === "desktop" || frappe.get_route()?.[0] === "desktop") {
				refresh({ quiet: true });
			}
		}, REFRESH_MS);
	}

	function stop_timer() {
		if (frappe.desk_inbox._timer) {
			clearInterval(frappe.desk_inbox._timer);
			frappe.desk_inbox._timer = null;
		}
	}

	$(document).on("desktop_screen", (_e, data) => {
		frappe.desk_inbox.mount(data?.desktop);
	});

	$(document).on("page-change", () => {
		const on_desktop =
			frappe.get_route_str() === "desktop" || frappe.get_route()?.[0] === "desktop";
		if (!on_desktop) {
			stop_timer();
			return;
		}
		if (frappe.desk_inbox.$root?.length) {
			refresh({ quiet: true });
			start_timer();
		}
	});

	$(window).on("resize.desk_inbox", () => {
		clearTimeout(frappe.desk_inbox._resize_timer);
		frappe.desk_inbox._resize_timer = setTimeout(() => {
			if (frappe.desk_inbox.$root?.length) {
				sync_width(frappe.desk_inbox.$root);
				// Recompute fade hint for new visible-row count
				const $root = frappe.desk_inbox.$root;
				$root.find("[data-panel]").each(function () {
					const $panel = $(this);
					const $list = $panel.find("[data-list]");
					const $wrap = $panel.find(".desk-inbox-panel__list-wrap");
					const itemCount = $list.find(".desk-inbox-row").length;
					const count = parseInt($panel.find("[data-count]").text(), 10) || 0;
					if (!itemCount) {
						$wrap.removeClass("has-more");
						return;
					}
					const rows = visible_rows();
					$wrap.toggleClass("has-more", itemCount > rows || count > itemCount);
				});
			}
		}, RESIZE_DEBOUNCE_MS);
	});
})();
