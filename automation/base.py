from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from clients.adspower_selenium import open_adspower_selenium_driver
from automation.recovery import ManualAssistResult, PageState

if TYPE_CHECKING:
    from clients.adspower import AdsPowerClient
    from models.account import Account
    from services.captcha_service import CaptchaService

logger = logging.getLogger(__name__)


@dataclass
class ScenarioResult:
    success: bool
    message: str
    data: dict = field(default_factory=dict)
    screenshot: bytes | None = None


class BaseScenario(ABC):
    def __init__(
        self,
        adspower: AdsPowerClient,
        account: Account,
        captcha_service: CaptchaService | None = None,
    ):
        self.adspower = adspower
        self.account = account
        self.captcha_service = captcha_service
        self.driver: webdriver.Chrome | None = None
        self.auto_close: bool = True
        self.progress_reporter: Callable[[str, dict], None] | None = None
        self.manual_assist_handler: Callable[[str, set[str], PageState], ManualAssistResult] | None = None
        self.network_recovery_handler: Callable[[str, PageState], str] | None = None
        self._cancel_requested = threading.Event()

    @abstractmethod
    def run(self) -> ScenarioResult:
        ...

    def execute(self) -> ScenarioResult:
        try:
            self._log_step("execute_start")
            self._raise_if_cancelled()
            self._start_browser()
            self._raise_if_cancelled()
            result = self.run()
            self._raise_if_cancelled()
            self._log_step(
                "execute_done",
                success=result.success,
                message=result.message,
            )
            return result
        except Exception as e:
            logger.exception("Scenario failed for %s", self.account.email)
            self._log_step("execute_failed", error=str(e))
            return ScenarioResult(success=False, message=str(e))
        finally:
            if self.auto_close:
                self._stop_browser()

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel_requested

    def cancel(self) -> None:
        self._cancel_requested.set()
        self._log_step("cancel_requested")
        profile_id = self.account.ads_profile_id
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                logger.debug("Selenium driver quit during cancel failed", exc_info=True)
            self.driver = None
        if profile_id:
            try:
                self.adspower.stop_browser(profile_id)
            except Exception:
                logger.debug("AdsPower browser stop during cancel failed", exc_info=True)

    def _raise_if_cancelled(self) -> None:
        if self._cancel_requested.is_set():
            raise RuntimeError("Scenario cancelled by user")

    def browser_is_closed(self) -> bool:
        if self._cancel_requested.is_set():
            return True
        driver = self.driver
        if driver is None:
            return True
        try:
            handles = list(driver.window_handles)
            if not handles:
                return True
            current_handle = driver.current_window_handle
            return current_handle not in handles
        except Exception as exc:
            message = str(exc).lower()
            if any(fragment in message for fragment in (
                "no such window",
                "target window already closed",
                "web view not found",
                "invalid session",
                "disconnected",
                "connection refused",
            )):
                return True
            logger.debug("Browser liveness check failed", exc_info=True)
            return False

    def _raise_if_browser_closed(self) -> None:
        if self.browser_is_closed():
            self._cancel_requested.set()
            raise RuntimeError("Browser tab was closed by user")

    def _start_browser(self) -> None:
        profile_id = self.account.ads_profile_id
        if not profile_id:
            raise RuntimeError("Account has no ads_profile_id")

        self._log_step("browser_start_requested", profile_id=profile_id)
        self.driver = open_adspower_selenium_driver(
            self.adspower,
            profile_id,
            context=type(self).__name__,
        )
        logger.info("Browser started for %s (profile %s)", self.account.email, profile_id)
        self._log_step(
            "browser_started",
            profile_id=profile_id,
            session_id=getattr(self.driver, "session_id", ""),
        )

    def _stop_browser(self) -> None:
        profile_id = self.account.ads_profile_id
        self._log_step("browser_stop_requested", profile_id=profile_id)
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                logger.debug("Selenium driver quit failed", exc_info=True)
                pass
            self.driver = None
        if profile_id:
            self.adspower.stop_browser(profile_id)
        logger.info("Browser stopped for %s", self.account.email)
        self._log_step("browser_stopped", profile_id=profile_id)

    def _take_screenshot(self) -> bytes:
        return self.driver.get_screenshot_as_png()

    def _wait_for_element(self, by: str, value: str, timeout: int = 10):
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def _notify_captcha(self, task_id: str = "") -> None:
        if self.captcha_service:
            self.captcha_service.notify(
                account_email=self.account.email,
                task_id=task_id,
            )

    def _log_step(self, step: str, **fields) -> None:
        logger.info(
            "Scenario step=%s scenario=%s account=%s fields=%s",
            step,
            type(self).__name__,
            self.account.email,
            fields,
        )
        if self.progress_reporter:
            try:
                self.progress_reporter(step, fields)
            except Exception:
                logger.debug("Scenario progress reporter failed", exc_info=True)
