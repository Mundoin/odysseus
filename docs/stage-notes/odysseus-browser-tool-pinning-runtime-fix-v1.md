# Stage: odysseus-browser-tool-pinning-runtime-fix-v1

Fix inconsistent browser tool exposure so browser operator tools stay available
for current-page inspection and form-fill workflows when browser MCP runtime is
connected.

## Root Cause: 3-Layer Pipeline Failure

### Layer 1 — Domain detection (`_classify_agent_request`, line 813)

The regex caught "browser", "browse", "inspect page", "fill form" etc. but
**missed** terms like `page inventory`, `form inventory`, `form-fill plan`,
`fill safe fields`, `detect fields`, `current page`, `buttons`, `links`,
`do not submit`, `do not upload`, `stop and report`. When a prompt didn't
contain a matched term, `"browser"` was never added to `intent.domains`.

**Fixed:** Added all missing browser-operator intent terms to the regex,
grouped by category (navigation, page inspection, form intent, guarded stop).

### Layer 2 — Domain-to-tool mapping (`_DOMAIN_TOOL_MAP["browser"]`, line 292)

`_DOMAIN_TOOL_MAP["browser"]` was **always `set()`**. Every other domain
(web, email, cookbook, etc.) maps to concrete tool names. Even when the
browser domain *was* detected, the general domain loop
(`_relevant_tools.update(_DOMAIN_TOOL_MAP.get(domain, set()))`) added
**zero** tool names. Since the schema filter (Layer 3) strips any MCP tool
whose name isn't in `_relevant_tools`, all browser schemas were dropped.

**Fixed:** Added a force-include block after the domain loop: when `"browser"`
is in `intent.domains` and `mcp_mgr` is connected, enumerate all MCP tools
via `mcp_mgr.get_all_tools()`, filter to browser-prefixed tools via
`is_browser_mcp_tool_name()`, and add their qualified names to `_relevant_tools`.

### Layer 3 — Schema filtering (line ~2170)

For API/native-tool models, when `_relevant_tools` is non-empty, MCP schemas
are filtered to only those whose names appear in `_relevant_tools`:

```python
_mcp_filtered = [
    s for s in mcp_schemas
    if s.get("function", {}).get("name") in _relevant_tools
]
```

Since Layer 2 never added browser tool names, all browser MCP schemas were
silently dropped. The model saw the system prompt diagnostics that said
"browser tools are CONNECTED and available" but received **no function-call
schemas** for any browser tool, causing the false "browser tools unavailable"
response.

**Fixed by Layer 2 fix:** Browser tools now appear in `_relevant_tools`, so
they survive the schema filter.

### Why "browse to example.com" worked but "inspect current page" failed

1. "browse" + URL matched the domain regex → browser domain detected.
2. RAG retrieval also picked up `browser_navigate`/`browser_snapshot` because
   URL/web terms embed close to those tool descriptions in vector space.
3. The follow-up query "what is on the current page" didn't match the old,
   narrower domain regex and didn't embed close to browser tools → no domain,
   no RAG hits, no tools.

## Changes

### `src/agent_loop.py`

1. **Line 813 (expanded regex):** Added multi-word browser-operator intent
   terms: `inspect current page`, `current browser page`, `current page`,
   `page inventory`, `buttons`, `links`, `form inventory`, `form-fill`,
   `fill fields`, `fill safe`, `safe fields`, `detect fields`, `input fields`,
   `text fields`, `textarea`, `upload field`, `submit button`, `apply button`,
   `do not submit`, `do not upload`, `stop and report`, `fill the form`,
   `fill in form`, `fill out form`, `form fill`.

2. **Line ~1896 (force-include):** After the domain seeding loop, if `"browser"`
   domain is detected and `mcp_mgr` is available, enumerate all MCP tools,
   filter to browser-prefixed names via `is_browser_mcp_tool_name()`, and add
   them to `_relevant_tools`. This is the single highest-impact fix.

3. **Follow-up turn pinning:** After the force-include, check the most recent
   assistant message for browser tool usage (`"browser_"` or `"mcp__"` in
   content). If found, re-enumerate and pin browser tools so terse follow-ups
   ("what about the form fields?") don't lose access.

4. **Line 624 (`_MCP_KEYWORDS`):** Added multi-word phrases for local/fenced-
   block model support: `"inspect page"`, `"page snapshot"`, `"fill form"`,
   `"fill field"`, `"form fill"`, `"form-fill"`, `"browser page"`,
   `"field fill"`, `"current page"`, `"page inventory"`, `"form inventory"`,
   `"safe field"`, `"stop and report"`. These are multi-word so they won't
   false-positive on raw substring matches.

### `tests/test_browser_tool_exposure.py`

- `test_classify_detects_page_inventory`
- `test_classify_detects_form_fill_plan`
- `test_classify_detects_fill_safe_fields`
- `test_classify_detects_stop_and_report`
- `test_classify_detects_inspect_current_page`
- `test_classify_detects_form_inventory`
- `test_classify_detects_detect_fields`
- `test_browser_domain_pins_browser_mcp_tools_from_mgr`
- `test_followup_keeps_browser_tools_after_browser_turn`
- `test_missing_runtime_does_not_invent_browser_tools`

## Validation

```powershell
.\tools\odysseus-status.ps1
.\tools\run-guard-tests.ps1
.\venv\Scripts\python.exe -m pytest -q tests/test_browser_tool_exposure.py
.\venv\Scripts\python.exe -m pytest -q tests/test_browser_operator_assistant.py
.\venv\Scripts\python.exe -m pytest -q tests/test_operator_scenario_smoke.py
git diff --check
git status --short
```

## Manual Smoke

1. Restart Odysseus.
2. Prompt: `browse to example.com and tell me what you see`
   Expected: browser tools work.
3. Then prompt:
   ```
   Inspect the current browser page. Build a page inventory. Create a form-fill plan. Fill only safe non-sensitive text fields. Do not upload. Do not submit. Stop and report.
   ```
   Expected: agent must NOT say browser tools unavailable. It should inspect
   / current-page snapshot or explain exact connected browser state.

## Hard Boundaries

- ✅ Risky browser actions remain guarded (submit/upload/click guarded)
- ✅ No browser tools invented when runtime is missing
- ✅ Browser tools not globally available for unrelated tasks
- ✅ No CV/document upload work added
- ✅ No approval rules loosened
- ✅ No remotes changed
- ✅ Browser action fingerprint/preview_id behaviour unchanged
