import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "app/templates/pms/partials/reservation_hub/page.html"
OTA_JS = ROOT / "app/static/js/pms/reservation_hub/ota.js"
THEME_CSS = ROOT / "app/static/css/pms/reservation_hub/theme.css"


class ReservationHubOtaUiContractTest(unittest.TestCase):
    def test_ota_agent_is_compact_top_strip_with_log_modal_trigger(self):
        html = PAGE.read_text(encoding="utf-8")

        self.assertRegex(html, r'<div class="bk-shell">\s*<div class="bk-dashboard-header">\s*<div class="bk-ota-strip">')
        self.assertNotIn("bk-ota-command-center", html)
        self.assertNotIn("bk-ota-summary", html)
        self.assertNotIn("bk-ota-log-preview", html)
        for element_id in [
            "bk-ota-total",
            "bk-ota-confirmed",
            "bk-ota-failed",
            "bk-ota-agent-ai",
            "bk-ota-agent-rule",
            "bk-ota-log-modal",
        ]:
            self.assertIn(element_id, html)

        self.assertIn("Log", html)
        self.assertIn("Quét OTA", html)
        self.assertIn('class="bk-control-group bk-branch-control"', html)
        self.assertIn('class="bk-select bk-branch-select"', html)
        self.assertIn('onchange="BookingHub.changeBranch(this.value)"', html)
        self.assertLess(html.index('id="bk-branch"'), html.index('id="bk-ota-scan-date"'))
        self.assertEqual(html.count('class="bk-metric-card'), 5)


    def test_log_modal_contains_filters_and_time_branch_table_columns(self):
        html = PAGE.read_text(encoding="utf-8")

        for element_id in [
            "bk-ota-log-status-filter",
            "bk-ota-log-method-filter",
            "bk-ota-log-action-filter",
            "bk-ota-log-from-date",
            "bk-ota-log-to-date",
            "bk-ota-log-search",
            "bk-ota-log-rows",
        ]:
            self.assertIn(element_id, html)

        for column in ["Thời gian", "Chi nhánh", "Nguồn", "Xử lý", "Booking", "Trạng thái"]:
            self.assertIn(column, html)

    def test_ota_js_loads_status_only_by_default_and_modal_logs_with_filters(self):
        js = OTA_JS.read_text(encoding="utf-8")

        self.assertIn("openOtaLogModal()", js)
        self.assertIn("loadOtaLogs()", js)
        self.assertIn("renderOtaLogTable", js)
        self.assertIn("parser_method", js)
        self.assertIn("action_type", js)
        self.assertIn("branch_id", js)
        self.assertIn("/api/pms/reservations/ota/logs?", js)
        self.assertIn("bk-ota-log-rows", js)
        self.assertIn("bk-ota-agent-ai", js)
        self.assertIn("bk-ota-agent-rule", js)

    def test_ota_css_defines_compact_strip_modal_filters_and_table(self):
        css = THEME_CSS.read_text(encoding="utf-8")

        for selector in [
            ".bk-ota-strip",
            ".bk-ota-strip-metrics",
            ".bk-ota-strip-controls",
            ".bk-ota-log-modal-dialog",
            ".bk-ota-log-filters",
            ".bk-ota-log-table-wrap",
            ".bk-ota-log-table",
            ".bk-method-pill",
        ]:
            self.assertIn(selector, css)
        self.assertNotIn(".bk-ota-agent-grid", css)
        self.assertNotIn(".bk-ota-agent-card", css)
        self.assertNotIn(".bk-ota-summary", css)
        self.assertNotIn(".bk-ota-logs", css)
        self.assertIn("grid-template-columns: repeat(5, minmax(56px, max-content))", css)
        self.assertNotIn("grid-template-columns: repeat(6, minmax(0, 1fr));\\n  gap: 0", css)



if __name__ == "__main__":
    unittest.main()
