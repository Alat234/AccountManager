# RK submission implementation plan — 2026-09-06

Historical plan from 2026-09-06. The later user-requested local Facescan switch
supersedes the mandatory-only rule below. Current behavior and verification are in
[mexc_risk_control_submission_task_status.md](mexc_risk_control_submission_task_status.md).
The 2026-09-09 implementation also handles the final confirmation dialog and
reports submission separately from document approval.
Plan before implementation:

1. Preserve the existing deposit API lookup and withdrawal screenshot workflow.
   Discover local PDFs and deposit screenshots in a service; present ambiguous
   file choices before launch. Cancellation starts no browser. Missing documents
   and settings text require the existing explicit continue confirmation.
2. Check RK availability after authentication. Public API error codes do not
   establish whether this account has an RK application form. A confirmed intro
   redirect means unavailable; loading/login/unknown must not mean unavailable.
3. Require a positive facial-recognition completion marker in that section.
   Missing marker, Start button, unknown DOM, and incomplete status stop the run.
   Never interpret the instruction “Complete Facial Recognition” as completion.
4. Request a fresh email code before filling; verify request acknowledgment.
   Fill address type and PDF, occupation PDF/text, then 1–2 deposit images/text.
   Keep dropdown interaction scoped to its owning input, including upward popups.
   Verify each selection/upload/text before advancing; failed or pending uploads
   cannot count as success. Files disappearing after preflight cause an error.
5. Fetch the code requested by this run, insert and verify it, recheck facescan,
   then submit once. Require an application-specific confirmation. Unknown result
   is not success and must not automatically cause another submission.
6. Keep cancellation/browser-close checks in waits and existing CAPTCHA/manual
   and network recovery hooks. Split DOM concerns from scenario orchestration.
7. Verify guards, upload matching, dropdowns, and state detection with local
   regression tests. Inspect the user-selected AdsPower account
   `coffer.poster-0v@icloud.com`; real submission permission remains unspecified.

User decision: show a file picker when several PDFs or more than two deposit
screenshots are available. No silent arbitrary choice in those cases.

Important cases: no folder/password/mailbox/profile; missing/empty files;
malformed deposit metadata; 0/1/2/>2 screenshots; duplicate screenshots; changed
DOM; incomplete facescan or KYC; expired login; unavailable RK; already submitted;
CAPTCHA; code delay; upload failure; timeout after Submit; cancellation; closed tab.
