# Odysseus Browser Operator Hardening v2

Stage: `odysseus-browser-operator-hardening-v2`

This stage hardens the local browser operator assistant approval path without
changing the underlying MCP/browser tool schemas or loosening existing guards.

## Production Changes

- Browser MCP risky actions now get a deterministic `action_fingerprint` and
  `preview_id` in the pending confirmation preview.
- The fingerprint is derived from the exact tool name, action name, target, and
  normalized arguments with `confirmed` excluded.
- Pending approvals are scoped to the current chat/session when available.
- A browser MCP retry with `confirmed=true` dispatches only when its fingerprint
  matches a previously previewed pending action in the same scope.
- A changed action, target, or argument with `confirmed=true` fails closed and
  returns a fresh `pending_confirmation` preview.
- A browser MCP risky action with `confirmed=true` and no prior matching preview
  fails closed instead of silently dispatching.
- Streamed and persisted confirmation previews use a redacted event payload so
  secret-like values are not echoed raw.
- Browser observations now separate observed page facts, detected actions,
  inferred next steps, and risky actions requiring approval.

## Sensitive Values

Browser-facing observation and confirmation formatting redacts obvious
passwords, tokens, auth codes, API keys, payment card numbers, CVV/CVC values,
SSNs/personal IDs, and private-message fields.

## Validation

Required focused validation:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_browser_operator_assistant.py
.\venv\Scripts\python.exe -m pytest -q tests/test_operator_scenario_smoke.py
.\tools\run-guard-tests.ps1
```

Expected result: browser operator tests and guard tests pass with only the
existing local `.pytest_cache` permission warning/noise if present.
