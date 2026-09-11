# RK reliability implementation — 2026-09-07

Authorized plan: remove synchronous monitoring delays, pin the RK tab, make
dropdown selection work in the background, validate/reuse uploads, bound email
retries, distinguish rejected/unknown/submitted outcomes, and exercise recovery.

Implementation order:
1. Queue and throttle resource sampling; never send WebDriver calls from workers.
2. Add RK-specific tab ownership and nonblocking navigation with state waits.
3. Separate popup existence from clickable layout; try native, keyboard and DOM
   selection, verifying the selected category after each attempt. If needed, notify
   and wait for the user to return, without raising the browser over other apps.
4. Validate format/size before launch, preview file-to-section mapping, and reuse
   successful uploads. Reject mismatched existing files instead of duplicating them.
5. Bound email waiting/re-requesting and keep existing form data intact.
6. Report server validation promptly, retain unknown submission state across runs,
   and require a deliberate review before another attempt with an unknown result.
7. Local unit/browser fixtures for background dropdown, cancellation, tab changes,
   uploads, email and outcomes; live read-only checks when available. Real submission
   remains dependent on completion of MEXC's required identity steps.

Important cases: loading/hidden popup, missing option, stale DOM, closed owned tab,
wrong tab, expired session, offline/online, 0/1/2 files, oversized/changed files,
already uploaded file, delayed/rejected code, CAPTCHA, server rejection, lost
submission response and cancellation during any wait.
