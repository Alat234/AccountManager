"""RK email verification request, acknowledgment, and code entry."""
import logging
import time
from automation.scenarios.rk_captcha import captcha_visible
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.remote.webelement import WebElement
from automation.scenarios.mexc_browser_helpers import (
    clear_and_type, click_get_code_if_active, fill_code_inputs,
    fill_named_code_input, wait_mexc_email_code,
)

logger = logging.getLogger(__name__)


class RKEmailMixin:
    def _request_email_code(self) -> None:
        if self.ctx is None:
            raise RuntimeError("MEXC context is not initialized")
        # A countdown left by a previous run does not prove a fresh request.
        self.email_code = ''
        deadline = time.monotonic() + 90
        if self._email_code_request_started():
            self.debug.step('rk_email_countdown_wait')
            # Use the server cooldown productively; never reuse an untracked old code.
            if getattr(self, '_form_document_id', None) is None:
                self._fill_documents()
                self._documents_filled_during_countdown = True
                self.debug.step('rk_email_countdown_wait')
        while self._email_code_request_started():
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            if time.monotonic() >= deadline:
                raise RuntimeError("Previous email code countdown has not finished. Try again later.")
            time.sleep(0.5)
        self.ctx.email_code_not_before_ts = time.time() - 10
        self.debug.step("rk_email_code_request_start")
        if not self._click_rk_get_code() and not click_get_code_if_active(self.ctx, timeout=30):
            raise RuntimeError("MEXC RK Get Code button was not found or was not clickable")
        if not self._wait_for_get_code_click_effect(timeout=12):
            self.debug.save_page_probe(self.driver, "rk_get_code_not_confirmed.json")
            raise RuntimeError("MEXC RK Get Code was clicked, but the page did not confirm that the code was requested.")
        self._handle_captcha("rk_after_get_code")
        if not self._email_code_request_started() and self._find_rk_get_code_element() is not None:
            self.debug.step("rk_get_code_retry_after_captcha")
            if not self._click_rk_get_code():
                self.debug.save_page_probe(self.driver, "rk_get_code_retry_after_captcha_failed.json")
                raise RuntimeError("MEXC RK Get Code was still visible after captcha, and retry did not start the code request.")
            self._handle_captcha("rk_after_get_code_retry")
        if not self._wait_for_email_code_request_state(timeout=12):
            raise RuntimeError("MEXC did not confirm the RK email code request after CAPTCHA.")
        self.debug.step("rk_email_code_requested")

    def _click_rk_get_code(self) -> bool:
        if self.ctx is None:
            raise RuntimeError("MEXC context is not initialized")
        deadline = time.time() + 24
        last_result = {}
        while time.time() < deadline:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            if self._email_code_request_started():
                self.debug.step("rk_get_code_already_requested")
                return True
            element = self._find_rk_get_code_element()
            if element is not None:
                last_result = self._click_rk_get_code_element(element)
                if last_result.get("clicked"):
                    self.ctx.email_code_not_before_ts = time.time() - 10
                    self.debug.step("rk_get_code_clicked", result=last_result)
                    if self._wait_for_get_code_click_effect(timeout=10):
                        return True
                    self.debug.warning("rk_get_code_click_not_confirmed", result=last_result)
                time.sleep(0.5)
                continue
            result = self.driver.execute_script(
                """
                const visible = (element) => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && style.pointerEvents !== 'none'
                        && Number(style.opacity || '1') > 0.05;
                };
                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const input = document.querySelector('#emailCode');
                if (!input || !visible(input)) return { clicked: false, reason: 'emailCode_not_visible' };

                const inputRect = input.getBoundingClientRect();
                const elements = [...document.querySelectorAll('button,a,[role="button"],span,div')];
                const candidates = elements
                    .filter(visible)
                    .filter((element) => {
                        const text = normalize(element.innerText || element.textContent);
                        if (text !== 'get code' && text !== 'send code') return false;
                        if (element === input || element.contains(input)) return false;
                        const rect = element.getBoundingClientRect();
                        const sameRow = Math.abs((rect.y + rect.height / 2) - (inputRect.y + inputRect.height / 2)) <= 80;
                        const nearInput = rect.x >= inputRect.x - 8 && rect.x <= inputRect.x + inputRect.width + 260;
                        return sameRow && nearInput;
                    })
                    .sort((left, right) => {
                        const a = left.getBoundingClientRect();
                        const b = right.getBoundingClientRect();
                        const inputCenterY = inputRect.y + inputRect.height / 2;
                        const dyLeft = Math.abs((a.y + a.height / 2) - inputCenterY);
                        const dyRight = Math.abs((b.y + b.height / 2) - inputCenterY);
                        return dyLeft - dyRight || (a.width * a.height) - (b.width * b.height);
                    });
                for (const element of candidates) {
                    const target = element.closest('button,a,[role="button"]') || element;
                    const classText = String(target.className || '').toLowerCase();
                    const disabled = target.disabled
                        || target.getAttribute('aria-disabled') === 'true'
                        || classText.includes('disabled');
                    if (disabled) continue;
                    target.scrollIntoView({ block: 'center', inline: 'center' });
                    for (const eventName of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
                    }
                    return {
                        clicked: true,
                        text: normalize(element.innerText || element.textContent),
                        rect: {
                            x: Math.round(target.getBoundingClientRect().x),
                            y: Math.round(target.getBoundingClientRect().y),
                            width: Math.round(target.getBoundingClientRect().width),
                            height: Math.round(target.getBoundingClientRect().height)
                        }
                    };
                }
                return { clicked: false, reason: 'get_code_not_found_near_email_code', candidateCount: candidates.length };
                """
            )
            last_result = result if isinstance(result, dict) else {}
            if last_result.get("clicked"):
                self.ctx.email_code_not_before_ts = time.time() - 10
                self.debug.step("rk_get_code_clicked", result=last_result)
                if self._wait_for_email_code_request_state(timeout=10):
                    return True
                self.debug.warning("rk_get_code_click_not_confirmed", result=last_result)
            time.sleep(0.5)
        self.debug.warning("rk_get_code_click_failed", result=last_result)
        return False

    def _find_rk_get_code_element(self) -> WebElement | None:
        try:
            return self.driver.execute_script(
                """
                const visible = (element) => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && style.pointerEvents !== 'none'
                        && Number(style.opacity || '1') > 0.05;
                };
                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const input = document.querySelector('#emailCode');
                if (!input || !visible(input)) return null;
                const inputRect = input.getBoundingClientRect();
                const suffix = input.closest('.ant-input-affix-wrapper')?.querySelector('.ant-input-suffix');
                const suffixMatches = suffix
                    ? [...suffix.querySelectorAll('button,a,[role="button"],span,div')]
                        .filter(visible)
                        .filter((element) => ['get code', 'send code'].includes(normalize(element.innerText || element.textContent)))
                    : [];
                const rowMatches = [...document.querySelectorAll('button,a,[role="button"],span,div')]
                    .filter(visible)
                    .filter((element) => {
                        const text = normalize(element.innerText || element.textContent);
                        if (text !== 'get code' && text !== 'send code') return false;
                        if (element === input || element.contains(input)) return false;
                        const rect = element.getBoundingClientRect();
                        const sameRow = Math.abs((rect.y + rect.height / 2) - (inputRect.y + inputRect.height / 2)) <= 90;
                        const nearInput = rect.x >= inputRect.x && rect.x <= inputRect.x + inputRect.width + 320;
                        return sameRow && nearInput;
                    });
                // Prefer the innermost text target: clicking its wrapper does not
                // dispatch a click to a child that owns the React handler.
                const matches = [...suffixMatches, ...rowMatches];
                const candidates = matches.filter(e => !matches.some(child => child !== e && e.contains(child)))
                    .sort((left, right) => {
                        const a = left.getBoundingClientRect();
                        const b = right.getBoundingClientRect();
                        const inputCenterY = inputRect.y + inputRect.height / 2;
                        return Math.abs((a.y + a.height / 2) - inputCenterY)
                            - Math.abs((b.y + b.height / 2) - inputCenterY)
                            || (a.width * a.height) - (b.width * b.height);
                    });
                for (const element of candidates) {
                    const target = element.closest('button,a,[role="button"]') || element;
                    const classText = String(target.className || '').toLowerCase();
                    const disabled = target.disabled
                        || target.getAttribute('aria-disabled') === 'true'
                        || classText.includes('disabled');
                    if (!disabled) return target;
                }
                return null;
                """
            )
        except Exception:
            logger.debug("RK Get Code element lookup failed", exc_info=True)
            return None

    def _click_rk_get_code_element(self, element: WebElement) -> dict:
        methods: list[str] = []
        try:
            geometry = self.driver.execute_script("""
                const e = arguments[0], r = e.getBoundingClientRect();
                const hit = document.elementFromPoint(r.x+r.width/2, r.y+r.height/2);
                return {tag:e.tagName, targetClass:String(e.className),
                    rect:{x:r.x,y:r.y,width:r.width,height:r.height},
                    viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio},
                    visibility:document.visibilityState, hasFocus:document.hasFocus(),
                    hitTag:hit?.tagName, hitClass:String(hit?.className || '')};
                """, element)
            self.debug.step('rk_get_code_target', geometry=geometry)
        except Exception:
            self._raise_if_cancelled()
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({ block: 'center', inline: 'center' });",
                element,
            )
        except Exception:
            pass
        for method_name, clicker in (
            ("selenium_click", lambda: element.click()),
            ("action_chains_click", lambda: ActionChains(self.driver).move_to_element(element).pause(0.1).click().perform()),
            ("html_click", lambda: self.driver.execute_script("arguments[0].click();", element)),
            (
                "suffix_html_click",
                lambda: self.driver.execute_script(
                    """
                    const element = arguments[0];
                    const target = element.closest('.ant-input-suffix') || element;
                    target.click();
                    """,
                    element,
                ),
            ),
        ):
            try:
                clicker()
                methods.append(method_name)
                time.sleep(0.8)
                if self._get_code_click_effect_visible():
                    return {"clicked": True, "method": method_name, "tried": methods}
            except Exception as exc:
                methods.append(f"{method_name}: {type(exc).__name__}")
                logger.debug("RK Get Code %s failed", method_name, exc_info=True)
        return {"clicked": bool(methods), "method": "", "tried": methods}

    def _wait_for_get_code_click_effect(self, *, timeout: int) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            if self._get_code_click_effect_visible():
                return True
            time.sleep(0.5)
        return False

    def _get_code_click_effect_visible(self) -> bool:
        return self._email_code_request_started() or self._captcha_visible()

    def _captcha_visible(self) -> bool:
        return captcha_visible(self.driver)

    def _wait_for_email_code_request_state(self, *, timeout: int) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            if self._email_code_request_started():
                return True
            time.sleep(0.5)
        return False

    def _email_code_request_started(self) -> bool:
        try:
            return bool(self.driver.execute_script(
                r"""
                const input = document.querySelector('#emailCode');
                const suffix = input?.closest('.ant-input-affix-wrapper')?.querySelector('.ant-input-suffix');
                if (!suffix || !suffix.getBoundingClientRect().width) return false;
                const text = (suffix.innerText || '').replace(/\s+/g, ' ').trim().toLowerCase();
                return /\b\d{1,3}\s*s\b|code sent|sent successfully|resend (?:in|after) \d/.test(text);
                """
            ))
        except Exception:
            return False

    def _fill_email_code(self) -> None:
        if self.ctx is None:
            raise RuntimeError("MEXC context is not initialized")
        self._restore_if_document_reloaded()
        self.debug.step("rk_email_code_wait_start")
        self.email_code = wait_mexc_email_code(self.ctx)
        self.debug.with_secrets(self.email_code)
        self.ctx.tried_email_codes.add(self.email_code)
        if not self._fill_rk_email_code(self.email_code):
            raise RuntimeError("MEXC RK Email Verification Code field was not found")
        if not self._email_code_value_matches(self.email_code):
            self.debug.save_page_probe(self.driver, "rk_email_code_value_not_confirmed.json")
            raise RuntimeError("MEXC RK Email Verification Code field did not keep the fetched code.")
        self.debug.step("rk_email_code_filled")

    def _fill_rk_email_code(self, email_code: str) -> bool:
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
            const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const direct = document.querySelector('#emailCode');
            if (direct && visible(direct)) return direct;
            const candidates = [...document.querySelectorAll('.ant-form-item, [class*="form-item"], section, div')]
                .filter(visible)
                .filter((element) => normalize(element.innerText || element.textContent).includes('email verification code'))
                .sort((left, right) => {
                    const a = left.getBoundingClientRect();
                    const b = right.getBoundingClientRect();
                    return (a.width * a.height) - (b.width * b.height);
                });
            for (const candidate of candidates) {
                const input = [...candidate.querySelectorAll('input,textarea')]
                    .filter(visible)
                    .find((item) => !['file', 'checkbox', 'radio', 'hidden'].includes(normalize(item.type || '')));
                if (input) return input;
            }
            return null;
            """
        )
        if element is not None:
            clear_and_type(self.driver, element, email_code)
            return True
        return fill_named_code_input(
            self.driver,
            email_code,
            ("email verification", "verification code"),
            security_modal_only=False,
        ) or fill_code_inputs(self.driver, email_code)

    def _email_code_value_matches(self, email_code: str) -> bool:
        deadline = time.time() + 6
        expected = (email_code or "").strip()
        while time.time() < deadline:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            try:
                value = str(
                    self.driver.execute_script(
                        """
                        const input = document.querySelector('#emailCode');
                        return input?.value || input?.getAttribute('value') || '';
                        """
                    )
                    or ""
                ).strip()
            except Exception:
                value = ""
            if value == expected:
                return True
            time.sleep(0.35)
        return False

