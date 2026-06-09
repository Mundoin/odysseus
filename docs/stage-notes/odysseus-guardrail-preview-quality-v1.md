# Stage: odysseus-guardrail-preview-quality-v1

Improve quality, structure, and clarity of `pending_confirmation` previews returned
by external-action guardrails. Operator-facing confirmation payload only — no new
safety layer, no changes to gating decisions (one keyword addition, see below).

## What changed

All changes centralised in `src/external_action_guard.py`. Call sites
(`src/tool_implementations.py` api_call/app_api, `src/tool_execution.py` MCP
dispatch) unchanged — they already route through `guard()` / `guard_mcp()`.

### Shared preview shape (`build_preview`)

Every preview now carries stable fields:

| Field | Notes |
|---|---|
| `pending_confirmation: true` | primary signal, unchanged |
| `confirmation_required: true` | new explicit flag |
| `action_category` | mirrors legacy `action_type` |
| `risk_level` | `"normal"` or `"high"` |
| `tool_name` | mirrors legacy `tool` |
| `action_name` | HTTP method or bare MCP tool name (e.g. `browser_click`) |
| `target` | unchanged |
| `target_domain` / `url` | when target/args contain an http(s) URL |
| `summary` | operator-grade sentence: what, where, which tool, effect, "Approval is required before execution." |
| `arguments_preview` | compacted copy of body/args (long strings truncated at 300 chars, lists capped at 10, depth-bounded) |
| `consequences` | what happens if the user approves |
| `approval_instruction` | mirrors legacy `instruction` (still contains `confirmed=true`) |

High-impact actions additionally carry:

- `high_impact: true`
- `high_impact_reason` — matched keyword(s) or tool-class reason
  (e.g. "uploads local files or documents to an external site")
- `final_review_checklist` — human checklist list (target correct, action
  intended, data reviewed, financial/legal impact understood, user requested it)

### MCP-specific summaries

`guard_mcp` now builds action-aware summaries via `_mcp_action_phrase` /
`_mcp_summary` / `_mcp_high_impact_reason`, e.g.:

> Odysseus is about to click 'Submit order' in the browser using MCP tool
> mcp__playwright__browser_click. This may trigger a high-impact, externally
> visible action (payment, submission, deletion, upload, or similar).
> Approval is required before execution.

### Keyword addition

`_CLICK_HIGH_IMPACT_KEYWORDS` gained `"return"` — stage requires return-item
clicks be high-impact. Over-gating direction (safe); may also catch e.g.
"Return to home" buttons, which then just require confirmation.

## Backward compatibility

Legacy fields preserved verbatim: `pending_confirmation`, `tool`, `action_type`,
`method`, `target`, `risk` (incl. "HIGH IMPACT" prefix), `instruction`
(incl. `confirmed=true`), `integration`, `body_preview` (raw, untruncated),
`final_checklist` (dict). New fields are additive. `confirmed=true` re-call
semantics and confirmed-strip before MCP dispatch unchanged.

## Tests

New: `tests/test_guard_preview_quality.py` (25 tests,
`area_security` / `sub_guard_preview_quality`):

- api_call preview: category, risk level, target, summary, consequences,
  arguments_preview, truncation, high-impact payment path
- app_api preview: route/action details in summary
- target_domain extraction from URL targets
- MCP click-submit: tool name + button context + reason
- MCP upload: high-impact + final_review_checklist
- MCP buy/pay/place-order clicks: high-impact
- MCP delete/cancel/refund/return clicks: high-impact
- plain click stays normal-risk, no high-impact fields
- network_request preview: url + domain + method in summary
- read-only (GET, snapshot) produce no preview
- confirmed=true allows api + MCP execution paths
- confirmed flag stripped before MCP call
- legacy field compatibility + new-field mirroring

## Validation (2026-06-09)

- New preview-quality tests: 25/25 passing
- Prior guard suites (`test_external_action_guards`, `test_mcp_dispatch_guards`,
  `test_live_browser_guardrail_smoke`): 82/82 passing, unchanged
- Full suite: see commit/PR notes for pre-existing failures (reported separately)

## Caveats

- Unit/smoke level only — does not prove live production browser safety.
- `arguments_preview` compaction is display-oriented; legacy `body_preview`
  remains the raw payload for consumers that need exact data.
