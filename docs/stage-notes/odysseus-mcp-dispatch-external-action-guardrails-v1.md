# Stage: odysseus-mcp-dispatch-external-action-guardrails-v1

## Policy

Browser and MCP tool invocations that cause external side-effects (clicks,
form submissions, file uploads, JS execution) require `confirmed=true` before
executing. First call without confirmation returns a `pending_confirmation`
preview. Re-call with `confirmed=true` executes.

## Dispatch paths patched

| Path | Location | Condition |
|---|---|---|
| Legacy MCP tools (in `_MCP_TOOL_MAP`) | `src/tool_execution.py:_call_mcp_tool` | Before `mcp.call_tool(qualified, args)` |
| Dynamic MCP tools (`mcp__*` prefix) | `src/tool_execution.py:execute_tool_block` | Before `mcp.call_tool(tool, args)` |

In both paths `confirmed` is popped from `args` before the guard is evaluated
and before the args dict is forwarded to the MCP server.

## Action classification — `classify_mcp_tool(tool, args)`

| Class | Tools / conditions |
|---|---|
| `safe_read` | `browser_snapshot`, `browser_take_screenshot`, `browser_navigate`, `browser_navigate_back`, `browser_wait_for`, `browser_console_messages`, `browser_network_requests`, `browser_tabs`, `browser_resize`, `browser_hover`, `browser_close`; `browser_network_request` with GET |
| `local_prepare` | `browser_type`, `browser_fill`, `browser_select_option`, `browser_drag`, `browser_drop`; `browser_press_key` with non-Enter key; `browser_handle_dialog` with dismiss |
| `external_write` | `browser_click` with neutral element text; `browser_press_key` with Enter/Return; `browser_handle_dialog` accept; `browser_network_request` POST/PUT/PATCH/DELETE to non-high-impact URL; `browser_fill_form` with neutral fields |
| `high_impact_external_write` | `browser_file_upload`, `browser_run_code_unsafe`, `browser_evaluate`; `browser_click` with element containing submit/pay/buy/order/cancel/refund/delete/checkout/…; `browser_fill_form` with high-impact field keywords |

Unknown MCP tools default to `external_write` (conservative).

## Shared helper

`src/external_action_guard.py` — extended with:

- `classify_mcp_tool(tool, args) -> str`
- `guard_mcp(tool, args, confirmed) -> dict | None`
- `_bare_mcp_tool_name(tool) -> str`
- Sets `_SAFE_MCP_TOOLS`, `_LOCAL_PREPARE_MCP_TOOLS`, `_ALWAYS_HIGH_IMPACT_MCP_TOOLS`, `_CLICK_HIGH_IMPACT_KEYWORDS`

Reuses `build_preview()` from the same module. Preview `method` field is set
to `"BROWSER_ACTION"` (no HTTP method applies to browser clicks).

## Tests

| File | Count | Covers |
|---|---|---|
| `tests/test_mcp_dispatch_guards.py` | 32 | `classify_mcp_tool` (20), `guard_mcp` (11), confirmed-strip behaviour (1) |

All 32 new tests pass. Prior 34 external-action guard tests unchanged.
Pre-existing failure count unchanged (82).

## Caveats

- `browser_click` classification is text/selector substring-based. Novel
  non-English element labels may produce false negatives.
- `browser_fill_form` field inspection stringifies the entire fields dict;
  if field values incidentally contain high-impact keywords, it will be
  escalated. This is intentionally conservative.
- `browser_evaluate` and `browser_run_code_unsafe` are unconditionally
  high-impact because arbitrary JS execution has no safe floor.
