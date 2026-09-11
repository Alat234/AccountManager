"""One owned RK tab per run; no foreground-window activation."""
import time
from urllib.parse import urlparse

from automation.scenarios.mexc_state import MexcPageStateAnalyzer
from automation.scenarios.rk_captcha import captcha_visible

FORM_URL = "https://www.mexc.com/support/apply-risk-account-protection/form"


def is_rk_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname in {"www.mexc.com", "mexc.com", "www.mexc.co", "mexc.co"} and \
        "/support/apply-risk-account-protection" in parsed.path


class RKPageStateAnalyzer(MexcPageStateAnalyzer):
    def _detect_captcha(self, driver):
        return captcha_visible(driver)

    def __init__(self):
        self.owned_handle = None

    def bind(self, driver, debug) -> None:
        started = time.monotonic()
        self.owned_handle = None
        initial_handle = driver.current_window_handle
        handles = driver.window_handles
        if is_rk_url(driver.current_url):
            self.owned_handle = driver.current_window_handle
        else:
            try:
                targets = driver.execute_cdp_cmd("Target.getTargets", {}).get("targetInfos", [])
                for target in targets:
                    if target.get("type") == "page" and is_rk_url(target.get("url", "")):
                        target_id = target["targetId"]
                        self.owned_handle = next((h for h in handles if h in {target_id, "CDwindow-" + target_id}), None)
                        if self.owned_handle:
                            break
            except Exception as exc:
                debug.warning("rk_tab_discovery_failed", error=type(exc).__name__)
            if self.owned_handle is None:
                driver.switch_to.new_window("tab")
                self.owned_handle = driver.current_window_handle
        self.ensure_owned(driver)
        debug.step("rk_tab_ready", elapsed_ms=round((time.monotonic() - started) * 1000),
                   initial_handle=initial_handle, owned_handle=self.owned_handle,
                   switched=initial_handle != self.owned_handle,
                   visibility=driver.execute_script('return document.visibilityState'))

    def ensure_owned(self, driver):
        if not self.owned_handle:
            return
        if self.owned_handle not in driver.window_handles:
            raise RuntimeError("RK browser tab was closed by user")
        if driver.current_window_handle != self.owned_handle:
            driver.switch_to.window(self.owned_handle)

    def _ensure_relevant_mexc_tab(self, driver):
        self.ensure_owned(driver)
        url = driver.current_url
        parsed = urlparse(url)
        login = parsed.hostname in {"www.mexc.com", "mexc.com", "www.mexc.co", "mexc.co"} and \
            any(part in parsed.path.lower() for part in ("login", "sign-in", "signin"))
        loading = url in {"about:blank", ""} or url.startswith("chrome-error:")
        return {"state": "current_mexc_tab" if is_rk_url(url) or login or loading else "wrong_browser_tab",
                "url": url, "handle": self.owned_handle, "switched": False}

    def open_form(self, driver, debug):
        self.ensure_owned(driver)
        started = time.monotonic()
        debug.step("rk_open_page", url=FORM_URL)
        # Page.navigate returns without waiting for unrelated videos/analytics.
        result = driver.execute_cdp_cmd("Page.navigate", {"url": FORM_URL})
        debug.step("rk_navigation_started", elapsed_ms=round((time.monotonic() - started) * 1000),
                   navigation_error=result.get("errorText", ""))
