# MEXC Risk Control Submission Workflow

This document describes the RK application submission scenario started by the
`Submit RK` button in the account card.

Updated: 2026-09-09

## Preconditions

The UI checks hard prerequisites before starting:

- selected account exists;
- account is linked to an active AdsPower profile;
- AdsPower Local API is running;
- MEXC password is saved for the account;
- mailbox credentials exist for fetching the MEXC email code;
- account folder exists.

The document discovery service reads PDFs and all PNG/JPG/JPEG files in
this account folder, including manually added screenshots with arbitrary names.
The user reviews and chooses deposit evidence in a dialog before every run.
PDF checkboxes allow multiple selections without an application-side count limit.
All selected PDFs are uploaded to both Proof of Address and Occupation Details.
Each file must be smaller than 10 MB; MEXC may enforce additional limits. Cancelling the dialog starts nothing.
Missing/empty documents and missing RK text are listed before launch; the user
may explicitly continue with incomplete data. A file disappearing after that
confirmation is a runtime error.

Existing `Find RK Deposits` (MEXC API) and `Make Deposit Screenshot` workflows
remain available. Submission can use the resulting files directly, without
requiring deposit metadata to be re-created.

## Settings

The separate `RK — Risk Control` settings card has its own Save RK button and stores:

- `rk_occupation_details_text`;
- `rk_deposit_source_text`;
- `rk_deposit_source_type_text` (Deposit Source dropdown);
- `rk_address_document_type_text` (Proof of Address dropdown);
- `rk_enforce_facescan_check` (Facescan switch; defaults to true when unset).

These values are written into the corresponding text fields on the MEXC RK
form.

As requested on 2026-09-07, the Facescan switch controls local facial-recognition
validation both before requesting a code and immediately before Submit. When
turned off and saved with Save RK, missing/incomplete facial recognition does not
block the scenario. KYC checks remain enabled. This setting does not change MEXC's
own validation. The saved setting is captured when a new scenario starts.

The two category settings are separate option menus, populated from
`models/rk_document_types.py` using labels captured from the MEXC form on
2026-09-07. Free-text input is no longer allowed. Proof of Address defaults to
`Bank, Credit Card & Financial Statements`; Deposit Source defaults to
`Funds From Personal Wallet or Trading Platform`. Legacy invalid source values,
including `Other Document` and the address-category label, are normalized to the
source default. Supported saved selections are preserved. Both categories are
used during filling and rechecked before Submit. The explanatory deposit-source
text remains a separate setting. Changing the category does not change the files
selected by the user: upload evidence appropriate to that category.

## Browser Flow

The scenario is implemented in
`automation/scenarios/submit_mexc_risk_control.py` as
`SubmitMexcRiskControlScenario`.

Main checkpoints:

1. Open `https://www.mexc.com/support/apply-risk-account-protection/form`,
   even if the current MEXC tab is on another page such as API Management.
2. Ensure the account is logged in.
3. Detect whether the RK form is available. If MEXC redirects to
   `https://www.mexc.com/support/apply-risk-account-protection/`, the scenario
   stops with a form-unavailable message (with or without a trailing slash).
   This redirect alone does not prove the absence of every account restriction.
4. Verify facial recognition if enabled and Advanced KYC when its block is present.
   Only a positive completion marker in the matching section counts.
5. Click `Get Code`, then confirm that the code request state changed near the
   `Email Verification Code` field before waiting for a fresh email code.
6. Open `Proof of Address` and select `rk_address_document_type_text` from settings.
   The selected dropdown text must
   be confirmed before continuing.
7. Upload all selected PDFs to `Proof of Address` and confirm that the uploaded file name
   appears inside that section.
8. Upload the same selected PDFs to `Occupation Details` and fill the settings text.
   Both the upload and text value are confirmed before continuing.
9. Select the `Proof of Source of Last 1-2 Deposits` type using
   `rk_deposit_source_type_text` from settings, defaulting to `Funds From Personal Wallet or Trading Platform`
   when the setting is empty.
10. Upload up to two deposit screenshots to
   `Proof of Source of Last 1-2 Deposits` and fill the settings text. The
   scenario confirms that the screenshots and text landed in this section.
11. Insert the email verification code and confirm that the field kept the exact
   fetched code.
12. Click `Submit Application`.
13. If `Confirm Application Details` appears, click its unique enabled
    `Submit Application` once. This dialog is not a submission receipt.
14. Confirm application-specific submitted/under-review status after the form
    disappears, or an explicit application receipt appears in a modal. A generic mention in help text is not success. If confirmation
    times out, report unknown status and do not automatically submit again.

## Submission outcomes

After the final confirmation click, wait up to 60 seconds for a receipt or explicit
error. A timeout/interruption remains unknown and must not cause another click.
Explicit document rejection is reported with the available site reason; documents
are not automatically replaced or resubmitted. An explicit invalid/expired email
code alone permits one fresh-code retry.

A receipt means submitted for review. The result includes
`application_status=submitted` and `document_review_status=pending`.
It does not mean documents approved or account restrictions removed. Later MEXC
review decisions are not monitored after scenario completion.

## Page States

`automation/scenarios/mexc_state.py` detects these RK-specific states:

- `risk_control_form`;
- `risk_control_unavailable`;
- `risk_control_submitted`.

These states are used by `CheckpointRunner` for resume/manual-assist behavior
and by `automation/progress.py` for short user-facing progress messages.

## Modules and verification

- `services/rk_submission_files.py`: document discovery and preflight.
- `ui/rk_file_picker.py`: ambiguous document selection.
- `automation/scenarios/rk_review_checks.py`: configurable facial and KYC prerequisites.
- `automation/scenarios/rk_dropdown.py`: exact category selection using the
  owning combobox/listbox relationship; native click, arrow, and keyboard fallback.
- `automation/scenarios/rk_documents.py`: section-scoped uploads and text.
- `automation/scenarios/rk_confirmation.py`: final confirmation-dialog button lookup.
- `automation/scenarios/rk_submission.py`: final checks, confirmation and receipt wait.
- `automation/scenarios/rk_validation.py`: explicit rejection and code-error classification.
- `services/rk_submission_journal.py`: pending/unknown/rejected/submitted receipt.
- `automation/scenarios/rk_email.py`: fresh code request and code entry.
- `automation/scenarios/submit_mexc_risk_control.py`: checkpoints and final checks.

Document, upload and text lookup prefers the matching label's `submitItem` or
`fileWrapper` ancestor, covering sibling form items and uploads above their label.
Older markup retains geometric fallback. Missing facial sections are allowed up
to 12 seconds to render when local Facescan validation is enabled.

Uploads require all full filenames, a successful upload/form marker, and no
pending upload/error indicator. A single-file input receives images sequentially.
Before Submit, uploaded files, texts, categories, facescan and email code are
checked again.

No dedicated public RK-form status endpoint was found in the
[MEXC Spot API documentation](https://mexcdevelop.github.io/apidocs/spot_v3_en/).
Risk-control error codes are not a reliable replacement for the authenticated
form/intro check. An unloaded intro page is not treated as confirmed unavailability.
