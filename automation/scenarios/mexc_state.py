from __future__ import annotations

import logging
from typing import Any

from selenium.webdriver.remote.webdriver import WebDriver

from automation.captcha import detect_captcha
from automation.recovery import PageState

logger = logging.getLogger(__name__)

REGISTER_URL = "https://www.mexc.com/register"
MEXC_HOST_MARKERS = ("mexc.com", "mexc.co")
REGISTER_PATH_MARKERS = ("/register", "/signup", "sign-up")
LOGIN_PATH_MARKERS = ("/login", "sign-in", "signin")
SECURITY_PATH_MARKERS = ("/user/security", "manage-google-auth")
OPENAPI_PATH_MARKERS = ("/openapi", "/api-management")


class MexcPageStateAnalyzer:
    """Best-effort MEXC screen classifier shared by all MEXC scenarios."""

    def analyze(self, driver: WebDriver | None) -> PageState:
        if driver is None:
            return PageState("browser_closed", confidence=1.0)
        try:
            tab_context = self._ensure_relevant_mexc_tab(driver)
            if tab_context.get("state") == "wrong_browser_tab":
                return PageState(
                    "wrong_browser_tab",
                    confidence=0.82,
                    url=str(tab_context.get("url") or ""),
                    title=str(tab_context.get("title") or ""),
                    hints=tab_context,
                )

            captcha_active = False
            try:
                captcha_active = detect_captcha(driver)
            except Exception:
                logger.debug("Shared CAPTCHA detector failed during state analysis", exc_info=True)

            snapshot = driver.execute_script(
                """
                const visible = (element) => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && Number(style.opacity || '1') > 0.05;
                };
                const text = (document.body?.innerText || '').replace(/\\s+/g, ' ').trim();
                const lower = text.toLowerCase();
                const visibleInputs = [...document.querySelectorAll('input,textarea')]
                    .filter(visible)
                    .map((input) => [
                        input.id,
                        input.name,
                        input.placeholder,
                        input.getAttribute('aria-label'),
                        input.getAttribute('autocomplete'),
                        input.type,
                        input.closest('.ant-form-item, label, div')?.innerText
                    ].join(' ').toLowerCase());
                const visibleButtons = [...document.querySelectorAll('button,[role="button"],a,span')]
                    .filter(visible)
                    .map((button) => (button.innerText || button.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase())
                    .filter(Boolean)
                    .slice(0, 80);
                const has = (needle) => lower.includes(needle);
                const inputHas = (needle) => visibleInputs.some((value) => value.includes(needle));
                const isReferralInput = (value) => /invite|invitation|referral/.test(value);
                const codeInputs = visibleInputs.filter((value) => value.includes('code') && !isReferralInput(value));
                const hasVerificationCopy = has('verification code')
                    || has('email verification')
                    || has('enter verification code');
                const buttonHas = (needle) => visibleButtons.some((value) => value.includes(needle));
                const captcha = [...document.querySelectorAll(
                    '.geetest_panel,.geetest_popup_wrap,.geetest_widget,.geetest_window,.captcha-container,.g-recaptcha,iframe[src*="captcha"],iframe[src*="geetest"],iframe[src*="recaptcha"]'
                )].some(visible);
                const visibleModals = [...document.querySelectorAll('.ant-modal-content, .ant-modal, [role="dialog"], [class*="modal"]')]
                    .filter(visible);
                const modalText = visibleModals
                    .map((modal) => (modal.innerText || modal.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase())
                    .join(' ');
                const modalInputs = visibleModals.flatMap((modal) =>
                    [...modal.querySelectorAll('input,textarea')]
                        .filter(visible)
                        .map((input) => [
                            input.id,
                            input.name,
                            input.placeholder,
                            input.getAttribute('aria-label'),
                            input.getAttribute('autocomplete'),
                            input.type,
                            input.closest('.ant-form-item, label, div')?.innerText
                        ].join(' ').toLowerCase())
                );
                const modalInputHas = (needle) => modalInputs.some((value) => value.includes(needle));
                const loader = [...document.querySelectorAll('[class*="loading"],[class*="spin"],[aria-busy="true"]')]
                    .some(visible);
                const url = window.location.href;
                const urlLower = url.toLowerCase();
                const readyState = document.readyState;
                const hostIsMexc = /mexc\\.(com|co)/.test(urlLower);
                const loginButton = buttonHas('login') || buttonHas('log in') || buttonHas('sign in');
                const signupButton = buttonHas('sign up') || buttonHas('signup') || buttonHas('register');
                const accountSignals = has('assets') || has('wallet') || has('deposit')
                    || has('orders') || has('account') || has('profile') || has('overview');
                const twofaUrl = /manage-google-auth|user\\/security/.test(urlLower);
                const compactText = text.replace(/\\s+/g, ' ');
                const base32Candidate = /\\b[A-Z2-7]{16,64}\\b/i.test(compactText);
                const twofaSecret = /\\bkey:\\s*[A-Z2-7]{16,64}\\b/i.test(compactText)
                    || (has('backup') && base32Candidate);
                const hasSecurityModal = modalText.includes('security verification');
                const twofaCompleted = twofaUrl && (
                    has('success') || has('enabled') || has('bound') || has('link successful')
                    || has('unbind') || has('disable google authenticator')
                );
                const twofaIntro = twofaUrl && !twofaSecret && !hasSecurityModal
                    && (has('google authenticator') || has('authenticator app') || buttonHas('next'));
                return {
                    url,
                    title: document.title,
                    readyState,
                    text: lower.slice(0, 2000),
                    inputHints: visibleInputs.slice(0, 60),
                    buttonHints: visibleButtons,
                    captcha: captcha || arguments[0],
                    loader,
                    login: /login|sign-in|signin/.test(urlLower) || (
                        (inputHas('password') || inputHas('email')) && (has('log in') || has('login'))
                    ),
                    registerEmail: /register|signup|sign-up/.test(urlLower)
                        && inputHas('email') && !codeInputs.length && !inputHas('password'),
                    registerCode: codeInputs.length > 0 || hasVerificationCopy,
                    registerPassword: inputHas('password') && (/register|signup|sign-up/.test(urlLower) || has('set password')),
                    registerCompleted: hostIsMexc
                        && !/register|signup|sign-up|login|sign-in|signin/.test(urlLower)
                        && !loginButton
                        && !signupButton
                        && accountSignals,
                    apiForm: /openapi/.test(urlLower) && (inputHas('memo') || inputHas('note') || has('api key permissions')),
                    apiCreated: /openapi/.test(urlLower) && (
                        modalText.includes('created successfully')
                        || (modalText.includes('access key') && modalText.includes('secret key'))
                    ),
                    twofaCompleted,
                    twofaSecret: twofaUrl && twofaSecret,
                    twofaIntro,
                    securityModalEmail: hasSecurityModal && (
                        modalInputHas('email') || modalText.includes('email verification') || modalText.includes('sent to')
                    ),
                    securityModalTotp: hasSecurityModal && (
                        modalInputHas('google') || modalInputHas('authenticator') || modalInputHas('totp')
                        || modalText.includes('google authenticator') || modalText.includes('authenticator code')
                    ),
                    networkError: has('this site can') || has('err_') || has('reload') && has('network')
                };
                """
                ,
                captcha_active,
            )
        except Exception as exc:
            message = str(exc).lower()
            if "no such window" in message or "invalid session" in message or "web view not found" in message:
                return PageState("browser_closed", confidence=1.0)
            logger.debug("MEXC page state analysis failed", exc_info=True)
            return PageState("unknown", confidence=0.0, hints={"error": str(exc)})

        data = snapshot if isinstance(snapshot, dict) else {}
        name, confidence = self._pick_state(data)
        return PageState(
            name=name,
            confidence=confidence,
            url=str(data.get("url") or ""),
            title=str(data.get("title") or ""),
            hints={
                "loader": bool(data.get("loader")),
                "captcha": bool(data.get("captcha")),
                "ready_state": str(data.get("readyState") or ""),
                "switched_tab": bool(tab_context.get("switched")),
                "buttons": data.get("buttonHints", []),
                "inputs": data.get("inputHints", []),
            },
        )

    @staticmethod
    def _pick_state(data: dict[str, Any]) -> tuple[str, float]:
        priority = [
            ("network_error", 0.95),
            ("captcha", 0.95),
            ("api_created", 0.92),
            ("twofa_completed", 0.92),
            ("security_modal_totp", 0.9),
            ("security_modal_email", 0.9),
            ("twofa_secret", 0.88),
            ("twofa_intro", 0.84),
            ("api_form", 0.88),
            ("register_completed", 0.86),
            ("register_password", 0.85),
            ("register_code", 0.85),
            ("register_email", 0.82),
            ("login", 0.82),
        ]
        for key, confidence in priority:
            if data.get(_camel_key(key)):
                return key, confidence
        if data.get("readyState") in ("loading", "interactive"):
            return "network_loading", 0.76
        if data.get("loader"):
            return "network_loading", 0.65
        return "unknown", 0.2

    def _ensure_relevant_mexc_tab(self, driver: WebDriver) -> dict[str, Any]:
        current_handle = ""
        try:
            current_handle = driver.current_window_handle
            current_url = driver.current_url or ""
            current_title = driver.title or ""
        except Exception as exc:
            message = str(exc).lower()
            if "no such window" in message or "invalid session" in message or "web view not found" in message:
                raise
            current_url = ""
            current_title = ""

        current_lower = current_url.lower()
        if any(marker in current_lower for marker in MEXC_HOST_MARKERS):
            return {
                "state": "current_mexc_tab",
                "url": current_url,
                "title": current_title,
                "handle": current_handle,
                "switched": False,
            }

        try:
            handles = list(driver.window_handles)
        except Exception:
            handles = []

        best_mexc = None
        best_security = None
        best_openapi = None
        best_register = None
        for handle in handles:
            try:
                driver.switch_to.window(handle)
                url = driver.current_url or ""
                title = driver.title or ""
            except Exception:
                continue
            lowered = url.lower()
            if not any(marker in lowered for marker in MEXC_HOST_MARKERS):
                continue
            candidate = {"handle": handle, "url": url, "title": title}
            if any(marker in lowered for marker in SECURITY_PATH_MARKERS):
                best_security = candidate
                break
            if any(marker in lowered for marker in OPENAPI_PATH_MARKERS):
                best_openapi = candidate
                continue
            if any(marker in lowered for marker in REGISTER_PATH_MARKERS):
                best_register = candidate
                continue
            if best_mexc is None:
                best_mexc = candidate

        selected = best_security or best_openapi or best_register or best_mexc
        if selected:
            if selected["handle"] != current_handle:
                driver.switch_to.window(selected["handle"])
            return {
                "state": "switched_mexc_tab",
                "url": selected["url"],
                "title": selected["title"],
                "handle": selected["handle"],
                "switched": selected["handle"] != current_handle,
            }

        if current_handle:
            try:
                driver.switch_to.window(current_handle)
            except Exception:
                pass
        return {
            "state": "wrong_browser_tab",
            "url": current_url,
            "title": current_title,
            "handle": current_handle,
            "switched": False,
        }


def _camel_key(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])
