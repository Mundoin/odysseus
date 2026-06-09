"""
Preview-quality tests for external-action guardrail pending_confirmation payloads
(stage: odysseus-guardrail-preview-quality-v1).

Covers:
- api_call risky action preview includes action category, risk level, target,
  summary, consequences
- app_api risky action preview includes route/action details
- MCP click-submit preview includes tool name and button/action context
- MCP upload preview is high-impact with final_review_checklist
- MCP buy/pay/order previews are high-impact
- MCP delete/cancel/refund/return previews are high-impact
- read-only actions do not produce pending_confirmation
- confirmed=true still allows dispatch/execution path
- confirmed flag still stripped before underlying MCP call
- legacy preview fields preserved for existing consumers
"""
import pytest

pytestmark = [pytest.mark.area_security, pytest.mark.sub_guard_preview_quality]


# ---------------------------------------------------------------------------
# api_call / app_api preview shape
# ---------------------------------------------------------------------------

class TestApiCallPreviewQuality:
    def test_api_call_preview_core_fields(self):
        from src.external_action_guard import guard
        result = guard(
            tool="api_call",
            method="POST",
            target="Gitea:/repos/bujar/odysseus/issues",
            confirmed=False,
            body={"title": "bug report"},
            integration="Gitea",
        )
        assert result["pending_confirmation"] is True
        assert result["confirmation_required"] is True
        assert result["action_category"] == "external_write"
        assert result["risk_level"] == "normal"
        assert result["tool_name"] == "api_call"
        assert result["action_name"] == "POST"
        assert result["target"] == "Gitea:/repos/bujar/odysseus/issues"
        assert "summary" in result and "POST" in result["summary"]
        assert "Gitea" in result["summary"]
        assert "Approval is required" in result["summary"]
        assert "consequences" in result and "If approved" in result["consequences"]
        assert "approval_instruction" in result
        assert "confirmed=true" in result["approval_instruction"]

    def test_api_call_arguments_preview_present(self):
        from src.external_action_guard import guard
        result = guard(
            tool="api_call", method="POST", target="Gitea:/repos/x/issues",
            confirmed=False, body={"title": "hello"}, integration="Gitea",
        )
        assert result["arguments_preview"] == {"title": "hello"}
        assert result["body_preview"] == {"title": "hello"}

    def test_api_call_long_string_args_truncated_in_preview(self):
        from src.external_action_guard import guard
        big = "x" * 5000
        result = guard(
            tool="api_call", method="POST", target="Gitea:/repos/x/issues",
            confirmed=False, body={"text": big}, integration="Gitea",
        )
        assert len(result["arguments_preview"]["text"]) < 1000
        assert "chars total" in result["arguments_preview"]["text"]
        # legacy body_preview stays raw
        assert result["body_preview"]["text"] == big

    def test_api_call_high_impact_payment(self):
        from src.external_action_guard import guard
        result = guard(
            tool="api_call", method="POST", target="Shop:/api/payment/charge",
            confirmed=False, integration="Shop",
        )
        assert result["risk_level"] == "high"
        assert result["high_impact"] is True
        assert "payment" in result["high_impact_reason"]
        assert isinstance(result["final_review_checklist"], list)
        assert len(result["final_review_checklist"]) >= 3

    def test_app_api_preview_includes_route_details(self):
        from src.external_action_guard import guard
        result = guard(
            tool="app_api", method="DELETE", target="/api/sessions/42",
            confirmed=False,
        )
        assert result["pending_confirmation"] is True
        assert result["tool_name"] == "app_api"
        assert result["action_name"] == "DELETE"
        assert result["target"] == "/api/sessions/42"
        assert "/api/sessions/42" in result["summary"]
        assert "DELETE" in result["summary"]

    def test_url_target_yields_target_domain(self):
        from src.external_action_guard import guard
        result = guard(
            tool="api_call", method="POST",
            target="https://shop.example.test/api/cart", confirmed=False,
        )
        assert result["target_domain"] == "shop.example.test"

    def test_url_target_yields_target_url_alias_and_explicit_high_impact_false(self):
        from src.external_action_guard import guard
        result = guard(
            tool="api_call", method="POST",
            target="https://api.example.test/messages", confirmed=False,
        )
        assert result["target_url"] == "https://api.example.test/messages"
        assert result["high_impact"] is False


# ---------------------------------------------------------------------------
# MCP browser action previews
# ---------------------------------------------------------------------------

class TestMcpPreviewQuality:
    def test_click_submit_preview_has_tool_and_button_context(self):
        from src.external_action_guard import guard_mcp
        result = guard_mcp(
            "mcp__playwright__browser_click", {"element": "Submit order"}, confirmed=False
        )
        assert result["pending_confirmation"] is True
        assert result["tool_name"] == "mcp__playwright__browser_click"
        assert result["action_name"] == "browser_click"
        assert result["action_category"] == "high_impact_external_write"
        assert "Submit order" in result["summary"]
        assert "click" in result["summary"]
        assert "mcp__playwright__browser_click" in result["summary"]
        assert "Approval is required" in result["summary"]
        assert "submit" in result["high_impact_reason"]

    def test_upload_preview_is_high_impact_with_checklist(self):
        from src.external_action_guard import guard_mcp
        result = guard_mcp(
            "mcp__playwright__browser_file_upload",
            {"paths": ["/tmp/tax-return.pdf"]},
            confirmed=False,
        )
        assert result["high_impact"] is True
        assert result["risk_level"] == "high"
        assert "upload" in result["summary"]
        assert "upload" in result["high_impact_reason"]
        assert isinstance(result["final_review_checklist"], list)
        assert any("reviewed" in item for item in result["final_review_checklist"])

    @pytest.mark.parametrize("element", ["Buy now", "Pay now", "Place order"])
    def test_buy_pay_order_clicks_are_high_impact(self, element):
        from src.external_action_guard import guard_mcp
        result = guard_mcp(
            "mcp__playwright__browser_click", {"element": element}, confirmed=False
        )
        assert result["high_impact"] is True
        assert result["risk_level"] == "high"
        assert element in result["summary"]

    @pytest.mark.parametrize("element", [
        "Delete account", "Cancel subscription", "Request refund", "Return item",
    ])
    def test_delete_cancel_refund_return_clicks_are_high_impact(self, element):
        from src.external_action_guard import guard_mcp
        result = guard_mcp(
            "mcp__playwright__browser_click", {"element": element}, confirmed=False
        )
        assert result["high_impact"] is True
        assert result["risk_level"] == "high"
        assert "high-impact keyword" in result["high_impact_reason"]

    def test_plain_click_is_normal_risk_with_explicit_high_impact_false(self):
        from src.external_action_guard import guard_mcp
        result = guard_mcp(
            "mcp__playwright__browser_click", {"element": "Open menu"}, confirmed=False
        )
        assert result["risk_level"] == "normal"
        assert result["high_impact"] is False
        assert "final_review_checklist" not in result

    def test_network_request_preview_has_url_and_domain(self):
        from src.external_action_guard import guard_mcp
        result = guard_mcp(
            "mcp__playwright__browser_network_request",
            {"method": "POST", "url": "https://api.example.test/messages"},
            confirmed=False,
        )
        assert result["url"] == "https://api.example.test/messages"
        assert result["target_domain"] == "api.example.test"
        assert "POST" in result["summary"]

    def test_mcp_preview_arguments_preview_mirrors_args(self):
        from src.external_action_guard import guard_mcp
        args = {"element": "Submit", "ref": "e42"}
        result = guard_mcp("mcp__playwright__browser_click", dict(args), confirmed=False)
        assert result["arguments_preview"] == args


# ---------------------------------------------------------------------------
# read-only / confirmed paths unchanged
# ---------------------------------------------------------------------------

class TestNoGateAndConfirmedPaths:
    def test_get_request_produces_no_preview(self):
        from src.external_action_guard import guard
        assert guard(tool="api_call", method="GET", target="Gitea:/repos",
                     confirmed=False) is None

    def test_snapshot_produces_no_preview(self):
        from src.external_action_guard import guard_mcp
        assert guard_mcp("mcp__playwright__browser_snapshot", {}, confirmed=False) is None

    def test_confirmed_true_allows_api_execution(self):
        from src.external_action_guard import guard
        assert guard(tool="api_call", method="POST", target="Shop:/api/payment",
                     confirmed=True) is None

    def test_confirmed_true_allows_mcp_dispatch(self):
        from src.external_action_guard import guard_mcp
        assert guard_mcp("mcp__playwright__browser_click",
                         {"element": "Submit order"}, confirmed=True) is None

    def test_confirmed_flag_stripped_before_mcp_call(self):
        from src.external_action_guard import guard_mcp
        args = {"element": "Buy now", "confirmed": True}
        confirmed = bool(args.pop("confirmed", False))
        assert guard_mcp("mcp__playwright__browser_click", args, confirmed) is None
        assert "confirmed" not in args


# ---------------------------------------------------------------------------
# legacy compatibility
# ---------------------------------------------------------------------------

class TestLegacyFieldCompatibility:
    def test_legacy_fields_still_present(self):
        from src.external_action_guard import guard
        result = guard(tool="api_call", method="POST", target="Shop:/api/payment",
                       confirmed=False, body={"amount": 5}, integration="Shop")
        assert result["tool"] == "api_call"
        assert result["action_type"] == "high_impact_external_write"
        assert "HIGH IMPACT" in result["risk"]
        assert "confirmed=true" in result["instruction"]
        assert result["integration"] == "Shop"
        assert result["body_preview"] == {"amount": 5}
        assert "final_checklist" in result

    def test_new_fields_mirror_legacy_values(self):
        from src.external_action_guard import guard_mcp
        result = guard_mcp("mcp__playwright__browser_click",
                           {"element": "Submit"}, confirmed=False)
        assert result["tool_name"] == result["tool"]
        assert result["action_category"] == result["action_type"]
        assert result["approval_instruction"] == result["instruction"]
