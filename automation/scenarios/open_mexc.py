from __future__ import annotations

import logging
import time

from automation.base import BaseScenario, ScenarioResult

logger = logging.getLogger(__name__)


class OpenMexcScenario(BaseScenario):
    """Open AdsPower browser, navigate to MEXC, take screenshot. Keeps browser open."""

    MEXC_URL = "https://www.mexc.com"

    def __init__(self, adspower, account, captcha_service=None):
        super().__init__(adspower, account, captcha_service)
        self.auto_close = False

    def run(self) -> ScenarioResult:
        self._log_step("open_mexc_navigate_start", url=self.MEXC_URL)
        self.driver.get(self.MEXC_URL)
        self._log_step(
            "open_mexc_navigate_done",
            current_url=self.driver.current_url,
            title=self.driver.title,
        )
        time.sleep(3)
        self._log_step(
            "open_mexc_page_probe",
            current_url=self.driver.current_url,
            title=self.driver.title,
        )
        screenshot = self._take_screenshot()
        logger.info(
            "Open MEXC screenshot captured account=%s bytes=%s",
            self.account.email,
            len(screenshot),
        )
        title = self.driver.title
        return ScenarioResult(
            success=True,
            message=f"MEXC opened: {title}",
            screenshot=screenshot,
        )
