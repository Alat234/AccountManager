# RK EXE log review, 2026-09-08

Archive: desktop AccountManager/logs.zip, runs 22:19–22:46.

## Evidence
- 22:19:37 and 22:20:47: facial section not found on first prerequisite snapshot;
  subsequent runs found the completed section. Added bounded render wait (12 s).
  An explicitly incomplete marker still stops immediately; cancellation is checked.
- Get Code native clicks repeatedly targeted ant-input-suffix and were intercepted
  by the page processing container. That class is the form container, not evidence
  of a loading overlay. Fallback clicks on the suffix cannot reach child handlers.
  Selection now prefers the innermost matching link; countdown/captcha confirmation
  remains required. Logged target geometry, hit target and browser focus metadata.
- 22:23:59–22:24:59: occupation PDF was visible in the saved screenshot, but the
  geometric snapshot reported no filenames. The upload row begins slightly above
  its label. Documents, file inputs and text inputs now prefer the label's fileWrapper
  DOM section; geometric fallback remains for older markup.
- Dropdown native/ActionChains attempts failed with intercepted/out-of-bounds
  errors, but keyboard fallback selected the requested bank statement category.
  No evidence of a missing bundled module or inaccessible document path.

## Limits and validation
38 RK tests passed, including 14 isolated Chrome DOM tests. Added regressions for
uploads above the section label, nested Get Code handlers and late facial section.
No real MEXC submission performed. The logs do not establish PyInstaller as the
cause or prove a browser zoom/driver issue. Startup logging now identifies frozen
mode, Python, executable, working directory and RK revision for comparison.

## Follow-up: 23:44 run 7af759b05cf7
The occupation upload still timed out before text entry. Both configured texts
were present. Actual saved HTML uses a submitItem container: its description,
upload and textarea are sibling form items. The earlier fileWrapper-only lookup
fell back to geometric bounds. All three document lookups now also recognize
submitItem. Added a browser regression with this nesting that confirms the PDF,
fills both text fields and verifies section isolation. 28 targeted tests passed.

## Final confirmation and document rejection, 2026-09-09
User screenshot shows Confirm Application Details: this is a pre-submission
confirmation, not a receipt. The verification loop now clicks the unique enabled
Submit Application inside that dialog once, marks the attempt before dispatch,
and starts a fresh bounded receipt wait. A timeout/interruption remains unknown;
no blind resubmission. Explicit email-code rejection alone retains its one retry.
Visible document rejection headings and error alerts stop with the site reason.
Successful submission reports document review pending, never document approval.
There is no polling after scenario completion; later review decisions must be
checked separately. 42 RK tests passed, including dialog scoping, one-shot click,
hidden dialogs, confirmation-vs-receipt, and document rejection reason fixtures.
Live submission was not exercised.
