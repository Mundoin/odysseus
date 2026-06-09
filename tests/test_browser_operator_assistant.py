"""Browser operator assistant wiring tests.

These tests cover the production-facing bridge: browser MCP prompt guidance,
readable browser observations/confirmation previews, and MCP dispatch behavior
for safe, blocked, and approved browser actions.
"""
from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.area_security, pytest.mark.sub_browser_operator_assistant]


class _FakeMcp:
    def __init__(self):
        self.calls = []

    async def call_tool(self, tool, args):
        self.calls.append((tool, dict(args)))
        return {"content": f"called {tool}", "exit_code": 0}


def test_browser_mcp_prompt_includes_operator_workflow():
    from src.mcp_manager import McpManager

    mgr = McpManager()
    mgr._tools = {
        "builtin_browser": [
            {
                "name": "browser_snapshot",
                "description": "Capture page accessibility snapshot.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "browser_click",
                "description": "Click an element.",
                "input_schema": {
                    "type": "object",
                    "properties": {"element": {"type": "string"}},
                },
            },
        ]
    }
    mgr._connections = {"builtin_browser": {"status": "connected", "name": "Browser", "identity": ""}}

    prompt = mgr.get_tool_descriptions_for_prompt()

    assert "Browser operator workflow" in prompt
    assert "Summarize what you see" in prompt
    assert "pending_confirmation" in prompt
    assert "confirmed=true" in prompt


def test_browser_snapshot_result_formats_as_operator_observation():
    from src.tool_execution import format_tool_result

    text = format_tool_result(
        "mcp: mcp__builtin_browser__browser_snapshot",
        {
            "content": "Title: Example Checkout\nURL: https://shop.example.test\nButtons: Submit payment",
            "exit_code": 0,
        },
    )

    assert "Browser observation" in text
    assert "Example Checkout" in text
    assert "Submit payment" in text


def test_pending_confirmation_formats_as_readable_user_facing_preview():
    from src.external_action_guard import guard_mcp
    from src.tool_execution import format_tool_result

    preview = guard_mcp(
        "mcp__builtin_browser__browser_click",
        {"element": "Submit payment"},
        confirmed=False,
    )
    text = format_tool_result("mcp: mcp__builtin_browser__browser_click", preview)

    assert "Confirmation required before execution." in text
    assert "Tool/action: mcp__builtin_browser__browser_click / browser_click" in text
    assert "Target: Submit payment" in text
    assert "Consequence:" in text
    assert "confirmed=true" in text
    assert "Review checklist:" in text


@pytest.mark.asyncio
async def test_safe_browser_action_dispatches_through_execute_tool_block(monkeypatch):
    import src.tool_execution as te

    fake_mcp = _FakeMcp()
    monkeypatch.setattr(te, "get_mcp_manager", lambda: fake_mcp)
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)
    block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_snapshot",
        content="{}",
    )

    desc, result = await te.execute_tool_block(block, owner="bujar")

    assert desc == "mcp: mcp__builtin_browser__browser_snapshot"
    assert result["content"].startswith("called")
    assert fake_mcp.calls == [("mcp__builtin_browser__browser_snapshot", {})]


@pytest.mark.asyncio
async def test_risky_browser_action_returns_pending_confirmation_without_dispatch(monkeypatch):
    import src.tool_execution as te

    fake_mcp = _FakeMcp()
    monkeypatch.setattr(te, "get_mcp_manager", lambda: fake_mcp)
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)
    block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_click",
        content='{"element": "Buy now"}',
    )

    desc, result = await te.execute_tool_block(block, owner="bujar")

    assert desc == "mcp: mcp__builtin_browser__browser_click"
    assert result["pending_confirmation"] is True
    assert result["confirmation_required"] is True
    assert result["tool_name"] == "mcp__builtin_browser__browser_click"
    assert result["action_name"] == "browser_click"
    assert result["target"] == "Buy now"
    assert result["high_impact"] is True
    assert fake_mcp.calls == []


@pytest.mark.asyncio
async def test_approved_browser_retry_dispatches_with_confirmed_stripped(monkeypatch):
    import src.tool_execution as te

    fake_mcp = _FakeMcp()
    monkeypatch.setattr(te, "get_mcp_manager", lambda: fake_mcp)
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)
    block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_click",
        content='{"element": "Buy now", "confirmed": true}',
    )

    desc, result = await te.execute_tool_block(block, owner="bujar")

    assert desc == "mcp: mcp__builtin_browser__browser_click"
    assert "pending_confirmation" not in result
    assert fake_mcp.calls == [("mcp__builtin_browser__browser_click", {"element": "Buy now"})]
