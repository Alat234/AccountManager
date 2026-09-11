# RK validation — 2026-09-09

43 RK tests passed, including 18 isolated Chrome DOM tests. Real submission and
server-side identity approval were not exercised by these tests.

The 17:24 failure was an inactive `ant-spin-container` / `ant-spin-nested-loading`
mistaken for an active loader. This suppressed the intro state and caused manual
assistance at `ensure_login`. Only active spinner/busy markers now count.

Manual PNG/JPG/JPEG filenames are now included in document selection, with no
required `rk_deposit_` prefix. The user selects which images prove deposits.

The public Spot API reviewed on 2026-09-07 exposes `GET /api/v3/account` flags
`canTrade`, `canWithdraw`, `canDeposit`, but no documented RK-form eligibility
endpoint. Codes 10098 and 10265 describe operation-specific risk errors, not a
reliable status query. No authenticated internal endpoint has been validated;
the implementation retains the browser check rather than guessing from flags.

Source: https://mexcdevelop.github.io/apidocs/spot_v3_en/

## Latest regressions

- submitItem nesting: occupation upload confirmation and both explanation fields;
- upload above its label remains in the correct section;
- innermost Get Code link receives the click;
- bounded wait for late facial-section rendering;
- Confirm Application Details is not success, targets only its final button once,
  and ignores hidden dialogs;
- explicit document rejection includes its reason and does not trigger code retry;
  instructional text about possible rejection is not a failure.

Latest EXE built successfully at `dist/rk-multi-pdf-20260909/main.exe`.
Live final submission remains unverified. Review decisions after scenario completion
are not polled. See [current status](mexc_risk_control_submission_task_status.md).

PDF selection now uses checkboxes. All selected PDFs are passed to both document
sections; single-file upload inputs receive them sequentially, and final validation
requires every selected filename. No application-side PDF count limit; site limits
and per-file validation remain in force. Multi-PDF regression coverage added.
