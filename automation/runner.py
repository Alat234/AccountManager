from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from automation.base import BaseScenario, ScenarioResult

logger = logging.getLogger(__name__)


class ScenarioRunner:
    def __init__(self, max_workers: int = 2):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._futures: dict[str, Future] = {}
        self._results: dict[str, ScenarioResult] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        task_id: str,
        scenario: BaseScenario,
        on_complete: Callable[[str, ScenarioResult], None] | None = None,
    ) -> None:
        future = self.executor.submit(self._run, task_id, scenario, on_complete)
        with self._lock:
            self._futures[task_id] = future

    def _run(
        self,
        task_id: str,
        scenario: BaseScenario,
        on_complete: Callable[[str, ScenarioResult], None] | None,
    ) -> ScenarioResult:
        logger.info("Running scenario %s (task %s)", type(scenario).__name__, task_id)
        result = scenario.execute()
        with self._lock:
            self._results[task_id] = result
            self._futures.pop(task_id, None)
        logger.info("Scenario %s finished: %s", task_id, result.success)
        if on_complete:
            try:
                on_complete(task_id, result)
            except Exception:
                logger.exception("on_complete callback failed for task %s", task_id)
        return result

    def get_result(self, task_id: str) -> ScenarioResult | None:
        with self._lock:
            return self._results.get(task_id)

    def is_running(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._futures

    def active_count(self) -> int:
        with self._lock:
            return len(self._futures)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
