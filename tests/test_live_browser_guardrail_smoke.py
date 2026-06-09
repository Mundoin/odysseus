"""
Live/local smoke harness for browser/MCP external-action guardrails.

Three test categories (spec: odysseus-live-browser-guardrail-smoke-harness-v1):

  TestSmokeGuardUnit
      Pure guard_mcp / classify_mcp_tool unit tests for each of the 7 required
      fake-page action types (submit, send, upload, buy, cancel, delete, settings).

  TestSmokeMcpDispatch
      Exercises the 4-line dispatch sequence mirrored from
      src/tool_execution.py execute_tool_block's mcp__ branch.
      The mock call_tool counter proves the guard fires before MCP dispatch.

  TestSmokeLiveLocal
      Starts a real local HTTP server (no Playwright required) and wires the
      mock call_tool to POST to it so the server-side counter increments only
      when the guard allows execution.

Related test files:
  tests/test_mcp_dispatch_guards.py  — full classify_mcp_tool / guard_mcp unit suite
  tests/test_external_action_guards.py — api_call / app_api guard integration
"""
from __future__ import annotations

import json
import threading
import http.server
from typing import Any
from unittest.mock import AsyncMock

import pytest
import httpx

pytestmark = [pytest.mark.area_security, pytest.mark.sub_live_browser_smoke]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _dispatch(tool: str, args: dict, mock_call_tool) -> dict:
    """
    Mirrors the mcp__ dispatch block in src/tool_execution.py:

        _confirmed = bool(args.pop("confirmed", False))
        _block = _ext_guard_mcp(tool, args, _confirmed)
        if _block is not None:
            result = _block
        else:
            result = await mcp.call_tool(tool, args)

    Uses the real guard_mcp function. Only mock_call_tool is substituted.
    """
    from src.external_action_guard import guard_mcp

    _args = dict(args)
    _confirmed = bool(_args.pop("confirmed", False))
    _block = guard_mcp(tool, _args, _confirmed)
    if _block is not None:
        return _block
    return await mock_call_tool(tool, _args)


# ---------------------------------------------------------------------------
# Local HTTP server fixture
# ---------------------------------------------------------------------------

class _SmokeHandler(http.server.BaseHTTPRequestHandler):
    _counter: int = 0
    _html: bytes = b""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self._html)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)  # consume body
        _SmokeHandler._counter += 1
        body = json.dumps({"counter": _SmokeHandler._counter, "action": "executed"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:  # suppress server output
        pass


@pytest.fixture()
def smoke_server():
    """Start a local HTTP server; yield {url, handler}; shutdown on teardown."""
    html_path = (
        __import__("pathlib").Path(__file__).parent / "fixtures" / "smoke_page.html"
    )
    _SmokeHandler._html = html_path.read_bytes() if html_path.exists() else b"<html>smoke</html>"
    _SmokeHandler._counter = 0

    server = http.server.HTTPServer(("127.0.0.1", 0), _SmokeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield {"url": f"http://127.0.0.1:{port}", "handler": _SmokeHandler}
    server.shutdown()


# ---------------------------------------------------------------------------
# 1. Guard unit tests for the 7 smoke-page action types
# ---------------------------------------------------------------------------

class TestSmokeGuardUnit:
    """Pure guard_mcp unit tests for every fake-page action category."""

    def test_submit_form_click_is_blocked(self):
        from src.external_action_guard import guard_mcp
        r = guard_mcp("mcp__playwright__browser_click", {"element": "Submit form"}, confirmed=False)
        assert r is not None and r["pending_confirmation"] is True

    def test_send_message_click_is_blocked(self):
        from src.external_action_guard import guard_mcp
        r = guard_mcp("mcp__playwright__browser_click", {"element": "Send message"}, confirmed=False)
        assert r is not None and r["pending_confirmation"] is True

    def test_upload_document_is_high_impact(self):
        from src.external_action_guard import guard_mcp
        r = guard_mcp("mcp__playwright__browser_file_upload", {"paths": ["/tmp/doc.pdf"]}, confirmed=False)
        assert r is not None
        assert r["action_type"] == "high_impact_external_write"

    def test_buy_order_pay_click_is_high_impact(self):
        from src.external_action_guard import guard_mcp
        r = guard_mcp("mcp__playwright__browser_click", {"element": "Buy / Order / Pay"}, confirmed=False)
        assert r is not None
        assert r["action_type"] == "high_impact_external_write"

    def test_cancel_refund_return_click_is_high_impact(self):
        from src.external_action_guard import guard_mcp
        r = guard_mcp("mcp__playwright__browser_click", {"element": "Cancel / Refund / Return"}, confirmed=False)
        assert r is not None
        assert r["action_type"] == "high_impact_external_write"

    def test_delete_account_click_is_high_impact(self):
        from src.external_action_guard import guard_mcp
        r = guard_mcp("mcp__playwright__browser_click", {"element": "Delete account"}, confirmed=False)
        assert r is not None
        assert r["action_type"] == "high_impact_external_write"

    def test_change_settings_security_payment_click_is_blocked(self):
        from src.external_action_guard import guard_mcp
        # "payment" matches high-impact keyword
        r = guard_mcp("mcp__playwright__browser_click", {"element": "Change settings / security / payment"}, confirmed=False)
        assert r is not None and r["pending_confirmation"] is True

    def test_read_settings_snapshot_is_allowed(self):
        from src.external_action_guard import guard_mcp
        assert guard_mcp("mcp__playwright__browser_snapshot", {}, confirmed=False) is None

    def test_navigate_to_page_is_allowed(self):
        from src.external_action_guard import guard_mcp
        assert guard_mcp("mcp__playwright__browser_navigate", {"url": "http://127.0.0.1:9999/"}, confirmed=False) is None

    def test_screenshot_is_allowed(self):
        from src.external_action_guard import guard_mcp
        assert guard_mcp("mcp__playwright__browser_take_screenshot", {}, confirmed=False) is None


# ---------------------------------------------------------------------------
# 2. MCP dispatch sequence tests
# ---------------------------------------------------------------------------

class TestSmokeMcpDispatch:
    """
    Verifies the mcp__ dispatch sequence (guard → MCP call_tool).
    mock_call_tool.call_count acts as the action counter:
      - blocked: count == 0
      - allowed: count == 1
    """

    @pytest.mark.asyncio
    async def test_read_only_snapshot_dispatches(self):
        mock = AsyncMock(return_value={"content": "snapshot"})
        result = await _dispatch("mcp__playwright__browser_snapshot", {}, mock)
        mock.assert_awaited_once()
        assert "pending_confirmation" not in result

    @pytest.mark.asyncio
    async def test_navigate_dispatches(self):
        mock = AsyncMock(return_value={"content": "navigated"})
        result = await _dispatch("mcp__playwright__browser_navigate", {"url": "http://localhost/"}, mock)
        mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_risky_click_blocked_counter_zero(self):
        mock = AsyncMock(return_value={"content": "clicked"})
        result = await _dispatch("mcp__playwright__browser_click", {"element": "Submit form"}, mock)
        assert mock.call_count == 0
        assert result["pending_confirmation"] is True

    @pytest.mark.asyncio
    async def test_buy_click_blocked_counter_zero(self):
        mock = AsyncMock(return_value={"content": "clicked"})
        result = await _dispatch("mcp__playwright__browser_click", {"element": "Buy / Order / Pay"}, mock)
        assert mock.call_count == 0
        assert result["action_type"] == "high_impact_external_write"

    @pytest.mark.asyncio
    async def test_file_upload_blocked_counter_zero(self):
        mock = AsyncMock(return_value={"content": "uploaded"})
        result = await _dispatch("mcp__playwright__browser_file_upload", {"paths": ["/tmp/x.pdf"]}, mock)
        assert mock.call_count == 0
        assert result["pending_confirmation"] is True

    @pytest.mark.asyncio
    async def test_risky_click_confirmed_counter_one(self):
        mock = AsyncMock(return_value={"content": "clicked"})
        result = await _dispatch(
            "mcp__playwright__browser_click",
            {"element": "Submit form", "confirmed": True},
            mock,
        )
        assert mock.call_count == 1
        assert "pending_confirmation" not in result

    @pytest.mark.asyncio
    async def test_file_upload_confirmed_counter_one(self):
        mock = AsyncMock(return_value={"content": "uploaded"})
        result = await _dispatch(
            "mcp__playwright__browser_file_upload",
            {"paths": ["/tmp/x.pdf"], "confirmed": True},
            mock,
        )
        assert mock.call_count == 1

    @pytest.mark.asyncio
    async def test_confirmed_stripped_before_mcp_call(self):
        """confirmed must not appear in args forwarded to call_tool."""
        captured: list[dict] = []

        async def _capture(tool, args):
            captured.append(dict(args))
            return {"content": "ok"}

        await _dispatch(
            "mcp__playwright__browser_click",
            {"element": "Submit form", "confirmed": True},
            _capture,
        )
        assert captured, "call_tool was never called"
        assert "confirmed" not in captured[0]


# ---------------------------------------------------------------------------
# 3. Live/local smoke harness (real HTTP server)
# ---------------------------------------------------------------------------

class TestSmokeLiveLocal:
    """
    Wire mock call_tool to the local HTTP server so the server-side counter
    increments only when the guard allows execution.
    """

    @pytest.mark.asyncio
    async def test_blocked_action_leaves_counter_at_zero(self, smoke_server):
        handler = smoke_server["handler"]
        handler._counter = 0
        url = smoke_server["url"]

        async def _mcp_call_tool(tool, args):
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{url}/action", content=json.dumps(args))
            return {"content": resp.text}

        # Guard should block — server never receives the POST
        result = await _dispatch(
            "mcp__playwright__browser_click",
            {"element": "Delete account"},
            _mcp_call_tool,
        )

        assert result["pending_confirmation"] is True
        assert handler._counter == 0

    @pytest.mark.asyncio
    async def test_confirmed_action_increments_counter(self, smoke_server):
        handler = smoke_server["handler"]
        handler._counter = 0
        url = smoke_server["url"]

        async def _mcp_call_tool(tool, args):
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{url}/action", content=json.dumps(args))
            return {"content": resp.text}

        result = await _dispatch(
            "mcp__playwright__browser_click",
            {"element": "Delete account", "confirmed": True},
            _mcp_call_tool,
        )

        assert "pending_confirmation" not in result
        assert handler._counter == 1

    @pytest.mark.asyncio
    async def test_multiple_blocked_actions_counter_still_zero(self, smoke_server):
        handler = smoke_server["handler"]
        handler._counter = 0
        url = smoke_server["url"]

        async def _mcp_call_tool(tool, args):
            async with httpx.AsyncClient() as client:
                await client.post(f"{url}/action", content=json.dumps(args))
            return {"content": "ok"}

        for element in ("Submit form", "Buy / Order / Pay", "Cancel subscription"):
            await _dispatch("mcp__playwright__browser_click", {"element": element}, _mcp_call_tool)

        assert handler._counter == 0

    @pytest.mark.asyncio
    async def test_read_only_navigate_does_not_hit_counter(self, smoke_server):
        handler = smoke_server["handler"]
        handler._counter = 0
        url = smoke_server["url"]

        async def _mcp_call_tool(tool, args):
            # navigate: guard allows it, but navigate goes to GET /, not POST
            async with httpx.AsyncClient() as client:
                await client.get(f"{url}/")
            return {"content": "navigated"}

        await _dispatch(
            "mcp__playwright__browser_navigate",
            {"url": f"{url}/"},
            _mcp_call_tool,
        )

        assert handler._counter == 0  # GET does not increment server counter

    @pytest.mark.asyncio
    async def test_page_html_served_by_smoke_server(self, smoke_server):
        url = smoke_server["url"]
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{url}/")
        assert resp.status_code == 200
        assert b"Guardrail Smoke Harness" in resp.content

    @pytest.mark.asyncio
    async def test_post_increments_server_counter_directly(self, smoke_server):
        handler = smoke_server["handler"]
        handler._counter = 0
        url = smoke_server["url"]

        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{url}/action", content=b"{}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["counter"] == 1
        assert handler._counter == 1
