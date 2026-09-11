# MEXC RK Submission Task Status

Updated: 2026-09-11

## Current implementation

- Preflight checks account/profile/mailbox and lets the user review document choices.
  All account-folder PNG/JPG/JPEG files are discoverable, including manual screenshots.
  Missing files or settings text require explicit continuation; cancelled selection
  starts no browser.
- Separate settings configure address and deposit categories and both explanation
  texts. Facescan validation defaults on but can be disabled locally; this does not
  bypass MEXC validation or disable KYC checks. A missing facial section gets a
  bounded 12-second render wait before failure.
- RK tab is pinned. Confirmed intro redirects with or without a trailing slash
  stop as form unavailable, not proof of absence of all account restrictions.
- Get Code targets the innermost matching link and requires acknowledgment.
  A previous countdown is not treated as a fresh request.
- Document and text lookup uses the label's submitItem/fileWrapper container.
  Older markup retains geometric fallback. Full filenames and successful upload
  state are required; text values and categories are checked before submission.
- Submit Application can open Confirm Application Details. The unique enabled
  final button inside that dialog is clicked once. The attempt is marked before
  dispatch to prevent duplicate clicks after an uncertain response.
- Explicit rejection stops with the site reason. Only explicit email-code rejection
  permits one fresh-code retry. Unknown results are recorded and never blindly retried.
- Successful submission reports document review pending, not approval. There is
  no background monitoring of review decisions after the scenario finishes.

## Recent diagnosis

The 2026-09-08 occupation upload was visible but missed by geometric bounds.
The first fileWrapper fix was incomplete: actual markup uses submitItem, with
upload and textarea in sibling form items. The corrected lookup covers both.
Get Code wrapper targeting and early facial-section lookup were also corrected.
The logs do not establish PyInstaller as the cause of these failures. Runtime logs
now include frozen mode, Python, executable, working directory and RK revision.

See [log review](rk_exe_log_review_20260908.md) for evidence and follow-ups.

## Verification and build

43 RK tests passed on 2026-09-09, including 18 isolated Chrome DOM tests.
Tests cover confirmation-dialog scoping, one-shot clicks, hidden dialogs,
receipt detection, document rejection reasons, upload/text section isolation,
file preflight, cancellation/recovery guards and bounded retries.
These are local fixtures, not a live MEXC submission or document approval.
User live testing reached the final confirmation dialog; the latest fix has not
been verified through a complete live submission by the assistant.

Latest successful application build: `dist/twofa-background-20260910/main.exe`.
It includes the multi-PDF RK changes plus the 2026-09-10 2FA fixes.
Previous RK-specific build: `dist/rk-multi-pdf-20260909/main.exe`.
Runtime revision: `20260909-multi-pdf`.
Close the old app before replacing its EXE; retain existing account data.

Run all RK tests with the project virtual environment:

```powershell
$env:RK_TEST_CHROMEDRIVER = "$env:APPDATA\adspower_global\cwd_global\chrome_152\chromedriver.exe"
$env:RK_TEST_CHROME = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_rk*.py' -v
```

Use compatible installed Chrome/driver paths. Without RK_TEST_CHROMEDRIVER,
browser tests are skipped. See [workflow](mexc_risk_control_submission_workflow.md)
and [development rules](development_rules.md).

PDF selection now uses checkboxes. All selected PDFs are passed to both document
sections; single-file upload inputs receive them sequentially, and final validation
requires every selected filename. No application-side PDF count limit; site limits
and per-file validation remain in force. Multi-PDF regression coverage added.
