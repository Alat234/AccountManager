from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class IssueType:
    BROWSER_CLOSED = "browser_closed"
    NETWORK_BAD = "network_bad"
    SITE_CHANGED = "site_changed"
    MISSING_ELEMENT = "missing_element"
    CAPTCHA_TIMEOUT = "captcha_timeout"
    EMAIL_TIMEOUT = "email_timeout"
    AUTH_REQUIRED = "auth_required"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ScenarioIssue:
    issue_type: str
    user_message: str
    technical_message: str = ""
    suggested_action: str = "continue"


@dataclass(frozen=True)
class PageState:
    name: str
    confidence: float = 0.0
    url: str = ""
    title: str = ""
    hints: dict[str, Any] = field(default_factory=dict)


class PageStateAnalyzer(Protocol):
    def analyze(self, driver: Any) -> PageState:
        ...


@dataclass(frozen=True)
class ManualAssistResult:
    action: str
    state: PageState


class ManualAssistAction:
    CONTINUE = "continue"
    RESTART = "restart"
    CANCEL = "cancel"
    TIMEOUT = "timeout"


class ManualAssistController:
    def __init__(
        self,
        analyzer: PageStateAnalyzer,
        *,
        timeout_seconds: int = 600,
        poll_interval: float = 3.0,
        min_confidence: float = 0.72,
    ):
        self.analyzer = analyzer
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self.min_confidence = min_confidence

    def wait_for_known_state(
        self,
        driver: Any,
        allowed_states: set[str],
        *,
        on_state: Callable[[PageState], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> ManualAssistResult:
        deadline = time.time() + self.timeout_seconds
        last_state = PageState("unknown", confidence=0.0)
        while time.time() < deadline:
            if should_stop and should_stop():
                return ManualAssistResult(ManualAssistAction.CANCEL, last_state)
            last_state = self.analyzer.analyze(driver)
            if on_state:
                on_state(last_state)
            if (
                last_state.name in allowed_states
                and last_state.confidence >= self.min_confidence
            ):
                return ManualAssistResult(ManualAssistAction.CONTINUE, last_state)
            time.sleep(self.poll_interval)
        return ManualAssistResult(ManualAssistAction.TIMEOUT, last_state)


class ScenarioErrorClassifier:
    def classify(self, error: BaseException | str) -> ScenarioIssue:
        technical = str(error or "")
        clean = clean_error_message(technical)
        lowered = technical.lower()

        if any(fragment in lowered for fragment in (
            "no such window",
            "target window already closed",
            "browser tab was closed",
            "web view not found",
            "invalid session id",
            "disconnected: not connected",
        )):
            return ScenarioIssue(
                IssueType.BROWSER_CLOSED,
                "Browser tab was closed or the automation lost connection to it.",
                clean,
                suggested_action="reopen_profile",
            )

        if any(fragment in lowered for fragment in (
            "timed out receiving message from renderer",
            "timeout loading page",
            "net::err",
            "connection",
            "dns",
            "proxy",
            "internet",
        )):
            return ScenarioIssue(
                IssueType.NETWORK_BAD,
                "The page did not load reliably. The internet connection or proxy may be unstable.",
                clean,
                suggested_action="refresh_or_wait",
            )

        if "captcha" in lowered and "time" in lowered:
            return ScenarioIssue(
                IssueType.CAPTCHA_TIMEOUT,
                "CAPTCHA was not solved in time.",
                clean,
                suggested_action="continue",
            )

        if "verification code" in lowered and ("180s" in lowered or "timeout" in lowered):
            return ScenarioIssue(
                IssueType.EMAIL_TIMEOUT,
                "Email verification code did not arrive in time.",
                clean,
                suggested_action="wait_more",
            )

        if "login" in lowered and ("required" in lowered or "not complete" in lowered):
            return ScenarioIssue(
                IssueType.AUTH_REQUIRED,
                "MEXC login is required before continuing.",
                clean,
                suggested_action="continue",
            )

        if any(fragment in lowered for fragment in (
            "was not found",
            "not clickable",
            "did not appear",
            "did not load",
            "not accepted",
        )):
            return ScenarioIssue(
                IssueType.MISSING_ELEMENT,
                "The expected control was not found. The page may already be on another step.",
                clean,
                suggested_action="analyze_screen",
            )

        return ScenarioIssue(IssueType.UNKNOWN, clean or "Operation stopped.", clean)


def clean_error_message(message: str, *, max_length: int = 360) -> str:
    text = str(message or "").strip()
    if not text:
        return ""

    stack_markers = ("Stacktrace:", "Traceback (most recent call last):")
    for marker in stack_markers:
        if marker in text:
            text = text.split(marker, 1)[0].strip()

    text = re.sub(r"\s+", " ", text)
    if text.startswith("Message: "):
        text = text[len("Message: "):].strip()
    if len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "..."
    return text
