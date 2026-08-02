from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

import pyotp
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from automation.base import BaseScenario, ScenarioResult
from automation.captcha import detect_captcha, wait_for_captcha_solved
from automation.checkpoints import CheckpointAlreadyComplete, CheckpointRunner, ScenarioCheckpoint
from automation.scenarios.mexc_browser_helpers import MexcBrowserContext, ensure_mexc_logged_in
from automation.scenarios.mexc_debug import MexcRegistrationDebug
from automation.scenarios.mexc_selectors import Locator, MexcRegistrationSelectors
from automation.scenarios.mexc_state import MexcPageStateAnalyzer

logger = logging.getLogger(__name__)


class LinkMexc2faScenario(BaseScenario):
    """Link MEXC/Google Authenticator for an already registered MEXC account."""

    SECURITY_URL = "https://www.mexc.com/user/security/manage-google-auth"

    def __init__(
        self,
        adspower,
        account,
        captcha_service=None,
        email_fetcher=None,
        on_captcha_detected: Callable[[str], None] | None = None,
        on_email_timeout: Callable[[str], bool] | None = None,
        on_secret_found: Callable[[str, str], None] | None = None,
    ):
        super().__init__(adspower, account, captcha_service)
        self.email_fetcher = email_fetcher
        self.on_captcha_detected = on_captcha_detected
        self.on_email_timeout = on_email_timeout
        self.on_secret_found = on_secret_found
        self.selectors = MexcRegistrationSelectors()
        self.task_id = ""
        self.auto_close = False
        self.email_code_not_before_ts: float | None = None
        self.tried_email_codes: set[str] = set()
        self.two_fa_secret = ""
        self.state_analyzer = MexcPageStateAnalyzer()
        self.checkpoint_runner: CheckpointRunner | None = None
        self.debug = MexcRegistrationDebug(
            account_email=self.account.email,
            secrets=(self.account.password, self.account.two_fa_secret),
        )

    def run(self) -> ScenarioResult:
        if not self.account.password:
            raise RuntimeError("Account has no saved password for automatic MEXC login")
        if not self.email_fetcher:
            raise RuntimeError("Email fetcher is not configured")

        self.debug.bind_task(self.task_id)
        self.debug.with_secrets(self.account.password)
        self.debug.step("2fa_start")

        try:
            self._run_2fa_checkpoints()
        except CheckpointAlreadyComplete:
            self.two_fa_secret = self.two_fa_secret or getattr(self.account, "two_fa_secret", "")
            self.debug.step("2fa_success_text_detected")
        except Exception as exc:
            self.debug.warning("2fa_failed", reason=str(exc))
            if self.driver:
                self.debug.save_failure_artifacts(self.driver, str(exc))
            raise

        self.debug.step("2fa_success")
        return ScenarioResult(
            success=True,
            message=f"MEXC 2FA linked for {self.debug.masked_email}",
            data={"two_fa_secret": self.two_fa_secret, "account_email": self.account.email},
        )

    def _run_2fa_checkpoints(self) -> None:
        runner = CheckpointRunner(
            driver_getter=lambda: self.driver,
            analyzer=self.state_analyzer,
            debug=self.debug,
            manual_assist_handler=self.manual_assist_handler,
            network_recovery_handler=self.network_recovery_handler,
            captcha_handler=lambda checkpoint: self._handle_captcha(f"{checkpoint}_captcha"),
            default_terminal_states={"twofa_completed"},
        )
        self.checkpoint_runner = runner
        runner.run(self._2fa_checkpoints())

    def _2fa_checkpoints(self) -> list[ScenarioCheckpoint]:
        terminal = {"twofa_completed"}
        setup_states = {"twofa_intro", "twofa_secret", "security_modal_email", "security_modal_totp", *terminal}
        security_states = {"security_modal_email", "security_modal_totp", *terminal}
        return [
            ScenarioCheckpoint(
                name="open_security_page",
                action=self._open_security_page,
                allowed_states={
                    "unknown",
                    "login",
                    "register_completed",
                    "api_form",
                    "network_loading",
                    "network_error",
                    "wrong_browser_tab",
                },
                done_states=setup_states,
                terminal_states=terminal,
                recover_wrong_tab=self._open_security_page,
            ),
            ScenarioCheckpoint(
                name="ensure_login",
                action=self._ensure_logged_in,
                allowed_states={"login", "unknown", "network_loading", "network_error"},
                done_states=setup_states,
                terminal_states=terminal,
                recover_wrong_tab=self._open_security_page,
                action_already_handles_captcha=True,
            ),
            ScenarioCheckpoint(
                name="download_authenticator",
                action=lambda: self._click_next("download_authenticator"),
                allowed_states={"twofa_intro"},
                done_states={"twofa_secret", *security_states},
                terminal_states=terminal,
                recover_wrong_tab=self._open_security_page,
            ),
            ScenarioCheckpoint(
                name="extract_secret",
                action=self._extract_and_save_secret,
                allowed_states={"twofa_secret"},
                done_states=security_states,
                terminal_states=terminal,
                recover_wrong_tab=self._open_security_page,
            ),
            ScenarioCheckpoint(
                name="backup_key",
                action=lambda: self._click_next("backup_key"),
                allowed_states={"twofa_secret"},
                done_states=security_states,
                terminal_states=terminal,
                recover_wrong_tab=self._open_security_page,
            ),
            ScenarioCheckpoint(
                name="security_verification",
                action=self._complete_security_verification,
                allowed_states={"security_modal_email", "security_modal_totp"},
                done_states=terminal,
                terminal_states=terminal,
                recover_wrong_tab=self._open_security_page,
            ),
            ScenarioCheckpoint(
                name="verify_success",
                action=self._verify_success,
                allowed_states={"security_modal_email", "security_modal_totp", "unknown", "twofa_secret"},
                done_states=terminal,
                terminal_states=terminal,
                recover_wrong_tab=self._open_security_page,
            ),
        ]

    def _extract_and_save_secret(self) -> None:
        self.two_fa_secret = self._extract_two_fa_secret()
        self.debug.with_secrets(self.two_fa_secret)
        self._save_secret_early()

    def _open_security_page(self) -> None:
        self.debug.step("2fa_open_security_page", url=self.SECURITY_URL)
        self.driver.get(self.SECURITY_URL)
        WebDriverWait(self.driver, 30).until(
            lambda driver: driver.execute_script("return document.readyState") == "complete"
        )
        time.sleep(2)
        self.debug.step("2fa_page_loaded", url=self.driver.current_url, title=self.driver.title)

    def _ensure_logged_in(self) -> None:
        ctx = MexcBrowserContext(
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
        ensure_mexc_logged_in(ctx, self.SECURITY_URL, "2fa")
        self.email_code_not_before_ts = ctx.email_code_not_before_ts
        self.tried_email_codes = ctx.tried_email_codes

    def _is_login_required(self) -> bool:
        current_url = (self.driver.current_url or "").lower()
        if "login" in current_url or "sign-in" in current_url:
            return True
        if self._find_visible(self.selectors.password_input, timeout=1) is not None:
            body_text = self._page_text().lower()
            return "log in" in body_text or "login" in body_text or "email" in body_text
        if self._find_visible(self.selectors.email_input, timeout=1) is not None:
            body_text = self._page_text().lower()
            return "log in" in body_text or "login" in body_text
        return False

    def _login(self) -> None:
        self.debug.step("login_email_lookup")
        email_input = self._find_visible(self.selectors.email_input, timeout=20)
        if email_input is not None:
            self._clear_and_type(email_input, self.account.email)
            self.debug.step("login_email_filled")
            self._click_login_continue_if_present()
            time.sleep(2)

        password_input = self._find_visible(self.selectors.password_input, timeout=20)
        if password_input is None:
            raise RuntimeError("MEXC login password input was not found")
        self._clear_and_type(password_input, self.account.password)
        self.debug.step("login_password_filled")

        if not self._click_by_text(("log in", "login", "continue", "next"), timeout=15):
            raise RuntimeError("MEXC login submit button was not found")
        self.debug.step("login_submitted")
        time.sleep(4)

        if self._is_email_code_step_visible():
            self.debug.step("login_email_code_step_detected")
            self._click_get_code_if_active()
            code = self._wait_for_email_code()
            self.tried_email_codes.add(code)
            self._fill_code_inputs(code)
            self._click_by_text(("confirm", "continue", "next", "submit"), timeout=10)
            time.sleep(4)

    def _click_login_continue_if_present(self) -> None:
        clicked = self._click_by_text(("continue", "next"), timeout=4)
        self.debug.step("login_continue_check", clicked=clicked)

    def _click_next(self, phase: str) -> None:
        self.debug.step("2fa_next_click_attempt", phase=phase)
        if not self._click_by_text(("next",), timeout=20):
            raise RuntimeError(f"Next button was not found during {phase}")
        time.sleep(2)
        self.debug.step("2fa_next_clicked", phase=phase, url=self.driver.current_url)

    def _extract_two_fa_secret(self) -> str:
        self.debug.step("2fa_secret_lookup")
        secret = self.driver.execute_script(
            """
            const visible = (element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none';
            };
            const text = [...document.querySelectorAll('body *')]
                .filter(visible)
                .map((element) => element.innerText || element.textContent || '')
                .join('\\n');
            const matches = [...text.matchAll(/\\b[A-Z2-7]{16,64}\\b/g)]
                .map((match) => match[0])
                .filter((value) => !/^(DOWNLOAD|AUTHENTICATOR|SECURITY|VERIFICATION)$/.test(value));
            matches.sort((left, right) => right.length - left.length);
            return matches[0] || '';
            """
        )
        secret = (secret or "").strip().replace(" ", "").upper()
        if not secret:
            self.debug.save_page_probe(self.driver, "2fa_secret_probe_not_found.json")
            raise RuntimeError("MEXC 2FA secret key was not found")
        try:
            pyotp.TOTP(secret).now()
        except Exception as exc:
            raise RuntimeError("MEXC 2FA secret key format is invalid") from exc
        self.debug.step("2fa_secret_found", secret_length=len(secret))
        return secret

    def _save_secret_early(self) -> None:
        self.debug.step("2fa_secret_early_save_attempt")
        if not self.on_secret_found:
            self.debug.warning("2fa_secret_early_save_no_callback")
            return
        self.on_secret_found(self.account.email, self.two_fa_secret)
        self.debug.step("2fa_secret_early_save_done")

    def _ensure_two_fa_secret_available(self) -> None:
        if self.two_fa_secret:
            return
        saved_secret = (getattr(self.account, "two_fa_secret", "") or "").strip()
        if saved_secret:
            self.two_fa_secret = saved_secret
            self.debug.with_secrets(self.two_fa_secret)
            self.debug.step("2fa_secret_reused_from_account", secret_length=len(self.two_fa_secret))
            return
        raise RuntimeError(
            "MEXC 2FA secret key is not available. Return to the backup key step or save the secret before continuing."
        )

    def _complete_security_verification(self) -> None:
        self.debug.step("2fa_security_verification_start")
        self._ensure_two_fa_secret_available()
        if not self._click_get_code_if_active(timeout=30):
            self.debug.save_page_probe(self.driver, "2fa_get_code_not_found.json")
            raise RuntimeError("MEXC 2FA Get Code button was not found or was not clickable")
        self._handle_captcha("2fa_security_after_get_code")

        email_code = self._wait_for_email_code()
        self.tried_email_codes.add(email_code)
        self._fill_email_verification_code(email_code)
        self._click_security_submit("email_code")
        self._handle_captcha("2fa_security_after_email_submit")
        self._wait_for_email_step_to_finish()
        self._wait_for_totp_step()
        self._fill_totp_verification_code()
        self._click_security_submit("totp_code")
        self._handle_captcha("2fa_security_after_totp_submit")
        time.sleep(4)
        self.debug.step("2fa_security_verification_submitted")

    def _fill_email_verification_code(self, email_code: str) -> None:
        self.debug.step("2fa_email_input_lookup")
        if self._fill_named_code_input(email_code, preferred_words=("email", "mail"), security_modal_only=True):
            self.debug.step("2fa_email_input_filled", mode="named_input")
            return
        if self._fill_code_inputs(email_code):
            self.debug.step("2fa_email_input_filled", mode="otp_inputs")
            return
        raise RuntimeError("MEXC email verification input was not found")

    def _wait_for_totp_step(self) -> None:
        self.debug.step("2fa_totp_step_wait_start")
        deadline = time.time() + 30
        while time.time() < deadline:
            if self._is_email_verification_step_visible():
                self.debug.step("2fa_totp_step_waiting_email_still_visible")
                time.sleep(0.5)
                continue
            if self._is_totp_verification_step_visible():
                self.debug.step("2fa_totp_step_detected")
                return
            error_text = self._collect_error_text()
            if error_text:
                raise RuntimeError(error_text)
            time.sleep(0.5)
        self.debug.save_page_probe(self.driver, "2fa_totp_step_timeout.json")
        raise RuntimeError("MEXC Google Authenticator code step did not appear after email verification")

    def _wait_for_email_step_to_finish(self) -> None:
        self.debug.step("2fa_email_step_finish_wait_start")
        deadline = time.time() + 30
        while time.time() < deadline:
            if self._is_totp_verification_step_visible():
                self.debug.step("2fa_email_step_finished", reason="totp_visible")
                return
            if not self._is_email_verification_step_visible():
                self.debug.step("2fa_email_step_finished", reason="email_not_visible")
                return
            error_text = self._collect_error_text()
            if error_text:
                raise RuntimeError(error_text)
            time.sleep(0.5)
        self.debug.save_page_probe(self.driver, "2fa_email_step_still_visible.json")
        raise RuntimeError("MEXC email verification was not confirmed; Google Authenticator step did not open")

    def _is_email_verification_step_visible(self) -> bool:
        text = self._security_modal_text().lower()
        if "email verification code" in text or "sent to" in text:
            return True
        return self._input_with_words(("email", "mail"), security_modal_only=True) is not None

    def _is_totp_verification_step_visible(self) -> bool:
        text = self._security_modal_text().lower()
        if any(word in text for word in ("google authenticator", "authenticator code", "mexc/google", "google verification")):
            return True
        if self._input_with_words(("google", "authenticator", "totp"), security_modal_only=True) is not None:
            return True
        return self._find_totp_input(security_modal_only=False) is not None

    def _fill_totp_verification_code(self) -> None:
        self.debug.step("2fa_totp_input_lookup")
        totp_code = self._fresh_totp_code(self.two_fa_secret)
        modal_input = self._find_totp_input(security_modal_only=True)
        if modal_input is not None:
            self._clear_and_type(modal_input, totp_code)
            self.debug.step("2fa_totp_input_filled", mode="modal_input")
            return

        inline_input = self._find_totp_input(security_modal_only=False)
        if inline_input is not None:
            self._clear_and_type(inline_input, totp_code)
            self.debug.step("2fa_totp_input_filled", mode="inline_input")
            return

        if self._fill_code_inputs(totp_code):
            self.debug.step("2fa_totp_input_filled", mode="otp_inputs")
            return
        raise RuntimeError("MEXC Google Authenticator code input was not found")

    def _click_security_submit(self, phase: str) -> None:
        self.debug.step("2fa_security_submit_attempt", phase=phase)
        button_texts = ("submit",) if phase == "email_code" else ("submit", "confirm")
        if phase == "totp_code" and self._find_totp_input(security_modal_only=False) is not None:
            self.debug.step("2fa_submit_path_selected", phase=phase, path="inline")
            clicked = self._click_inline_submit_button(button_texts, timeout=5)
        else:
            self.debug.step("2fa_submit_path_selected", phase=phase, path="modal")
            clicked = self._click_security_modal_button(button_texts, timeout=20)
            if not clicked and phase == "totp_code":
                self.debug.step("2fa_submit_path_selected", phase=phase, path="inline_fallback")
                clicked = self._click_inline_submit_button(button_texts, timeout=5)
        if not clicked:
            self.debug.save_page_probe(self.driver, f"2fa_submit_not_found_{phase}.json")
            raise RuntimeError(f"MEXC 2FA security submit button was not found during {phase}")
        time.sleep(2)
        self.debug.step("2fa_security_submit_clicked", phase=phase)

    def _click_security_modal_button(self, texts: tuple[str, ...], timeout: int = 10) -> bool:
        wanted = tuple(text.lower() for text in texts)
        deadline = time.time() + timeout
        attempt = 1
        while time.time() < deadline:
            clicked = self.driver.execute_script(
                """
                const wanted = arguments[0];
                const visible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && style.pointerEvents !== 'none';
                };
                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const modalCandidates = [...document.querySelectorAll('.ant-modal-content, .ant-modal, [role="dialog"], .modal')]
                    .filter(visible)
                    .filter((element) => normalize(element.innerText || element.textContent).includes('security verification'));
                const modal = modalCandidates[modalCandidates.length - 1];
                if (!modal) return { clicked: false, reason: 'security_modal_not_found' };
                const candidates = [...modal.querySelectorAll('button,a,span,div,[role="button"]')]
                    .filter(visible)
                    .filter((element) => {
                        const text = normalize(element.innerText || element.textContent);
                        return wanted.some((value) => text === value);
                    })
                    .sort((left, right) => {
                        const leftRect = left.getBoundingClientRect();
                        const rightRect = right.getBoundingClientRect();
                        return (leftRect.width * leftRect.height) - (rightRect.width * rightRect.height);
                    });
                for (const element of candidates) {
                    const target = element.closest('button,a,[role="button"]') || element;
                    const style = window.getComputedStyle(target);
                    const className = (target.className || '').toString().toLowerCase();
                    const disabled = target.disabled
                        || target.getAttribute('aria-disabled') === 'true'
                        || /(^|\\s)(disabled|is-disabled)(\\s|$)/.test(className)
                        || style.pointerEvents === 'none'
                        || Number(style.opacity || '1') < 0.25;
                    if (disabled) continue;

                    target.scrollIntoView({ block: 'center', inline: 'center' });
                    const rect = target.getBoundingClientRect();
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;
                    const topElement = document.elementFromPoint(x, y);
                    const clickTarget = topElement && target.contains(topElement) ? topElement : target;

                    try { clickTarget.click(); } catch (error) {}
                    if (target.tagName === 'BUTTON' && target.type === 'submit' && target.form) {
                        try {
                            if (target.form.requestSubmit) {
                                target.form.requestSubmit(target);
                            } else {
                                target.form.submit();
                            }
                        } catch (error) {}
                    }
                    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        clickTarget.dispatchEvent(new MouseEvent(type, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: x,
                            clientY: y
                        }));
                    }
                    return {
                        clicked: true,
                        tag: target.tagName,
                        text: normalize(target.innerText || target.textContent).slice(0, 80),
                        className: className.slice(0, 120)
                    };
                }
                return { clicked: false };
                """,
                list(wanted),
            )
            did_click = isinstance(clicked, dict) and clicked.get("clicked")
            self.debug.step(
                "2fa_security_modal_button_click",
                attempt=attempt,
                clicked=bool(did_click),
                text=clicked.get("text") if isinstance(clicked, dict) else None,
                tag=clicked.get("tag") if isinstance(clicked, dict) else None,
            )
            if did_click:
                return True
            time.sleep(0.5)
            attempt += 1
        return False

    def _click_inline_submit_button(self, texts: tuple[str, ...], timeout: int = 10) -> bool:
        wanted = tuple(text.lower() for text in texts)
        deadline = time.time() + timeout
        attempt = 1
        while time.time() < deadline:
            clicked = self.driver.execute_script(
                """
                const wanted = arguments[0];
                const visible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && style.pointerEvents !== 'none';
                };
                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const hasSecurityModal = [...document.querySelectorAll('.ant-modal-content, .ant-modal, [role="dialog"], .modal')]
                    .filter(visible)
                    .some((element) => normalize(element.innerText || element.textContent).includes('security verification'));
                if (hasSecurityModal) return { clicked: false, reason: 'security_modal_still_open' };

                const findTotpInput = () => {
                    const words = ['authenticator', 'authentication', 'google', 'totp'];
                    return [...document.querySelectorAll('input,textarea')]
                        .filter(visible)
                        .find((element) => {
                            const containerText = normalize(
                                element.closest('label,div,section,form,li')?.innerText
                                || element.parentElement?.innerText
                                || ''
                            );
                            const haystack = [
                                element.name,
                                element.id,
                                element.placeholder,
                                element.getAttribute('aria-label'),
                                element.getAttribute('data-testid'),
                                element.getAttribute('class'),
                                containerText
                            ].join(' ').toLowerCase();
                            return words.some((word) => haystack.includes(word));
                        });
                };
                const input = findTotpInput();
                const roots = [];
                if (input) {
                    const form = input.closest('form');
                    const section = input.closest('section,form,div');
                    if (form) roots.push(form);
                    if (section && section !== form) roots.push(section);
                }
                roots.push(document);

                const candidates = roots.flatMap((root) => [...root.querySelectorAll('button,a,span,div,[role="button"]')])
                    .filter(visible)
                    .filter((element) => {
                        const text = normalize(element.innerText || element.textContent);
                        return wanted.some((value) => text === value);
                    })
                    .sort((left, right) => {
                        const leftRect = left.getBoundingClientRect();
                        const rightRect = right.getBoundingClientRect();
                        return (leftRect.width * leftRect.height) - (rightRect.width * rightRect.height);
                    });
                for (const element of candidates) {
                    const target = element.closest('button,a,[role="button"]') || element;
                    const style = window.getComputedStyle(target);
                    const className = (target.className || '').toString().toLowerCase();
                    const disabled = target.disabled
                        || target.getAttribute('aria-disabled') === 'true'
                        || /(^|\\s)(disabled|is-disabled)(\\s|$)/.test(className)
                        || style.pointerEvents === 'none'
                        || Number(style.opacity || '1') < 0.25;
                    if (disabled) continue;
                    target.scrollIntoView({ block: 'center', inline: 'center' });
                    target.click();
                    if (target.tagName === 'BUTTON' && target.type === 'submit' && target.form) {
                        try {
                            if (target.form.requestSubmit) {
                                target.form.requestSubmit(target);
                            } else {
                                target.form.submit();
                            }
                        } catch (error) {}
                    }
                    return {
                        clicked: true,
                        tag: target.tagName,
                        text: normalize(target.innerText || target.textContent).slice(0, 80)
                    };
                }
                return { clicked: false, reason: 'inline_submit_not_found' };
                """,
                list(wanted),
            )
            did_click = isinstance(clicked, dict) and clicked.get("clicked")
            self.debug.step(
                "2fa_inline_submit_click",
                attempt=attempt,
                clicked=bool(did_click),
                text=clicked.get("text") if isinstance(clicked, dict) else None,
                tag=clicked.get("tag") if isinstance(clicked, dict) else None,
                reason=clicked.get("reason") if isinstance(clicked, dict) else None,
            )
            if did_click:
                return True
            time.sleep(0.5)
            attempt += 1
        return False

    def _fresh_totp_code(self, secret: str) -> str:
        remaining = 30 - (int(time.time()) % 30)
        if remaining <= 8:
            self.debug.step("2fa_totp_wait_for_fresh_cycle", seconds=remaining)
            time.sleep(remaining + 1)
        code = pyotp.TOTP(secret).now()
        self.debug.step("2fa_totp_generated", code_length=len(code))
        return code

    def _verify_success(self) -> None:
        self.debug.step("2fa_success_check")
        deadline = time.time() + 20
        while time.time() < deadline:
            text = self._page_text().lower()
            if any(word in text for word in ("success", "enabled", "bound")) or "link successful" in text:
                self.debug.step("2fa_success_text_detected")
                return
            if self.SECURITY_URL not in (self.driver.current_url or ""):
                self.debug.step("2fa_success_url_changed", url=self.driver.current_url)
                return
            error_text = self._collect_error_text()
            if error_text:
                raise RuntimeError(error_text)
            time.sleep(2)
        error_text = self._collect_error_text()
        if error_text:
            raise RuntimeError(error_text)
        self.debug.warning("2fa_success_not_confirmed")

    def _click_get_code_if_active(self, timeout: int = 10) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
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
                const candidates = [...document.querySelectorAll('button,a,span,div,[role="button"]')]
                    .filter(visible)
                    .filter((element) => {
                        const text = normalize(element.innerText || element.textContent);
                        return text === 'get code' || text === 'send code';
                    })
                    .sort((left, right) => {
                        const leftRect = left.getBoundingClientRect();
                        const rightRect = right.getBoundingClientRect();
                        return (leftRect.width * leftRect.height) - (rightRect.width * rightRect.height);
                    });
                for (const element of candidates) {
                    const target = element.closest('button,a,[role="button"]') || element;
                    const disabled = target.disabled
                        || target.getAttribute('aria-disabled') === 'true'
                        || target.className.toString().toLowerCase().includes('disabled');
                    if (disabled) continue;
                    target.scrollIntoView({ block: 'center', inline: 'center' });
                    target.click();
                    return true;
                }
                return false;
                """
            )
            if clicked:
                self.email_code_not_before_ts = time.time() - 10
                time.sleep(3)
                self.debug.step("2fa_get_code_active_check", clicked=True)
                return True
            time.sleep(0.5)

        self.debug.step("2fa_get_code_active_check", clicked=False)
        return False

    def _wait_for_email_code(self) -> str:
        attempt = 1
        while True:
            self.debug.step(
                "2fa_email_code_wait_start",
                attempt=attempt,
                timeout=180,
                poll_interval=5,
                not_before=int(self.email_code_not_before_ts) if self.email_code_not_before_ts else None,
                ignored_count=len(self.tried_email_codes),
            )
            try:
                code = self.email_fetcher.wait_for_code(
                    self.account.email,
                    timeout=180,
                    poll_interval=5,
                    not_before_ts=self.email_code_not_before_ts,
                    ignored_codes=self.tried_email_codes,
                    cancel_event=self.cancel_event,
                    cancel_checker=self.browser_is_closed,
                )
            except RuntimeError as exc:
                if "No MEXC verification code received within 180s" not in str(exc):
                    raise
                self.debug.warning("2fa_email_code_wait_timeout", attempt=attempt)
                if not self._ask_wait_more_for_email_code():
                    raise RuntimeError("MEXC email verification code wait was stopped by user") from exc
                attempt += 1
                self.debug.step("2fa_email_code_wait_extended", next_attempt=attempt)
                continue
            self.debug.step("2fa_email_code_found", code_found=True, code_length=len(code), attempt=attempt)
            return code

    def _ask_wait_more_for_email_code(self) -> bool:
        if not self.on_email_timeout:
            self.debug.warning("2fa_email_code_wait_timeout_no_callback")
            return False
        try:
            should_continue = bool(self.on_email_timeout(self.account.email))
        except Exception:
            logger.exception("Email timeout callback failed for %s", self.debug.masked_email)
            self.debug.warning("2fa_email_code_wait_timeout_callback_failed")
            return False
        self.debug.step("2fa_email_code_wait_user_decision", wait_more=should_continue)
        return should_continue

    def _is_email_code_step_visible(self) -> bool:
        return bool(self._visible_code_inputs()) or "verification code" in self._page_text().lower()

    def _visible_code_inputs(self) -> list[WebElement]:
        try:
            inputs = self.driver.execute_script(
                """
                const visible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                return [...document.querySelectorAll(
                    [
                        '.react-code-input input',
                        "input[data-id][type='number']",
                        "input[autocomplete='one-time-code']",
                        "input[name*='code']",
                        "input[id*='code']",
                        "input[placeholder*='code' i]",
                        "input[type='number']"
                    ].join(',')
                )]
                    .filter(visible)
                    .sort((left, right) => left.getBoundingClientRect().x - right.getBoundingClientRect().x);
                """
            )
        except Exception:
            return []
        return inputs if isinstance(inputs, list) else []

    def _security_modal_text(self) -> str:
        try:
            return self.driver.execute_script(
                """
                const visible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                const modals = [...document.querySelectorAll('.ant-modal-content, .ant-modal, [role="dialog"], .modal')]
                    .filter(visible)
                    .filter((element) => normalize(element.innerText || element.textContent).toLowerCase().includes('security verification'));
                const modal = modals[modals.length - 1];
                return modal ? (modal.innerText || modal.textContent || '') : '';
                """
            ) or ""
        except Exception:
            return ""

    def _find_totp_input(self, security_modal_only: bool) -> WebElement | None:
        try:
            inputs = self.driver.execute_script(
                """
                const securityModalOnly = arguments[0];
                const visible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                let root = document;
                if (securityModalOnly) {
                    const modals = [...document.querySelectorAll('.ant-modal-content, .ant-modal, [role="dialog"], .modal')]
                        .filter(visible)
                        .filter((element) => normalize(element.innerText || element.textContent).includes('security verification'));
                    root = modals[modals.length - 1];
                    if (!root) return [];
                }
                const words = ['authenticator', 'authentication', 'google', 'totp'];
                return [...root.querySelectorAll('input,textarea')]
                    .filter(visible)
                    .filter((element) => {
                        const containerText = normalize(
                            element.closest('label,div,section,form,li')?.innerText
                            || element.parentElement?.innerText
                            || ''
                        );
                        const haystack = [
                            element.name,
                            element.id,
                            element.placeholder,
                            element.getAttribute('aria-label'),
                            element.getAttribute('data-testid'),
                            element.getAttribute('class'),
                            containerText
                        ].join(' ').toLowerCase();
                        return words.some((word) => haystack.includes(word));
                    })
                    .sort((left, right) => {
                        const leftRect = left.getBoundingClientRect();
                        const rightRect = right.getBoundingClientRect();
                        return (leftRect.y - rightRect.y) || (leftRect.x - rightRect.x);
                    });
                """,
                security_modal_only,
            )
        except Exception:
            return None
        if not isinstance(inputs, list) or not inputs:
            return None
        return inputs[0]

    def _input_with_words(self, words: tuple[str, ...], security_modal_only: bool = False) -> WebElement | None:
        wanted = tuple(word.lower() for word in words)
        try:
            inputs = self.driver.execute_script(
                """
                const wanted = arguments[0];
                const securityModalOnly = arguments[1];
                const visible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                let root = document;
                if (securityModalOnly) {
                    const modals = [...document.querySelectorAll('.ant-modal-content, .ant-modal, [role="dialog"], .modal')]
                        .filter(visible)
                        .filter((element) => normalize(element.innerText || element.textContent).includes('security verification'));
                    root = modals[modals.length - 1];
                    if (!root) return [];
                }
                return [...root.querySelectorAll('input,textarea')]
                    .filter(visible)
                    .filter((element) => {
                        const haystack = [
                            element.name,
                            element.id,
                            element.placeholder,
                            element.getAttribute('aria-label'),
                            element.getAttribute('data-testid'),
                            element.getAttribute('class')
                        ].join(' ').toLowerCase();
                        return wanted.some((word) => haystack.includes(word));
                    })
                    .sort((left, right) => left.getBoundingClientRect().x - right.getBoundingClientRect().x);
                """,
                list(wanted),
                security_modal_only,
            )
        except Exception:
            return None
        if not isinstance(inputs, list) or not inputs:
            return None
        return inputs[0]

    def _fill_named_code_input(
        self,
        code: str,
        preferred_words: tuple[str, ...],
        security_modal_only: bool = False,
    ) -> bool:
        element = self._input_with_words(preferred_words, security_modal_only=security_modal_only)
        if element is None:
            return False
        digits = "".join(char for char in code if char.isdigit())
        if len(digits) < 6:
            return False
        self._clear_and_type(element, digits[:6])
        return True

    def _fill_code_inputs(self, code: str) -> bool:
        inputs = self._visible_code_inputs()
        digits = [char for char in code if char.isdigit()]
        if not inputs or len(digits) < 6:
            return False
        if len(inputs) >= 6:
            for index, digit in enumerate(digits[:6]):
                fresh = self._visible_code_inputs()
                if len(fresh) <= index:
                    return False
                self._clear_and_type(fresh[index], digit)
            return True
        self._clear_and_type(inputs[0], "".join(digits[:6]))
        return True

    def _click_by_text(self, texts: tuple[str, ...], timeout: int = 10) -> bool:
        wanted = tuple(text.lower() for text in texts)
        deadline = time.time() + timeout
        while time.time() < deadline:
            clicked = self.driver.execute_script(
                """
                const wanted = arguments[0];
                const visible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const candidates = [...document.querySelectorAll('button,a,span,div,[role="button"]')]
                    .filter(visible)
                    .filter((element) => {
                        const text = (element.innerText || element.textContent || '').trim().toLowerCase();
                        return wanted.some((value) => text === value || text.includes(value));
                    })
                    .sort((left, right) => {
                        const leftRect = left.getBoundingClientRect();
                        const rightRect = right.getBoundingClientRect();
                        return (leftRect.width * leftRect.height) - (rightRect.width * rightRect.height);
                    });
                for (const element of candidates) {
                    const target = element.closest('button,a,[role="button"]') || element;
                    const targetStyle = window.getComputedStyle(target);
                    const disabledAncestor = element.closest('[aria-disabled="true"], .disabled, .is-disabled');
                    const disabled = target.disabled
                        || target.getAttribute('aria-disabled') === 'true'
                        || target.className.toString().toLowerCase().includes('disabled')
                        || targetStyle.pointerEvents === 'none'
                        || Boolean(disabledAncestor);
                    if (disabled) continue;
                    target.scrollIntoView({ block: 'center' });
                    target.click();
                    return true;
                }
                return false;
                """,
                wanted,
            )
            if clicked:
                return True
            time.sleep(0.3)
        return False

    def _handle_captcha(self, phase: str) -> None:
        self.debug.step("2fa_captcha_check", phase=phase)
        captcha_found = False
        deadline = time.time() + 8
        while time.time() < deadline:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            if detect_captcha(self.driver):
                captcha_found = True
                break
            state = self.state_analyzer.analyze(self.driver)
            if state.name == "captcha" and state.confidence >= 0.72:
                captcha_found = True
                break
            time.sleep(1)
        if not captcha_found:
            self.debug.step("2fa_captcha_not_detected", phase=phase)
            return
        logger.info("CAPTCHA detected during %s for %s", phase, self.debug.masked_email)
        self.debug.step("2fa_captcha_detected", phase=phase)
        self.debug.save_screenshot(self.driver, f"2fa_captcha_{phase}.png")
        self.debug.save_page_probe(self.driver, f"2fa_captcha_probe_{phase}.json")
        self._notify_captcha(self.task_id)
        if self.on_captcha_detected:
            self.on_captcha_detected(self.account.email)
        if not wait_for_captcha_solved(self.driver, timeout=180):
            raise RuntimeError("Captcha was not solved in time")
        self.debug.step("2fa_captcha_solved", phase=phase)

    def _find_visible(
        self,
        locators: tuple[Locator, ...],
        timeout: int = 10,
        reject_words: tuple[str, ...] = (),
    ) -> WebElement | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for by, value in locators:
                try:
                    elements = self.driver.find_elements(by, value)
                except Exception:
                    continue
                for element in elements:
                    try:
                        if not element.is_displayed():
                            continue
                        haystack = " ".join(
                            str(element.get_attribute(attr) or "").lower()
                            for attr in ("name", "id", "placeholder", "class", "aria-label")
                        )
                        if any(word in haystack for word in reject_words):
                            continue
                        return element
                    except Exception:
                        continue
            time.sleep(0.3)
        return None

    def _clear_and_type(self, element: WebElement, value: str) -> None:
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(0.2)
        try:
            self.driver.execute_script("arguments[0].focus();", element)
            element.send_keys(Keys.CONTROL, "a")
            element.send_keys(Keys.BACKSPACE)
            element.send_keys(value)
            actual_value = element.get_attribute("value") or ""
            if actual_value == value:
                return
        except Exception:
            logger.debug("Keyboard input failed, falling back to JS value setter", exc_info=True)

        self.driver.execute_script(
            """
            const element = arguments[0];
            const value = arguments[1];
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,
                'value'
            ).set;
            setter.call(element, value);
            element.dispatchEvent(new Event('input', { bubbles: true }));
            element.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            element,
            value,
        )

    def _collect_error_text(self) -> str:
        parts: list[str] = []
        for by, value in self.selectors.error_message:
            try:
                for element in self.driver.find_elements(by, value):
                    if element.is_displayed():
                        text = element.text.strip()
                        if text:
                            parts.append(text)
            except Exception:
                continue
        return "\n".join(dict.fromkeys(parts))

    def _page_text(self) -> str:
        try:
            return self.driver.execute_script("return document.body ? document.body.innerText : ''") or ""
        except Exception:
            return ""
