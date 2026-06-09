# Stage: odysseus-browser-fill-tool-exposure-and-execution-fix-v1

Fix browser fill tool exposure so `browser_fill`/`browser_type`/`browser_select_option`
are available as function-call schemas after domain detection fires and after the
user approves a safe fill plan.

## Root Cause: 3-Part Pipeline Failure for Fill Tools

### Part 1 — Follow-up pinning checked only assistant role messages

The previous fix (`browser-tool-pinning-runtime-fix-v1`) added follow-up turn
pinning but only scanned `msg.get("role") == "assistant"` messages. Tool execution
results are injected as `role="user"` messages after the assistant calls tools.
When the user approved a fill plan and the agent tried to execute, the previous
browser tool call appeared in a user-role message (e.g.
`"[Tool execution results]\nmcp__builtin_browser__browser_navigate OK"`).
The follow-up pin missed these, so `_relevant_tools` had no browser tool names,
the schema filter dropped all browser schemas, and the agent said "I don't have
browser fill tools."

**Fix:** Changed the follow-up pin to scan all messages (both assistant and user
roles) for `browser_` or `mcp__builtin_browser__` content. The scan now finds
tool execution result messages and correctly re-pins browser tools.

### Part 2 — No explicit fill-workflow guidance in domain rules

The `_DOMAIN_RULES["browser"]` prompt section told the model to inspect pages
and required confirmation for risky actions, but gave no guidance on what to do
after a fill plan is approved. The model kept re-asking for approval instead of
executing fills.

**Fix:** Added explicit rules: "after the user explicitly approves a fill plan,
execute fills using the available fill/type/select tools. Do NOT ask for approval
again for the same approved fill batch." Also added batching guidance and a
requirement to name specific missing tool names rather than saying "browser
tools unavailable."

### Part 3 — Browser runtime diagnostic lumped all tools together

The system prompt diagnostic said "Exposed browser tools (X): ..." without
distinguishing read tools (snapshot, navigate) from fill tools (fill, type,
select_option). When fill tools were present, the model didn't know they were
specifically for form filling.

**Fix:** The diagnostic now separates tools into:
- General tool list (all browser tools)
- Fill/type tools available (with explicit names and usage guidance)
- Missing fill tools diagnostic when they're not present

### Part 4 — Safe fill bridge hardcoded tool names

`build_safe_browser_fill_calls` and `execute_safe_browser_fill_batch` defaulted
to `mcp__builtin_browser__browser_fill` and `mcp__builtin_browser__browser_snapshot`.
If the actual Playwright MCP server exposed tools with different qualified names
(e.g., from a differently-named server), the bridge would call non-existent tools.

**Fix:** Added `_discover_browser_tool()` helper that queries `mcp_mgr.get_all_tools()`
and finds the first candidate tool name by bare name matching. Both bridge functions
now auto-discover tool names when an `mcp_mgr` parameter is provided, falling back
to the built-in defaults.

### Part 5 — _MCP_KEYWORDS used raw substring matching

For local/fenced-block models, the `_MCP_KEYWORDS` check used raw substring
matching (`any(kw in _last_content for kw in _MCP_KEYWORDS)`). Short keywords
like `"fill"` would false-positive on words like `"fulfill"`, `"refill"`, etc.

**Fix:** Changed to word-boundary regex matching:
`any(re.search(rf"\b{re.escape(kw)}\b", _last_content) for kw in _MCP_KEYWORDS)`

## Changes

### `src/agent_loop.py`

1. **`_DOMAIN_RULES["browser"]`** (line 272): Added 4 new rules:
   - Execute fills after explicit approval (no re-ask)
   - Batch safe fills 2-3 at a time, verify with snapshot
   - Name specific missing tool names in diagnostics
   - Full batching workflow guidance

2. **Browser runtime diagnostic** (line 1377): Now breaks tools into read_tools
   and fill_tools lists, with different guidance text depending on whether
   fill/type/select tools are available.

3. **Follow-up turn pinning** (line 1941): Changed from checking only
   `role == "assistant"` to checking all messages for `browser_` or
   `mcp__builtin_browser__` content. This catches tool execution result messages
   injected as user-role content.

4. **`_MCP_KEYWORDS` word-boundary check** (line 2252): Changed from raw
   substring match to `re.search(rf"\b{re.escape(kw)}\b", ...)` so short
   keywords don't false-positive on unrelated words.

### `src/browser_operator.py`

1. **Added `_discover_browser_tool()`** helper (line 1024): Queries
   `mcp_mgr.get_all_tools()` and finds the first available candidate tool by
   bare name matching. Returns the qualified name if found, otherwise the fallback.

2. **`build_safe_browser_fill_calls()`** (line 1052): Now accepts optional
   `mcp_mgr` parameter. When provided, auto-discovers `fill_tool_name` and
   `snapshot_tool_name` from connected MCP tools. Falls back to built-in
   defaults when not provided or no MCP connected.

3. **Added `logging` import and logger** (line 9): For debug logging in tool
   discovery.

### `tests/test_browser_tool_exposure.py`

- `test_fill_tools_appear_in_openai_schemas_when_connected` — fill/type/select in schemas
- `test_followup_after_browser_tool_result_keeps_fill_tools` — user-role tool result keeps fill tools on follow-up
- `test_classify_detects_fill_plan_from_prompt` — form-fill plan triggers browser domain
- `test_classify_detects_fill_approved_followup_with_context` — follow-up with context
- `test_classify_detects_verify_after_fill` — snapshot verify triggers browser domain

### `tests/test_browser_operator_assistant.py`

- `test_fill_bridge_discover_browser_tool_names` — `_discover_browser_tool` resolves correctly
- `test_fill_bridge_uses_discovered_tool_names` — bridge uses auto-discovered names

## Validation (187 tests, 0 failures)

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_browser_tool_exposure.py -v  # 40 passed
.\venv\Scripts\python.exe -m pytest -q tests/test_browser_operator_assistant.py -v  # 35 passed
.\venv\Scripts\python.exe -m pytest -q tests/test_operator_scenario_smoke.py -v  # 4 passed
.\venv\Scripts\python.exe -m pytest -q tests/test_external_action_guards.py -v  # 27 passed
.\venv\Scripts\python.exe -m pytest -q tests/test_mcp_dispatch_guards.py -v  # 26 passed
.\venv\Scripts\python.exe -m pytest -q tests/test_live_browser_guardrail_smoke.py -v  # 24 passed
.\venv\Scripts\python.exe -m pytest -q tests/test_guard_preview_quality.py -v  # 31 passed
```

## Manual Smoke

1. Restart Odysseus:
   ```
   python -m uvicorn app:app --host 127.0.0.1 --port 7000
   ```

2. Serve local form page in another terminal:
   ```
   .\venv\Scripts\python.exe -m http.server 8765
   ```

3. Prompt:
   ```
   Open this page in the browser, then inspect it:
   http://127.0.0.1:8765/odysseus-smoke-form.html

   Build a page inventory. Then create a form-fill plan using these values:
   first_name: Bujar
   last_name: Smoke
   email: bujar.smoke@example.com
   phone: +49123456789
   city: Dortmund
   postcode: 44137
   cover_letter: Short smoke-test cover letter text.

   Fill only safe non-sensitive text fields if supported. Do not fill password fields. Do not upload files. Do not submit or apply. Stop and report what happened.
   ```

Expected:
- Browser opens local form
- Inventory detects all fields
- Safe fields are filled after approval
- Password stays empty
- Upload stays empty
- Apply is not clicked
- Snapshot verifies fields
- Agent does NOT say fill tools unavailable

## Hard Boundaries

- ✅ Risky actions (submit/upload/click) remain guarded with pending_confirmation
- ✅ No browser tools invented when runtime is missing
- ✅ No upload of files
- ✅ No submit/apply
- ✅ Password/payment/ID/tax/health fields remain blocked
- ✅ Raw values are not persisted in public output/history
- ✅ No remotes changed
- ✅ No upstream PR material created
- ✅ Fill tool discovery falls back gracefully when no MCP connected
