from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from automation.recovery import (
    ManualAssistAction,
    ManualAssistController,
    ManualAssistResult,
    PageState,
    PageStateAnalyzer,
)

logger = logging.getLogger(__name__)


class CheckpointAlreadyComplete(Exception):
    """Raised when analyzer confirms the scenario already reached its terminal state."""


@dataclass(frozen=True)
class ScenarioCheckpoint:
    name: str
    action: Callable[[], None]
    allowed_states: set[str] = field(default_factory=set)
    done_states: set[str] = field(default_factory=set)
    terminal_states: set[str] = field(default_factory=set)
    recover_wrong_tab: Callable[[], None] | None = None
    wait_timeout: int = 18
    min_confidence: float = 0.72
    action_already_handles_captcha: bool = False


@dataclass
class CheckpointRuntimeState:
    current: str = ""
    last_completed: str = ""
    last_page_state: PageState = field(default_factory=lambda: PageState("unknown", 0.0))
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CheckpointRunResult:
    completed: bool
    terminal_state: PageState | None = None


class CheckpointRunner:
    """In-memory scenario checkpoint executor.

    The runner keeps only runtime state while the app is open. A scenario may still
    mirror the short current checkpoint to TaskService through its progress reporter.
    """

    def __init__(
        self,
        *,
        driver_getter: Callable[[], Any],
        analyzer: PageStateAnalyzer,
        debug: Any,
        manual_assist_handler: Callable[[str, set[str], PageState], ManualAssistResult] | None = None,
        network_recovery_handler: Callable[[str, PageState], str] | None = None,
        captcha_handler: Callable[[str], None] | None = None,
        default_terminal_states: Iterable[str] = (),
        manual_timeout_seconds: int = 600,
    ):
        self.driver_getter = driver_getter
        self.analyzer = analyzer
        self.debug = debug
        self.manual_assist_handler = manual_assist_handler
        self.network_recovery_handler = network_recovery_handler
        self.captcha_handler = captcha_handler
        self.default_terminal_states = set(default_terminal_states)
        self.manual_assist = ManualAssistController(
            self.analyzer,
            timeout_seconds=manual_timeout_seconds,
        )
        self.state = CheckpointRuntimeState()

    def run(self, checkpoints: Iterable[ScenarioCheckpoint]) -> CheckpointRunResult:
        for checkpoint in checkpoints:
            self._run_checkpoint(checkpoint)
        return CheckpointRunResult(completed=True)

    def _run_checkpoint(self, checkpoint: ScenarioCheckpoint) -> None:
        self.state.current = checkpoint.name
        self._emit("checkpoint_start", checkpoint=checkpoint.name)

        while True:
            state = self._analyze()
            terminal_states = checkpoint.terminal_states or self.default_terminal_states
            if self._is_confident(state, terminal_states, checkpoint):
                self._emit("checkpoint_terminal", checkpoint=checkpoint.name, state=state.name)
                raise CheckpointAlreadyComplete()

            if self._is_confident(state, checkpoint.done_states, checkpoint):
                self._mark_done(checkpoint, state, already_done=True)
                return

            if state.name == "captcha" and self._is_confident(state, {"captcha"}, checkpoint):
                if checkpoint.action_already_handles_captcha:
                    self._mark_allowed(checkpoint, state)
                    break
                self._handle_captcha(checkpoint)
                continue

            if state.name in ("network_loading", "unknown"):
                state = self._wait_for_known_state(checkpoint, state)
                if self._is_confident(state, terminal_states, checkpoint):
                    self._emit("checkpoint_terminal", checkpoint=checkpoint.name, state=state.name)
                    raise CheckpointAlreadyComplete()
                if self._is_confident(state, checkpoint.done_states, checkpoint):
                    self._mark_done(checkpoint, state, already_done=True)
                    return
                if state.name == "captcha" and self._is_confident(state, {"captcha"}, checkpoint):
                    if checkpoint.action_already_handles_captcha:
                        self._mark_allowed(checkpoint, state)
                        break
                    self._handle_captcha(checkpoint)
                    continue
                if self._is_confident(state, checkpoint.allowed_states, checkpoint):
                    self._mark_allowed(checkpoint, state)
                    break

            if state.name in ("network_loading", "network_error"):
                self._recover_network(checkpoint, state)
                continue

            if state.name == "browser_closed":
                raise RuntimeError("Browser tab was closed by user")

            if state.name == "wrong_browser_tab" and checkpoint.recover_wrong_tab:
                self._emit("checkpoint_wrong_tab_recover", checkpoint=checkpoint.name, state=state.name)
                checkpoint.recover_wrong_tab()
                continue

            if self._is_confident(state, checkpoint.allowed_states, checkpoint):
                self._mark_allowed(checkpoint, state)
                break

            recovered = self._manual_assist(checkpoint, state)
            if self._is_confident(recovered, terminal_states, checkpoint):
                self._emit("checkpoint_terminal", checkpoint=checkpoint.name, state=recovered.name)
                raise CheckpointAlreadyComplete()
            if self._is_confident(recovered, checkpoint.done_states, checkpoint):
                self._mark_done(checkpoint, recovered, already_done=True)
                return
            if recovered.name == "captcha" and self._is_confident(recovered, {"captcha"}, checkpoint):
                if checkpoint.action_already_handles_captcha:
                    self._mark_allowed(checkpoint, recovered)
                    break
                self._handle_captcha(checkpoint)
                continue
            if self._is_confident(recovered, checkpoint.allowed_states, checkpoint):
                self._mark_allowed(checkpoint, recovered)
                break
            raise RuntimeError(
                f"Unable to continue from screen state {recovered.name} "
                f"while preparing checkpoint {checkpoint.name}"
            )

        checkpoint.action()
        self._mark_done(checkpoint, self._analyze(), already_done=False)

    def _analyze(self) -> PageState:
        state = self.analyzer.analyze(self.driver_getter())
        self.state.last_page_state = state
        self._emit(
            "checkpoint_state_check",
            checkpoint=self.state.current,
            state=state.name,
            confidence=state.confidence,
            url=state.url,
        )
        return state

    def _wait_for_known_state(
        self,
        checkpoint: ScenarioCheckpoint,
        initial_state: PageState,
    ) -> PageState:
        self._emit(
            "checkpoint_wait_for_page",
            checkpoint=checkpoint.name,
            state=initial_state.name,
            confidence=initial_state.confidence,
        )
        deadline = time.time() + checkpoint.wait_timeout
        last_state = initial_state
        target_states = (
            checkpoint.allowed_states
            | checkpoint.done_states
            | checkpoint.terminal_states
            | self.default_terminal_states
            | {"captcha", "network_error", "wrong_browser_tab"}
        )
        while time.time() < deadline:
            time.sleep(1.5)
            state = self.analyzer.analyze(self.driver_getter())
            self.state.last_page_state = state
            last_state = state
            if self._is_confident(state, target_states, checkpoint):
                self._emit(
                    "checkpoint_wait_resolved",
                    checkpoint=checkpoint.name,
                    state=state.name,
                    confidence=state.confidence,
                )
                return state
        return last_state

    def _recover_network(self, checkpoint: ScenarioCheckpoint, state: PageState) -> None:
        self._emit("checkpoint_network_state_detected", checkpoint=checkpoint.name, state=state.name)
        action = "wait"
        if self.network_recovery_handler:
            action = self.network_recovery_handler(checkpoint.name, state)
        if action == "cancel":
            raise RuntimeError("Scenario stopped by user during network recovery")
        if action == "refresh":
            driver = self.driver_getter()
            if driver is not None:
                driver.refresh()
            time.sleep(5)
            return
        time.sleep(10)

    def _manual_assist(self, checkpoint: ScenarioCheckpoint, state: PageState) -> PageState:
        allowed_states = (
            checkpoint.allowed_states
            | checkpoint.done_states
            | checkpoint.terminal_states
            | self.default_terminal_states
            | {"captcha"}
        )
        self._emit(
            "checkpoint_manual_assist_required",
            checkpoint=checkpoint.name,
            state=state.name,
            confidence=state.confidence,
        )
        if self.manual_assist_handler:
            result = self.manual_assist_handler(checkpoint.name, allowed_states, state)
        else:
            result = self.manual_assist.wait_for_known_state(self.driver_getter(), allowed_states)
        if result.action == ManualAssistAction.RESTART:
            raise RuntimeError("Scenario restart requested by user")
        if result.action == ManualAssistAction.CANCEL:
            raise RuntimeError("Scenario cancelled by user")
        if result.action == ManualAssistAction.TIMEOUT:
            raise RuntimeError("Manual assist timed out after 10 minutes")
        self._emit(
            "checkpoint_manual_assist_resume",
            checkpoint=checkpoint.name,
            state=result.state.name,
            confidence=result.state.confidence,
        )
        return result.state

    def _handle_captcha(self, checkpoint: ScenarioCheckpoint) -> None:
        self._emit("checkpoint_captcha_detected", checkpoint=checkpoint.name)
        if not self.captcha_handler:
            raise RuntimeError("CAPTCHA detected, but no CAPTCHA handler is configured")
        self.captcha_handler(checkpoint.name)
        self._emit("checkpoint_captcha_resolved", checkpoint=checkpoint.name)

    def _mark_allowed(self, checkpoint: ScenarioCheckpoint, state: PageState) -> None:
        self._emit("checkpoint_ready", checkpoint=checkpoint.name, state=state.name)

    def _mark_done(
        self,
        checkpoint: ScenarioCheckpoint,
        state: PageState,
        *,
        already_done: bool,
    ) -> None:
        self.state.last_completed = checkpoint.name
        self.state.history.append({
            "checkpoint": checkpoint.name,
            "state": state.name,
            "already_done": already_done,
            "time": time.time(),
        })
        self._emit(
            "checkpoint_already_done" if already_done else "checkpoint_done",
            checkpoint=checkpoint.name,
            state=state.name,
        )

    @staticmethod
    def _is_confident(
        state: PageState,
        states: set[str],
        checkpoint: ScenarioCheckpoint,
    ) -> bool:
        return state.name in states and state.confidence >= checkpoint.min_confidence

    def _emit(self, step: str, **fields: Any) -> None:
        if hasattr(self.debug, "step"):
            try:
                self.debug.step(step, **fields)
            except Exception:
                logger.debug("Checkpoint debug emit failed", exc_info=True)
