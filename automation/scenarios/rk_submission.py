"""Final RK validation, one-shot submit, and server receipt handling."""
import time
from automation.scenarios.rk_confirmation import CONFIRMATION_BUTTON
from automation.scenarios.rk_documents import uploads_confirmed
from automation.scenarios.rk_dropdown import SNAPSHOT as DROPDOWN_SNAPSHOT
from automation.scenarios.rk_validation import (
    VALIDATION_ERRORS, rejection_error, RKSubmissionUnknown,
)
from services.rk_submission_journal import write_submission_state


class RKSubmissionMixin:
    def _submit_application(self) -> None:
        if self._submission_attempted:
            raise RuntimeError("Submission was already attempted. Check the application status before trying again.")
        self._verify_review_checks()
        if self._restore_if_document_reloaded():
            self._fill_email_code()
        self._verify_document_values()
        if not self.email_code or not self._email_code_value_matches(self.email_code):
            raise RuntimeError("RK email code changed. Restart verification before submitting.")
        self.debug.step("rk_submit_click_start")
        write_submission_state(self.account_dir, 'pending', self.task_id)
        self._external_action_pending = True
        self._submission_attempted = True
        clicked = self.driver.execute_script(
            """
            const visible = (element) => {
                if (!element) return false;
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && style.pointerEvents !== 'none';
            };
            const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const buttons = [...document.querySelectorAll('button,[role="button"]')]
                .filter(visible)
                .filter((button) => {
                    const text = normalize(button.innerText || button.textContent);
                    return text.includes('submit application')
                        || text.includes('submit apolication')
                        || (text.includes('submit') && text.includes('application'));
                })
                .sort((left, right) => {
                    const a = left.getBoundingClientRect();
                    const b = right.getBoundingClientRect();
                    return (a.width * a.height) - (b.width * b.height);
                });
            for (const button of buttons) {
                const disabled = button.disabled
                    || button.getAttribute('aria-disabled') === 'true'
                    || String(button.className || '').toLowerCase().includes('disabled');
                if (disabled) continue;
                button.scrollIntoView({ block: 'center', inline: 'center' });
                button.click();
                return true;
            }
            return false;
            """
        )
        if not clicked:
            self._external_action_pending = False
            write_submission_state(self.account_dir, 'rejected', self.task_id, 'Submit button unavailable; no click sent')
            raise RuntimeError("MEXC RK Submit Application button was not found or is disabled")
        self._handle_captcha("rk_after_submit")
        self.debug.step("rk_submit_clicked")

    def _verify_document_values(self) -> None:
        for input_id, expected in (
            ("requiredItemId-155-relatedSelect", self.address_document_type_text),
            ("requiredItemId-78-relatedSelect", self.deposit_source_type_text),
        ):
            snapshot = self.driver.execute_script(DROPDOWN_SNAPSHOT, input_id) or {}
            if snapshot.get("selected") != " ".join(expected.lower().split()):
                raise RuntimeError("RK document type changed. Review the form before submitting.")
        for section, paths, text in (
            ("proof of address", self.address_pdf_paths, ""),
            ("occupation details", self.occupation_pdf_paths, self.occupation_details_text),
            ("proof of source of last", self.deposit_screenshot_paths, self.deposit_source_text),
        ):
            self._rk_check_cancelled()
            if paths and not uploads_confirmed(self._section_file_snapshot((section,)), paths):
                raise RuntimeError(f"Uploaded documents are not confirmed in {section}.")
            if text:
                element = self._find_text_input_for_section((section,))
                if element is None or not self._wait_for_element_value(element, text, timeout=2):
                    raise RuntimeError(f"Text changed in {section}. Review the form before submitting.")

    def _verify_submitted(self) -> None:
        self.debug.step("rk_submit_verify_start")
        deadline = time.time() + 60

        while time.time() < deadline:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            error = rejection_error(self.driver.execute_script(VALIDATION_ERRORS) or [])
            if error:
                self._external_action_pending = False
                write_submission_state(self.account_dir, 'rejected', self.task_id, str(error))
                raise error
            if self._submitted_visible():
                self._external_action_pending = False
                self.debug.step("rk_submit_verified", document_review='pending')
                return
            if self._confirm_application_details():
                deadline = time.time() + 60
            self._handle_captcha('rk_submit_verification')
            time.sleep(1)
        self.debug.save_page_probe(self.driver, "rk_submit_verify_timeout.json")
        raise RKSubmissionUnknown("Submission status is unknown. Check the RK page before submitting again.")

    def _confirm_application_details(self) -> bool:
        if getattr(self, '_confirmation_attempted', False):
            return False
        button = self.driver.execute_script(CONFIRMATION_BUTTON)
        if button is None:
            return False
        self._raise_if_cancelled()
        # Mark before dispatch: an interrupted response must never cause a double submit.
        self._confirmation_attempted = True
        self.debug.step('rk_confirmation_submit_start')
        self.driver.execute_script('arguments[0].click();', button)
        self.debug.step('rk_confirmation_submit_clicked')
        return True

    def _submitted_visible(self) -> bool:
        state = self.state_analyzer.analyze(self.driver)
        if state.name == "risk_control_submitted" and state.confidence >= 0.72:
            return True
        return False

