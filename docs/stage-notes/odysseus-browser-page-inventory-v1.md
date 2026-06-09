# Odysseus Browser Page Inventory v1

Stage: `odysseus-browser-page-inventory-v1`

This stage adds a production page-inventory layer for the local browser
operator. The goal is to help Odysseus understand what is visible on a page
before planning, filling, clicking, uploading, or submitting.

## Inventory

Browser observations now build a structured inventory with:

- `url`
- `title`
- `visible_text_summary`
- `links`
- `buttons`
- `fields`
- `upload_fields`
- `forms`
- `safe_actions`
- `risky_actions`

The parser is defensive and works with plain text snapshots, structured
dict/list content, common content blocks, and simple accessibility-like role
nodes. It does not claim full DOM coverage when the MCP output does not expose
that detail.

## Classification

Obvious risky controls are classified as approval-required when they involve
submit, send, upload, buy, pay, delete, cancel, refund, return, confirm, apply,
login/security/account/payment/legal/admin, checkout, purchase, or order-like
actions.

Safe actions are separated for controls that look read/view/search/filter/
expand/navigation oriented.

## Redaction

The inventory reuses the browser operator redaction layer for passwords,
tokens, auth codes, API keys, payment cards, CVV/CVC values, SSNs/personal IDs,
and private-message fields.

## Validation

Focused validation:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_browser_operator_assistant.py
.\venv\Scripts\python.exe -m pytest -q tests/test_operator_scenario_smoke.py
.\tools\run-guard-tests.ps1
```

Expected result: browser operator tests, scenario smoke tests, and guard tests
pass with only known local warning/noise if present.
