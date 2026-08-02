from __future__ import annotations

import logging
import time
from collections.abc import Callable
from threading import Event

from email_parser import fetch_mexc_codes_all_folders

logger = logging.getLogger(__name__)


class MexcEmailCodeFetcher:
    def __init__(self, mailboxes: list[tuple[str, str, str]], scan_limit: int = 25):
        self.mailboxes = mailboxes
        self.scan_limit = scan_limit

    def fetch_code(
        self,
        target_email: str,
        not_before_ts: float | None = None,
        ignored_codes: set[str] | None = None,
    ) -> str | None:
        for index, (user, password, server) in enumerate(self.mailboxes, start=1):
            logger.info(
                "MEXC email code fetch mailbox=%s/%s server=%s target=%s not_before=%s ignored_count=%s",
                index,
                len(self.mailboxes),
                server,
                self._mask_email(target_email),
                int(not_before_ts) if not_before_ts else None,
                len(ignored_codes or []),
            )
            result = fetch_mexc_codes_all_folders(
                server,
                user,
                password,
                target_email,
                scan_limit=self.scan_limit,
                not_before_ts=not_before_ts,
                ignored_codes=ignored_codes,
            )
            data = result.get("data") if isinstance(result, dict) else None
            if data:
                logger.info(
                    "MEXC email code found target=%s mailbox=%s folders=%s",
                    self._mask_email(target_email),
                    index,
                    result.get("folders_checked", []),
                )
                return data[0].get("code")
            if isinstance(result, dict) and result.get("error"):
                logger.warning(
                    "MEXC email code fetch error target=%s mailbox=%s error=%s folders=%s",
                    self._mask_email(target_email),
                    index,
                    result.get("error"),
                    result.get("folders_checked", []),
                )
            elif isinstance(result, dict):
                logger.info(
                    "MEXC email code not found target=%s mailbox=%s folders=%s",
                    self._mask_email(target_email),
                    index,
                    result.get("folders_checked", []),
                )
        return None

    def wait_for_code(
        self,
        target_email: str,
        timeout: int = 180,
        poll_interval: float = 5.0,
        not_before_ts: float | None = None,
        ignored_codes: set[str] | None = None,
        cancel_event: Event | None = None,
        cancel_checker: Callable[[], bool] | None = None,
    ) -> str:
        logger.info(
            "MEXC email code polling started target=%s timeout=%s poll_interval=%s scan_limit=%s not_before=%s ignored_count=%s",
            self._mask_email(target_email),
            timeout,
            poll_interval,
            self.scan_limit,
            int(not_before_ts) if not_before_ts else None,
            len(ignored_codes or []),
        )
        deadline = time.time() + timeout

        def stop_if_cancelled() -> None:
            if cancel_event and cancel_event.is_set():
                raise RuntimeError("Scenario cancelled by user")
            if cancel_checker and cancel_checker():
                if cancel_event:
                    cancel_event.set()
                raise RuntimeError("Browser tab was closed by user")

        while time.time() < deadline:
            stop_if_cancelled()
            code = self.fetch_code(
                target_email,
                not_before_ts=not_before_ts,
                ignored_codes=ignored_codes,
            )
            stop_if_cancelled()
            if code:
                return code
            logger.info("MEXC email code polling continues target=%s", self._mask_email(target_email))
            sleep_until = time.time() + poll_interval
            while time.time() < sleep_until:
                stop_if_cancelled()
                time.sleep(max(0.01, min(0.25, sleep_until - time.time())))
        raise RuntimeError(f"No MEXC verification code received within {timeout}s")

    @staticmethod
    def _mask_email(email: str) -> str:
        if "@" not in email:
            return "***"
        name, domain = email.split("@", 1)
        if len(name) <= 1:
            return f"{name}***@{domain}"
        return f"{name[0]}***{name[-1]}@{domain}"
