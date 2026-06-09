# Stage: odysseus-browser-operator-tool-enforcement-v1

Date: 2025-06-09
Branch: bujar-odysseus-hardening
HEAD: 2f9477c

Three-layer enforcement so models reliably call `browser_operator_safe_fill` instead of
describing it in prose or falling back to low-level `browser_fill`/`browser_type`.

## Problem

Models occasionally:
1. **Narrate** "I will call browser_operator_safe_fill" but end the turn without emitting the tool call.
2. **Fall back** to `browser_fill`/`browser_type` directly even when `browser_operator_safe_fill` is available.
3. **Lose tool context** on terse approval follow-ups ("approved", "fill them"), causing the fill tool to disappear from the active schema.
4. **Re-request approval** for the same approved fill batch instead of calling with `confirmed=true`.

## Enforcement mechanism

### Layer 1 — Prompt rules
- **`_DOMAIN_RULES["browser"]`**: rewritten to mandate `browser_operator_safe_fill` as the single fill tool, prohibit claiming success without tool result, block fallback to `browser_fill`/`browser_type`/`browser_select_option`, and require `confirmed=true` after approval.
- **`BROWSER_OPERATOR_RULES`**: same mandates for the operator-assisted path. Added "do not narrate — actually emit the call" and "after `pending_confirmation`, the only correct follow-up is `browser_operator_safe_fill` with `confirmed=true`."
- **`_AGENT_RULES` / `_API_AGENT_RULES`**: added specific `browser_operator_safe_fill` sentence to the Local operating contract.

### Layer 2 — Follow-up tool pinning
- **`_EXPLICIT_CONTINUATION_RE`**: extended with `approved|execute|proceed|fill them|fill it|I approve|do it now|go for it|apply them` so terse approval text inherits the prior browser context and keeps `browser_operator_safe_fill` in the tool set.

### Layer 3 — Supervisor detection
- **`_INTENT_RE`**: broadened with `submit|execute|send|dispatch|fill|apply` action verbs.
- **`browser_operator_safe_fill` prose detector**: added after the existing intent check. When the round text contains `browser_operator_safe_fill` but no tool block uses it, injects a targeted nudge and logs a warning with `tool_intent_without_call: browser_operator_safe_fill`.
- **`_MAX_INTENT_NUDGES = 2`** cap still applies.

### Diagnostic logging
- Per-round debug log extended: when `browser_operator_safe_fill` is in `relevant_tools` but the user message contains `fill`/`form`/`approved`/`confirm` keywords, logs a `warning`-level diagnostic so operators can inspect.

## Files changed

| File | Change |
|---|---|
| `src/browser_operator.py` | `BROWSER_OPERATOR_RULES` — mandated `browser_operator_safe_fill`, no-narrate rule, confirmed=true follow-up |
| `src/agent_loop.py` | `_DOMAIN_RULES["browser"]` rewrite; `_EXPLICIT_CONTINUATION_RE` extension; `_INTENT_RE` broadening; browser_operator_safe_fill prose detector; diagnostic logging; `_AGENT_RULES`/`_API_AGENT_RULES` update |
| `tests/test_browser_tool_exposure.py` | 10 new tests covering domain/operator rules, continuation regex, intent regex, form-fill pinning, approval follow-up, and reinforcement |
| `docs/stage-notes/odysseus-browser-operator-tool-enforcement-v1.md` | This file |

## Known limitations

- **Prompt-level enforcement**: models that ignore system prompts (weak/small local models) can still disregard the rules. The supervisor nudge provides a second line of defense but is capped at 2 nudges.
- **`_EXPLICIT_CONTINUATION_RE` uses `re.match()` (full-string)**: multi-word approval text works as long as it's the entire message. "fill them" alone is fine; "fill them and check" would not match.
- **`_INTENT_RE` 140-char tail limit**: the matched phrase must be ≤140 chars after the action verb. "Now submitting the form-fill plan with browser_operator_safe_fill" (~60 chars) fits comfortably.
- **Browser domain detection**: "fill in the form" does not trigger browser domain due to regex structure (`fill in form` is in the alternation but "the" between "in" and "form" breaks it). Use "fill the form" or "fill form" instead.
- **`_classify_agent_request` test mocks**: `test_form_fill_prompt_pins_safe_fill` and `test_approval_followup_pins_safe_fill` test the domain detection + continuation classification, but the actual tool-pinning logic requires a full agent loop with `mcp_mgr`. These verify the prerequisite condition, not the full pin.

## Validation

```bash
python -m py_compile src/browser_operator.py
python -m py_compile src/agent_loop.py
python -m pytest tests/test_browser_tool_exposure.py -v
python -m pytest tests/test_browser_operator_safe_fill.py -v
python -m pytest tests/test_browser_operator_assistant.py -v
```
