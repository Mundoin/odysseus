# Odysseus Form Fill Planner v1

Stage: `odysseus-form-fill-planner-v1`

This stage adds a safe form-fill planning layer on top of the browser page
inventory. It produces a structured plan only; it does not execute fills,
uploads, submissions, payments, sends, or destructive actions.

## Planner

`build_form_fill_plan(page_inventory, known_values=None, document_candidates=None)`
returns:

- `page_url`
- `page_title`
- `confidence`
- `fields_total`
- `fields_mapped`
- `fields_missing`
- `fields_sensitive`
- `fill_steps`
- `missing_values`
- `sensitive_values`
- `upload_steps`
- `blocked_actions`
- `next_safe_actions`

`format_form_fill_plan(plan)` renders the operator-facing summary with mapped,
missing, sensitive, upload, blocked, and next-safe sections.

## Field Mapping

The first deterministic mapping set covers common application/contact fields:
first name, last name, email, phone, address/street, city, postcode, country,
LinkedIn, GitHub, website/portfolio, cover letter/motivation, salary
expectation, and availability/start date, including common German labels.

## Safety Boundaries

- Password, token, auth-code, API-key, payment-card, CVV/CVC, IBAN/bank,
  national-ID/passport/personalausweis, tax, health/medical, and private-message
  fields are not auto-filled.
- Upload fields become approval-required `upload_steps` only.
- Submit/send/apply/payment/risky controls become approval-required
  `blocked_actions`.
- Value previews are redacted and truncated.
- Existing browser action approval binding, fingerprints, and pending
  confirmations remain unchanged.

## Validation

Focused validation:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_browser_operator_assistant.py
.\venv\Scripts\python.exe -m pytest -q tests/test_operator_scenario_smoke.py
.\tools\run-guard-tests.ps1
```

Expected result: planner, browser operator, scenario smoke, and guard tests pass
with only known local warning/noise if present.
