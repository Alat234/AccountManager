from __future__ import annotations

import logging
import time
from collections.abc import Callable

from selenium.webdriver import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from automation.base import BaseScenario, ScenarioResult
from automation.captcha import detect_captcha, wait_for_captcha_solved
from automation.checkpoints import CheckpointAlreadyComplete, CheckpointRunner, ScenarioCheckpoint
from automation.scenarios.mexc_debug import MexcRegistrationDebug
from automation.scenarios.mexc_selectors import Locator, MexcRegistrationSelectors
from automation.scenarios.mexc_state import MexcPageStateAnalyzer

logger = logging.getLogger(__name__)


class RegisterMexcScenario(BaseScenario):
    """Register selected account email on MEXC through an AdsPower browser."""

    def __init__(
        self,
        adspower,
        account,
        captcha_service=None,
        referral_code: str = "",
        default_password: str = "",
        email_fetcher=None,
        on_captcha_detected: Callable[[str], None] | None = None,
    ):
        super().__init__(adspower, account, captcha_service)
        self.referral_code = referral_code
        self.default_password = default_password
        self.email_fetcher = email_fetcher
        self.on_captcha_detected = on_captcha_detected
        self.selectors = MexcRegistrationSelectors()
        self.task_id = ""
        self.auto_close = False
        self.email_code_not_before_ts: float | None = None
        self.tried_email_codes: set[str] = set()
        self.state_analyzer = MexcPageStateAnalyzer()
        self.checkpoint_runner: CheckpointRunner | None = None
        self.debug = MexcRegistrationDebug(
            account_email=self.account.email,
            secrets=(self.referral_code, self.default_password),
        )

    def run(self) -> ScenarioResult:
        if not self.email_fetcher:
            raise RuntimeError("Email fetcher is not configured")

        self.debug.bind_task(self.task_id)
        self.debug.with_secrets(self.referral_code, self.default_password)
        self.debug.step("start")

        try:
            self._run_registration_checkpoints()
        except CheckpointAlreadyComplete:
            self.debug.step("success_verification_passed", url=getattr(self.driver, "current_url", ""))
        except Exception as exc:
            self.debug.warning("failed", reason=str(exc))
            if self.driver:
                self.debug.save_failure_artifacts(self.driver, str(exc))
            raise

        self.debug.step("success")
        return ScenarioResult(
            success=True,
            message=f"MEXC registration complete for {self.debug.masked_email}",
            data={"password": self.default_password, "account_email": self.account.email},
        )

    def _run_registration_checkpoints(self) -> None:
        runner = CheckpointRunner(
            driver_getter=lambda: self.driver,
            analyzer=self.state_analyzer,
            debug=self.debug,
            manual_assist_handler=self.manual_assist_handler,
            network_recovery_handler=self.network_recovery_handler,
            captcha_handler=lambda checkpoint: self._handle_captcha(f"{checkpoint}_captcha"),
            default_terminal_states={"register_completed"},
        )
        self.checkpoint_runner = runner
        runner.run(self._registration_checkpoints())

    def _registration_checkpoints(self) -> list[ScenarioCheckpoint]:
        terminal = {"register_completed"}
        after_email = {"register_code", "register_password", *terminal}
        after_code = {"register_password", *terminal}
        return [
            ScenarioCheckpoint(
                name="navigate",
                action=self._navigate_to_signup,
                allowed_states={"unknown", "network_loading", "network_error", "wrong_browser_tab"},
                done_states={"register_email", *after_email},
                terminal_states=terminal,
                recover_wrong_tab=self._navigate_to_signup,
            ),
            ScenarioCheckpoint(
                name="email",
                action=self._fill_email,
                allowed_states={"register_email"},
                done_states=after_email,
                terminal_states=terminal,
                recover_wrong_tab=self._navigate_to_signup,
            ),
            ScenarioCheckpoint(
                name="referral",
                action=self._fill_referral_code,
                allowed_states={"register_email"},
                done_states=after_email,
                terminal_states=terminal,
                recover_wrong_tab=self._navigate_to_signup,
            ),
            ScenarioCheckpoint(
                name="continue",
                action=self._click_continue,
                allowed_states={"register_email"},
                done_states=after_email,
                terminal_states=terminal,
                recover_wrong_tab=self._navigate_to_signup,
            ),
            ScenarioCheckpoint(
                name="email_code_request",
                action=self._request_verification_code,
                allowed_states={"register_code"},
                done_states=after_code,
                terminal_states=terminal,
                recover_wrong_tab=self._navigate_to_signup,
            ),
            ScenarioCheckpoint(
                name="email_code_submit",
                action=self._complete_verification_code_step,
                allowed_states={"register_code"},
                done_states=after_code,
                terminal_states=terminal,
                recover_wrong_tab=self._navigate_to_signup,
            ),
            ScenarioCheckpoint(
                name="password",
                action=self._fill_password,
                allowed_states={"register_password"},
                done_states=terminal,
                terminal_states=terminal,
                recover_wrong_tab=self._navigate_to_signup,
            ),
            ScenarioCheckpoint(
                name="final_submit",
                action=self._submit_final_registration,
                allowed_states={"register_password"},
                done_states=terminal,
                terminal_states=terminal,
                recover_wrong_tab=self._navigate_to_signup,
            ),
        ]

    def _submit_final_registration(self) -> None:
        self._accept_terms_if_present()
        self._click_signup()
        self._handle_captcha("after_signup")
        self._verify_registration_success()

    def _navigate_to_signup(self) -> None:
        self.debug.step("navigate_start", url="https://www.mexc.com/register")
        self.driver.get("https://www.mexc.com/register")
        WebDriverWait(self.driver, 30).until(
            lambda driver: driver.execute_script("return document.readyState") == "complete"
        )
        time.sleep(2)
        self.debug.step("page_loaded", url=self.driver.current_url, title=self.driver.title)

    def _fill_email(self) -> None:
        self.debug.step("email_input_lookup")
        element = self._find_visible(self.selectors.email_input, timeout=20)
        if element is None:
            raise RuntimeError("Email input was not found on MEXC registration page")
        self._clear_and_type(element, self.account.email)
        self.debug.step("email_filled")

    def _fill_referral_code(self) -> None:
        self.debug.step("referral_input_lookup_before_expand")
        element = self._find_visible(self.selectors.referral_input, timeout=1)
        if element is None:
            self.debug.step("referral_reveal_hidden_attempt")
            self._reveal_hidden_referral_input()
            element = self._find_visible(self.selectors.referral_input, timeout=2)
        if element is None:
            self.debug.step("referral_expand_attempt")
            self._expand_referral_code()
            element = self._find_visible(self.selectors.referral_input, timeout=3)
        if element is None:
            element = self._find_present(self.selectors.referral_input, timeout=1)
            if element is None:
                debug = self._debug_referral_elements()
                self.debug.save_page_probe(self.driver, "referral_probe_not_found.json")
                raise RuntimeError(
                    "Referral code field was not found on MEXC registration page"
                    + (f"\nVisible referral elements: {debug}" if debug else "")
                )
            self.debug.step("referral_present_hidden_input_found")
        self._clear_and_type(element, self.referral_code)
        self._verify_referral_code_filled(element)
        self.debug.step("referral_filled", value_length=len(self.referral_code))

    def _verify_referral_code_filled(self, element: WebElement) -> None:
        expected = self.referral_code
        deadline = time.time() + 3
        last_length = 0
        while time.time() < deadline:
            try:
                actual = self.driver.execute_script(
                    "return arguments[0].value || arguments[0].getAttribute('value') || '';",
                    element,
                ) or ""
            except Exception:
                element = self._find_present(self.selectors.referral_input, timeout=1)
                actual = ""
            last_length = len(str(actual))
            if actual == expected:
                self.debug.step("referral_value_verified", value_length=len(expected))
                return
            time.sleep(0.2)

        self.debug.warning(
            "referral_value_verify_failed",
            expected_length=len(expected),
            actual_length=last_length,
        )
        self.debug.save_page_probe(self.driver, "referral_value_verify_failed.json")
        raise RuntimeError("Referral code field did not keep the expected value after input")

    def _expand_referral_code(self) -> None:
        if self._click_referral_toggle_with_actions(timeout=4):
            time.sleep(1)
            if self._find_visible(self.selectors.referral_input, timeout=2) is not None:
                self.debug.step("referral_expanded", strategy="actions")
                return

        if self._click_optional(self.selectors.referral_toggle, timeout=3):
            time.sleep(1)
            if self._find_visible(self.selectors.referral_input, timeout=2) is not None:
                self.debug.step("referral_expanded", strategy="optional_click")
                return

        clicked = self.driver.execute_script(
            """
            const selectors = [
                "label[for='full-sign-up-account-form_inviteCode']",
                "span[class*='inviteCodeToggle']",
                "span[class*='inviteCodeCheckLabel']",
                "svg[class*='inviteCodeExpandArrow']",
                "[class*='inviteCodeToggle']",
                "[class*='inviteCodeCheckLabel']",
                "[class*='inviteCodeExpandArrow']"
            ];
            const visible = (element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none';
            };
            for (const selector of selectors) {
                for (const element of document.querySelectorAll(selector)) {
                    if (!visible(element)) continue;
                    const target = element.closest('label') || element;
                    target.scrollIntoView({ block: 'center' });
                    for (const type of ['pointerdown', 'mousedown', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(type, {
                            bubbles: true,
                            cancelable: true,
                            view: window
                        }));
                    }
                    return true;
                }
            }
            return false;
            """
        )
        if clicked:
            time.sleep(1)
            self.debug.step("referral_expand_js_clicked")
        else:
            self.debug.warning("referral_expand_js_no_target")

        if self._find_visible(self.selectors.referral_input, timeout=2) is None:
            self._reveal_hidden_referral_input()

    def _reveal_hidden_referral_input(self) -> bool:
        revealed = self.driver.execute_script(
            """
            const input = document.querySelector('#full-sign-up-account-form_inviteCode')
                || document.querySelector("input[id*='invite']")
                || document.querySelector("input[name*='invite']");
            if (!input) return { revealed: false, reason: 'input_not_found' };

            const container = input.closest('.global__inviteCodeInput')
                || input.closest("[class*='inviteCodeInput']")
                || input.closest('.ant-form-item');
            if (!container) return { revealed: false, reason: 'container_not_found' };

            const beforeClass = String(container.className || '');
            container.className = beforeClass
                .split(/\\s+/)
                .filter((className) => !/inviteCodeInputHide/i.test(className))
                .join(' ');

            for (const element of [container, ...container.querySelectorAll('*')]) {
                const style = element.style;
                if (!style) continue;
                if (style.display === 'none') style.display = '';
                if (style.visibility === 'hidden') style.visibility = '';
                if (style.opacity === '0') style.opacity = '';
                if (style.height === '0px') style.height = '';
                if (style.maxHeight === '0px') style.maxHeight = '';
                if (style.overflow === 'hidden') style.overflow = '';
            }

            container.style.display = 'block';
            container.style.visibility = 'visible';
            container.style.opacity = '1';
            container.style.height = 'auto';
            container.style.maxHeight = 'none';
            container.style.overflow = 'visible';

            input.removeAttribute('hidden');
            input.disabled = false;
            input.style.display = '';
            input.style.visibility = 'visible';
            input.style.opacity = '1';

            container.scrollIntoView({ block: 'center' });
            return {
                revealed: true,
                beforeClass,
                afterClass: String(container.className || ''),
                inputDisplayed: Boolean(input.offsetWidth || input.offsetHeight || input.getClientRects().length)
            };
            """
        )
        self.debug.step("referral_reveal_hidden_result", result=revealed)
        return bool(isinstance(revealed, dict) and revealed.get("revealed"))

    def _click_referral_toggle_with_actions(self, timeout: int = 4) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for locator in self.selectors.referral_toggle:
                try:
                    elements = self.driver.find_elements(*locator)
                except Exception:
                    continue
                for element in elements:
                    try:
                        if not element.is_displayed():
                            continue
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block: 'center'});",
                            element,
                        )
                        time.sleep(0.2)
                        size = element.size
                        x_offset = max(1, min(size.get("width", 1) - 4, size.get("width", 1) // 2))
                        y_offset = max(1, min(size.get("height", 1) - 4, size.get("height", 1) // 2))
                        ActionChains(self.driver).move_to_element_with_offset(
                            element,
                            x_offset,
                            y_offset,
                        ).click().perform()
                        self.debug.step(
                            "referral_toggle_clicked",
                            strategy="action_chain",
                            locator=locator,
                        )
                        return True
                    except Exception:
                        continue

            clicked = self.driver.execute_script(
                """
                const candidates = [...document.querySelectorAll('span,label,svg,div')]
                    .filter((element) => {
                        const text = (element.innerText || element.textContent || '').trim();
                        const cls = String(element.className || '');
                        const rect = element.getBoundingClientRect();
                        const style = window.getComputedStyle(element);
                        return rect.width > 0 && rect.height > 0
                            && style.visibility !== 'hidden'
                            && style.display !== 'none'
                            && (
                                /Referral Code/i.test(text)
                                || /Invitation code/i.test(text)
                                || /inviteCode/i.test(cls)
                            );
                    });
                const element = candidates[0];
                if (!element) return false;
                const target = element.closest('label') || element;
                target.scrollIntoView({ block: 'center' });
                const rect = target.getBoundingClientRect();
                const x = rect.left + rect.width - 8;
                const y = rect.top + rect.height / 2;
                for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                    target.dispatchEvent(new MouseEvent(type, {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y
                    }));
                }
                return true;
                """
            )
            if clicked:
                self.debug.step("referral_toggle_clicked", strategy="js_text_candidate")
                return True
            time.sleep(0.2)
        return False

    def _request_verification_code(self) -> None:
        self.debug.step("verification_step_lookup")
        if self._find_visible(self.selectors.verification_code_input, timeout=5) is not None:
            self._click_get_code_if_active()
            self.debug.step("verification_input_already_visible")
            return

        if self._click_optional(self.selectors.send_code_button, timeout=8):
            time.sleep(3)
            self.debug.step("send_code_clicked")
            return

        if self._find_visible(self.selectors.password_input, timeout=2) is not None:
            self.debug.step("password_step_before_code")
            self._fill_password()
            if self._click_optional(self.selectors.send_code_button, timeout=8):
                time.sleep(3)
                self.debug.step("send_code_clicked_after_password")
                return
            if self._find_visible(self.selectors.verification_code_input, timeout=5) is not None:
                self.debug.step("verification_input_visible_after_password")
                return

        if self._find_visible(self.selectors.verification_code_input, timeout=5) is not None:
            self._click_get_code_if_active()
            self.debug.step("verification_input_visible")
            return

        raise RuntimeError("Verification code step was not found after Continue")

    def _click_get_code_if_active(self) -> None:
        clicked = self.driver.execute_script(
            """
            const visible = (element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none';
            };
            const candidates = [...document.querySelectorAll('button,span,[role="button"]')]
                .filter(visible)
                .filter((element) => {
                    const text = (element.innerText || element.textContent || '').trim().toLowerCase();
                    return text === 'get code' || text === 'send code';
                });
            const element = candidates[0];
            if (!element) return false;
            const target = element.closest('button,[role="button"]') || element;
            target.scrollIntoView({ block: 'center' });
            target.click();
            return true;
            """
        )
        if clicked:
            self.email_code_not_before_ts = time.time() - 10
            time.sleep(3)
        self.debug.step("get_code_active_check", clicked=bool(clicked))

    def _click_continue(self) -> None:
        self.debug.step("continue_click_attempt")
        self.email_code_not_before_ts = time.time() - 10
        last_state = None
        for attempt in range(1, 4):
            self._raise_if_cancelled()
            self._blur_active_element()
            if not self._click_optional(self.selectors.continue_button, timeout=5):
                raise RuntimeError("Continue button was not found or is not clickable")
            last_state = self._wait_for_continue_transition(timeout=5)
            if last_state.name in ("register_code", "register_password", "register_completed", "captcha"):
                self.debug.step(
                    "continue_clicked",
                    url=self.driver.current_url,
                    state=last_state.name,
                    attempt=attempt,
                )
                return
            self.debug.warning(
                "continue_no_transition",
                attempt=attempt,
                state=last_state.name,
                confidence=last_state.confidence,
            )
            time.sleep(0.8)
        state_name = last_state.name if last_state else "unknown"
        raise RuntimeError(f"Continue button clicked, but registration did not advance from {state_name}")

    def _wait_for_continue_transition(self, timeout: int = 5):
        deadline = time.time() + timeout
        last_state = self.state_analyzer.analyze(self.driver)
        while time.time() < deadline:
            self._raise_if_cancelled()
            state = self.state_analyzer.analyze(self.driver)
            last_state = state
            if state.name in ("register_code", "register_password", "register_completed", "captcha"):
                return state
            if state.name in ("network_loading", "network_error", "wrong_browser_tab", "browser_closed"):
                return state
            time.sleep(0.5)
        return last_state

    def _blur_active_element(self) -> None:
        try:
            self.driver.execute_script("if (document.activeElement) document.activeElement.blur();")
        except Exception:
            pass

    def _wait_for_email_code(self) -> str:
        self.debug.step(
            "email_code_wait_start",
            timeout=180,
            poll_interval=5,
            not_before=int(self.email_code_not_before_ts) if self.email_code_not_before_ts else None,
            ignored_count=len(self.tried_email_codes),
        )
        code = self.email_fetcher.wait_for_code(
            self.account.email,
            timeout=180,
            poll_interval=5,
            not_before_ts=self.email_code_not_before_ts,
            ignored_codes=self.tried_email_codes,
            cancel_event=self.cancel_event,
            cancel_checker=self.browser_is_closed,
        )
        self.debug.step("email_code_found", code_found=True, code_length=len(code))
        return code

    def _complete_verification_code_step(self) -> None:
        last_error = ""
        for attempt in range(1, 4):
            self.debug.step("verification_code_attempt_start", attempt=attempt)
            code = self._wait_for_email_code()
            self.tried_email_codes.add(code)
            try:
                self._fill_verification_code(code)
                self._submit_verification_code()
            except RuntimeError as exc:
                last_error = str(exc)
                if not self._is_retryable_verification_error(last_error):
                    raise
                self.debug.warning(
                    "verification_code_retry",
                    attempt=attempt,
                    reason=last_error,
                    ignored_count=len(self.tried_email_codes),
                )
                self._clear_otp_inputs()
                continue

            if self._is_password_step_visible(timeout=5):
                self.debug.step("verification_code_accepted", attempt=attempt)
                return

            error_text = self._collect_error_text()
            if self._is_retryable_verification_error(error_text):
                last_error = error_text
                self.debug.warning(
                    "verification_code_retry",
                    attempt=attempt,
                    reason=error_text,
                    ignored_count=len(self.tried_email_codes),
                )
                self._clear_otp_inputs()
                continue

            return

        raise RuntimeError(last_error or "MEXC verification code was not accepted")

    def _is_retryable_verification_error(self, text: str) -> bool:
        normalized = (text or "").lower()
        retry_words = (
            "invalid",
            "incorrect",
            "expired",
            "verification code",
            "code inputs did not accept",
            "captcha_reg",
            "код",
        )
        return any(word in normalized for word in retry_words)

    def _fill_verification_code(self, code: str) -> None:
        self.debug.step("verification_code_input_lookup")
        otp_inputs = self._find_otp_inputs(timeout=10)
        if len(otp_inputs) >= len(code):
            self._fill_otp_inputs(otp_inputs, code)
            self.debug.step("verification_code_filled", input_mode="split_otp", fields_count=len(otp_inputs))
            return

        element = self._find_visible(
            self.selectors.verification_code_input,
            timeout=20,
            reject_words=("invite", "referral"),
        )
        if element is None:
            raise RuntimeError("Verification code input was not found")
        self._clear_and_type(element, code)
        self.debug.step("verification_code_filled", input_mode="single_input")

    def _submit_verification_code(self) -> None:
        self.debug.step("verification_continue_click_attempt")
        if self._is_password_step_visible(timeout=2):
            self.debug.step("verification_continue_skipped", reason="password_step_visible")
            return
        if not self._click_optional(self.selectors.continue_button, timeout=15):
            raise RuntimeError("Verification Continue button was not found or is not clickable")
        time.sleep(3)
        self.debug.step("verification_continue_clicked", url=self.driver.current_url)

    def _find_otp_inputs(self, timeout: int = 10) -> list[WebElement]:
        deadline = time.time() + timeout
        while time.time() < deadline:
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
                            "[class*='auth_code_input'] input",
                            "[class*='sign_up_auth_code_input'] input",
                            "input[data-id][type='number']"
                        ].join(',')
                    )]
                        .filter(visible)
                        .sort((left, right) => {
                            const leftId = Number(left.getAttribute('data-id') || '0');
                            const rightId = Number(right.getAttribute('data-id') || '0');
                            if (leftId !== rightId) return leftId - rightId;
                            return left.getBoundingClientRect().x - right.getBoundingClientRect().x;
                        });
                    """
                )
            except Exception:
                inputs = []
            if isinstance(inputs, list) and len(inputs) >= 6:
                return inputs
            time.sleep(0.3)
        return []

    def _fill_otp_inputs(self, inputs: list[WebElement], code: str) -> None:
        digits = [char for char in code if char.isdigit()]
        if len(digits) < 6:
            raise RuntimeError("MEXC verification code is not 6 digits")

        code_value = "".join(digits[:6])
        try:
            fresh_inputs = self._find_otp_inputs(timeout=2)
            first = fresh_inputs[0] if fresh_inputs else inputs[0]
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", first)
            self.driver.execute_script("arguments[0].focus();", first)
            first.send_keys(code_value)
            time.sleep(1)
            if self._is_password_step_visible(timeout=2):
                self.debug.step("otp_input_accepted", mode="paste_transitioned")
                return
            if self._otp_values_match(code_value):
                self.debug.step("otp_input_accepted", mode="paste")
                return
        except Exception:
            logger.debug("OTP paste failed, falling back to per-digit input", exc_info=True)
            if self._is_password_step_visible(timeout=2):
                self.debug.step("otp_input_accepted", mode="paste_transitioned_after_stale")
                return

        for index, digit in enumerate(digits[:6]):
            if self._is_password_step_visible(timeout=1):
                self.debug.step("otp_input_accepted", mode="per_digit_transitioned", index=index)
                return
            fresh_inputs = self._find_otp_inputs(timeout=3)
            if len(fresh_inputs) <= index:
                if self._is_password_step_visible(timeout=2):
                    self.debug.step("otp_input_accepted", mode="per_digit_transitioned_missing_inputs")
                    return
                raise RuntimeError("MEXC verification code inputs disappeared before password step")
            try:
                self._clear_and_type(fresh_inputs[index], digit)
            except Exception:
                logger.debug("OTP digit input failed at index %s", index, exc_info=True)
                if self._is_password_step_visible(timeout=2):
                    self.debug.step("otp_input_accepted", mode="per_digit_transitioned_after_stale", index=index)
                    return
                raise

        time.sleep(0.5)
        if self._is_password_step_visible(timeout=2):
            self.debug.step("otp_input_accepted", mode="per_digit_transitioned_after_complete")
            return
        if not self._otp_values_match(code_value):
            raise RuntimeError("MEXC verification code inputs did not accept the full code")

    def _otp_values_match(self, code: str) -> bool:
        try:
            values = self.driver.execute_script(
                """
                const inputs = [...document.querySelectorAll(
                    [
                        '.react-code-input input',
                        "[class*='auth_code_input'] input",
                        "[class*='sign_up_auth_code_input'] input",
                        "input[data-id][type='number']"
                    ].join(',')
                )].sort((left, right) => {
                    const leftId = Number(left.getAttribute('data-id') || '0');
                    const rightId = Number(right.getAttribute('data-id') || '0');
                    if (leftId !== rightId) return leftId - rightId;
                    return left.getBoundingClientRect().x - right.getBoundingClientRect().x;
                }).slice(0, 6).map((input) => input.value || '');
                return values;
                """
            )
        except Exception:
            return False
        return (
            isinstance(values, list)
            and len(values) >= 6
            and all(len(str(value)) == 1 for value in values[:6])
            and "".join(str(value) for value in values[:6]) == code
        )

    def _clear_otp_inputs(self) -> None:
        try:
            cleared = self.driver.execute_script(
                """
                const inputs = [...document.querySelectorAll(
                    [
                        '.react-code-input input',
                        "[class*='auth_code_input'] input",
                        "[class*='sign_up_auth_code_input'] input",
                        "input[data-id][type='number']"
                    ].join(',')
                )].sort((left, right) => {
                    const leftId = Number(left.getAttribute('data-id') || '0');
                    const rightId = Number(right.getAttribute('data-id') || '0');
                    if (leftId !== rightId) return leftId - rightId;
                    return left.getBoundingClientRect().x - right.getBoundingClientRect().x;
                });
                for (const input of inputs) {
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype,
                        'value'
                    ).set;
                    setter.call(input, '');
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                }
                if (inputs[0]) inputs[0].focus();
                return inputs.length;
                """
            )
            self.debug.step("otp_inputs_cleared", fields_count=cleared)
        except Exception:
            logger.debug("Failed to clear OTP inputs", exc_info=True)

    def _is_password_step_visible(self, timeout: int = 1) -> bool:
        return self._find_visible(self.selectors.password_input, timeout=timeout) is not None

    def _fill_password(self) -> None:
        self.debug.step("password_input_lookup")
        elements = self._find_all_visible(self.selectors.password_input)
        if not elements:
            raise RuntimeError("Password input was not found")
        for element in elements[:2]:
            self._clear_and_type(element, self.default_password)
        self.debug.step("password_filled", fields_count=len(elements[:2]))

    def _accept_terms_if_present(self) -> None:
        clicked = self._click_optional(self.selectors.agree_checkbox, timeout=2)
        self.debug.step("terms_checkbox_checked", clicked=clicked)

    def _click_signup(self) -> None:
        self.debug.step("signup_click_attempt")
        if not self._click_optional(self.selectors.signup_button, timeout=15):
            raise RuntimeError("Sign Up/Register button was not found or is not clickable")
        time.sleep(3)
        self.debug.step("signup_clicked", url=self.driver.current_url)

    def _verify_registration_success(self) -> None:
        self.debug.step("success_verification_start")
        deadline = time.time() + 30
        while time.time() < deadline:
            state = self.state_analyzer.analyze(self.driver)
            if state.name == "register_completed" and state.confidence >= 0.72:
                self.debug.step("success_verification_passed", url=self.driver.current_url)
                return
            error_text = self._collect_error_text()
            if error_text:
                raise RuntimeError(error_text)
            time.sleep(2)

        error_text = self._collect_error_text()
        if error_text:
            raise RuntimeError(error_text)
        raise RuntimeError("MEXC registration did not complete within 30s")

    def _handle_captcha(self, phase: str) -> None:
        self.debug.step("captcha_check", phase=phase)
        captcha_found = False
        deadline = time.time() + 8
        while time.time() < deadline:
            if detect_captcha(self.driver):
                captcha_found = True
                break
            state = self.state_analyzer.analyze(self.driver)
            if state.name == "captcha" and state.confidence >= 0.72:
                captcha_found = True
                break
            time.sleep(1)
        if not captcha_found:
            self.debug.step("captcha_not_detected", phase=phase)
            return
        logger.info("CAPTCHA detected during %s for %s", phase, self.debug.masked_email)
        self.debug.step("captcha_detected", phase=phase)
        self.debug.save_screenshot(self.driver, f"captcha_{phase}.png")
        self.debug.save_page_probe(self.driver, f"captcha_probe_{phase}.json")
        self._notify_captcha(self.task_id)
        if self.on_captcha_detected:
            self.on_captcha_detected(self.account.email)
        if not wait_for_captcha_solved(self.driver, timeout=180):
            raise RuntimeError("Captcha was not solved in time")
        self.debug.step("captcha_solved", phase=phase)

    def _find_visible(
        self,
        locators: tuple[Locator, ...],
        timeout: int = 10,
        reject_words: tuple[str, ...] = (),
    ) -> WebElement | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            elements = self._find_all_visible(locators, reject_words=reject_words)
            if elements:
                return elements[0]
            time.sleep(0.3)
        return None

    def _find_present(
        self,
        locators: tuple[Locator, ...],
        timeout: int = 10,
    ) -> WebElement | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for locator in locators:
                try:
                    elements = self.driver.find_elements(*locator)
                except Exception:
                    continue
                if elements:
                    return elements[0]
            time.sleep(0.3)
        return None

    def _find_all_visible(
        self,
        locators: tuple[Locator, ...],
        reject_words: tuple[str, ...] = (),
    ) -> list[WebElement]:
        for by, value in locators:
            try:
                elements = self.driver.find_elements(by, value)
            except Exception:
                continue
            visible = []
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
                    visible.append(element)
                except Exception:
                    continue
            if visible:
                return visible
        return []

    def _click_optional(self, locators: tuple[Locator, ...], timeout: int = 5) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for locator in locators:
                try:
                    element = WebDriverWait(self.driver, 1).until(
                        EC.element_to_be_clickable(locator)
                    )
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                    time.sleep(0.2)
                    element.click()
                    return True
                except Exception:
                    try:
                        elements = self.driver.find_elements(*locator)
                    except Exception:
                        continue
                    for element in elements:
                        try:
                            if not element.is_displayed():
                                continue
                            self.driver.execute_script(
                                """
                                const element = arguments[0];
                                const target = element.closest('button,label,[role="button"]') || element;
                                target.scrollIntoView({ block: 'center' });
                                target.click();
                                """,
                                element,
                            )
                            return True
                        except Exception:
                            continue
            time.sleep(0.2)
        return False

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

    def _debug_referral_elements(self) -> str:
        try:
            return self.driver.execute_script(
                """
                return [...document.querySelectorAll('label,span,svg,input,div')]
                    .filter((element) => {
                        const text = (element.innerText || element.textContent || '').trim();
                        const attrs = [
                            element.id || '',
                            element.getAttribute('for') || '',
                            element.getAttribute('placeholder') || '',
                            String(element.className || '')
                        ].join(' ');
                        const haystack = `${text} ${attrs}`;
                        const rect = element.getBoundingClientRect();
                        const style = window.getComputedStyle(element);
                        return /referral|invite|invitation/i.test(haystack)
                            && rect.width > 0 && rect.height > 0
                            && style.visibility !== 'hidden'
                            && style.display !== 'none';
                    })
                    .slice(0, 8)
                    .map((element) => ({
                        tag: element.tagName,
                        id: element.id || '',
                        forAttr: element.getAttribute('for') || '',
                        placeholder: element.getAttribute('placeholder') || '',
                        className: String(element.className || '').slice(0, 120),
                        text: (element.innerText || element.textContent || '').trim().slice(0, 80)
                    }));
                """
            )
        except Exception:
            return ""
