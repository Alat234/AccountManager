from __future__ import annotations

import logging
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

logger = logging.getLogger(__name__)

# CSS selectors for known MEXC captcha overlays.
CAPTCHA_SELECTORS = [
    ".geetest_panel",
    ".geetest_popup_wrap",
    ".geetest_widget",
    ".geetest_box",
    ".geetest_panel_box",
    ".geetest_panel_next",
    ".geetest_holder",
    ".geetest_window",
    ".captcha-container",
    ".captcha_wrapper",
    ".captcha-box",
    "[aria-label*='captcha' i]",
    "[title*='captcha' i]",
    ".rc-anchor",
    ".g-recaptcha",
    "[class*='recaptcha']",
    "[id*='recaptcha']",
    "iframe[src*='captcha']",
    "iframe[src*='geetest']",
    "iframe[src*='recaptcha']",
    "iframe[src*='google.com/recaptcha']",
    "iframe[title*='reCAPTCHA']",
    "iframe[title*='captcha' i]",
]

CAPTCHA_FALLBACK_SELECTORS = [
    "[class*='geetest']",
    "[class*='captcha']",
    "[id*='captcha']",
]

IFRAME_CAPTCHA_KEYWORDS = [
    "captcha",
    "recaptcha",
    "geetest",
    "verify",
    "challenge",
]


def detect_captcha(driver: WebDriver) -> bool:
    for selector in CAPTCHA_SELECTORS:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                if el.is_displayed() and _is_active_captcha_element(driver, el, strict=True):
                    logger.info("CAPTCHA detected: %s", selector)
                    return True
        except Exception:
            logger.debug("CAPTCHA selector check failed: %s", selector, exc_info=True)

    for selector in CAPTCHA_FALLBACK_SELECTORS:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                if el.is_displayed() and _is_active_captcha_element(driver, el, strict=False):
                    logger.info("CAPTCHA detected by fallback: %s", selector)
                    return True
        except Exception:
            logger.debug("CAPTCHA fallback selector check failed: %s", selector, exc_info=True)

    if _detect_captcha_iframe(driver):
        return True
    return False


def _is_active_captcha_element(driver: WebDriver, element, strict: bool = True) -> bool:
    try:
        state = driver.execute_script(
            """
            const element = arguments[0];
            const strict = arguments[1];
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            const className = String(element.className || '').toLowerCase();
            const id = String(element.id || '').toLowerCase();
            const text = (element.innerText || element.textContent || '').toLowerCase();
            const attrs = [
                element.getAttribute('aria-label') || '',
                element.getAttribute('title') || '',
                element.getAttribute('role') || '',
                className,
                id,
                text
            ].join(' ').toLowerCase();

            const visible = rect.width > 0
                && rect.height > 0
                && style.display !== 'none'
                && style.visibility !== 'hidden'
                && Number(style.opacity || '1') > 0.05;
            if (!visible) return { active: false, reason: 'not_visible' };

            const solved = /success|succeed|passed|done|hide|hidden|offline/.test(attrs);
            if (solved) return { active: false, reason: 'solved_or_hidden_class' };

            const hasChallengeControls = Boolean(element.querySelector(
                [
                    '.geetest_close',
                    '.geetest_refresh',
                    '.geetest_slider_button',
                    '.geetest_btn',
                    '.geetest_submit',
                    '.geetest_panel',
                    '.geetest_window',
                    '[class*="slider"]',
                    '[class*="challenge"]',
                    'canvas'
                ].join(',')
            ));
            const looksLikeGeeTest = /geetest/.test(attrs);
            const looksLikeCaptcha = /captcha|recaptcha|challenge|verify/.test(attrs);
            const overlaySized = rect.width >= 180 && rect.height >= 80;

            if (looksLikeGeeTest && (hasChallengeControls || overlaySized)) {
                return { active: true, reason: 'geetest_active' };
            }
            if (strict && looksLikeCaptcha && overlaySized) {
                return { active: true, reason: 'strict_captcha_active' };
            }
            if (!strict && looksLikeCaptcha && hasChallengeControls && overlaySized) {
                return { active: true, reason: 'fallback_captcha_active' };
            }
            return { active: false, reason: 'no_active_challenge', rect: {
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            }};
            """,
            element,
            strict,
        )
        if isinstance(state, dict) and state.get("active"):
            logger.debug("Active CAPTCHA element state: %s", state)
            return True
        logger.debug("Ignoring CAPTCHA candidate state: %s", state)
        return False
    except Exception:
        logger.debug("Active CAPTCHA element check failed", exc_info=True)
        return False


def _detect_captcha_iframe(driver: WebDriver) -> bool:
    try:
        iframes = driver.find_elements(By.CSS_SELECTOR, "iframe")
    except Exception:
        logger.debug("CAPTCHA iframe lookup failed", exc_info=True)
        return False

    for index, iframe in enumerate(iframes):
        try:
            if not iframe.is_displayed():
                continue
            haystack = " ".join(
                str(iframe.get_attribute(attr) or "").lower()
                for attr in ("src", "title", "name", "id", "class")
            )
            if any(keyword in haystack for keyword in IFRAME_CAPTCHA_KEYWORDS):
                logger.info("CAPTCHA detected in iframe attrs index=%s attrs=%s", index, haystack[:300])
                return True

            driver.switch_to.frame(iframe)
            try:
                for selector in CAPTCHA_SELECTORS:
                    if selector.startswith("iframe"):
                        continue
                    for element in driver.find_elements(By.CSS_SELECTOR, selector):
                        if element.is_displayed():
                            logger.info(
                                "CAPTCHA detected inside iframe index=%s selector=%s",
                                index,
                                selector,
                            )
                            return True
            finally:
                driver.switch_to.default_content()
        except Exception:
            logger.debug("CAPTCHA iframe check failed index=%s", index, exc_info=True)
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
    return False


def wait_for_captcha_solved(
    driver: WebDriver,
    timeout: int = 120,
    poll_interval: float = 2.0,
) -> bool:
    """Poll until captcha disappears or timeout. Returns True if solved."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        if not detect_captcha(driver):
            logger.info("CAPTCHA solved")
            return True
        time.sleep(poll_interval)
    logger.warning("CAPTCHA timeout after %ds", timeout)
    return False
