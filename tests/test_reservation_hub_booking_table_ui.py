import re
import unittest
from pathlib import Path


PAGE = Path("app/templates/pms/partials/reservation_hub/page.html")
RESERVATIONS_JS = Path("app/static/js/pms/reservation_hub/reservations.js")
THEME_CSS = Path("app/static/css/pms/reservation_hub/theme.css")


class ReservationHubBookingTableUiContractTest(unittest.TestCase):
    def test_table_headers_match_ota_dashboard_reference_layout(self):
        html = PAGE.read_text(encoding="utf-8")
        for label in [
            "Mã đơn",
            "Kênh OTA",
            "Khách hàng",
            "Chi nhánh & phòng",
            "Lưu trú",
            "Trạng thái",
            "Tổng tiền",
            "Yêu cầu",
            "Thao tác",
        ]:
            self.assertIn(label, html)

    def test_professional_toolbar_removes_redundant_title_and_keeps_filters_one_row(self):
        html = PAGE.read_text(encoding="utf-8")
        css = THEME_CSS.read_text(encoding="utf-8")
        js = RESERVATIONS_JS.read_text(encoding="utf-8")

        self.assertNotIn("bk-list-title", html)
        self.assertNotIn("bk-list-summary", html)
        self.assertNotIn("bk-list-summary", js)
        self.assertIn("bk-reservations-card", html)
        self.assertIn("bk-search-box", html)
        self.assertIn("bk-stay-filter", html)
        self.assertIn("id=\"bk-stay-from\"", html)
        self.assertIn("id=\"bk-stay-to\"", html)
        self.assertIn("resetReservationFilters", js)
        self.assertIn(".bk-filter-row", css)
        self.assertIn("display: grid", css)
        self.assertIn("grid-template-columns: minmax(320px, 1fr) minmax(170px, 190px) minmax(310px, 360px) 42px max-content", css)
        self.assertIn("align-items: center", css)
        self.assertIn("flex-wrap: nowrap", css)

    def test_stats_are_unified_and_table_insights_removed(self):
        html = PAGE.read_text(encoding="utf-8")
        css = THEME_CSS.read_text(encoding="utf-8")
        self.assertNotIn("bk-table-insights", html)
        self.assertNotIn("bk-table-insights", css)
        self.assertIn("id=\"bk-stats\"", html)
        for element_id in [
            "bk-stat-total",
            "bk-stat-arrivals",
            "bk-stat-departures",
            "bk-stat-confirmed",
            "bk-stat-pending",
            "bk-visible-revenue",
        ]:
            self.assertIn(element_id, html)
        self.assertIn("grid-template-columns: repeat(6, minmax(0, 1fr))", css)
        self.assertIn("min-height: 78px", css)


    def test_stats_cards_use_inline_svg_icons_not_empty_icon_slots(self):
        html = PAGE.read_text(encoding="utf-8")
        self.assertIn('class="bk-stats-grid" id="bk-stats"', html)
        self.assertEqual(html.count('class="bk-stat-card'), 6)
        self.assertGreaterEqual(html.count('class="bk-stat-icon" aria-hidden="true"'), 6)
        self.assertGreaterEqual(html.count('<svg viewBox="0 0 24 24"'), 6)
        self.assertNotIn('<div class="bk-stat-icon"><i class=', html)

        css = THEME_CSS.read_text(encoding="utf-8")
        self.assertIn(".bk-stat-icon svg", css)
        self.assertIn("stroke: currentColor", css)

    def test_reservation_filters_include_stay_dates_and_search_query(self):
        js = RESERVATIONS_JS.read_text(encoding="utf-8")
        for token in [
            "const search = this.value('bk-search')",
            "const stayFrom = this.value('bk-stay-from')",
            "const stayTo = this.value('bk-stay-to')",
            "params.set('search', search)",
            "params.set('check_in_from', stayFrom)",
            "params.set('check_in_to', stayTo)",
        ]:
            self.assertIn(token, js)

    def test_reservation_row_renders_reference_style_cells_without_click_hint(self):
        js = RESERVATIONS_JS.read_text(encoding="utf-8")
        for token in [
            "bk-order-cell",
            "bk-ota-cell",
            "bk-branch-room-cell",
            "bk-stay-cell",
            "bk-request-cell",
            "branch_name",
            "special_requests",
            "internal_notes",
            "num_guests",
        ]:
            self.assertIn(token, js)
        self.assertNotIn("bk-row-click-hint", js)
        self.assertNotIn("Bấm dòng để xem chi tiết", js)

    def test_ota_overnight_with_times_is_not_labelled_hourly(self):
        js = RESERVATIONS_JS.read_text(encoding="utf-8")
        self.assertIn("const parseStayMinutes = (value) => {", js)
        self.assertIn("const crossesMidnight = Boolean(", js)
        self.assertIn("rawData.ota_cross_midnight_booking", js)
        self.assertIn("checkOutMinutes <= checkInMinutes", js)
        self.assertIn("const checkOutDate = rawData.ota_actual_check_out && !crossesMidnight ? rawData.ota_actual_check_out : booking.check_out", js)
        self.assertIn("const actualStayDays = this.dateDiff(booking.check_in, checkOutDate)", js)
        self.assertIn("const isHourlyStay = Boolean(rawData.ota_same_day_booking && !crossesMidnight && actualStayDays <= 0)", js)
        self.assertNotIn("rawData.ota_same_day_booking || rawData.check_in_time || rawData.check_out_time", js)

    def test_booking_hub_polls_ota_changes_and_refreshes_table(self):
        core_js = Path("app/static/js/pms/reservation_hub/core.js").read_text(encoding="utf-8")
        ota_js = Path("app/static/js/pms/reservation_hub/ota.js").read_text(encoding="utf-8")
        self.assertIn("this.startOtaRealtimePolling()", core_js)
        for token in [
            "params.set('fresh', '1')",
            "latest_cancel_log_id",
            "latest_success_log_id",
            "pmsToast(this.otaRealtimeMessage(data.latest_cancel_booking, 'cancel'), true)",
            "await Promise.all([this.loadStats(), this.loadReservations()])",
        ]:
            self.assertIn(token, ota_js)

    def test_row_click_opens_detail_modal_and_detail_action_button_is_removed(self):
        js = RESERVATIONS_JS.read_text(encoding="utf-8")
        self.assertIn("onclick=\"BookingHub.openDetail(${booking.id})\"", js)
        self.assertNotIn(">Chi tiết</button>", js)
        self.assertNotIn("title=\"Chi tiết\"", js)

    def test_no_show_button_only_after_checkout_for_not_checked_in_bookings(self):
        js = RESERVATIONS_JS.read_text(encoding="utf-8")
        self.assertIn("const canNoShow", js)
        self.assertIn("this.isPastCheckoutDate(booking.check_out)", js)
        self.assertIn("!['CHECKED_IN', 'CHECKED_OUT', 'CANCELLED', 'NO_SHOW'].includes(status)", js)
        self.assertNotRegex(js, r"canCancel \? `[^`]*noShow")

    def test_action_buttons_are_svg_icons_with_tooltips(self):
        js = RESERVATIONS_JS.read_text(encoding="utf-8")
        for token in [
            "checkin:",
            "confirm:",
            "assign:",
            "edit:",
            "unassign:",
            "cancel:",
            "noshow:",
            "title=\"${safeLabel}\"",
            "aria-label=\"${safeLabel}\"",
            "<svg",
        ]:
            self.assertIn(token, js)

    def test_css_uses_light_blue_ota_dashboard_visual_language(self):
        css = THEME_CSS.read_text(encoding="utf-8")
        expectations = [
            "--bk-primary: #1a73e8",
            "--bk-bg: #ffffff",
            "min-width: 1420px",
            "background: #f9fafb",
            ".bk-order-cell",
            ".bk-ota-cell",
            ".bk-branch-room-cell",
            ".bk-request-cell",
        ]
        for token in expectations:
            self.assertIn(token, css)

    def test_booking_page_avoids_noisy_nested_backgrounds(self):
        css = THEME_CSS.read_text(encoding="utf-8")
        self.assertNotIn("background: var(--bk-bg)", css)
        self.assertNotIn("background: var(--bk-surface-muted)", css)
        self.assertNotIn("background: #f8fafc", css)

        page_block = re.search(r"#pms-booking-page \{(?P<body>.*?)\n\}", css, re.S)
        self.assertIsNotNone(page_block)
        self.assertNotIn("background", page_block.group("body"))

        quiet_blocks = [".bk-filter-row", ".bk-tabs", ".bk-avail-dates", ".bk-empty"]
        for selector in quiet_blocks:
            block = re.search(re.escape(selector) + r"[^\{]*\{(?P<body>.*?)\n\}", css, re.S)
            self.assertIsNotNone(block, selector)
            self.assertNotIn("background:", block.group("body"), selector)

    def test_dark_mode_tokens_and_filter_controls_are_consistent(self):
        css = THEME_CSS.read_text(encoding="utf-8")
        self.assertNotIn(".dark :root", css)
        self.assertIn("html.dark {", css)
        for token in [
            "--bk-surface: #111827",
            "--bk-ink: #f8fafc",
            "html.dark .bk-search-box",
            "html.dark .bk-table th",
            "html.dark .bk-ota-log-table-wrap",
        ]:
            self.assertIn(token, css)

        for token in [
            "box-sizing: border-box",
            ".bk-filter-row .bk-select",
            ".bk-filter-row .bk-input",
            ".bk-search-input",
            ".bk-stay-filter .bk-input",
            "height: 42px",
            "min-width: 0",
            "appearance: none",
        ]:
            self.assertIn(token, css)

    def test_css_has_icon_action_and_clickable_row_styles(self):
        css = THEME_CSS.read_text(encoding="utf-8")
        for token in [
            ".bk-table tbody tr[data-booking-id]",
            "cursor: pointer",
            ".bk-icon-btn",
            ".bk-icon-btn svg",
            ".bk-row-actions",
            "pointer-events: auto",
        ]:
            self.assertIn(token, css)

    def test_table_no_longer_uses_old_green_header(self):
        css = THEME_CSS.read_text(encoding="utf-8")
        table_block = re.search(r"\.bk-table th \{(?P<body>.*?)\n\}", css, re.S)
        self.assertIsNotNone(table_block)
        self.assertNotIn("background: #0f766e", table_block.group("body"))
        self.assertNotIn("html.dark .bk-table th { background: #0f766e", css)
        self.assertIn("background: #f9fafb", table_block.group("body"))

    def test_group_deposit_step_has_manual_split_controls(self):
        html = Path("app/templates/pms/partials/reservation_hub/create_modal.html").read_text(encoding="utf-8")
        js = Path("app/static/js/pms/reservation_hub/form.js").read_text(encoding="utf-8")
        css = Path("app/static/css/pms/reservation_hub/form.css").read_text(encoding="utf-8")

        for token in [
            "bk-deposit-allocation-panel",
            "bk-deposit-split-lines",
            "BookingHub.setDepositAllocationMode('split')",
            "BookingHub.setDepositAllocationMode('single')",
        ]:
            self.assertIn(token, html)
        for token in [
            "setDepositSplitAmount",
            "rebalanceDepositSplitAmounts",
            "getDefaultDepositSplitAmounts",
            "depositSplitAmounts",
        ]:
            self.assertIn(token, js)
        self.assertIn('onchange="BookingHub.setDepositSplitAmount', js)
        self.assertNotIn('oninput="BookingHub.setDepositSplitAmount', js)
        self.assertIn("el.addEventListener('input', () => {", js)
        self.assertIn("el.addEventListener('blur', () => {", js)
        self.assertIn("if (id !== 'bk-form-deposit')", js)
        self.assertIn("if (id === 'bk-form-deposit')", js)
        self.assertIn(".bk-deposit-split-line", css)


if __name__ == "__main__":
    unittest.main()
