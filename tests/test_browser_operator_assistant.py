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
    assert "Page inventory" in text
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

    desc, result = await te.execute_tool_block(
        block, owner="bujar", session_id="browser-session-1"
    )

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

    desc, result = await te.execute_tool_block(block, owner="bujar", session_id="browser-session-1")

    assert desc == "mcp: mcp__builtin_browser__browser_click"
    assert result["pending_confirmation"] is True
    assert result["confirmation_required"] is True
    assert result["tool_name"] == "mcp__builtin_browser__browser_click"
    assert result["action_name"] == "browser_click"
    assert result["target"] == "Buy now"
    assert result["high_impact"] is True
    assert result["action_fingerprint"]
    assert result["preview_id"].startswith("browser-action:")
    assert fake_mcp.calls == []


@pytest.mark.asyncio
async def test_approved_browser_retry_dispatches_after_matching_preview(monkeypatch):
    import src.tool_execution as te
    from src.browser_operator import clear_browser_pending_actions

    clear_browser_pending_actions()
    fake_mcp = _FakeMcp()
    monkeypatch.setattr(te, "get_mcp_manager", lambda: fake_mcp)
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)
    preview_block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_click",
        content='{"element": "Buy now"}',
    )
    block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_click",
        content='{"element": "Buy now", "confirmed": true}',
    )

    preview_desc, preview_result = await te.execute_tool_block(
        preview_block, owner="bujar", session_id="browser-session-1"
    )
    desc, result = await te.execute_tool_block(
        block, owner="bujar", session_id="browser-session-1"
    )

    assert preview_desc == "mcp: mcp__builtin_browser__browser_click"
    assert preview_result["pending_confirmation"] is True
    assert desc == "mcp: mcp__builtin_browser__browser_click"
    assert "pending_confirmation" not in result
    assert fake_mcp.calls == [("mcp__builtin_browser__browser_click", {"element": "Buy now"})]


@pytest.mark.asyncio
async def test_confirmed_browser_action_without_prior_preview_fails_closed(monkeypatch):
    import src.tool_execution as te
    from src.browser_operator import clear_browser_pending_actions

    clear_browser_pending_actions()
    fake_mcp = _FakeMcp()
    monkeypatch.setattr(te, "get_mcp_manager", lambda: fake_mcp)
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)
    block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_click",
        content='{"element": "Delete account", "confirmed": true}',
    )

    _desc, result = await te.execute_tool_block(block, owner="bujar", session_id="browser-session-2")

    assert result["pending_confirmation"] is True
    assert "No matching pending browser approval" in result["approval_instruction"]
    assert fake_mcp.calls == []


@pytest.mark.asyncio
async def test_confirmed_browser_action_with_changed_args_is_blocked(monkeypatch):
    import src.tool_execution as te
    from src.browser_operator import clear_browser_pending_actions

    clear_browser_pending_actions()
    fake_mcp = _FakeMcp()
    monkeypatch.setattr(te, "get_mcp_manager", lambda: fake_mcp)
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)

    preview_block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_click",
        content='{"element": "Buy now"}',
    )
    changed_block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_click",
        content='{"element": "Buy later", "confirmed": true}',
    )

    _preview_desc, preview = await te.execute_tool_block(
        preview_block, owner="bujar", session_id="browser-session-3"
    )
    _changed_desc, changed = await te.execute_tool_block(
        changed_block, owner="bujar", session_id="browser-session-3"
    )

    assert changed["pending_confirmation"] is True
    assert changed["action_fingerprint"] != preview["action_fingerprint"]
    assert "No matching pending browser approval" in changed["approval_instruction"]
    assert fake_mcp.calls == []


@pytest.mark.asyncio
async def test_confirmed_browser_action_with_changed_target_is_blocked(monkeypatch):
    import src.tool_execution as te
    from src.browser_operator import clear_browser_pending_actions

    clear_browser_pending_actions()
    fake_mcp = _FakeMcp()
    monkeypatch.setattr(te, "get_mcp_manager", lambda: fake_mcp)
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)

    preview_block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_network_request",
        content='{"method": "POST", "url": "https://shop.example.test/cart"}',
    )
    changed_block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_network_request",
        content='{"method": "POST", "url": "https://shop.example.test/payment", "confirmed": true}',
    )

    _preview_desc, preview = await te.execute_tool_block(
        preview_block, owner="bujar", session_id="browser-session-4"
    )
    _changed_desc, changed = await te.execute_tool_block(
        changed_block, owner="bujar", session_id="browser-session-4"
    )

    assert changed["pending_confirmation"] is True
    assert changed["target"] == "https://shop.example.test/payment"
    assert changed["action_fingerprint"] != preview["action_fingerprint"]
    assert fake_mcp.calls == []


def test_browser_observation_redacts_sensitive_values_and_separates_sections():
    from src.browser_operator import format_browser_observation

    text = format_browser_observation(
        "mcp__builtin_browser__browser_snapshot",
        {
            "content": (
                "Title: Checkout\n"
                "URL: https://shop.example.test\n"
                "Visible: password: hunter2 token=abc123 4111 1111 1111 1111\n"
                "Buttons: Submit payment"
            )
        },
    )

    assert "Observed page facts:" in text
    assert "Inferred next steps:" in text
    assert "Risky actions requiring approval:" in text
    assert "hunter2" not in text
    assert "abc123" not in text
    assert "4111 1111 1111 1111" not in text
    assert "[REDACTED" in text


def test_confirmation_preview_event_payload_redacts_sensitive_values():
    from src.browser_operator import confirmation_preview_for_event

    event = confirmation_preview_for_event(
        {
            "pending_confirmation": True,
            "tool_name": "mcp__builtin_browser__browser_fill_form",
            "action_name": "browser_fill_form",
            "target": "checkout form",
            "summary": "Fill password: hunter2 and token=abc123",
            "arguments_preview": {"password": "hunter2", "card_number": "4111111111111111"},
            "action_fingerprint": "abc",
            "preview_id": "browser-action:abc",
        }
    )

    rendered = str(event)
    assert event["action_fingerprint"] == "abc"
    assert event["preview_id"] == "browser-action:abc"
    assert "hunter2" not in rendered
    assert "abc123" not in rendered
    assert "4111111111111111" not in rendered


def test_snapshot_text_builds_page_inventory_visible_text_summary():
    from src.browser_operator import build_page_inventory

    inventory = build_page_inventory(
        {
            "content": (
                "Title: Example Checkout\n"
                "URL: https://shop.example.test/checkout\n"
                "Welcome to checkout. Buttons: Submit payment"
            )
        }
    )

    assert inventory["title"] == "Example Checkout"
    assert inventory["url"] == "https://shop.example.test/checkout"
    assert "Welcome to checkout" in inventory["visible_text_summary"]


def test_structured_content_extracts_links_buttons_fields_forms_and_uploads():
    from src.browser_operator import build_page_inventory

    inventory = build_page_inventory(
        {
            "content": {
                "url": "https://shop.example.test/checkout",
                "title": "Checkout",
                "text": "Review your cart before payment.",
                "links": [
                    {"text": "View cart", "href": "/cart"},
                    {"text": "Delete account", "href": "/account/delete"},
                ],
                "buttons": [
                    {"text": "Search", "type": "button"},
                    {"text": "Pay now", "type": "submit"},
                ],
                "inputs": [
                    {"label": "Email", "name": "email", "type": "email", "required": True, "value": "bujar@example.test"},
                    {"label": "Password", "name": "password", "type": "password", "required": True, "value": "hunter2"},
                    {"label": "Receipt upload", "name": "receipt", "type": "file", "accept": ".pdf,.png"},
                ],
                "forms": [
                    {
                        "id": "checkout-form",
                        "action": "/pay",
                        "fields": ["email", "password", "receipt"],
                        "submit_actions": ["Pay now"],
                    }
                ],
            }
        }
    )

    assert inventory["links"][0]["text"] == "View cart"
    assert inventory["links"][0]["classification"] == "safe"
    assert inventory["links"][1]["classification"] == "risky"
    assert inventory["buttons"][0]["classification"] == "safe"
    assert inventory["buttons"][1]["classification"] == "risky"
    assert inventory["fields"][0]["required"] == "required"
    assert inventory["fields"][1]["current_value_redacted"] == "[REDACTED]"
    assert inventory["upload_fields"][0]["accepted_types"] == ".pdf,.png"
    assert inventory["forms"][0]["id"] == "checkout-form"
    assert any(action["target"] == "Pay now" for action in inventory["risky_actions"])
    assert any(action["target"] == "Search" for action in inventory["safe_actions"])


def test_page_inventory_redacts_secret_values_everywhere():
    from src.browser_operator import build_page_inventory

    inventory = build_page_inventory(
        {
            "content": {
                "title": "Secrets",
                "text": "Token token=abc123 card 4111 1111 1111 1111",
                "fields": [
                    {"label": "API key", "name": "api_key", "value": "sk-secret"},
                    {"label": "Private message", "name": "private_message", "value": "hello quietly"},
                ],
            }
        }
    )

    rendered = str(inventory)
    assert "abc123" not in rendered
    assert "4111 1111 1111 1111" not in rendered
    assert "sk-secret" not in rendered
    assert "hello quietly" not in rendered


def test_browser_operator_output_shows_page_inventory_sections():
    from src.browser_operator import format_browser_observation

    text = format_browser_observation(
        "mcp__builtin_browser__browser_snapshot",
        {
            "content": {
                "title": "Search",
                "url": "https://example.test",
                "links": [{"text": "View help", "href": "/help"}],
                "buttons": [{"text": "Search"}],
                "fields": [{"label": "Query", "name": "q", "type": "search"}],
            }
        },
    )

    assert "Page inventory" in text
    assert "Detected links:" in text
    assert "Detected buttons:" in text
    assert "Detected fields:" in text
    assert "Safe actions:" in text
    assert "Risky actions requiring approval:" in text
    assert "Unknowns/questions for the user:" in text
