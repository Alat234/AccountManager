from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class CaptchaNotification:
    task_id: str
    account_email: str
    message: str
    timestamp: datetime = field(default_factory=datetime.now)


class CaptchaService:
    """Notification-based captcha service.

    Scenarios detect captcha in the browser and call notify().
    Listeners (UI, TG bot) receive notification and alert the user.
    User solves captcha manually in the browser window.
    Scenario polls the browser until captcha disappears.
    """

    def __init__(self):
        self._listeners: list[Callable[[CaptchaNotification], None]] = []

    def register_listener(
        self, callback: Callable[[CaptchaNotification], None]
    ) -> None:
        self._listeners.append(callback)

    def notify(
        self,
        account_email: str,
        task_id: str,
        message: str = "CAPTCHA! Перейдіть в браузер для вирішення",
    ) -> None:
        notification = CaptchaNotification(
            task_id=task_id,
            account_email=account_email,
            message=message,
        )
        logger.info("CAPTCHA notification: %s (%s)", account_email, task_id)
        for listener in self._listeners:
            try:
                listener(notification)
            except Exception:
                logger.exception("Captcha listener failed")
