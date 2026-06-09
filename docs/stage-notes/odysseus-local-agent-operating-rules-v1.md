# Stage: odysseus-local-agent-operating-rules-v1

Align local agent operating instructions with the external-action guardrails
already enforced by the backend. This is prompt/policy wording only; no guardrail
classification, dispatch behavior, tool schema, or confirmation execution path
changed.

## Contract added to agent instructions

Local operating contract: read/search/summarise actions are allowed; drafting,
preparing, or staging local content is allowed. External actions require explicit
approval in the current chat before execution. Only set `confirmed=true` after
that approval; if a guarded tool returns `pending_confirmation`, show or explain
that preview and wait for approval before retrying.
Send/submit/upload/buy/cancel/refund/return/delete/account/settings/security/payment/tax/legal/admin
actions are confirmation-gated.

## Files touched

- `src/agent_loop.py` - added the contract to both fenced-tool and native
  tool-calling base rules.
- `tests/test_agent_loop.py` - pinned the contract text in both prompt rule
  blocks.

## Validation

Run the targeted guard suites plus focused prompt coverage for this wording.
