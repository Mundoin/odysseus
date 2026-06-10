# Odysseus Browser Visible Fill Proof v1

Stage: `odysseus-browser-visible-fill-proof-v1`

This stage keeps the existing Fill preview -> Fill approved flow, then executes
approved browser form fills in a headed Browser MCP window by default.

## Behavior

- Browser visible fill is the default for approved form-fill execution.
- The built-in Browser MCP launches headed unless `ODYSSEUS_BROWSER_HEADLESS=1`
  is set before starting Odysseus.
- Approved fills pause around each field by default
  (`ODYSSEUS_BROWSER_VISIBLE_FILL_DELAY_MS`, default `550`) so the operator can
  watch fields fill.
- Password, upload/file, submit/apply/payment/send, and sensitive fields remain
  skipped or blocked.
- The browser/page is not closed after fill; the result reports
  `browser_session_status=open_after_fill`.
- Hidden/backend proof mode remains available with
  `ODYSSEUS_BROWSER_HEADLESS=1` and/or `visible_mode=false`.

## Manual Smoke

1. Start Odysseus:

   ```powershell
   D:\Repos\odysseus\odysseus\start-odysseus-hidden.ps1
   ```

2. Open the smoke/test form target, for example:

   ```text
   http://127.0.0.1:8765/odysseus-smoke-form.html
   ```

3. Ask Odysseus to fill normal fields with values like:

   ```text
   Fill this form:
   first_name: Bujar
   last_name: Smoke
   email: bujar.smoke@example.com
   phone: +49123456789
   city: Dortmund
   postcode: 44137
   cover_letter: Short smoke-test cover letter text.

   Do not fill password fields. Do not upload files. Do not submit.
   ```

4. Review the Fill preview.

5. Reply with a short approval such as:

   ```text
   yes fill it
   ```

6. Watch the visible browser window fill the normal fields.

7. Confirm password/upload/submit controls stayed untouched and the browser
   remained open after the fill.

8. Check the result summary for Fields filled, skipped/blocked counts,
   field labels/names, and final browser/session status.
