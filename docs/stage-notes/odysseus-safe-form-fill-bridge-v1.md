# Odysseus Safe Form Fill Bridge v1

Stage: `odysseus-safe-form-fill-bridge-v1`

This stage wires the safe form-fill executor planning layer to real browser/MCP
fill calls where a browser MCP server exposes fill tools. It does not submit
forms, upload files, send messages, pay, buy, delete, cancel, confirm, or apply.

## Existing Fill Tools

The existing MCP/browser guard model already treats these as local prepare
actions:

- `browser_fill`
- `browser_type`
- `browser_select_option`

The bridge defaults to qualified tool names:

- `mcp__builtin_browser__browser_fill`
- `mcp__builtin_browser__browser_snapshot`

Callers can pass alternate qualified tool names when a different MCP browser
server is active.

## Implemented

- `build_safe_browser_fill_calls(form_fill_plan, known_values, batch_size=3, ...)`
- `execute_safe_browser_fill_batch(mcp, batch, snapshot_tool_name=...)`
- `build_safe_fill_verification_request(snapshot_tool_name=...)`
- `merge_safe_fill_verification(execution, observation_result)`

The bridge constructs raw MCP fill payloads only for safe non-sensitive
text-like fields selected by the executor. It also creates redacted
`public_calls`/`public_batches` for logs, UI, streamed output, and history.

## Raw Value Policy

- Raw values come from `known_values` at execution time.
- Raw values are present only in `calls[].args.value` while constructing or
  dispatching MCP fill calls.
- Raw values are not included in formatted output, public call previews,
  verification reports, or stage notes.
- Reports and public previews use `value_preview_redacted`.

## Safety

The bridge skips fields that are sensitive, ambiguous, missing raw values, not
marked safe, low confidence, non-text-like, upload fields, or risky controls.
Upload/submit/apply/payment/send actions remain in approval-required blocked
actions.

Verification uses a fresh browser snapshot/observation where available. If the
redacted expected value cannot be confirmed, the result is `unknown`, not
success.

## Validation

Focused validation:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_browser_operator_assistant.py
.\venv\Scripts\python.exe -m pytest -q tests/test_operator_scenario_smoke.py
.\tools\run-guard-tests.ps1
```

Expected result: bridge, executor, planner, inventory, approval-binding,
scenario smoke, and guard tests pass with only known local warning/noise if
present.
