# Stage: odysseus-browser-operator-single-action-tool-v1

Create one stable Odysseus-owned `browser_operator_safe_fill` tool so the model
never depends on low-level `browser_fill`/`browser_type` MCP tools appearing
each turn. The backend bridges to MCP internally.

## Problem

Browser navigate/snapshot worked. Page inventory worked. Form-fill plan worked.
Approval preview worked. User approved. But at execution turn, the model
reported only `manage_memory`, `ask_user`, `update_plan` — browser fill tools
were absent from the active tool schema.

The active model depended on low-level browser/MCP tools being exposed *every*
turn. That is brittle. Browser tools can disappear due to:
- Domain filtering (domain didn't fire for the approval follow-up)
- Schema filtering (tools not in `_relevant_tools`)
- Provider turn state (tool lists recalculated each turn)
- RAG tool retrieval (no embedding match for approval text)
- Approval-loop context (tool result messages in user role)

## Solution

Expose one first-class tool: **`browser_operator_safe_fill`**

The model calls this stable Odysseus tool after approval. Odysseus backend
internally:
1. Validates the approved safe-fill request
2. Uses the form-fill plan and raw known_values
3. Discovers available MCP/browser fill tools internally
4. Executes safe non-sensitive field fills
5. Requests browser snapshot
6. Verifies honestly
7. Returns a redacted report

The LLM never needs to call `browser_fill`/`browser_type` directly. Low-level
MCP browser tools remain internal.

## Changes

### New: `do_browser_operator_safe_fill` (`src/tool_implementations.py`)

- Two-phase: no `confirmed` → returns `pending_confirmation` preview with
  redacted fields, skipped, blocked_actions, fingerprint
- With `confirmed=true` and matching fingerprint → discovers MCP tools
  internally, executes fills via `execute_safe_browser_fill_batch`, verifies
  with snapshot, returns redacted report
- Missing MCP → returns exact diagnostic: `browser_fill_tool_available`,
  `browser_snapshot_available`, `mcp_server_name`, `missing_tool_names`
- Mismatched fingerprint → returns `approval_mismatch: True` with fresh preview

### Schema (`src/tool_schemas.py`)

Added `browser_operator_safe_fill` to `FUNCTION_TOOL_SCHEMAS` with parameters:
`page_url` (required), `known_values` (required), `form_fill_plan` (optional),
`fields_to_fill` (optional), `confirmed` (optional), `batch_size` (optional).

Also added to `function_call_to_tool_block` JSON serialization group.

### Dispatch (`src/tool_execution.py`)

Added `elif tool == "browser_operator_safe_fill"` branch calling
`do_browser_operator_safe_fill(content, owner=owner, session_id=session_id)`.

### Tool index (`src/tool_index.py`)

- Added `BUILTIN_TOOL_DESCRIPTIONS` entry
- Changed browser keyword hints from `set()` to `{"browser_operator_safe_fill"}`

### Persistent exposure (`src/agent_loop.py`)

- Browser domain detection now always adds `browser_operator_safe_fill` to
  `_relevant_tools`, regardless of MCP status
- Follow-up turn pinning also adds `browser_operator_safe_fill`

## Tests (`tests/test_browser_operator_safe_fill.py`)

| Test | What it proves |
|---|---|
| `test_schema_included_in_function_tool_schemas` | Schema registered |
| `test_schema_has_required_parameters` | Required params correct |
| `test_tool_description_in_index` | Description in BUILTIN_TOOL_DESCRIPTIONS |
| `test_keyword_hint_includes_tool` | Browser keywords map to the tool |
| `test_first_call_without_confirmed_returns_pending` | Preview with fingerprint |
| `test_call_without_known_values_fails` | Empty values rejected |
| `test_raw_values_not_in_preview_output` | No secrets in output |
| `test_confirmed_without_pending_returns_mismatch` | Mismatch detected |
| `test_missing_mcp_returns_exact_diagnostic` | Missing backend diagnostic |
| `test_low_level_browser_fill_not_needed` | fill tool not in preview |
| `test_same_fingerprint_does_not_reask` | Approval idempotent |
| `test_execution_with_mocked_mcp` | Full preview→confirmed flow |

## Validation

All 7 test suites: 187+ tests.

## Manual Smoke

1. Restart Odysseus:
   ```
   python -m uvicorn app:app --host 127.0.0.1 --port 7000
   ```
2. Serve smoke form in another terminal:
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

   Fill only safe non-sensitive text fields if supported. Do not fill password
   fields. Do not upload files. Do not submit or apply. Stop and report.
   ```
4. Expected:
   - It may ask one approval for safe fill
   - After approval, it calls `browser_operator_safe_fill`
   - Safe fields fill, password empty, upload empty, apply not clicked
   - Verification snapshot runs
   - Does NOT say "browser fill tools unavailable"
   - Does NOT ask for approval repeatedly

## Hard Boundaries

- ✅ Safe fill execution happens in backend logic, not dependent on LLM seeing low-level tools
- ✅ Password/upload/submit/apply blocked
- ✅ Raw values used only for immediate dispatch, never persisted
- ✅ Verification unknown is not success
- ✅ No remotes changed
- ✅ No upstream PR material
