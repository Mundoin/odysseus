# Stage: odysseus-external-action-guardrails-v1

## Policy

Any irreversible or externally visible action performed via `api_call` or `app_api`
must return a `pending_confirmation` preview on the first call. Execution proceeds
only when the caller re-calls with `confirmed=true`.

Actions are classified by the central helper `src/external_action_guard.py`:

| Class | Trigger | Gate |
|---|---|---|
| `safe_read` | GET / read-only | none |
| `local_prepare` | local state, no external side-effect | none |
| `external_write` | POST/PUT/PATCH/DELETE to non-high-impact path | preview required |
| `high_impact_external_write` | mutating + high-impact keyword in path | preview + `final_checklist` |

High-impact keywords (path substring match): `buy`, `order`, `pay`, `payment`,
`purchase`, `checkout`, `cart`, `cancel`, `refund`, `chargeback`, `dispute`,
`delete`, `destroy`, `purge`, `wipe`, `submit`, `publish`, `account`,
`password`, `credential`, `secret`, `security`, `2fa`, `mfa`, `tax`,
`invoice`, `billing`, `contract`, `upload`, `transfer`, `wire`.

## Affected tools / routes

| Tool | Change |
|---|---|
| `api_call` | Guard inserted in `do_api_call` before `execute_api_call`; `confirmed` param added to schema |
| `app_api` | Guard inserted in `do_app_api` after blocklist checks, before httpx call; `confirmed` param added to schema |

`action=endpoints` in `app_api` is always safe (read-only OpenAPI discovery).

## Reference implementation

Email send guardrail (`mcp_servers/email_server.py` + `src/tool_schemas.py`).

## Tests

| File | Count | Covers |
|---|---|---|
| `tests/test_external_action_guards.py` | 26 | `classify()`, `guard()`, `build_preview()`, `app_api` integration |
| `tests/test_external_action_schemas.py` | 8 | `api_call` and `app_api` schema shape (`confirmed` param present, boolean, optional, description mentions `confirmed=true`) |

All 34 new tests pass. Pre-existing failure count unchanged (82).

## Caveats

- `api_call` integration tests (testing `do_api_call` directly) are excluded due to a
  pre-existing `tool_schemas ↔ agent_tools` circular import that poisons `sys.modules`
  when `tool_implementations` is imported in the same pytest session. Guard logic for
  `api_call` is fully covered by unit tests in `TestExternalActionGuardFunction`.
- Playwright/browser MCP tools have no native tool wrapper in `tool_implementations`;
  they are invoked via the MCP server directly. If a browser-action guardrail is needed,
  add it at the MCP dispatch layer or in a dedicated browser-action tool wrapper.
- `app_api action=endpoints` (OpenAPI discovery) is intentionally ungated.
- High-impact keyword list is path-substring-based; false negatives are possible for
  novel or non-English paths.
