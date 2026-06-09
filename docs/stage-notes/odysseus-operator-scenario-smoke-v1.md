# Stage: odysseus-operator-scenario-smoke-v1

Add operator-facing scenario smoke tests for Bujar's hardened Mundoin Odysseus
fork. This stage is test/proof only; it changes no production behavior,
guardrail code, remotes, dependencies, or external-service workflows.

## Scenario coverage

`tests/test_operator_scenario_smoke.py` covers:

- Email operator flow: unconfirmed send returns `pending_confirmation` without
  SMTP, preview includes sender, recipient, subject/body preview, consequence,
  approval instruction, and high-impact checklist; confirmed mocked send reaches
  SMTP.
- Skill operator flow: list/view/search stay allowed; add/edit/delete return
  normalized confirmation previews without mutating; confirmed add calls the
  mocked local skill manager.
- External API flow: GET/read stays allowed; high-impact payment-like POST
  returns readable normalized preview; `confirmed=true` allows the guard path.
- Browser/MCP flow: snapshot/read and fill/prepare dispatch; submit/payment
  click is blocked with readable preview; confirmed second call dispatches with
  `confirmed` stripped before the mocked MCP call.

## Safety

All execution paths are mocked or local guard-helper calls. No real email,
browser, network, external service, remote, or destructive action is performed.

## Validation

Run:

```powershell
.\tools\odysseus-status.ps1
.\tools\run-guard-tests.ps1
.\venv\Scripts\python.exe -m pytest -q tests/test_operator_scenario_smoke.py
git diff --check
git status --short
```
