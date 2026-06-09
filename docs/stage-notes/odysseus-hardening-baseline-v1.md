# Stage: odysseus-hardening-baseline-v1

Final hardening baseline checkpoint for Bujar's Mundoin Odysseus fork.

## Repository

- Path: `D:\Repos\odysseus\odysseus`
- Branch: `bujar-odysseus-hardening`
- Baseline HEAD: `ce8b683 add windows operator helpers for odysseus hardening fork`
- Tracking branch: `mundoin/bujar-odysseus-hardening`

## Remote model

- `origin` is upstream source: `https://github.com/pewdiepie-archdaemon/odysseus.git`
- `mundoin` is Bujar's writable fork: `https://github.com/Mundoin/odysseus.git`
- Do not push this local fork hardening branch to `origin`.

Safe push command:

```powershell
git push mundoin bujar-odysseus-hardening
```

## Hardening stack summary

- `201a743` harden external api action guardrails
- `6eb2bde` harden mcp dispatch external action guardrails
- `6106d38` test browser external action guardrail smoke harness
- `cb67500` harden guardrail confirmation preview quality
- `55852e1` align agent loop with external action approval contract
- `83dcab2` standardise external action confirmation previews
- `ce8b683` add windows operator helpers for odysseus hardening fork

## Validation commands

Primary one-command validation:

```powershell
.\tools\odysseus-status.ps1
.\tools\run-guard-tests.ps1
```

Expanded guard validation:

```powershell
.\venv\Scripts\python.exe -m pytest -q `
  tests/test_external_action_guards.py `
  tests/test_mcp_dispatch_guards.py `
  tests/test_live_browser_guardrail_smoke.py `
  tests/test_guard_preview_quality.py

.\venv\Scripts\python.exe -m pytest -q `
  tests/test_agent_loop.py -k external_action_confirmation_contract
```

Expected result from `.\tools\run-guard-tests.ps1`:

- Guardrail suites: `108 passed`
- Focused agent operating-rules prompt test: `1 passed, 51 deselected`

## Known warnings/noise

- `git status` may warn that `.pytest_cache/` cannot be opened due local
  permission state.
- Pytest may warn that it cannot write `.pytest_cache` nodeids.
- SQLAlchemy emits `MovedIn20Warning` for `declarative_base()`.
- In restricted shells, `odysseus-status.ps1` may warn that CIM-based process or
  port queries are unavailable; the status helper continues and falls back to
  `netstat` for listener visibility.

## Optional tag

After committing and pushing this baseline note, Bujar can tag the fork baseline:

```powershell
git tag mundoin-hardening-v1
git push mundoin mundoin-hardening-v1
```
