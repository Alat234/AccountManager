from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from collections.abc import Callable

import pyotp
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait

from automation.captcha import detect_captcha, wait_for_captcha_solved
from automation.scenarios.mexc_debug import MexcRegistrationDebug
from automation.scenarios.mexc_selectors import Locator, MexcRegistrationSelectors

logger = logging.getLogger(__name__)


@dataclass
class MexcBrowserContext:
    driver: WebDriver
    account: object
    debug: MexcRegistrationDebug
    email_fetcher: object | None = None
    captcha_service: object | None = None
    task_id: str = ""
    selectors: MexcRegistrationSelectors = field(default_factory=MexcRegistrationSelectors)
    on_captcha_detected: Callable[[str], None] | None = None
    on_email_timeout: Callable[[str], bool] | None = None
    email_code_not_before_ts: float | None = None
    tried_email_codes: set[str] = field(default_factory=set)


def open_mexc_page(ctx: MexcBrowserContext, url: str, step_prefix: str) -> None:
    ctx.debug.step(f"{step_prefix}_open_page", url=url)
    ctx.driver.get(url)
    WebDriverWait(ctx.driver, 30).until(
        lambda driver: driver.execute_script("return document.readyState") == "complete"
    )
    time.sleep(2)
    ctx.debug.step(f"{step_prefix}_page_loaded", url=ctx.driver.current_url, title=ctx.driver.title)


def ensure_mexc_logged_in(ctx: MexcBrowserContext, return_url: str, step_prefix: str) -> None:
    if not is_mexc_login_required(ctx):
        ctx.debug.step(f"{step_prefix}_login_not_required")
        return

    ctx.debug.step(f"{step_prefix}_login_required")
    if not getattr(ctx.account, "password", ""):
        raise RuntimeError("MEXC account is not logged in and no saved password is available")

    perform_mexc_login(ctx)
    handle_mexc_captcha(ctx, "after_login")
    ctx.driver.get(return_url)
    WebDriverWait(ctx.driver, 30).until(
        lambda driver: driver.execute_script("return document.readyState") == "complete"
    )
    time.sleep(2)
    if is_mexc_login_required(ctx):
        raise RuntimeError("MEXC login did not complete; please log in manually and retry")
    ctx.debug.step(f"{step_prefix}_login_completed")


def is_mexc_login_required(ctx: MexcBrowserContext) -> bool:
    current_url = (ctx.driver.current_url or "").lower()
    if "login" in current_url or "sign-in" in current_url:
        return True
    body_text = page_text(ctx.driver).lower()
    if find_visible(ctx.driver, ctx.selectors.password_input, timeout=1) is not None:
        return "log in" in body_text or "login" in body_text or "email" in body_text
    if find_visible(ctx.driver, ctx.selectors.email_input, timeout=1) is not None:
        return "log in" in body_text or "login" in body_text
    return False


def perform_mexc_login(ctx: MexcBrowserContext) -> None:
    ctx.debug.step("login_email_lookup")
    email_input = find_visible(ctx.driver, ctx.selectors.email_input, timeout=20)
    if email_input is not None:
        clear_and_type(ctx.driver, email_input, ctx.account.email)
        ctx.debug.step("login_email_filled")
        clicked = click_by_text(ctx.driver, ("continue", "next"), timeout=4)
        ctx.debug.step("login_continue_check", clicked=clicked)
        time.sleep(2)

    password_input = find_visible(ctx.driver, ctx.selectors.password_input, timeout=20)
    if password_input is None:
        raise RuntimeError("MEXC login password input was not found")
    clear_and_type(ctx.driver, password_input, ctx.account.password)
    ctx.debug.step("login_password_filled")

    if not click_by_text(ctx.driver, ("log in", "login", "continue", "next"), timeout=15):
        raise RuntimeError("MEXC login submit button was not found")
    ctx.debug.step("login_submitted")
    time.sleep(4)

    if is_email_code_step_visible(ctx):
        ctx.debug.step("login_email_code_step_detected")
        if click_get_code_if_active(ctx, timeout=15):
            email_code = wait_mexc_email_code(ctx)
            ctx.tried_email_codes.add(email_code)
            if not fill_code_inputs(ctx.driver, email_code):
                fill_named_code_input(ctx.driver, email_code, ("email", "mail"), security_modal_only=False)
            click_by_text(ctx.driver, ("confirm", "continue", "next", "submit"), timeout=10)
            time.sleep(4)

    complete_login_totp_if_visible(ctx)


def complete_login_totp_if_visible(ctx: MexcBrowserContext) -> bool:
    if not getattr(ctx.account, "two_fa_secret", ""):
        return False
    deadline = time.time() + 20
    while time.time() < deadline:
        totp_input = find_totp_input(ctx.driver, security_modal_only=False)
        if totp_input is None:
            text = page_text(ctx.driver).lower()
            if "authenticator code" not in text and "google authenticator" not in text:
                time.sleep(0.5)
                continue
            totp_input = find_totp_input(ctx.driver, security_modal_only=False)
        if totp_input is None:
            time.sleep(0.5)
            continue
        ctx.debug.step("login_totp_step_detected")
        code = fresh_totp_code(ctx.account.two_fa_secret, ctx.debug, "login_totp")
        clear_and_type(ctx.driver, totp_input, code)
        if click_security_submit(ctx.driver, ("confirm", "continue", "next", "submit")):
            time.sleep(4)
            ctx.debug.step("login_totp_submitted")
            return True
        raise RuntimeError("MEXC login authenticator submit button was not found")
    return False


def handle_mexc_captcha(ctx: MexcBrowserContext, phase: str) -> None:
    ctx.debug.step("captcha_check", phase=phase)
    if not detect_captcha(ctx.driver):
        ctx.debug.step("captcha_not_detected", phase=phase)
        return

    ctx.debug.step("captcha_detected", phase=phase)
    ctx.debug.save_screenshot(ctx.driver, f"captcha_{phase}.png")
    ctx.debug.save_page_probe(ctx.driver, f"captcha_probe_{phase}.json")
    if ctx.captcha_service:
        ctx.captcha_service.notify(account_email=ctx.account.email, task_id=ctx.task_id)
    if ctx.on_captcha_detected:
        ctx.on_captcha_detected(ctx.account.email)
    if not wait_for_captcha_solved(ctx.driver, timeout=180):
        raise RuntimeError("CAPTCHA was not solved within 180s")
    ctx.debug.step("captcha_solved", phase=phase)


def click_get_code_if_active(ctx: MexcBrowserContext, timeout: int = 10) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        clicked = ctx.driver.execute_script(
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
                    || String(target.className || '').toLowerCase().includes('disabled');
                if (disabled) continue;
                target.scrollIntoView({ block: 'center', inline: 'center' });
                target.click();
                return true;
            }
            return false;
            """
        )
        if clicked:
            ctx.email_code_not_before_ts = time.time() - 10
            time.sleep(3)
            ctx.debug.step("get_code_active_check", clicked=True)
            return True
        time.sleep(0.5)
    ctx.debug.step("get_code_active_check", clicked=False)
    return False


def wait_mexc_email_code(ctx: MexcBrowserContext, timeout: int = 180) -> str:
    if not ctx.email_fetcher:
        raise RuntimeError("Email fetcher is not configured")

    attempt = 1
    while True:
        ctx.debug.step(
            "email_code_wait_start",
            attempt=attempt,
            timeout=timeout,
            ignored_count=len(ctx.tried_email_codes),
            not_before=int(ctx.email_code_not_before_ts) if ctx.email_code_not_before_ts else None,
        )
        try:
            code = ctx.email_fetcher.wait_for_code(
                ctx.account.email,
                timeout=timeout,
                poll_interval=5,
                not_before_ts=ctx.email_code_not_before_ts,
                ignored_codes=ctx.tried_email_codes,
            )
        except RuntimeError as exc:
            if f"No MEXC verification code received within {timeout}s" not in str(exc):
                raise
            ctx.debug.warning("email_code_wait_timeout", attempt=attempt)
            if not ask_wait_more_for_email_code(ctx):
                raise RuntimeError("MEXC email verification code wait was stopped by user") from exc
            attempt += 1
            continue
        ctx.debug.step("email_code_found", code_found=True, code_length=len(code), attempt=attempt)
        return code


def ask_wait_more_for_email_code(ctx: MexcBrowserContext) -> bool:
    if not ctx.on_email_timeout:
        return False
    try:
        should_continue = bool(ctx.on_email_timeout(ctx.account.email))
    except Exception:
        logger.exception("Email timeout callback failed")
        return False
    ctx.debug.step("email_code_wait_user_decision", wait_more=should_continue)
    return should_continue


def fresh_totp_code(secret: str, debug: MexcRegistrationDebug, step_prefix: str = "totp") -> str:
    remaining = 30 - (int(time.time()) % 30)
    if remaining <= 8:
        debug.step(f"{step_prefix}_wait_for_fresh_cycle", seconds=remaining)
        time.sleep(remaining + 1)
    code = pyotp.TOTP(secret).now()
    debug.step(f"{step_prefix}_generated", code_length=len(code))
    return code


def is_email_code_step_visible(ctx: MexcBrowserContext) -> bool:
    return bool(visible_code_inputs(ctx.driver)) or "verification code" in page_text(ctx.driver).lower()


def security_modal_text(driver: WebDriver) -> str:
    try:
        return str(
            driver.execute_script(
                """
                const visible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const modal = [...document.querySelectorAll(
                    '.ant-modal, .ant-modal-v2, [role="dialog"], [class*="modal"]'
                )].find(visible);
                return modal ? (modal.innerText || modal.textContent || '') : '';
                """
            )
            or ""
        )
    except Exception:
        return ""


def fill_named_code_input(
    driver: WebDriver,
    code: str,
    preferred_words: tuple[str, ...],
    *,
    security_modal_only: bool,
) -> bool:
    element = input_with_words(driver, preferred_words, security_modal_only=security_modal_only)
    if element is None:
        return False
    clear_and_type(driver, element, code)
    return True


def input_with_words(
    driver: WebDriver,
    words: tuple[str, ...],
    *,
    security_modal_only: bool = False,
) -> WebElement | None:
    wanted = tuple(word.lower() for word in words)
    try:
        return driver.execute_script(
            """
            const wanted = arguments[0];
            const modalOnly = arguments[1];
            const visible = (element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && !element.disabled;
            };
            const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const root = modalOnly
                ? [...document.querySelectorAll('.ant-modal, .ant-modal-v2, [role="dialog"], [class*="modal"]')]
                    .find(visible)
                : document;
            if (!root) return null;
            const inputs = [...root.querySelectorAll('input')]
                .filter(visible)
                .filter((input) => {
                    const attrs = [
                        input.id,
                        input.name,
                        input.placeholder,
                        input.getAttribute('aria-label'),
                        input.getAttribute('autocomplete'),
                        input.closest('.ant-form-item, .ant-row, label, div')?.innerText
                    ].map(normalize).join(' ');
                    return wanted.some((word) => attrs.includes(word));
                });
            return inputs[0] || null;
            """,
            list(wanted),
            security_modal_only,
        )
    except Exception:
        logger.debug("Named input lookup failed", exc_info=True)
        return None


def find_totp_input(driver: WebDriver, *, security_modal_only: bool) -> WebElement | None:
    return input_with_words(
        driver,
        ("google", "authenticator", "totp", "mexc/google"),
        security_modal_only=security_modal_only,
    )


def fill_code_inputs(driver: WebDriver, code: str) -> bool:
    inputs = visible_code_inputs(driver)
    if not inputs:
        return False
    digits = [char for char in code if char.isdigit()]
    if len(digits) != 6:
        raise RuntimeError("MEXC verification code is not 6 digits")
    code_value = "".join(digits)

    try:
        first = inputs[0]
        first.click()
        first.send_keys(Keys.CONTROL, "a")
        first.send_keys(code_value)
        time.sleep(1)
        if otp_values_match(driver, code_value):
            return True
    except Exception:
        logger.debug("OTP paste failed", exc_info=True)

    for index, digit in enumerate(code_value):
        fresh_inputs = visible_code_inputs(driver)
        if len(fresh_inputs) <= index:
            return otp_values_match(driver, code_value)
        clear_and_type(driver, fresh_inputs[index], digit)
        time.sleep(0.1)
    return otp_values_match(driver, code_value)


def visible_code_inputs(driver: WebDriver) -> list[WebElement]:
    try:
        inputs = driver.execute_script(
            """
            const visible = (element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && !element.disabled;
            };
            return [...document.querySelectorAll(
                [
                    '.react-code-input input',
                    "[class*='auth_code_input'] input",
                    "[class*='sign_up_auth_code_input'] input",
                    "input[data-id][type='number']",
                    "input[maxlength='1'][type='number']",
                    "input[maxlength='6']"
                ].join(',')
            )].filter(visible);
            """
        )
        return inputs if isinstance(inputs, list) else []
    except Exception:
        return []


def otp_values_match(driver: WebDriver, code: str) -> bool:
    try:
        values = driver.execute_script(
            """
            return [...document.querySelectorAll(
                [
                    '.react-code-input input',
                    "[class*='auth_code_input'] input",
                    "[class*='sign_up_auth_code_input'] input",
                    "input[data-id][type='number']",
                    "input[maxlength='1'][type='number']",
                    "input[maxlength='6']"
                ].join(',')
            )].slice(0, 6).map((input) => input.value || '');
            """
        )
        return isinstance(values, list) and "".join(str(value) for value in values[:6]) == code
    except Exception:
        return False


def click_security_submit(driver: WebDriver, texts: tuple[str, ...] = ("submit", "confirm")) -> bool:
    return click_button_in_modal(driver, texts, timeout=10) or click_by_text(driver, texts, timeout=5)


def click_button_in_modal(driver: WebDriver, texts: tuple[str, ...], timeout: int = 10) -> bool:
    wanted = tuple(text.lower() for text in texts)
    deadline = time.time() + timeout
    while time.time() < deadline:
        clicked = driver.execute_script(
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
            const modal = [...document.querySelectorAll(
                '.ant-modal, .ant-modal-v2, [role="dialog"], [class*="modal"]'
            )].find(visible);
            if (!modal) return false;
            const buttons = [...modal.querySelectorAll('button,[role="button"]')]
                .filter(visible)
                .filter((button) => wanted.some((text) => normalize(button.innerText || button.textContent).includes(text)));
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
            """,
            list(wanted),
        )
        if clicked:
            time.sleep(1)
            return True
        time.sleep(0.5)
    return False


def click_by_text(driver: WebDriver, texts: tuple[str, ...], timeout: int = 10) -> bool:
    wanted = tuple(text.lower() for text in texts)
    deadline = time.time() + timeout
    while time.time() < deadline:
        clicked = driver.execute_script(
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
            const candidates = [...document.querySelectorAll('button,a,label,span,div,[role="button"]')]
                .filter(visible)
                .filter((element) => {
                    const text = normalize(element.innerText || element.textContent);
                    return wanted.some((word) => text === word || text.includes(word));
                })
                .sort((left, right) => {
                    const leftRect = left.getBoundingClientRect();
                    const rightRect = right.getBoundingClientRect();
                    return (leftRect.width * leftRect.height) - (rightRect.width * rightRect.height);
                });
            for (const element of candidates) {
                const target = element.closest('button,a,label,[role="button"]') || element;
                const disabled = target.disabled
                    || target.getAttribute('aria-disabled') === 'true'
                    || String(target.className || '').toLowerCase().includes('disabled');
                if (disabled) continue;
                target.scrollIntoView({ block: 'center', inline: 'center' });
                target.click();
                return true;
            }
            return false;
            """,
            list(wanted),
        )
        if clicked:
            time.sleep(1)
            return True
        time.sleep(0.5)
    return False


def find_visible(driver: WebDriver, locators: tuple[Locator, ...], timeout: int = 10) -> WebElement | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for by, value in locators:
            try:
                for element in driver.find_elements(by, value):
                    if element.is_displayed() and element.is_enabled():
                        return element
            except Exception:
                logger.debug("Visible lookup failed for %s=%s", by, value, exc_info=True)
        time.sleep(0.3)
    return None


def clear_and_type(driver: WebDriver, element: WebElement, value: str) -> None:
    try:
        element.click()
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(Keys.BACKSPACE)
        element.send_keys(value)
        return
    except Exception:
        logger.debug("Keyboard input failed, using JS value setter", exc_info=True)
    driver.execute_script(
        """
        const element = arguments[0];
        const value = arguments[1];
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
            || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
        setter.call(element, value);
        element.dispatchEvent(new Event('input', { bubbles: true }));
        element.dispatchEvent(new Event('change', { bubbles: true }));
        """,
        element,
        value,
    )


def page_text(driver: WebDriver) -> str:
    try:
        return str(driver.execute_script("return document.body ? document.body.innerText : ''") or "")
    except Exception:
        return ""


def collect_error_text(driver: WebDriver) -> str:
    try:
        text = str(
            driver.execute_script(
                """
                const visible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                return [...document.querySelectorAll(
                    '.ant-form-item-explain-error, .ant-message-error, .ant-notification-notice-message, '
                    + '.ant-modal .error, [class*="error"], [class*="Error"]'
                )].filter(visible).map((element) => element.innerText || element.textContent || '')
                    .join('\\n').trim();
                """
            )
            or ""
        )
    except Exception:
        return ""
    return re.sub(r"\s+", " ", text).strip()
