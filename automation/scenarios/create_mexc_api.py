from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

from automation.base import BaseScenario, ScenarioResult
from automation.checkpoints import CheckpointRunner, ScenarioCheckpoint
from automation.scenarios.mexc_browser_helpers import (
    MexcBrowserContext,
    click_get_code_if_active,
    click_security_submit,
    collect_error_text,
    ensure_mexc_logged_in,
    fill_named_code_input,
    find_totp_input,
    fresh_totp_code,
    handle_mexc_captcha,
    open_mexc_page,
    security_modal_text,
    wait_mexc_email_code,
    clear_and_type,
)
from automation.scenarios.mexc_debug import MexcRegistrationDebug
from automation.scenarios.mexc_state import MexcPageStateAnalyzer

logger = logging.getLogger(__name__)


class CreateMexcApiScenario(BaseScenario):
    """Create a MEXC API key and return it for saving in the desktop app."""

    OPENAPI_URL = "https://www.mexc.com/user/openapi"
    NOTE_TEXT = "trading"

    def __init__(
        self,
        adspower,
        account,
        captcha_service=None,
        email_fetcher=None,
        on_captcha_detected: Callable[[str], None] | None = None,
        on_email_timeout: Callable[[str], bool] | None = None,
    ):
        super().__init__(adspower, account, captcha_service)
        self.email_fetcher = email_fetcher
        self.on_captcha_detected = on_captcha_detected
        self.on_email_timeout = on_email_timeout
        self.task_id = ""
        self.auto_close = False
        self.state_analyzer = MexcPageStateAnalyzer()
        self.checkpoint_runner: CheckpointRunner | None = None
        self.api_key = ""
        self.secret_key = ""
        self.debug = MexcRegistrationDebug(
            account_email=self.account.email,
            secrets=(self.account.password, self.account.two_fa_secret),
            root_dir="logs/mexc_api",
        )
        self.ctx: MexcBrowserContext | None = None

    def run(self) -> ScenarioResult:
        if not self.account.password:
            raise RuntimeError("Account has no saved password for automatic MEXC login")
        if not self.account.two_fa_secret:
            raise RuntimeError("Account has no saved 2FA secret. Link 2FA first.")
        if not self.email_fetcher:
            raise RuntimeError("Email fetcher is not configured")

        self.debug.bind_task(self.task_id)
        self.debug.with_secrets(self.account.password, self.account.two_fa_secret)
        self.debug.step("api_create_start")

        self.ctx = self._build_context()

        try:
            self._run_api_checkpoints()
        except Exception as exc:
            self.debug.warning("api_create_failed", reason=str(exc))
            if self.driver:
                self.debug.save_failure_artifacts(self.driver, str(exc))
            raise

        self.debug.step("api_create_success", api_key_found=bool(self.api_key), secret_key_found=bool(self.secret_key))
        return ScenarioResult(
            success=True,
            message=f"MEXC API key created for {self.debug.masked_email}",
            data={
                "account_email": self.account.email,
                "api_key": self.api_key,
                "secret_key": self.secret_key,
            },
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

    def _run_api_checkpoints(self) -> None:
        runner = CheckpointRunner(
            driver_getter=lambda: self.driver,
            analyzer=self.state_analyzer,
            debug=self.debug,
            manual_assist_handler=self.manual_assist_handler,
            network_recovery_handler=self.network_recovery_handler,
            captcha_handler=lambda checkpoint: self._handle_captcha(f"{checkpoint}_captcha"),
        )
        self.checkpoint_runner = runner
        runner.run(self._api_checkpoints())

    def _api_checkpoints(self) -> list[ScenarioCheckpoint]:
        form_states = {"api_form", "security_modal_email", "security_modal_totp", "api_created"}
        security_states = {"security_modal_email", "security_modal_totp", "api_created"}
        return [
            ScenarioCheckpoint(
                name="open_api_page",
                action=self._open_api_page,
                allowed_states={
                    "unknown",
                    "login",
                    "register_completed",
                    "twofa_completed",
                    "network_loading",
                    "network_error",
                    "wrong_browser_tab",
                },
                done_states=form_states,
                recover_wrong_tab=self._open_api_page,
            ),
            ScenarioCheckpoint(
                name="ensure_login",
                action=self._ensure_logged_in,
                allowed_states={"login", "unknown", "network_loading", "network_error"},
                done_states=form_states,
                recover_wrong_tab=self._open_api_page,
                action_already_handles_captcha=True,
            ),
            ScenarioCheckpoint(
                name="wait_api_form",
                action=self._wait_for_api_form,
                allowed_states={"api_form"},
                done_states=security_states,
                recover_wrong_tab=self._open_api_page,
            ),
            ScenarioCheckpoint(
                name="prepare_api_form",
                action=self._prepare_api_form,
                allowed_states={"api_form"},
                done_states=security_states,
                recover_wrong_tab=self._open_api_page,
            ),
            ScenarioCheckpoint(
                name="submit_api_create",
                action=self._click_create,
                allowed_states={"api_form"},
                done_states=security_states,
                recover_wrong_tab=self._open_api_page,
            ),
            ScenarioCheckpoint(
                name="security_verification",
                action=self._complete_security_verification,
                allowed_states={"security_modal_email", "security_modal_totp"},
                done_states={"api_created"},
                recover_wrong_tab=self._open_api_page,
            ),
            ScenarioCheckpoint(
                name="extract_api_keys",
                action=self._extract_and_store_api_keys,
                allowed_states={"api_created"},
                done_states=set(),
                recover_wrong_tab=self._open_api_page,
            ),
            ScenarioCheckpoint(
                name="confirm_keys_saved",
                action=self._confirm_keys_copied,
                allowed_states={"api_created", "api_form", "unknown"},
                done_states=set(),
                recover_wrong_tab=self._open_api_page,
                min_confidence=0.2,
            ),
        ]

    def _open_api_page(self) -> None:
        if self.ctx is None:
            self.ctx = self._build_context()
        open_mexc_page(self.ctx, self.OPENAPI_URL, "api")

    def _ensure_logged_in(self) -> None:
        if self.ctx is None:
            self.ctx = self._build_context()
        ensure_mexc_logged_in(self.ctx, self.OPENAPI_URL, "api")
        handle_mexc_captcha(self.ctx, "after_login")

    def _prepare_api_form(self) -> None:
        self._set_exact_permissions()
        self._fill_note()
        self._accept_risk_reminder()

    def _extract_and_store_api_keys(self) -> None:
        self.api_key, self.secret_key = self._extract_api_keys()
        self.debug.with_secrets(self.api_key, self.secret_key)

    def _wait_for_api_form(self) -> None:
        self.debug.step("api_form_wait_start")
        deadline = time.time() + 90
        refreshed = False
        last_state = {}
        while time.time() < deadline:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            state = self.driver.execute_script(
                """
                const visible = (element) => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const permissionInputs = [...document.querySelectorAll('input[type="checkbox"]')]
                    .filter((input) => /^(SPOT|CONTRACT|P2P)_/.test(input.value || ''));
                const memo = document.querySelector('input#memo, textarea#memo');
                const createButton = [...document.querySelectorAll('button,[role="button"]')]
                    .find((button) => visible(button) && /create/i.test(button.innerText || button.textContent || ''));
                const loader = [...document.querySelectorAll('[class*="MBiz__wrapper"], [class*="loading"], [class*="spin"]')]
                    .some(visible);
                return {
                    memo: Boolean(memo),
                    permissionCount: permissionInputs.length,
                    createButton: Boolean(createButton),
                    loader,
                    title: document.title,
                    url: window.location.href,
                    bodyHint: (document.body?.innerText || '').replace(/\\s+/g, ' ').slice(0, 300)
                };
                """
            )
            last_state = state if isinstance(state, dict) else {}
            if last_state.get("memo") and int(last_state.get("permissionCount") or 0) >= 6:
                self.debug.step(
                    "api_form_wait_done",
                    permission_count=last_state.get("permissionCount"),
                    create_button=last_state.get("createButton"),
                )
                return
            if not refreshed and time.time() > deadline - 45:
                self.debug.warning("api_form_wait_refresh", state=last_state)
                self.driver.refresh()
                refreshed = True
                time.sleep(5)
                continue
            time.sleep(1)

        self.debug.save_page_probe(self.driver, "api_form_wait_timeout.json")
        raise RuntimeError(f"MEXC API form did not load: {last_state}")

    def _set_exact_permissions(self) -> None:
        self.debug.step("api_permissions_set_start")
        desired_values = {
            "SPOT_ACCOUNT_R",
            "SPOT_ACCOUNT_W",
            "SPOT_DEAL_R",
            "SPOT_DEAL_W",
            "CONTRACT_ACCOUNT_R",
            "CONTRACT_DEAL_R",
        }
        total_changes = 0
        attempts = 0
        last_seen = []
        while attempts < 20:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            result = self.driver.execute_script(
                """
                const desiredValues = new Set(arguments[0]);
                const permissionPrefixes = ['SPOT_', 'CONTRACT_', 'P2P_'];
                const visible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const isPermissionInput = (input) => {
                    const value = input.value || '';
                    return permissionPrefixes.some((prefix) => value.startsWith(prefix));
                };
                const checked = (input) => {
                    const label = input.closest('label');
                    const classText = [label, ...((label && [...label.querySelectorAll('[class*="checkbox"]')]) || [])]
                        .filter(Boolean)
                        .map((element) => String(element.className || '').toLowerCase())
                        .join(' ');
                    return Boolean(input?.checked || classText.includes('checked'));
                };
                const clickInput = (input) => {
                    const label = input.closest('label');
                    const target = label || input.closest('.ant-checkbox-v2') || input;
                    target.scrollIntoView({ block: 'center', inline: 'center' });
                    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
                    target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
                    target.click();
                };
                const inputs = [...document.querySelectorAll('input[type="checkbox"]')]
                    .filter(isPermissionInput)
                    .filter((input) => visible(input) || visible(input.closest('label') || input));
                const seen = [];
                for (const input of inputs) {
                    const value = input.value || '';
                    const label = input.closest('label');
                    const text = (label?.innerText || label?.textContent || '').replace(/\\s+/g, ' ').trim();
                    const desired = desiredValues.has(value);
                    const current = checked(input);
                    seen.push({ value, text, desired, current });
                    if (current !== desired) {
                        clickInput(input);
                        return { clicked: true, seen, change: { value, text, desired } };
                    }
                }
                return { clicked: false, seen, change: null };
                """,
                list(desired_values),
            )
            attempts += 1
            if isinstance(result, dict):
                last_seen = result.get("seen", [])
                if result.get("clicked"):
                    total_changes += 1
                    time.sleep(0.45)
                    continue
            break

        final_state = self.driver.execute_script(
            """
            const desiredValues = new Set(arguments[0]);
            const permissionPrefixes = ['SPOT_', 'CONTRACT_', 'P2P_'];
            const visible = (element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none';
            };
            const isPermissionInput = (input) => {
                const value = input.value || '';
                return permissionPrefixes.some((prefix) => value.startsWith(prefix));
            };
            const checked = (input) => {
                const label = input.closest('label');
                const classText = [label, ...((label && [...label.querySelectorAll('[class*="checkbox"]')]) || [])]
                    .filter(Boolean)
                    .map((element) => String(element.className || '').toLowerCase())
                    .join(' ');
                return Boolean(input?.checked || classText.includes('checked'));
            };
            const missing = [];
            const unwanted = [];
            const inputs = [...document.querySelectorAll('input[type="checkbox"]')]
                .filter(isPermissionInput)
                .filter((input) => visible(input) || visible(input.closest('label') || input));
            for (const input of inputs) {
                const value = input.value || '';
                const label = input.closest('label');
                const text = (label?.innerText || label?.textContent || '').replace(/\\s+/g, ' ').trim();
                const desired = desiredValues.has(value);
                const current = checked(input);
                if (desired && !current) missing.push({ value, text });
                if (!desired && current) unwanted.push({ value, text });
            }
            return { missing, unwanted };
            """,
            list(desired_values),
        )
        selected = [
            f"{item.get('value')}:{item.get('text')}"
            for item in last_seen
            if item.get("desired")
        ]
        self.debug.step(
            "api_permissions_set_done",
            changed_count=total_changes,
            attempts=attempts,
            selected=selected,
        )
        missing = final_state.get("missing", []) if isinstance(final_state, dict) else []
        unwanted = final_state.get("unwanted", []) if isinstance(final_state, dict) else []
        if missing or unwanted:
            self.debug.warning("api_permissions_verify_failed", missing=missing, unwanted=unwanted)
            raise RuntimeError(f"MEXC API permissions were not set exactly: missing={missing}, unwanted={unwanted}")

    def _fill_note(self) -> None:
        self.debug.step("api_note_fill_start")
        element = None
        deadline = time.time() + 30
        while time.time() < deadline and element is None:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            element = self.driver.execute_script(
                """
                const visible = (element) => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && !element.disabled;
                };
                const memo = document.querySelector('input#memo, textarea#memo');
                if (memo && visible(memo)) return memo;
                return [...document.querySelectorAll('input,textarea')]
                    .filter(visible)
                    .find((element) => /note|memo/i.test([
                        element.id,
                        element.name,
                        element.placeholder,
                        element.closest('.ant-form-item, .ant-row, label, div')?.innerText
                    ].join(' ')))
                    || null;
                """
            )
            if element is None:
                time.sleep(0.5)
        if element is None:
            self.debug.save_page_probe(self.driver, "api_note_field_not_found.json")
            raise RuntimeError("MEXC API notes field was not found")
        clear_and_type(self.driver, element, self.NOTE_TEXT)
        self.debug.step("api_note_filled")

    def _accept_risk_reminder(self) -> None:
        self.debug.step("api_risk_accept_start")
        clicked = self.driver.execute_script(
            """
            const visible = (element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none';
            };
            const input = document.querySelector('input#agreed');
            const target = input?.closest('label') || input;
            if (!input || input.checked) return Boolean(input);
            target.scrollIntoView({ block: 'center', inline: 'center' });
            target.click();
            return true;
            """
        )
        if not clicked:
            raise RuntimeError("MEXC API risk agreement checkbox was not found")
        time.sleep(1)
        self.debug.step("api_risk_accepted")

    def _click_create(self) -> None:
        self.debug.step("api_create_click_start")
        clicked = self.driver.execute_script(
            """
            const visible = (element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && style.pointerEvents !== 'none';
            };
            const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const candidates = [...document.querySelectorAll('button,[role="button"]')]
                .filter(visible)
                .filter((button) => {
                    const text = normalize(button.innerText || button.textContent);
                    return text === 'create' || text.includes('create');
                });
            for (const button of candidates) {
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
            raise RuntimeError("MEXC API Create button was not found or is disabled")
        time.sleep(2)
        self.debug.step("api_create_clicked")

    def _complete_security_verification(self) -> None:
        if self.ctx is None:
            raise RuntimeError("MEXC context is not initialized")
        self.debug.step("api_security_verification_start")
        self._raise_if_cancelled()
        self._raise_if_browser_closed()

        if self._api_email_step_visible() or not self._api_totp_step_visible():
            if not click_get_code_if_active(self.ctx, timeout=30):
                if self._api_totp_step_visible():
                    self.debug.step("api_email_step_already_done")
                elif self._api_keys_created_visible():
                    self.debug.step("api_security_verification_done", mode="already_created")
                    return
                else:
                    raise RuntimeError("MEXC API Get Code button was not found or was not clickable")
            else:
                self._handle_captcha("api_security_after_get_code")

                email_code = wait_mexc_email_code(self.ctx)
                self.ctx.tried_email_codes.add(email_code)
                if not self._fill_api_email_code(email_code):
                    raise RuntimeError("MEXC API email verification input was not found")
                self.debug.step("api_email_code_filled")

                if self._api_totp_step_visible():
                    self.debug.step("api_email_totp_combined_modal")
                else:
                    if not click_security_submit(self.driver, ("submit", "confirm", "next")):
                        raise RuntimeError("MEXC API email verification Submit button was not found")
                    self._handle_captcha("api_security_after_email_submit")
                    time.sleep(3)
                    if self._api_keys_created_visible() or not self._security_modal_visible():
                        self.debug.step("api_security_verification_done", mode="email_only")
                        return

        last_error = ""
        for attempt in range(1, 4):
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            self.debug.step("api_totp_attempt_start", attempt=attempt)
            totp_code = fresh_totp_code(self.account.two_fa_secret, self.debug, "api_totp")
            totp_input = self._find_api_totp_input()
            if totp_input is None:
                raise RuntimeError("MEXC API authenticator code input was not found")
            clear_and_type(self.driver, totp_input, totp_code)
            self.debug.step("api_totp_code_filled", attempt=attempt)
            if not click_security_submit(self.driver, ("submit", "confirm")):
                raise RuntimeError("MEXC API security verification Submit button was not found")
            self._handle_captcha("api_security_after_totp_submit")
            time.sleep(4)

            if self._api_keys_created_visible() or not self._security_modal_visible():
                self.debug.step("api_security_verification_done", attempt=attempt)
                return

            last_error = collect_error_text(self.driver) or security_modal_text(self.driver)
            if not self._is_retryable_totp_error(last_error):
                break
            self.debug.warning("api_totp_retry", attempt=attempt, error=last_error)

        raise RuntimeError(last_error or "MEXC API security verification was not accepted")

    def _fill_api_email_code(self, email_code: str) -> bool:
        email_input = self._find_security_input_by_id("emailCode")
        if email_input is not None:
            clear_and_type(self.driver, email_input, email_code)
            return True
        return fill_named_code_input(self.driver, email_code, ("email", "mail"), security_modal_only=True)

    def _find_api_totp_input(self):
        return self._find_security_input_by_id("googleAuthCode") or find_totp_input(
            self.driver,
            security_modal_only=True,
        )

    def _api_email_step_visible(self) -> bool:
        if self._find_security_input_by_id("emailCode") is not None:
            return True
        try:
            return bool(
                self.driver.execute_script(
                    """
                    const visible = (element) => {
                        const rect = element.getBoundingClientRect();
                        const style = window.getComputedStyle(element);
                        return rect.width > 0 && rect.height > 0
                            && style.visibility !== 'hidden'
                            && style.display !== 'none'
                            && !element.disabled;
                    };
                    const modal = [...document.querySelectorAll('.ant-modal-content, .ant-modal, [role="dialog"], .modal')]
                        .filter(visible)
                        .at(-1);
                    const root = modal || document.body;
                    const text = (root.innerText || root.textContent || '').toLowerCase();
                    const inputs = [...root.querySelectorAll('input,textarea')]
                        .filter(visible)
                        .map((input) => [
                            input.id,
                            input.name,
                            input.placeholder,
                            input.getAttribute('aria-label'),
                            input.closest('.ant-form-item, label, div')?.innerText
                        ].join(' ').toLowerCase());
                    return text.includes('email verification')
                        || text.includes('email code')
                        || inputs.some((value) => value.includes('email') || value.includes('mail'));
                    """
                )
            )
        except Exception:
            return False

    def _api_totp_step_visible(self) -> bool:
        return self._find_api_totp_input() is not None

    def _api_keys_created_visible(self) -> bool:
        try:
            state = self.state_analyzer.analyze(self.driver)
            return state.name == "api_created" and state.confidence >= 0.72
        except Exception:
            return False

    def _find_security_input_by_id(self, element_id: str):
        try:
            return self.driver.execute_script(
                """
                const id = arguments[0];
                const visible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && !element.disabled;
                };
                const modals = [...document.querySelectorAll('.ant-modal-content, .ant-modal, [role="dialog"], .modal')]
                    .filter(visible);
                for (let index = modals.length - 1; index >= 0; index -= 1) {
                    const input = modals[index].querySelector(`input#${CSS.escape(id)}`);
                    if (input && visible(input)) return input;
                }
                const input = document.querySelector(`input#${CSS.escape(id)}`);
                return input && visible(input) ? input : null;
                """,
                element_id,
            )
        except Exception:
            logger.debug("MEXC API security input lookup failed id=%s", element_id, exc_info=True)
            return None

    def _security_modal_visible(self) -> bool:
        try:
            return bool(
                self.driver.execute_script(
                    """
                    const visible = (element) => {
                        const rect = element.getBoundingClientRect();
                        const style = window.getComputedStyle(element);
                        return rect.width > 0 && rect.height > 0
                            && style.visibility !== 'hidden'
                            && style.display !== 'none';
                    };
                    return [...document.querySelectorAll('.ant-modal, .ant-modal-v2, [role="dialog"], [class*="modal"]')]
                        .some((element) => visible(element) && /security verification/i.test(element.innerText || element.textContent || ''));
                    """
                )
            )
        except Exception:
            return False

    @staticmethod
    def _is_retryable_totp_error(text: str) -> bool:
        value = (text or "").lower()
        retry_words = (
            "authenticator",
            "google",
            "2fa",
            "totp",
            "verification code",
            "invalid",
            "expired",
            "incorrect",
            "code error",
        )
        return any(word in value for word in retry_words)

    def _extract_api_keys(self) -> tuple[str, str]:
        self.debug.step("api_key_extract_start")
        deadline = time.time() + 60
        last_snapshot = {}
        while time.time() < deadline:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
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
                const textOf = (element) => (element?.innerText || element?.textContent || '').trim();
                const modals = [...document.querySelectorAll('.ant-modal-content, .ant-modal, [role="dialog"]')]
                    .filter(visible);
                const createdModal = [...modals].reverse().find((modal) =>
                    /created\\s+successfully|access\\s+key|secret\\s+key/i.test(textOf(modal))
                );
                const root = createdModal || document.body;
                const pageText = root ? textOf(root) : '';
                const inputs = [...root.querySelectorAll('input,textarea')]
                    .filter(visible)
                    .map((element) => element.value || '')
                    .filter(Boolean);
                const sections = [...root.querySelectorAll('section')]
                    .filter(visible)
                    .map((section) => ({
                        label: textOf(section.querySelector('h1,h2,h3,h4,h5,h6,label')),
                        value: textOf(section.querySelector('p,input,textarea')),
                        text: textOf(section),
                    }))
                    .filter((section) => section.label || section.value || section.text);
                const labelBlocks = [...root.querySelectorAll('div,li,p,span,label,h1,h2,h3,h4,h5,h6')]
                    .filter(visible)
                    .map((element) => textOf(element))
                    .filter(Boolean)
                    .slice(-500);
                const attributeValues = [...root.querySelectorAll('*')]
                    .flatMap((element) => [
                        element.getAttribute('data-clipboard-text'),
                        element.getAttribute('data-copy'),
                        element.getAttribute('data-value'),
                        element.getAttribute('title'),
                        element.getAttribute('aria-label'),
                    ])
                    .filter(Boolean);
                return {
                    pageText,
                    inputs,
                    sections,
                    labelBlocks,
                    attributeValues,
                    modalFound: Boolean(createdModal),
                };
                """
            )
            last_snapshot = data if isinstance(data, dict) else {}
            api_key, secret_key = self._parse_keys(last_snapshot)
            if api_key and secret_key:
                self.debug.step("api_key_extract_done", api_key_length=len(api_key), secret_key_length=len(secret_key))
                return api_key, secret_key
            time.sleep(1)

        self.debug.warning(
            "api_key_extract_timeout",
            has_page_text=bool(last_snapshot.get("pageText")),
            inputs_count=len(last_snapshot.get("inputs", [])) if isinstance(last_snapshot, dict) else 0,
            sections_count=len(last_snapshot.get("sections", [])) if isinstance(last_snapshot, dict) else 0,
            modal_found=bool(last_snapshot.get("modalFound")) if isinstance(last_snapshot, dict) else False,
        )
        raise RuntimeError("MEXC API key and secret key were not found after creation")

    def _parse_keys(self, data: dict) -> tuple[str, str]:
        candidates: list[str] = []
        page_text = str(data.get("pageText") or "")
        candidates.append(page_text)
        candidates.extend(str(value) for value in data.get("inputs", []) if value)
        candidates.extend(str(value) for value in data.get("attributeValues", []) if value)
        candidates.extend(str(value) for value in data.get("labelBlocks", []) if value)

        api_key = ""
        secret_key = ""
        for section in data.get("sections", []) or []:
            if not isinstance(section, dict):
                continue
            label = str(section.get("label") or section.get("text") or "")
            value = self._extract_key_token(str(section.get("value") or ""))
            if not value:
                value = self._find_token_after_label(str(section.get("text") or ""), "")
            label_lower = label.lower()
            if value and not api_key and ("access key" in label_lower or "api key" in label_lower):
                api_key = value
            if value and not secret_key and "secret key" in label_lower:
                secret_key = value
            if api_key and secret_key:
                return api_key, secret_key

        key_pattern = r"([A-Za-z0-9._\-]{16,160})"
        for text in candidates:
            compact = re.sub(r"\s+", " ", text)
            if not api_key:
                api_key = self._find_token_after_label(compact, r"(?:api|access)\s*key")
            if not secret_key:
                secret_key = self._find_token_after_label(compact, r"secret\s*key")
            if api_key and secret_key:
                break
            if not api_key:
                match = re.search(r"api\s*key\s*[:：]?\s*" + key_pattern, compact, re.IGNORECASE)
                if match:
                    api_key = match.group(1)
            if not secret_key:
                match = re.search(r"secret\s*key\s*[:：]?\s*" + key_pattern, compact, re.IGNORECASE)
                if match:
                    secret_key = match.group(1)
            if api_key and secret_key:
                break

        if not api_key or not secret_key:
            long_values = [
                value.strip()
                for value in candidates
                if self._looks_like_key_token(value.strip() or "")
            ]
            if not api_key and long_values:
                api_key = long_values[0]
            if not secret_key and len(long_values) > 1:
                secret_key = long_values[1]
        return api_key, secret_key

    def _find_token_after_label(self, text: str, label_pattern: str) -> str:
        if not text:
            return ""
        if label_pattern:
            clean_match = re.search(
                label_pattern + r"\s*[:：]?\s*([A-Za-z0-9._\-]{16,160})",
                text,
                re.IGNORECASE,
            )
            if clean_match and self._looks_like_key_token(clean_match.group(1)):
                return clean_match.group(1)
            match = re.search(
                label_pattern + r"\s*[:：пјљ]?\s*([A-Za-z0-9._\-]{16,160})",
                text,
                re.IGNORECASE,
            )
            if match and self._looks_like_key_token(match.group(1)):
                return match.group(1)

        lines = [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]
        for index, line in enumerate(lines):
            if label_pattern and not re.search(label_pattern, line, re.IGNORECASE):
                continue
            if not label_pattern:
                token = self._extract_key_token(line)
                if token:
                    return token
            for nearby in lines[index : index + 4]:
                token = self._extract_key_token(nearby)
                if token:
                    return token
        return ""

    def _extract_key_token(self, text: str) -> str:
        for match in re.finditer(r"[A-Za-z0-9._\-]{16,160}", text or ""):
            token = match.group(0).strip("._-")
            if self._looks_like_key_token(token):
                return token
        return ""

    @staticmethod
    def _looks_like_key_token(value: str) -> bool:
        if not value or "*" in value:
            return False
        if not re.fullmatch(r"[A-Za-z0-9._\-]{16,160}", value):
            return False
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            return False
        lowered = value.lower()
        blocked_fragments = (
            "mexc.com",
            "static.",
            "http",
            "apikey",
            "api-key",
            "secretkey",
            "openapi",
            "checkbox",
            "module",
        )
        return not any(fragment in lowered for fragment in blocked_fragments)

    def _confirm_keys_copied(self) -> None:
        self.debug.step("api_confirm_copied_start")
        clicked = self.driver.execute_script(
            """
            const visible = (element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && style.pointerEvents !== 'none';
            };
            const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const checkbox = [...document.querySelectorAll('label')]
                .filter(visible)
                .find((label) => /copied|backup|saved|read|agree/i.test(label.innerText || label.textContent || ''));
            if (checkbox) {
                const input = checkbox.querySelector('input[type="checkbox"]');
                if (!input || !input.checked) {
                    checkbox.scrollIntoView({ block: 'center', inline: 'center' });
                    checkbox.click();
                }
            }
            const buttons = [...document.querySelectorAll('button,[role="button"]')]
                .filter(visible)
                .filter((button) => {
                    const text = normalize(button.innerText || button.textContent);
                    return ['confirm', 'done', 'ok', 'i have saved', 'i have copied'].some((word) => text.includes(word));
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
            return Boolean(checkbox);
            """
        )
        self.debug.step("api_confirm_copied_done", clicked=bool(clicked))

    def _handle_captcha(self, phase: str) -> None:
        if self.ctx is None:
            raise RuntimeError("MEXC context is not initialized")
        handle_mexc_captcha(self.ctx, phase)
