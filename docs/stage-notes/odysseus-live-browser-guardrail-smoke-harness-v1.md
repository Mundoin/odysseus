# Stage: odysseus-live-browser-guardrail-smoke-harness-v1

## Purpose

Prove that the browser/MCP external-action guardrails added in prior stages
fire correctly — before execution, with a real action counter — using a
local-only test harness. No Playwright server, no real network requests.

## Fake page

`tests/fixtures/smoke_page.html` — static HTML with one button per required
action category. The page POSTs to `/action` and updates a counter. Used as
the HTTP fixture's home page and as a reference for human-readable action labels.

## Local HTTP server fixture

`_SmokeHandler` in `tests/test_live_browser_guardrail_smoke.py`:
- `GET /` → serves `smoke_page.html`
- `POST /action` → increments `_SmokeHandler._counter`, returns JSON `{"counter": N}`
- Runs in a daemon thread on a random OS-assigned port; torn down after each test

The fixture counter starts at 0 per test; only increments on `POST`. This
models the real invariant: counter stays 0 while guard blocks, increments when
`confirmed=true` allows the action through.

## Dispatch helper

`_dispatch(tool, args, mock_call_tool)` in the test file mirrors the 4-line
sequence in `src/tool_execution.py:execute_tool_block` (mcp__ branch):

```python
_confirmed = bool(args.pop("confirmed", False))
_block = guard_mcp(tool, args, _confirmed)
if _block is not None:
    result = _block
else:
    result = await mcp.call_tool(tool, args)
```

Only `call_tool` is substituted. `guard_mcp` is the real function, so
classification and preview logic is exercised end-to-end.

## Test organisation

| Class | Count | What is tested |
|---|---|---|
| `TestSmokeGuardUnit` | 10 | `guard_mcp` for each of the 7 fake-page action categories + 3 safe/read-only |
| `TestSmokeMcpDispatch` | 8 | dispatch sequence with AsyncMock call_tool; mock.call_count as counter |
| `TestSmokeLiveLocal` | 6 | real HTTP server; counter 0 when blocked, 1 when confirmed; page served correctly |

Total: **24 new tests**, all passing.

## Results

| Suite | New | Prior | Status |
|---|---|---|---|
| `test_live_browser_guardrail_smoke.py` | 24 | — | 24/24 pass |
| `test_mcp_dispatch_guards.py` | — | 32 | 32/32 pass |
| `test_external_action_guards.py` | — | 26 | 26/26 pass |
| `test_external_action_schemas.py` | — | 8 | 8/8 pass |
| Pre-existing failures (other files) | — | 82 | unchanged |

## Caveats

- No real Playwright browser is started. The harness proves guard dispatch
  behaviour, not browser rendering.
- `_SmokeHandler._counter` is a class variable — tests reset it explicitly
  in each test method. The fixture also resets it on setup.
- To run with a real Playwright server in the future, replace `_dispatch`
  with a full call to `execute_tool_block` and inject a real MCP manager.
