# Odysseus Browser Tool Exposure Runtime (v1)

**Stage:** `odysseus-browser-tool-exposure-runtime-v1`
**Branch:** `bujar-odysseus-hardening`
**Date:** 2026-06-09

## Problem

Active Odysseus agent/model says it does not have browser automation tools available.
It only sees tools like `web_fetch`, `web_search`, and `ui_control`.
It cannot inspect the current browser page, detect fields, fill fields, or click browser controls.

## Root Cause

Three exposure gaps between the browser MCP runtime and the active agent session:

1. **No browser keyword hints in RAG tool index** (`src/tool_index.py`):
   - `_KEYWORD_HINTS` dictionary had no browser-related keywords
   - RAG-based tool selection never force-included browser tools even when user requested browsing

2. **No browser domain in agent_loop.py**:
   - `_DOMAIN_RULES` and `_DOMAIN_TOOL_MAP` had no browser domain
   - `_classify_agent_request()` never detected browser intent
   - `_domain_rules_for_tools()` could not match browser MCP tool names (they use `mcp__` prefix)

3. **No browser operator status diagnostic**:
   - No mechanism reported whether browser MCP was connected or not
   - When disconnected, agent silently pretended tools didn't exist instead of giving a clear diagnostic

The browser tools ARE properly wired in `mcp_manager.py` (schemas and prompts handle `builtin_browser` specially) and in `tool_execution.py` (guarded dispatch works). The gap was in exposure — making the agent reliably aware of the tools.

## Changes

### `src/browser_operator.py`
- Added `BROWSER_OPERATOR_UNAVAILABLE` constant with clear diagnostic message when browser runtime is missing

### `src/mcp_manager.py`
- Added `get_browser_operator_status()` method that returns:
  - `browser_ready`: bool — whether at least one browser MCP server is connected
  - `servers`: list of browser server connection info
  - `tools`: list of exposed browser-prefixed tool names
  - `missing_runtime_message`: user-facing diagnostic when disconnected
  - `configured`: bool — whether any browser server exists at all

### `src/agent_loop.py`
- Added `browser` domain rules to `_DOMAIN_RULES`
- Added `browser` entry to `_DOMAIN_TOOL_MAP`
- Added browser intent detection to `_classify_agent_request()`
- Updated `_domain_rules_for_tools()` to detect browser MCP tool names by `browser_` prefix
- Added browser operator runtime diagnostic injection to `_build_base_prompt()`:
  - When ready: "Browser automation tools are CONNECTED and available"
  - When missing: injected `BROWSER_OPERATOR_UNAVAILABLE` message

### `src/tool_index.py`
- Added 20+ browser-related keyword hints to `_KEYWORD_HINTS` for RAG retrieval

### `tests/test_browser_tool_exposure.py` (new)
- 22 focused tests covering:
  - Browser tools appear in OpenAI schemas when connected
  - Browser tools not in schemas when disconnected
  - Built-in Python servers excluded from schemas but browser included
  - Browser operator rules injected when tools present
  - Browser operator rules not injected when no tools
  - `get_browser_operator_status()` ready/not-ready/error states
  - Playwright server detection
  - Browser snapshot/fill/navigate route through guarded MCP dispatch
  - Risky browser click remains guarded
  - Browser type as local prepare (not blocked)
  - Prompt integration (unavailable constant)
  - Tool index keyword hints present and trigger retrieval
  - Domain rules for tools detect browser tool prefix
  - Browser domain tool map and rules exist
  - MCP disabled map doesn't block browser tools by default
  - Plan mode blocks browser write tools

## What Happens When Browser Runtime Is Missing

The agent now sees a clear diagnostic in its prompt:

> Browser automation runtime is not connected. Browser tools such as browser_snapshot, browser_navigate, browser_fill, and browser_click are unavailable until a browser MCP server (e.g., @playwright/mcp) is connected and running.
>
> To enable browser automation:
> 1. Ensure npx and Node.js are installed.
> 2. Cache the Playwright MCP package: npx -y @playwright/mcp@latest --version
> 3. Restart Odysseus.
> 4. Verify in Settings → MCP Servers that 'Built-in: Browser' shows as connected.

## Validation

- `.\tools\odysseus-status.ps1` — workspace status
- `.\tools\run-guard-tests.ps1` — existing guardrails still pass
- `venv\Scripts\python.exe -m pytest -q tests/test_browser_operator_assistant.py` — existing operator tests
- `venv\Scripts\python.exe -m pytest -q tests/test_operator_scenario_smoke.py` — existing scenario smoke
- `venv\Scripts\python.exe -m pytest -q tests/test_browser_tool_exposure.py` — new focused tests

## Manual Smoke

After startup with browser MCP connected:
- Agent must see browser tools in available tool list
- Agent must NOT say "I don't have browser automation tools available"
- Agent must use browser_snapshot before planning browser actions
- Browser click on risky elements must return pending_confirmation
