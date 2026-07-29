from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from selenium.webdriver.remote.webdriver import WebDriver

logger = logging.getLogger(__name__)


class MexcRegistrationDebug:
    """Small helper for registration logs and failure artifacts."""

    def __init__(
        self,
        account_email: str,
        task_id: str = "",
        secrets: tuple[str, ...] = (),
        root_dir: Path | str = Path("logs") / "mexc_registration",
    ):
        self.account_email = account_email
        self.masked_email = self.mask_email(account_email)
        self.task_id = task_id
        self.secrets = tuple(secret for secret in secrets if secret)
        self.root_dir = Path(root_dir)
        self._artifact_dir: Path | None = None

    @staticmethod
    def mask_email(email: str) -> str:
        if "@" not in email:
            return "***"
        name, domain = email.split("@", 1)
        if not name:
            masked_name = "***"
        elif len(name) == 1:
            masked_name = f"{name}***"
        else:
            masked_name = f"{name[0]}***{name[-1]}"
        return f"{masked_name}@{domain}"

    def bind_task(self, task_id: str) -> None:
        self.task_id = task_id

    def with_secrets(self, *secrets: str) -> None:
        self.secrets = tuple(secret for secret in (*self.secrets, *secrets) if secret)

    def step(self, name: str, **fields: Any) -> None:
        safe_fields = {key: self._redact(value) for key, value in fields.items()}
        logger.info(
            "MEXC registration step=%s account=%s task=%s fields=%s",
            name,
            self.masked_email,
            self.task_id or "-",
            safe_fields,
        )

    def warning(self, name: str, **fields: Any) -> None:
        safe_fields = {key: self._redact(value) for key, value in fields.items()}
        logger.warning(
            "MEXC registration warning=%s account=%s task=%s fields=%s",
            name,
            self.masked_email,
            self.task_id or "-",
            safe_fields,
        )

    def save_failure_artifacts(self, driver: WebDriver, reason: str) -> Path:
        artifact_dir = self.artifact_dir
        self._write_json(
            artifact_dir / "metadata.json",
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "task_id": self.task_id,
                "account": self.masked_email,
                "reason": self._redact(reason),
                "url": self._safe_current_url(driver),
                "title": self._safe_title(driver),
            },
        )
        self.save_page_probe(driver, "page_probe_failure.json")
        self.save_html(driver, "page_failure.html")
        self.save_screenshot(driver, "screenshot_failure.png")
        logger.info("MEXC registration failure artifacts saved: %s", artifact_dir)
        return artifact_dir

    def save_page_probe(self, driver: WebDriver, filename: str) -> None:
        probe = self._collect_page_probe(driver)
        self._write_json(self.artifact_dir / filename, probe)

    def save_html(self, driver: WebDriver, filename: str) -> None:
        try:
            html = driver.page_source or ""
        except Exception as exc:
            html = f"Failed to read page_source: {type(exc).__name__}: {exc}"
        (self.artifact_dir / filename).write_text(self._redact(html), encoding="utf-8")

    def save_screenshot(self, driver: WebDriver, filename: str) -> None:
        try:
            driver.save_screenshot(str(self.artifact_dir / filename))
        except Exception:
            logger.exception("Failed to save MEXC registration screenshot")

    @property
    def artifact_dir(self) -> Path:
        if self._artifact_dir is None:
            digest = hashlib.sha1(self.account_email.lower().encode("utf-8")).hexdigest()[:10]
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._artifact_dir = self.root_dir / f"{stamp}_{digest}"
            self._artifact_dir.mkdir(parents=True, exist_ok=True)
        return self._artifact_dir

    def _collect_page_probe(self, driver: WebDriver) -> dict[str, Any]:
        try:
            data = driver.execute_script(
                """
                const visible = (element) => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const compact = (element) => ({
                    tag: element.tagName,
                    id: element.id || '',
                    name: element.getAttribute('name') || '',
                    type: element.getAttribute('type') || '',
                    role: element.getAttribute('role') || '',
                    ariaExpanded: element.getAttribute('aria-expanded') || '',
                    forAttr: element.getAttribute('for') || '',
                    placeholder: element.getAttribute('placeholder') || '',
                    className: String(element.className || '').slice(0, 180),
                    text: (element.innerText || element.textContent || '').trim().slice(0, 180),
                    valueLength: element.value ? String(element.value).length : 0,
                    rect: (() => {
                        const rect = element.getBoundingClientRect();
                        return {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height)
                        };
                    })()
                });
                const referral = [...document.querySelectorAll('label,span,svg,input,button,div')]
                    .filter((element) => {
                        const haystack = [
                            element.id || '',
                            element.getAttribute('name') || '',
                            element.getAttribute('for') || '',
                            element.getAttribute('placeholder') || '',
                            element.getAttribute('aria-label') || '',
                            String(element.className || ''),
                            element.innerText || element.textContent || ''
                        ].join(' ');
                        return visible(element) && /referral|invite|invitation/i.test(haystack);
                    })
                    .slice(0, 30)
                    .map(compact);
                const inputs = [...document.querySelectorAll('input')]
                    .filter(visible)
                    .slice(0, 30)
                    .map(compact);
                const buttons = [...document.querySelectorAll('button,[role="button"]')]
                    .filter(visible)
                    .slice(0, 30)
                    .map(compact);
                const iframes = [...document.querySelectorAll('iframe')]
                    .filter(visible)
                    .slice(0, 20)
                    .map((iframe) => ({
                        id: iframe.id || '',
                        name: iframe.name || '',
                        title: iframe.title || '',
                        src: iframe.src || '',
                        className: String(iframe.className || '').slice(0, 180)
                    }));
                return {
                    url: window.location.href,
                    title: document.title,
                    referral,
                    inputs,
                    buttons,
                    iframes
                };
                """
            )
            return self._redact(data)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    def _safe_current_url(self, driver: WebDriver) -> str:
        try:
            return self._redact(driver.current_url)
        except Exception:
            return ""

    def _safe_title(self, driver: WebDriver) -> str:
        try:
            return self._redact(driver.title)
        except Exception:
            return ""

    def _write_json(self, path: Path, data: Any) -> None:
        path.write_text(
            json.dumps(self._redact(data), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact(item) for item in value)
        if not isinstance(value, str):
            return value

        redacted = value.replace(self.account_email, self.masked_email)
        for secret in self.secrets:
            redacted = redacted.replace(secret, "***REDACTED***")
        redacted = re.sub(
            r"((?:Access|API)\s*Key(?:.|\n){0,500}?<p[^>]*>)([^<]{16,160})(</p>)",
            r"\1***REDACTED***\3",
            redacted,
            flags=re.IGNORECASE,
        )
        redacted = re.sub(
            r"(Secret\s*Key(?:.|\n){0,800}?<p[^>]*>)([^<]{16,200})(</p>)",
            r"\1***REDACTED***\3",
            redacted,
            flags=re.IGNORECASE,
        )
        redacted = re.sub(
            r"(?<![#a-zA-Z0-9])\d{6}(?![a-zA-Z0-9])",
            "***CODE***",
            redacted,
        )
        return redacted
