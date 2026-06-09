"""
Regression tests for external-action guardrails (api_call, app_api).

Covers:
- GET requests pass through unblocked (safe_read)
- POST/PUT/PATCH/DELETE without confirmed return pending_confirmation
- confirmed=true allows execution path (no preview returned)
- high-impact keywords escalate to high_impact_external_write with final_checklist
- read/search actions (GET) remain unblocked
- tool schemas expose confirmed param for api_call and app_api
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

pytestmark = [pytest.mark.area_security, pytest.mark.sub_external_action_guards]

# ---------------------------------------------------------------------------
# Unit tests for the guard helper itself
# ---------------------------------------------------------------------------

class TestExternalActionGuardClassify:
    def test_get_is_safe_read(self):
        from src.external_action_guard import classify
        assert classify("GET", "/api/foo") == "safe_read"

    def test_get_with_high_impact_path_still_safe(self):
        from src.external_action_guard import classify
        assert classify("GET", "/api/orders/cancel") == "safe_read"

    def test_post_plain_path_is_external_write(self):
        from src.external_action_guard import classify
        assert classify("POST", "/api/messages") == "external_write"

    def test_delete_plain_path_is_external_write(self):
        from src.external_action_guard import classify
        assert classify("DELETE", "/api/items/42") == "external_write"

    def test_patch_plain_path_is_external_write(self):
        from src.external_action_guard import classify
        assert classify("PATCH", "/api/profile") == "external_write"

    def test_post_buy_is_high_impact(self):
        from src.external_action_guard import classify
        assert classify("POST", "/api/buy") == "high_impact_external_write"

    def test_post_payment_is_high_impact(self):
        from src.external_action_guard import classify
        assert classify("POST", "/api/payment/process") == "high_impact_external_write"

    def test_delete_account_is_high_impact(self):
        from src.external_action_guard import classify
        assert classify("DELETE", "/api/account/close") == "high_impact_external_write"

    def test_post_cancel_is_high_impact(self):
        from src.external_action_guard import classify
        assert classify("POST", "/orders/cancel") == "high_impact_external_write"

    def test_post_password_is_high_impact(self):
        from src.external_action_guard import classify
        assert classify("POST", "/api/password/reset") == "high_impact_external_write"

    def test_post_tax_is_high_impact(self):
        from src.external_action_guard import classify
        assert classify("POST", "/api/tax/submit") == "high_impact_external_write"


class TestExternalActionGuardFunction:
    def test_get_returns_none(self):
        from src.external_action_guard import guard
        result = guard(tool="api_call", method="GET", target="/api/foo", confirmed=False)
        assert result is None

    def test_post_no_confirmed_returns_preview(self):
        from src.external_action_guard import guard
        result = guard(tool="api_call", method="POST", target="/api/messages", confirmed=False)
        assert result is not None
        assert result["pending_confirmation"] is True

    def test_post_confirmed_true_returns_none(self):
        from src.external_action_guard import guard
        result = guard(tool="api_call", method="POST", target="/api/messages", confirmed=True)
        assert result is None

    def test_delete_no_confirmed_returns_preview(self):
        from src.external_action_guard import guard
        result = guard(tool="api_call", method="DELETE", target="/api/items/5", confirmed=False)
        assert result is not None
        assert result["pending_confirmation"] is True

    def test_preview_contains_required_fields(self):
        from src.external_action_guard import guard
        result = guard(tool="api_call", method="POST", target="/api/create", confirmed=False)
        assert "action_type" in result
        assert "method" in result
        assert "target" in result
        assert "risk" in result
        assert "instruction" in result
        assert "confirmed=true" in result["instruction"]

    def test_high_impact_preview_has_final_checklist(self):
        from src.external_action_guard import guard
        result = guard(tool="api_call", method="POST", target="/api/buy", confirmed=False)
        assert result["action_type"] == "high_impact_external_write"
        assert "final_checklist" in result

    def test_high_impact_risk_stronger_wording(self):
        from src.external_action_guard import guard
        result = guard(tool="api_call", method="POST", target="/api/payment", confirmed=False)
        assert "HIGH IMPACT" in result["risk"]

    def test_external_write_action_type(self):
        from src.external_action_guard import guard
        result = guard(tool="app_api", method="PUT", target="/api/settings", confirmed=False)
        assert result["action_type"] == "external_write"

    def test_integration_included_in_preview(self):
        from src.external_action_guard import guard
        result = guard(
            tool="api_call", method="POST", target="Gitea:/repos/create",
            confirmed=False, integration="Gitea"
        )
        assert result["integration"] == "Gitea"

    def test_body_included_in_preview(self):
        from src.external_action_guard import guard
        result = guard(
            tool="api_call", method="POST", target="/api/msg",
            confirmed=False, body={"text": "hello"}
        )
        assert result["body_preview"] == {"text": "hello"}


# ---------------------------------------------------------------------------
# do_app_api integration
# ---------------------------------------------------------------------------

class TestAppApiGuard:
    @pytest.mark.asyncio
    async def test_get_bypasses_guard(self):
        """GET app_api must not be blocked."""
        args = '{"action": "call", "method": "GET", "path": "/api/cookbook/gpus"}'
        with patch("httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"gpus": []}
            mock_resp.text = '{"gpus": []}'
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.request = AsyncMock(return_value=mock_resp)
            from src.tool_implementations import do_app_api
            result = await do_app_api(args)
        assert result.get("pending_confirmation") is not True

    @pytest.mark.asyncio
    async def test_post_without_confirmed_returns_preview(self):
        """POST app_api without confirmed must return preview, not call httpx."""
        args = '{"action": "call", "method": "POST", "path": "/api/gallery/upload", "body": {}}'
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.request = AsyncMock()
            from src.tool_implementations import do_app_api
            result = await do_app_api(args)
        mock_client.return_value.request.assert_not_awaited()
        assert result["pending_confirmation"] is True

    @pytest.mark.asyncio
    async def test_delete_without_confirmed_returns_preview(self):
        args = '{"action": "call", "method": "DELETE", "path": "/api/sessions/123"}'
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.request = AsyncMock()
            from src.tool_implementations import do_app_api
            result = await do_app_api(args)
        assert result["pending_confirmation"] is True

    @pytest.mark.asyncio
    async def test_post_cancel_path_is_high_impact(self):
        args = '{"action": "call", "method": "POST", "path": "/api/subscription/cancel"}'
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.request = AsyncMock()
            from src.tool_implementations import do_app_api
            result = await do_app_api(args)
        assert result["pending_confirmation"] is True
        assert result["action_type"] == "high_impact_external_write"

    @pytest.mark.asyncio
    async def test_endpoints_action_always_safe(self):
        """action=endpoints is a read — must never be blocked."""
        args = '{"action": "endpoints"}'
        with patch("httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"paths": {}}
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_resp)
            from src.tool_implementations import do_app_api
            result = await do_app_api(args)
        assert result.get("pending_confirmation") is not True


# Schema tests for api_call / app_api confirmed param live in
# test_external_action_schemas.py to avoid circular-import poisoning from
# the tool_implementations imports in TestAppApiGuard above.
