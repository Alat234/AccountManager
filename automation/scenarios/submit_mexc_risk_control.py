from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from dataclasses import replace
from models.rk_document_types import (
    ADDRESS_DOCUMENT_TYPES, DEPOSIT_SOURCE_TYPES,
    DEFAULT_ADDRESS_TYPE, DEFAULT_DEPOSIT_SOURCE_TYPE,
)


from automation.base import BaseScenario, ScenarioResult
from automation.checkpoints import CheckpointRunner, ScenarioCheckpoint
from automation.scenarios.mexc_browser_helpers import (
    MexcBrowserContext,
    collect_error_text,
    ensure_mexc_logged_in,
    handle_mexc_captcha,
    open_mexc_page,
    raise_if_context_cancelled,
)
from automation.scenarios.mexc_debug import MexcRegistrationDebug
from automation.scenarios.mexc_state import MexcPageStateAnalyzer
from automation.scenarios.rk_documents import RKDocumentsMixin, uploads_confirmed
from automation.scenarios.rk_email import RKEmailMixin
from automation.scenarios.rk_dropdown import RKDropdown, SNAPSHOT as DROPDOWN_SNAPSHOT
from automation.scenarios.rk_review_checks import REVIEW_CHECKS_SCRIPT, require_review_checks
from automation.scenarios.rk_submission import RKSubmissionMixin
from automation.scenarios.rk_validation import RKEmailCodeRejected, RKSubmissionRejected, RKSubmissionUnknown
from services.rk_submission_journal import read_submission_state, write_submission_state
from automation.scenarios.rk_navigation import RKPageStateAnalyzer, is_rk_url
from automation.scenarios.rk_recovery import RKRecoveryMixin

logger = logging.getLogger(__name__)


class SubmitMexcRiskControlScenario(RKDocumentsMixin, RKEmailMixin, RKSubmissionMixin, RKRecoveryMixin, BaseScenario):
    """Submit the MEXC risk-control application for a selected RK account."""

    FORM_URL = "https://www.mexc.com/support/apply-risk-account-protection/form"
    INTRO_URL = "https://www.mexc.com/support/apply-risk-account-protection/"

    def __init__(
        self,
        adspower,
        account,
        *,
        account_dir: Path,
        address_pdf_path: Path | None = None,
        occupation_pdf_path: Path | None = None,
        deposit_screenshot_paths: list[Path],
        occupation_details_text: str,
        deposit_source_text: str,
        deposit_source_type_text: str = DEFAULT_DEPOSIT_SOURCE_TYPE,
        address_document_type_text: str = DEFAULT_ADDRESS_TYPE,
        enforce_facescan_check: bool = True,
        allow_resubmit_after_review: bool = False,
        address_pdf_paths: list[Path] | None = None,
        occupation_pdf_paths: list[Path] | None = None,
        captcha_service=None,
        email_fetcher=None,
        on_captcha_detected: Callable[[str], None] | None = None,
        on_email_timeout: Callable[[str], bool] | None = None,
    ):
        super().__init__(adspower, account, captcha_service)
        self.account_dir = Path(account_dir)
        self.address_pdf_path = Path(address_pdf_path) if address_pdf_path else None
        self.occupation_pdf_path = Path(occupation_pdf_path) if occupation_pdf_path else None
        self.address_pdf_paths = list(dict.fromkeys(Path(p) for p in (
            address_pdf_paths if address_pdf_paths is not None else ([address_pdf_path] if address_pdf_path else []))))
        self.occupation_pdf_paths = list(dict.fromkeys(Path(p) for p in (
            occupation_pdf_paths if occupation_pdf_paths is not None else ([occupation_pdf_path] if occupation_pdf_path else []))))
        self.deposit_screenshot_paths = [Path(path) for path in deposit_screenshot_paths[:2] if path]
        self.occupation_details_text = (occupation_details_text or "").strip()
        self.deposit_source_text = (deposit_source_text or "").strip()
        self.deposit_source_type_text = (deposit_source_type_text or DEFAULT_DEPOSIT_SOURCE_TYPE).strip()
        self.address_document_type_text = (address_document_type_text or DEFAULT_ADDRESS_TYPE).strip()
        if self.address_document_type_text not in ADDRESS_DOCUMENT_TYPES:
            raise ValueError("Choose a valid Proof of Address category in RK Settings.")
        if self.deposit_source_type_text not in DEPOSIT_SOURCE_TYPES:
            raise ValueError("Choose a valid Deposit Source category in RK Settings.")
        self.enforce_facescan_check = enforce_facescan_check
        self.email_fetcher = email_fetcher
        self.on_captcha_detected = on_captcha_detected
        self.on_email_timeout = on_email_timeout
        self.task_id = ""
        self.auto_close = False
        self.state_analyzer = RKPageStateAnalyzer()
        self.checkpoint_runner: CheckpointRunner | None = None
        self.ctx: MexcBrowserContext | None = None
        self.email_code = ""
        self._submission_attempted = False
        self._form_document_id = None
        self.allow_resubmit_after_review = allow_resubmit_after_review
        self.debug = MexcRegistrationDebug(
            account_email=self.account.email,
            secrets=(self.account.password,),
            root_dir="logs/mexc_risk_control",
        )

    def prepare(self):
        from automation.input_bundle import prepare_uploads
        from storage.constants import BASE_DIR
        copied = prepare_uploads({
            'address': self.address_pdf_paths,
            'occupation': self.occupation_pdf_paths,
            'deposits': self.deposit_screenshot_paths,
        }, BASE_DIR / '.operation_inputs')
        self.address_pdf_paths = copied['address']
        self.occupation_pdf_paths = copied['occupation']
        self.deposit_screenshot_paths = copied['deposits']
        self.address_pdf_path = next(iter(self.address_pdf_paths), None)
        self.occupation_pdf_path = next(iter(self.occupation_pdf_paths), None)

    def run(self) -> ScenarioResult:
        if not self.account.password:
            raise RuntimeError("Save the MEXC account password first.")
        if not self.email_fetcher:
            raise RuntimeError("Email fetcher is not configured")

        self.debug.bind_task(self.task_id)
        self.debug.with_secrets(self.account.password)
        self.debug.step(
            "rk_submit_start",
            address_pdf_count=len(self.address_pdf_paths),
            occupation_pdf_count=len(self.occupation_pdf_paths),
            deposit_screenshot_count=len([p for p in self.deposit_screenshot_paths if p.exists()]),
            has_occupation_text=bool(self.occupation_details_text),
            has_deposit_text=bool(self.deposit_source_text),
            deposit_source_type=self.deposit_source_type_text,
        )
        self.ctx = self._build_context()

        try:
            self.state_analyzer.bind(self.driver, self.debug)
            if not is_rk_url(self.driver.current_url):
                self._open_rk_form()
            previous = read_submission_state(self.account_dir)
            if previous.get('status') in {'pending', 'unknown'} and not self.allow_resubmit_after_review:
                self._ensure_logged_in()
                self._wait_for_rk_form()
                if not self._submitted_visible():
                    raise RKSubmissionUnknown('Previous submission status is unknown. Review the RK page before allowing a new submission.')
            else:
                self._run_checkpoints()
        except (RKSubmissionRejected, RKSubmissionUnknown) as exc:
            status = 'rejected' if isinstance(exc, RKSubmissionRejected) else 'unknown'
            write_submission_state(self.account_dir, status, self.task_id, str(exc))
            self.debug.warning('rk_submit_' + status, reason=str(exc))
            self.debug.save_failure_artifacts(self.driver, str(exc))
            return ScenarioResult(False, str(exc), {'account_email': self.account.email, 'application_status': status})
        except Exception as exc:
            self.debug.warning("rk_submit_failed", reason=str(exc))
            if self.driver:
                self.debug.save_failure_artifacts(self.driver, str(exc))
            if self._submission_attempted and read_submission_state(self.account_dir).get('status') == 'pending':
                message = 'Submission status is unknown after an interruption. Check the RK page before submitting again.'
                write_submission_state(self.account_dir, 'unknown', self.task_id, message)
                return ScenarioResult(False, message, {'account_email': self.account.email, 'application_status': 'unknown'})
            raise

        write_submission_state(self.account_dir, "submitted", self.task_id)
        self.debug.step("rk_submit_success")
        return ScenarioResult(
            success=True,
            message=f"Заявку РК подано для {self.debug.masked_email}. Очікується перевірка документів MEXC; це ще не схвалення.",
            data={"account_email": self.account.email, "application_status": "submitted", "document_review_status": "pending"},
        )

    def _build_context(self) -> MexcBrowserContext:
        return MexcBrowserContext(
            driver=self.driver,
            account=self.account,
            debug=self.debug,
            email_fetcher=self.email_fetcher,
            captcha_service=self.captcha_service,
            task_id=self.task_id,
            on_captcha_detected=self.on_captcha_detected,
            on_email_timeout=self.on_email_timeout,
            manual_assist_handler=self.manual_assist_handler,
            network_recovery_handler=self.network_recovery_handler,
            state_analyzer=self.state_analyzer,
            cancel_event=self.cancel_event,
            cancel_checker=self.browser_is_closed,
        )

    def _start_browser(self):
        started = time.monotonic()
        self.debug.step('rk_browser_attach_start')
        super()._start_browser()
        self.debug.step('rk_browser_attach_done', elapsed_ms=round((time.monotonic() - started) * 1000))

    def _run_checkpoints(self) -> None:
        runner = CheckpointRunner(
            driver_getter=lambda: self.driver,
            analyzer=self.state_analyzer,
            debug=self.debug,
            manual_assist_handler=self.manual_assist_handler,
            network_recovery_handler=self.network_recovery_handler,
            captcha_handler=lambda checkpoint: self._handle_captcha(f"{checkpoint}_captcha"),
            scenario_name=type(self).__name__,
        )
        self.checkpoint_runner = runner
        try:
            runner.run(self._checkpoints())
        except RKEmailCodeRejected:
            # Explicit code rejection confirms no application was accepted; one retry only.
            self.debug.warning('rk_email_code_retry')
            self._submission_attempted = False
            self._confirmation_attempted = False
            self._request_email_code()
            self._fill_email_code()
            self._submit_application()
            self._verify_submitted()

    def _checkpoints(self) -> list[ScenarioCheckpoint]:
        form_states = {
            "risk_control_form",
            "risk_control_unavailable",
            "risk_control_submitted",
        }
        checkpoints = [
            ScenarioCheckpoint(
                name="open_rk_form",
                initial_navigation=True,
                action=self._open_rk_form,
                allowed_states={
                    "unknown",
                    "login",
                    "register_completed",
                    "network_loading",
                    "network_error",
                    "wrong_browser_tab",
                    "api_form",
                    "api_created",
                    "twofa_completed",
                    "twofa_intro",
                    "twofa_secret",
                    "security_modal_email",
                    "security_modal_totp",
                },
                done_states=form_states,
                recover_wrong_tab=self._open_rk_form,
            ),
            ScenarioCheckpoint(
                name="ensure_login",
                action=self._ensure_logged_in,
                allowed_states={"login", "unknown", "network_loading", "network_error"},
                done_states=form_states,
                recover_wrong_tab=self._open_rk_form,
                action_already_handles_captcha=True,
            ),
            ScenarioCheckpoint(
                name="wait_rk_form",
                action=self._wait_for_rk_form,
                allowed_states=form_states,
                done_states={"risk_control_submitted"},
                recover_wrong_tab=self._open_rk_form,
            ),
            ScenarioCheckpoint(
                name="verify_review_checks",
                action=self._verify_review_checks,
                allowed_states={"risk_control_form"},
                done_states={"risk_control_submitted"},
                recover_wrong_tab=self._open_rk_form,
            ),
            ScenarioCheckpoint(
                name="request_email_code",
                action=self._request_email_code,
                allowed_states={"risk_control_form"},
                done_states={"risk_control_submitted"},
                recover_wrong_tab=self._open_rk_form,
            ),
            ScenarioCheckpoint(
                name="fill_documents",
                action=self._fill_documents,
                allowed_states={"risk_control_form"},
                done_states={"risk_control_submitted"},
                recover_wrong_tab=self._open_rk_form,
            ),
            ScenarioCheckpoint(
                name="fill_email_code",
                action=self._fill_email_code,
                allowed_states={"risk_control_form"},
                done_states={"risk_control_submitted"},
                recover_wrong_tab=self._open_rk_form,
            ),
            ScenarioCheckpoint(
                name="submit_application",
                action=self._submit_application,
                allowed_states={"risk_control_form"},
                done_states={"risk_control_submitted"},
                recover_wrong_tab=self._open_rk_form,
            ),
            ScenarioCheckpoint(
                name="verify_submitted",
                action=self._verify_submitted,
                allowed_states={"risk_control_form", "risk_control_submitted", "unknown"},
                done_states={"risk_control_submitted"},
                recover_wrong_tab=self._open_rk_form,
                min_confidence=0.2,
            ),
        ]
        safe_steps = {'wait_rk_form', 'verify_review_checks', 'request_email_code', 'fill_documents', 'fill_email_code'}
        return [replace(cp, action=lambda cp=cp: self._run_recoverable_step(cp.name, cp.action))
                if cp.name in safe_steps else cp for cp in checkpoints]

    def _open_rk_form(self) -> None:
        if self.ctx is None:
            self.ctx = self._build_context()
        self.state_analyzer.open_form(self.driver, self.debug)

    def _ensure_logged_in(self) -> None:
        if self.ctx is None:
            self.ctx = self._build_context()
        ensure_mexc_logged_in(self.ctx, self.FORM_URL, "rk")
        self._handle_captcha("rk_after_login")

    def _wait_for_rk_form(self) -> None:
        self.debug.step("rk_form_wait_start")
        deadline = time.time() + 60
        last_state = None
        while time.time() < deadline:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            state = self.state_analyzer.analyze(self.driver)
            last_state = state
            if state.name == 'login':
                self._ensure_logged_in()
                continue
            if state.name == "risk_control_unavailable" and state.confidence >= 0.72:
                raise RuntimeError("Форма РК недоступна: MEXC перенаправив на оглядову сторінку. Заявку не подано. Перевірте статус акаунта через Apply / Submit Record.")
            if state.name == "risk_control_submitted" and state.confidence >= 0.72:
                self.debug.step("rk_form_already_submitted")
                return
            if state.name == "risk_control_form" and state.confidence >= 0.72:
                self.debug.step("rk_form_wait_done", state=state.name)
                return
            self.control.wait(1)
        self.debug.save_page_probe(self.driver, "rk_form_wait_timeout.json")
        state_name = last_state.name if last_state else "unknown"
        raise RuntimeError(f"MEXC RK form did not load; last screen state was {state_name}.")

    def _verify_review_checks(self) -> None:
        self._raise_if_cancelled()
        self._raise_if_browser_closed()
        checks = self.driver.execute_script(REVIEW_CHECKS_SCRIPT) or {}
        deadline = time.monotonic() + 12
        while self.enforce_facescan_check and not (checks.get('facial') or {}).get('found'):
            if time.monotonic() >= deadline:
                break
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            self.control.wait(0.4)
            checks = self.driver.execute_script(REVIEW_CHECKS_SCRIPT) or {}
        self.debug.step("rk_review_checks_snapshot", **checks)
        try:
            require_review_checks(checks, enforce_facescan=self.enforce_facescan_check)
            if not self.enforce_facescan_check:
                self.debug.step("rk_facescan_check_skipped", reason="disabled_in_settings")
        except RuntimeError:
            self.debug.save_page_probe(self.driver, "rk_review_checks_failed.json")
            raise
        self.debug.step("rk_review_checks_done")

    def _fill_documents(self) -> None:
        if getattr(self, '_documents_filled_during_countdown', False):
            self._documents_filled_during_countdown = False
            self._verify_document_values()
            return
        self.debug.step("rk_documents_fill_start")
        self._save_rk_form_structure_probe("rk_form_structure_before_fill.json")
        self._select_proof_of_address_type()
        self._upload_optional_files(
            ("proof of address",),
            self.address_pdf_paths,
            "rk_proof_address",
        )
        self._upload_optional_files(
            ("occupation details",),
            self.occupation_pdf_paths,
            "rk_occupation",
        )
        self._fill_section_text(
            ("occupation details",),
            self.occupation_details_text,
            "rk_occupation_text",
        )
        self._select_deposit_source_type()
        self._upload_optional_files(
            ("proof of source of last", "last 1-2 deposits", "source of last"),
            self.deposit_screenshot_paths,
            "rk_deposit_source",
        )
        self._fill_section_text(
            ("proof of source of last", "last 1-2 deposits", "source of last"),
            self.deposit_source_text,
            "rk_deposit_source_text",
        )
        self.debug.step("rk_documents_fill_done")
        self._remember_form_document()

    def _save_rk_form_structure_probe(self, filename: str) -> None:
        try:
            data = self.driver.execute_script(
                """
                const visible = (element) => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                const compact = (element) => {
                    const rect = element.getBoundingClientRect();
                    return {
                        tag: element.tagName,
                        id: element.id || '',
                        name: element.getAttribute('name') || '',
                        type: element.getAttribute('type') || '',
                        role: element.getAttribute('role') || '',
                        placeholder: element.getAttribute('placeholder') || '',
                        className: String(element.className || '').slice(0, 160),
                        text: normalize(element.innerText || element.textContent).slice(0, 220),
                        visible: visible(element),
                        rect: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height)
                        }
                    };
                };
                const wanted = /proof of address|occupation details|proof of source|last 1-2 deposits|email verification code/i;
                const roots = [...document.querySelectorAll('.ant-form-item, [class*="form-item"], section, div')]
                    .filter((element) => wanted.test(normalize(element.innerText || element.textContent)))
                    .sort((left, right) => {
                        const a = left.getBoundingClientRect();
                        const b = right.getBoundingClientRect();
                        return (a.y - b.y) || ((a.width * a.height) - (b.width * b.height));
                    })
                    .slice(0, 40);
                return {
                    url: window.location.href,
                    title: document.title,
                    sections: roots.map((root) => ({
                        root: compact(root),
                        inputs: [...root.querySelectorAll('input,textarea')].map(compact),
                        selects: [...root.querySelectorAll('.ant-select, [role="combobox"], input[role="combobox"]')].map(compact),
                        uploads: [...root.querySelectorAll('.ant-upload, [class*="upload"], [class*="Upload"], input[type="file"]')].map(compact),
                        buttons: [...root.querySelectorAll('button,[role="button"],a')].filter(visible).map(compact)
                    }))
                };
                """
            )
            self.debug._write_json(self.debug.artifact_dir / filename, data)
            self.debug.step("rk_form_structure_probe_saved", filename=filename)
        except Exception as exc:
            logger.debug("RK form structure probe failed", exc_info=True)
            self.debug.warning("rk_form_structure_probe_failed", error=str(exc))

    def _rk_check_cancelled(self):
        self._raise_if_cancelled()
        self._raise_if_browser_closed()

    def _raise_if_browser_closed(self):
        super()._raise_if_browser_closed()
        self.state_analyzer.ensure_owned(self.driver)

    def _select_proof_of_address_type(self) -> None:
        RKDropdown(self.driver, self._rk_check_cancelled, self.debug).select(
            "requiredItemId-155-relatedSelect",
            self.address_document_type_text, "rk_proof_address_type",
        )

    def _select_deposit_source_type(self) -> None:
        RKDropdown(self.driver, self._rk_check_cancelled, self.debug).select(
            "requiredItemId-78-relatedSelect", self.deposit_source_type_text,
            "rk_deposit_source_type",
        )

    def _handle_captcha(self, phase: str) -> None:
        if self.ctx is None:
            raise RuntimeError("MEXC context is not initialized")
        raise_if_context_cancelled(self.ctx)
        # The request/submit waits keep probing for late CAPTCHA. No fixed 8s delay.
        if self._captcha_visible():
            handle_mexc_captcha(self.ctx, phase, already_detected=True)
