(() => {
	const REFRESH_MS = 60_000;
	const ROOT_ID = "desk-inbox-root";
	const WIDTH_SYNC_MIN = 1100;
	const RESIZE_DEBOUNCE_MS = 100;

	const PANEL_DEFS = [
		{
			key: "assigned",
			label: () => __("Assigned to me"),
			className: "desk-inbox-panel--assigned",
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
			viewAll: () => ({
				doctype: "Workflow Action",
				filters: { status: "Open" },
			}),
		},
		{
			key: "waiting_others",
			label: () => __("Waiting on others"),
			className: "desk-inbox-panel--waiting",
			viewAll: () => ({
				doctype: "Workflow Action",
				filters: { status: "Open" },
			}),
		},
	];

	frappe.desk_inbox = frappe.desk_inbox || {};

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
		} else if (!$root.prev().is($icons_row)) {
			$icons_row.after($root);
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
		frappe.desk_inbox.$root = null;
	};

	function build_shell() {
		const panels = PANEL_DEFS.map(
			(p) => `
			<section class="desk-inbox-panel ${p.className}" data-panel="${p.key}">
				<div class="desk-inbox-panel__head">
					<span class="desk-inbox-panel__label">${frappe.utils.escape_html(p.label())}</span>
					<span class="desk-inbox-panel__count" data-count>0</span>
				</div>
				<div class="desk-inbox-panel__list-wrap has-more">
					<div class="desk-inbox-panel__list" data-list></div>
				</div>
				<div class="desk-inbox-panel__foot">
					<a class="desk-inbox-panel__view-all" href="#" data-view-all="${p.key}">${__(
						"View all"
					)}</a>
				</div>
			</section>`
		).join("");

		return `
		<section class="desk-inbox" id="${ROOT_ID}" aria-label="${__("Inbox")}">
			<div class="desk-inbox__header">
				<div class="desk-inbox__title-wrap">
					<h2 class="desk-inbox__title">${__("Inbox")}</h2>
					<span class="desk-inbox__total" data-total title="${__("Assigned + pending")}">0</span>
				</div>
				<button type="button" class="desk-inbox__refresh" data-refresh title="${__(
					"Refresh"
				)}" aria-label="${__("Refresh")}">
					${frappe.utils.icon("refresh", "sm")}
				</button>
			</div>
			<div class="desk-inbox__panels">${panels}</div>
		</section>`;
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
			const def = PANEL_DEFS.find((p) => p.key === key);
			if (!def) return;
			const { doctype, filters } = def.viewAll();
			frappe.route_options = filters;
			frappe.set_route("List", doctype);
		});

		$root.on("click", ".desk-inbox-row", (e) => {
			const $row = $(e.currentTarget);
			const doctype = $row.attr("data-doctype");
			const name = $row.attr("data-name");
			if (doctype && name) {
				frappe.set_route("Form", doctype, name);
			}
		});
	}

	function refresh() {
		const $root = frappe.desk_inbox.$root;
		if (!$root || !$root.length) return;
		if (!$(".desktop-wrapper").length) {
			frappe.desk_inbox.unmount();
			return;
		}

		sync_width($root);
		$root.addClass("is-loading");
		frappe.call({
			method: "desk_inbox.api.get_inbox",
			args: { limit: 20 },
			callback: (r) => {
				$root.removeClass("is-loading");
				if (!r.message) return;
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
		tick_count($root.find("[data-total]"), assignedCount + pendingCount);

		PANEL_DEFS.forEach((def) => {
			const bucket = data[def.key] || { count: 0, items: [] };
			const $panel = $root.find(`[data-panel="${def.key}"]`);
			tick_count($panel.find("[data-count]"), bucket.count || 0);
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

	function tick_count($el, next) {
		if (!$el.length) return;
		const prev = parseInt($el.text(), 10) || 0;
		$el.text(next);
		if (prev !== next) {
			$el.removeClass("is-ticking");
			// reflow so animation restarts
			void $el[0].offsetWidth;
			$el.addClass("is-ticking");
		}
	}

	function row_html(item, panelKey) {
		const title = frappe.utils.escape_html(item.title || item.name || "");
		const when = item.modified
			? frappe.utils.escape_html(frappe.datetime.prettyDate(item.modified, true) || "")
			: "";
		const doctype = frappe.utils.escape_html(item.doctype || "");
		const name = frappe.utils.escape_html(item.name || "");
		const status_label = format_status(item.status, panelKey);
		const status_html = status_label
			? `<span class="desk-inbox-row__status">${frappe.utils.escape_html(
					status_label
			  )}</span>`
			: "";

		return `
		<div class="desk-inbox-row" data-doctype="${doctype}" data-name="${name}">
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
				refresh();
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
			refresh();
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
