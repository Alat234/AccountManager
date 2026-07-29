from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from clients.adspower_selenium import open_adspower_selenium_driver

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

    @abstractmethod
    def run(self) -> ScenarioResult:
        ...

    def execute(self) -> ScenarioResult:
        try:
            self._log_step("execute_start")
            self._start_browser()
            result = self.run()
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
