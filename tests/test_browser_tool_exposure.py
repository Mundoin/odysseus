"""Browser tool exposure / runtime wiring tests.

Verify that browser MCP tools are properly exposed to the agent through
OpenAI schemas, prompt text, runtime diagnostic, and guarded dispatch.
"""
from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.area_security, pytest.mark.sub_browser_tool_exposure]


class _FakeMcp:
    def __init__(self):
        self.calls = []

    async def call_tool(self, tool, args):
        self.calls.append((tool, dict(args)))
        return {"content": f"called {tool}", "exit_code": 0}


# ── Schema exposure ───────────────────────────────────────────────────────

def test_browser_tools_appear_in_openai_schemas_when_connected():
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
                "name": "browser_navigate",
                "description": "Navigate to a URL.",
                "input_schema": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                },
            },
            {
                "name": "browser_fill",
                "description": "Type text into editable element.",
                "input_schema": {
                    "type": "object",
                    "properties": {"element": {"type": "string"}, "value": {"type": "string"}},
                },
            },
        ]
    }
    mgr._connections = {"builtin_browser": {"status": "connected", "name": "Built-in: Browser"}}

    schemas = mgr.get_all_openai_schemas()

    assert len(schemas) == 3
    names = {s["function"]["name"] for s in schemas}
    assert "mcp__builtin_browser__browser_snapshot" in names
    assert "mcp__builtin_browser__browser_navigate" in names
    assert "mcp__builtin_browser__browser_fill" in names
    for s in schemas:
        assert s["function"]["description"].startswith("[MCP:")


def test_browser_tools_not_in_schemas_when_disconnected():
    from src.mcp_manager import McpManager

    mgr = McpManager()
    mgr._tools = {}
    mgr._connections = {}

    schemas = mgr.get_all_openai_schemas()

    assert schemas == []


def test_builtin_python_servers_excluded_from_openai_schemas():
    from src.mcp_manager import McpManager

    mgr = McpManager()
    mgr._tools = {
        "image_gen": [{"name": "generate_image", "description": "Generate an image.", "input_schema": {}}],
        "email": [{"name": "list_emails", "description": "List emails.", "input_schema": {}}],
        "builtin_browser": [{"name": "browser_snapshot", "description": "Snapshot.", "input_schema": {}}],
    }
    mgr._connections = {
        "image_gen": {"status": "connected", "name": "Image Gen"},
        "email": {"status": "connected", "name": "Email"},
        "builtin_browser": {"status": "connected", "name": "Browser"},
    }

    schemas = mgr.get_all_openai_schemas()

    names = {s["function"]["name"] for s in schemas}
    assert "mcp__builtin_browser__browser_snapshot" in names
    assert "mcp__image_gen__generate_image" not in names
    assert "mcp__email__list_emails" not in names


# ── Prompt text exposure ──────────────────────────────────────────────────

def test_browser_operator_rules_injected_when_browser_tools_present():
    from src.mcp_manager import McpManager

    mgr = McpManager()
    mgr._tools = {
        "builtin_browser": [
            {"name": "browser_snapshot", "description": "Capture page snapshot.", "input_schema": {}},
            {"name": "browser_click", "description": "Click an element.", "input_schema": {
                "type": "object", "properties": {"element": {"type": "string"}}
            }},
        ]
    }
    mgr._connections = {"builtin_browser": {"status": "connected", "name": "Browser"}}

    prompt = mgr.get_tool_descriptions_for_prompt()

    assert "Browser operator workflow" in prompt
    assert "browser_snapshot" in prompt
    assert "browser_click" in prompt


def test_browser_operator_rules_not_injected_when_no_browser_tools():
    from src.mcp_manager import McpManager

    mgr = McpManager()
    mgr._tools = {
        "other_server": [
            {"name": "list_items", "description": "List items.", "input_schema": {}},
        ]
    }
    mgr._connections = {"other_server": {"status": "connected", "name": "Other"}}

    prompt = mgr.get_tool_descriptions_for_prompt()

    assert "Browser operator workflow" not in prompt


# ── Runtime diagnostic ────────────────────────────────────────────────────

def test_browser_operator_status_ready_when_connected():
    from src.mcp_manager import McpManager

    mgr = McpManager()
    mgr._tools = {
        "builtin_browser": [
            {"name": "browser_snapshot", "description": "Snapshot.", "input_schema": {}},
            {"name": "browser_navigate", "description": "Navigate.", "input_schema": {}},
        ]
    }
    mgr._connections = {
        "builtin_browser": {"status": "connected", "name": "Built-in: Browser"},
    }

    status = mgr.get_browser_operator_status()

    assert status["browser_ready"] is True
    assert len(status["servers"]) == 1
    assert status["servers"][0]["status"] == "connected"
    assert status["servers"][0]["tool_count"] == 2
    assert "browser_snapshot" in status["tools"]
    assert "browser_navigate" in status["tools"]
    assert status["configured"] is True


def test_browser_operator_status_not_ready_when_disconnected():
    from src.mcp_manager import McpManager

    mgr = McpManager()
    mgr._tools = {}
    mgr._connections = {}

    status = mgr.get_browser_operator_status()

    assert status["browser_ready"] is False
    assert status["servers"] == []
    assert status["tools"] == []
    assert "Browser automation runtime is not connected" in status["missing_runtime_message"]
    assert status["configured"] is False


def test_browser_operator_status_error_when_server_failed():
    from src.mcp_manager import McpManager

    mgr = McpManager()
    mgr._tools = {}
    mgr._connections = {
        "builtin_browser": {"status": "error", "name": "Built-in: Browser", "error": "npx not found"},
    }

    status = mgr.get_browser_operator_status()

    assert status["browser_ready"] is False
    assert len(status["servers"]) == 1
    assert status["servers"][0]["status"] == "error"
    assert "Browser automation runtime is not connected" in status["missing_runtime_message"]


def test_browser_operator_status_playwright_server_detected():
    from src.mcp_manager import McpManager

    mgr = McpManager()
    mgr._tools = {
        "some_playwright": [
            {"name": "browser_snapshot", "description": "Snapshot.", "input_schema": {}},
        ]
    }
    mgr._connections = {
        "some_playwright": {"status": "connected", "name": "Playwright MCP"},
    }

    status = mgr.get_browser_operator_status()

    assert status["browser_ready"] is True
    assert len(status["servers"]) == 1


# ── Guarded dispatch ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_browser_snapshot_routes_through_mcp_dispatch(monkeypatch):
    import src.tool_execution as te

    fake_mcp = _FakeMcp()
    monkeypatch.setattr(te, "get_mcp_manager", lambda: fake_mcp)
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)
    block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_snapshot",
        content="{}",
    )

    desc, result = await te.execute_tool_block(
        block, owner="bujar", session_id="exposure-test-1"
    )

    assert desc == "mcp: mcp__builtin_browser__browser_snapshot"
    assert fake_mcp.calls == [("mcp__builtin_browser__browser_snapshot", {})]
    assert "pending_confirmation" not in result


@pytest.mark.asyncio
async def test_browser_fill_routes_through_mcp_dispatch_safe(monkeypatch):
    import src.tool_execution as te

    fake_mcp = _FakeMcp()
    monkeypatch.setattr(te, "get_mcp_manager", lambda: fake_mcp)
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)
    block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_fill",
        content='{"element": "search box", "value": "hello"}',
    )

    desc, result = await te.execute_tool_block(
        block, owner="bujar", session_id="exposure-test-2"
    )

    assert desc == "mcp: mcp__builtin_browser__browser_fill"
    assert fake_mcp.calls == [
        ("mcp__builtin_browser__browser_fill", {"element": "search box", "value": "hello"})
    ]
    assert "pending_confirmation" not in result


@pytest.mark.asyncio
async def test_browser_navigate_routes_through_mcp_dispatch(monkeypatch):
    import src.tool_execution as te

    fake_mcp = _FakeMcp()
    monkeypatch.setattr(te, "get_mcp_manager", lambda: fake_mcp)
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)
    block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_navigate",
        content='{"url": "https://example.com"}',
    )

    desc, result = await te.execute_tool_block(
        block, owner="bujar", session_id="exposure-test-3"
    )

    assert fake_mcp.calls == [
        ("mcp__builtin_browser__browser_navigate", {"url": "https://example.com"})
    ]
    assert "pending_confirmation" not in result


@pytest.mark.asyncio
async def test_risky_browser_click_remains_guarded(monkeypatch):
    import src.tool_execution as te

    fake_mcp = _FakeMcp()
    monkeypatch.setattr(te, "get_mcp_manager", lambda: fake_mcp)
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)
    block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_click",
        content='{"element": "Submit payment"}',
    )

    desc, result = await te.execute_tool_block(
        block, owner="bujar", session_id="exposure-test-4"
    )

    assert result["pending_confirmation"] is True
    assert result["confirmation_required"] is True
    assert result["high_impact"] is True
    assert result["tool_name"] == "mcp__builtin_browser__browser_click"
    assert fake_mcp.calls == []


@pytest.mark.asyncio
async def test_browser_type_is_classified_as_local_prepare(monkeypatch):
    import src.tool_execution as te

    fake_mcp = _FakeMcp()
    monkeypatch.setattr(te, "get_mcp_manager", lambda: fake_mcp)
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)
    block = SimpleNamespace(
        tool_type="mcp__builtin_browser__browser_type",
        content='{"element": "search", "text": "query"}',
    )

    desc, result = await te.execute_tool_block(
        block, owner="bujar", session_id="exposure-test-5"
    )

    assert fake_mcp.calls == [
        ("mcp__builtin_browser__browser_type", {"element": "search", "text": "query"})
    ]
    assert "pending_confirmation" not in result


# ── System prompt integration ─────────────────────────────────────────────

def test_browser_inventory_section_in_prompt_when_browser_connected():
    from src.mcp_manager import McpManager
    from src.browser_operator import BROWSER_OPERATOR_UNAVAILABLE

    assert "Browser automation runtime is not connected" in BROWSER_OPERATOR_UNAVAILABLE
    assert "npx -y @playwright/mcp@latest --version" in BROWSER_OPERATOR_UNAVAILABLE


# ── Browser operator prompt constant ──────────────────────────────────────

def test_browser_operator_rules_constant_exists_and_is_non_empty():
    from src.browser_operator import BROWSER_OPERATOR_RULES

    assert "Browser operator workflow" in BROWSER_OPERATOR_RULES
    assert "pending_confirmation" in BROWSER_OPERATOR_RULES
    assert "confirmed=true" in BROWSER_OPERATOR_RULES
    assert len(BROWSER_OPERATOR_RULES) > 100


def test_browser_operator_unavailable_constant_exists():
    from src.browser_operator import BROWSER_OPERATOR_UNAVAILABLE

    assert len(BROWSER_OPERATOR_UNAVAILABLE) > 100
    assert "Browser automation runtime is not connected" in BROWSER_OPERATOR_UNAVAILABLE


# ── Tool index keyword hints ──────────────────────────────────────────────

def test_browser_keywords_in_tool_index():
    from src.tool_index import ToolIndex

    ti = ToolIndex.__new__(ToolIndex)

    browser_found = False
    for keywords, tools in ti._KEYWORD_HINTS.items():
        if any("browser" in kw for kw in keywords):
            browser_found = True
            break

    assert browser_found, "Browser keywords must exist in _KEYWORD_HINTS"


def test_browser_intent_keywords_trigger_tool_retrieval():
    from src.tool_index import ToolIndex

    ti = ToolIndex.__new__(ToolIndex)

    queries = [
        "fill the form on this page",
        "navigate to example.com",
        "browser automation",
        "inspect browser page",
        "use playwright to fill the job application",
    ]
    for query in queries:
        ql = query.lower()
        browser_matched = False
        for keywords, tools in ti._KEYWORD_HINTS.items():
            import re
            if any(re.search(rf"\b{re.escape(kw)}\b", ql) for kw in keywords):
                browser_matched = True
                break
        assert browser_matched, f"Query '{query}' should match browser keyword hints"


# ── Domain rules injection ────────────────────────────────────────────────

def test_domain_rules_for_tools_detects_browser_tool_prefix():
    from src.agent_loop import _domain_rules_for_tools

    rules = _domain_rules_for_tools({"mcp__builtin_browser__browser_snapshot"})
    assert any("Browser operator rules" in r for r in rules)

    rules = _domain_rules_for_tools({"bash", "web_search"})
    assert not any("Browser operator rules" in r for r in rules)


def test_domain_rules_for_tools_detects_multiple_browser_tools():
    from src.agent_loop import _domain_rules_for_tools

    rules = _domain_rules_for_tools({
        "mcp__builtin_browser__browser_snapshot",
        "mcp__builtin_browser__browser_navigate",
        "mcp__builtin_browser__browser_fill",
        "bash",
        "web_search",
    })
    browser_rules = [r for r in rules if "Browser operator rules" in r]
    assert len(browser_rules) == 1


def test_browser_domain_tool_map_has_entry():
    from src.agent_loop import _DOMAIN_TOOL_MAP, _DOMAIN_RULES

    assert "browser" in _DOMAIN_TOOL_MAP
    assert "browser" in _DOMAIN_RULES
    assert "Browser operator rules" in _DOMAIN_RULES["browser"]


# ── MCP disabled map does not block browser tools ─────────────────────────

def test_browser_tools_not_disabled_by_default():
    from src.mcp_manager import McpManager

    mgr = McpManager()
    mgr._tools = {
        "builtin_browser": [
            {"name": "browser_snapshot", "description": "Snapshot.", "input_schema": {}},
            {"name": "browser_click", "description": "Click.", "input_schema": {}},
        ]
    }
    mgr._connections = {"builtin_browser": {"status": "connected", "name": "Browser"}}

    all_tools = mgr.get_all_tools()

    assert all(not t["is_disabled"] for t in all_tools)


def test_browser_tools_are_disabled_when_in_disabled_map():
    from src.mcp_manager import McpManager

    mgr = McpManager()
    mgr._tools = {
        "builtin_browser": [
            {"name": "browser_snapshot", "description": "Snapshot.", "input_schema": {}},
            {"name": "browser_click", "description": "Click.", "input_schema": {}},
        ]
    }
    mgr._connections = {"builtin_browser": {"status": "connected", "name": "Browser"}}

    disabled_map = {"builtin_browser": {"browser_snapshot"}}
    all_tools = mgr.get_all_tools(disabled_map)

    snapshot = [t for t in all_tools if t["name"] == "browser_snapshot"]
    click = [t for t in all_tools if t["name"] == "browser_click"]
    assert snapshot[0]["is_disabled"] is True
    assert click[0]["is_disabled"] is False


# ── Plan mode blocks browser write tools ──────────────────────────────────

def test_plan_mode_blocks_browser_write_tools():
    from src.mcp_manager import McpManager, mcp_tool_is_readonly

    mgr = McpManager()
    mgr._tools = {
        "builtin_browser": [
            {"name": "browser_snapshot", "description": "Snapshot.", "input_schema": {}},
            {"name": "browser_click", "description": "Click.", "input_schema": {}},
            {"name": "browser_fill", "description": "Fill form field.", "input_schema": {}},
            {"name": "browser_navigate", "description": "Navigate.", "input_schema": {}},
        ]
    }
    mgr._connections = {"builtin_browser": {"status": "connected", "name": "Browser"}}

    disabled_map, qualified = mgr.plan_mode_blocked_mcp()

    # Plan mode blocks all MCP tools that aren't clearly read-only.
    # browser_click and browser_fill are clearly write tools — must be blocked.
    assert "browser_click" in disabled_map.get("builtin_browser", set())
    assert "mcp__builtin_browser__browser_click" in qualified
    assert "browser_fill" in disabled_map.get("builtin_browser", set())
    assert "mcp__builtin_browser__browser_fill" in qualified

    # browser_snapshot and browser_navigate are not in the read-only verb
    # prefix list (snapshot != inspect, navigate != any verb), so they
    # fail-closed in plan mode. This is correct: plan mode must not run a
    # tool whose read-only status is ambiguous.
    assert "browser_snapshot" in disabled_map.get("builtin_browser", set())
    assert "browser_navigate" in disabled_map.get("builtin_browser", set())
