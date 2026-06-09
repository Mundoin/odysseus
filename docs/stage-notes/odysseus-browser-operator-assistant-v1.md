# Stage: odysseus-browser-operator-assistant-v1

Make the hardened Mundoin Odysseus fork more usable as Bujar's local browser
operator assistant. This stage wires an actual browser-operator path on top of
the existing MCP/browser tools and confirmation guardrails.

## Production path implemented

- Browser MCP tool prompts now include a focused browser-operator workflow when
  browser tools are available.
- Browser read/prepare results are formatted as readable browser observations
  for the agent/user-facing tool result path.
- Guarded browser/MCP `pending_confirmation` payloads are rendered as readable
  confirmation previews instead of blank/raw tool output.
- Live streamed `tool_output` events include `confirmation_preview` when a
  browser/MCP action is blocked.
- Persisted tool events also retain `confirmation_preview` for history reloads.
- Approved retries still pass through the existing MCP dispatch path: the
  dispatcher strips `confirmed` before forwarding arguments to the MCP server.

## User-facing workflow now possible

For browser tasks, Odysseus can:

- inspect current page state with MCP browser read tools such as snapshot or
  screenshot,
- summarize the page state and useful controls,
- fill/prepare fields where the action is local prepare,
- navigate/read where safe,
- block submit/send/upload/buy/cancel/refund/return/delete/account/settings/
  security/payment/tax/legal/admin-like actions with `pending_confirmation`,
- after explicit current-chat approval, retry the same MCP action with
  `confirmed=true`,
- show what happened from the MCP tool result.

## Safety

No confirmation requirement was loosened. This stage only adds browser-operator
instructions and readable result rendering around the existing guard path.

## Tests

`tests/test_browser_operator_assistant.py` covers:

- browser MCP prompt includes operator workflow,
- browser snapshot result formats as an operator observation,
- pending confirmation formats as readable user-facing preview,
- safe browser action dispatches,
- risky browser action returns `pending_confirmation` without dispatch,
- approved retry dispatches with `confirmed` stripped.
