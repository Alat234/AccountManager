from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, CancelledError
from automation.base import ScenarioResult

logger = logging.getLogger(__name__)


class ScenarioRunner:
    def __init__(self, max_workers=2):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._futures = {}
        self._scenarios = {}
        self._results = {}
        self._lock = threading.Lock()
        self._closed = False

    def submit(self, task_id, scenario, on_complete=None, on_start=None):
        prepare = getattr(scenario, 'prepare', None)
        if prepare:
            prepare()
        with self._lock:
            if self._closed:
                raise RuntimeError('Scenario runner is shutting down')
            if task_id in self._futures or task_id in self._results:
                raise ValueError('Task already submitted')
            future = self.executor.submit(self._run, task_id, scenario, on_start)
            self._futures[task_id] = future
            self._scenarios[task_id] = scenario
        future.add_done_callback(lambda done: self._finish(task_id, scenario, done, on_complete))

    @staticmethod
    def _run(task_id, scenario, on_start):
        if on_start:
            on_start(task_id)
        return scenario.execute()

    def _finish(self, task_id, scenario, future, callback):
        try:
            result = future.result()
            if not isinstance(result, ScenarioResult):
                raise TypeError('Scenario did not return ScenarioResult')
        except BaseException as exc:
            pending = bool(getattr(scenario, '_external_action_pending', False))
            status = 'outcome_unknown' if pending else 'cancelled' if isinstance(exc, CancelledError) else 'failed'
            result = ScenarioResult(False, str(exc) or 'Operation cancelled before start',
                                    {'operation_status': status})
        with self._lock:
            self._results[task_id] = result
        try:
            if callback:
                callback(task_id, result)
        except Exception:
            logger.exception('Task completion callback failed: %s', task_id)
        finally:
            with self._lock:
                self._futures.pop(task_id, None)
                self._scenarios.pop(task_id, None)

    def get_result(self, task_id):
        with self._lock:
            return self._results.get(task_id)

    def is_running(self, task_id):
        with self._lock:
            return task_id in self._futures

    def active_count(self):
        with self._lock:
            return len(self._futures)

    def shutdown(self):
        with self._lock:
            self._closed = True
            scenarios = list(self._scenarios.values())
        for scenario in scenarios:
            try:
                scenario.cancel()
            except Exception:
                logger.exception('Could not signal scenario cancellation')
        self.executor.shutdown(wait=False, cancel_futures=True)
