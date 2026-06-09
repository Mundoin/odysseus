"""
Tests for MCP dispatch guardrails (stage: odysseus-mcp-dispatch-external-action-guardrails-v1).

Covers:
- classify_mcp_tool: safe reads pass through, local-prepare pass through,
  external_write and high_impact require confirmation
- guard_mcp: returns None when safe/local/confirmed, preview dict otherwise
- confirmed stripped from args before MCP call
- browser_click keywords escalate to high_impact
- browser_press_key Enter = external_write
- browser_file_upload always high_impact
- browser_snapshot / browser_take_screenshot always safe_read
- browser_type / browser_fill always local_prepare
"""
import pytest

pytestmark = [pytest.mark.area_security, pytest.mark.sub_mcp_dispatch_guards]


# ---------------------------------------------------------------------------
# classify_mcp_tool
# ---------------------------------------------------------------------------

class TestClassifyMcpTool:
    def test_snapshot_is_safe_read(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_snapshot", {}) == "safe_read"

    def test_take_screenshot_is_safe_read(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_take_screenshot", {}) == "safe_read"

    def test_navigate_is_safe_read(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_navigate", {"url": "https://example.com"}) == "safe_read"

    def test_console_messages_is_safe_read(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_console_messages", {}) == "safe_read"

    def test_browser_type_is_local_prepare(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_type", {"text": "hello"}) == "local_prepare"

    def test_browser_fill_is_local_prepare(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_fill", {"value": "test"}) == "local_prepare"

    def test_browser_select_option_is_local_prepare(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_select_option", {}) == "local_prepare"

    def test_file_upload_is_high_impact(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_file_upload", {"paths": ["/tmp/doc.pdf"]}) == "high_impact_external_write"

    def test_run_code_unsafe_is_high_impact(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_run_code_unsafe", {}) == "high_impact_external_write"

    def test_evaluate_is_high_impact(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_evaluate", {"expression": "1+1"}) == "high_impact_external_write"

    def test_click_submit_is_high_impact(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_click", {"element": "Submit order"}) == "high_impact_external_write"

    def test_click_pay_is_high_impact(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_click", {"element": "Pay now"}) == "high_impact_external_write"

    def test_click_cancel_is_high_impact(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_click", {"element": "Cancel subscription"}) == "high_impact_external_write"

    def test_click_delete_is_high_impact(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_click", {"element": "Delete account"}) == "high_impact_external_write"

    def test_click_plain_button_is_external_write(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_click", {"element": "Open menu"}) == "external_write"

    def test_press_enter_is_external_write(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_press_key", {"key": "Enter"}) == "external_write"

    def test_press_tab_is_local_prepare(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_press_key", {"key": "Tab"}) == "local_prepare"

    def test_network_request_get_is_safe(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_network_request", {"method": "GET", "url": "/api/data"}) == "safe_read"

    def test_network_request_post_is_external_write(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("mcp__playwright__browser_network_request", {"method": "POST", "url": "/api/messages"}) == "external_write"

    def test_bare_tool_name_also_works(self):
        from src.external_action_guard import classify_mcp_tool
        assert classify_mcp_tool("browser_snapshot", {}) == "safe_read"


# ---------------------------------------------------------------------------
# guard_mcp
# ---------------------------------------------------------------------------

class TestGuardMcp:
    def test_snapshot_returns_none(self):
        from src.external_action_guard import guard_mcp
        assert guard_mcp("mcp__playwright__browser_snapshot", {}, confirmed=False) is None

    def test_browser_type_returns_none(self):
        from src.external_action_guard import guard_mcp
        assert guard_mcp("mcp__playwright__browser_fill", {"value": "hello"}, confirmed=False) is None

    def test_click_plain_without_confirmed_returns_preview(self):
        from src.external_action_guard import guard_mcp
        result = guard_mcp("mcp__playwright__browser_click", {"element": "Next"}, confirmed=False)
        assert result is not None
        assert result["pending_confirmation"] is True

    def test_click_submit_without_confirmed_is_high_impact(self):
        from src.external_action_guard import guard_mcp
        result = guard_mcp("mcp__playwright__browser_click", {"element": "Submit"}, confirmed=False)
        assert result["action_type"] == "high_impact_external_write"
        assert "final_checklist" in result

    def test_file_upload_without_confirmed_is_high_impact(self):
        from src.external_action_guard import guard_mcp
        result = guard_mcp("mcp__playwright__browser_file_upload", {"paths": ["/tmp/file.pdf"]}, confirmed=False)
        assert result["action_type"] == "high_impact_external_write"
        assert result["pending_confirmation"] is True

    def test_click_with_confirmed_true_returns_none(self):
        from src.external_action_guard import guard_mcp
        assert guard_mcp("mcp__playwright__browser_click", {"element": "Submit"}, confirmed=True) is None

    def test_file_upload_with_confirmed_true_returns_none(self):
        from src.external_action_guard import guard_mcp
        assert guard_mcp("mcp__playwright__browser_file_upload", {"paths": ["/tmp/x"]}, confirmed=True) is None

    def test_preview_contains_required_fields(self):
        from src.external_action_guard import guard_mcp
        result = guard_mcp("mcp__playwright__browser_click", {"element": "Buy now"}, confirmed=False)
        assert "tool" in result
        assert "action_type" in result
        assert "target" in result
        assert "risk" in result
        assert "instruction" in result
        assert "confirmed=true" in result["instruction"]

    def test_target_uses_element_text(self):
        from src.external_action_guard import guard_mcp
        result = guard_mcp("mcp__playwright__browser_click", {"element": "Pay $9.99"}, confirmed=False)
        assert "Pay $9.99" in result["target"]

    def test_press_enter_without_confirmed_returns_preview(self):
        from src.external_action_guard import guard_mcp
        result = guard_mcp("mcp__playwright__browser_press_key", {"key": "Enter"}, confirmed=False)
        assert result is not None
        assert result["pending_confirmation"] is True

    def test_press_tab_returns_none(self):
        from src.external_action_guard import guard_mcp
        assert guard_mcp("mcp__playwright__browser_press_key", {"key": "Tab"}, confirmed=False) is None


# ---------------------------------------------------------------------------
# confirmed stripped from args before dispatch
# ---------------------------------------------------------------------------

class TestConfirmedStripped:
    def test_confirmed_popped_before_guard(self):
        """confirm that guard_mcp receives args WITHOUT confirmed already stripped"""
        from src.external_action_guard import guard_mcp
        args = {"element": "Next", "confirmed": True}
        # simulate the strip the dispatcher does
        confirmed = bool(args.pop("confirmed", False))
        result = guard_mcp("mcp__playwright__browser_click", args, confirmed)
        assert result is None
        assert "confirmed" not in args
