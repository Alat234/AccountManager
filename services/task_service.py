from __future__ import annotations

import uuid
import json
from datetime import datetime
from typing import Any

from automation.base import ScenarioResult
from automation.recovery import clean_error_message
from models.task import AutomationTask
from storage.database import DatabaseManager
from services.operation_event_service import OperationEventService


class TaskService:
    def __init__(self, db: DatabaseManager, event_service: OperationEventService | None = None):
        self.db = db
        self.events = event_service

    def create_task(self, account_email: str, scenario_type: str) -> AutomationTask:
        task = AutomationTask(
            id=uuid.uuid4().hex[:12],
            account_email=account_email,
            scenario_type=scenario_type,
            status="pending",
            created_at=datetime.now(),
        )
        self.db.add_task(task)
        return task

    def start_task(self, task_id: str) -> None:
        def change(task):
            if task.status in ('completed', 'cancelled', 'outcome_unknown', 'failed'):
                return False
            task.status = "running"
            task.current_step = "started"
        task = self.db.mutate_task(task_id, change)
        if task is None:
            return

    def mark_external_action(self, task_id: str, pending: bool):
        def change(task):
            if task.status in ('completed', 'cancelled', 'outcome_unknown', 'failed'):
                return False
            task.external_action_pending = bool(pending)
            payload = json.loads(task.resume_data or '{}')
            payload['external_action_pending'] = bool(pending)
            task.resume_data = json.dumps(payload)
        task = self.db.mutate_task(task_id, change)
        if task is None:
            raise RuntimeError("Cannot record an external action for a finished task")

    def recover_interrupted_tasks(self):
        for existing in self.db.get_unfinished_tasks():
            def recover(task):
                if task.status not in ('pending', 'running', 'retrying', 'waiting_user', 'paused'):
                    return False
                task.status = 'cancelled' if task.status == 'pending' and not task.external_action_pending else 'outcome_unknown'
                task.completed_at = datetime.now()
                task.result_message = 'Програму закрито до завершення. Перевірте результат перед повторним запуском.'
            self.db.mutate_task(existing.id, recover)

    def complete_task(self, task_id: str, result: ScenarioResult) -> None:
        def change(task):
            if task.status in ('completed', 'cancelled', 'outcome_unknown', 'failed'):
                return False
            operation_status = result.data.get('operation_status', '') if result.data else ''
            if (result.data or {}).get('application_status') == 'unknown' or (task.external_action_pending and not result.success):
                operation_status = 'outcome_unknown'
            if result.success:
                task.external_action_pending = False
                payload = json.loads(task.resume_data or '{}')
                payload['external_action_pending'] = False
                task.resume_data = json.dumps(payload)
            task.status = 'completed' if result.success else operation_status if operation_status in ('cancelled', 'outcome_unknown') else 'failed'
            task.completed_at = datetime.now()
            clean_message = result.message if result.success else clean_error_message(result.message)
            task.result_message = clean_message
            task.result_data = json.dumps(result.data, ensure_ascii=False) if result.data else ""
            task.last_error = "" if result.success else clean_message
            task.recoverable = False
            task.requires_user_confirmation = False
            task.current_step = "completed" if result.success else task.current_step
        task = self.db.mutate_task(task_id, change)
        if task is None:
            return
        event_data = dict(result.data or {})
        event_data["scenario_type"] = task.scenario_type
        self._emit(
            task,
            task.result_message,
            event_type="task_completed" if result.success else 'task_' + task.status,
            level="success" if result.success else 'warning' if task.status in ('cancelled', 'outcome_unknown') else "error",
            data=event_data,
        )

    def fail_task(self, task_id: str, error: str) -> None:
        def change(task):
            if task.status in ('completed', 'cancelled', 'outcome_unknown', 'failed'):
                return False
            clean_error = clean_error_message(error)
            task.status = "outcome_unknown" if task.external_action_pending else "failed"
            task.completed_at = datetime.now()
            task.result_message = clean_error
            task.last_error = clean_error
            task.recoverable = False
            task.requires_user_confirmation = False
        task = self.db.mutate_task(task_id, change)
        if task is None:
            return
        self._emit(task, task.last_error, event_type="task_failed", level="error")

    def record_step(
        self,
        task_id: str,
        step: str,
        *,
        message: str = "",
        level: str = "info",
        data: dict[str, Any] | None = None,
    ) -> None:
        def change(task):
            if task.status in ('completed', 'cancelled', 'outcome_unknown', 'failed'):
                return False
            task.current_step = step
        task = self.db.mutate_task(task_id, change)
        if task is None:
            return
        self._emit(
            task,
            message or step,
            event_type="task_step",
            level=level,
            title=step,
            data=data,
        )

    def pause_for_user(
        self,
        task_id: str,
        error: str,
        *,
        current_step: str = "",
        resume_data: dict[str, Any] | None = None,
    ) -> None:
        def change(task):
            if task.status in ('completed', 'cancelled', 'outcome_unknown', 'failed'):
                return False
            task.status = "waiting_user"
            clean_error = clean_error_message(error)
            task.last_error = clean_error
            task.current_step = current_step or task.current_step
            task.recoverable = True
            task.requires_user_confirmation = True
            payload = json.loads(task.resume_data or '{}')
            payload.update(resume_data or {})
            payload['external_action_pending'] = task.external_action_pending
            task.resume_data = json.dumps(payload, ensure_ascii=False)
        task = self.db.mutate_task(task_id, change)
        if task is None:
            return
        self._emit(
            task,
            f"Task paused: {task.last_error}",
            event_type="task_waiting_user",
            level="warning",
            data={"current_step": task.current_step},
        )

    def mark_retrying(self, task_id: str) -> None:
        def change(task):
            if task.external_action_pending or task.status in ('completed', 'cancelled', 'outcome_unknown'):
                return False
            task.status = "retrying"
            task.retry_count += 1
            task.recoverable = False
            task.requires_user_confirmation = False
        task = self.db.mutate_task(task_id, change)
        if task is None:
            return
        self._emit(
            task,
            f"Retrying task from step: {task.current_step or 'unknown'}",
            event_type="task_retrying",
            level="info",
            data={"retry_count": task.retry_count, "current_step": task.current_step},
        )

    def get_recent_tasks(self, limit: int = 20) -> list[AutomationTask]:
        return self.db.get_recent_tasks(limit)

    def get_task(self, task_id: str) -> AutomationTask | None:
        return self._get_or_none(task_id)

    def _get_or_none(self, task_id: str) -> AutomationTask | None:
        return self.db.get_task(task_id)

    def _emit(
        self,
        task: AutomationTask,
        message: str,
        *,
        event_type: str,
        level: str = "info",
        title: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        if not self.events:
            return
        self.events.emit(
            message,
            account_email=task.account_email,
            task_id=task.id,
            event_type=event_type,
            level=level,
            title=title,
            data=data,
        )
