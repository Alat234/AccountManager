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
        task = self._get_or_none(task_id)
        if task:
            task.status = "running"
            task.current_step = "started"
            self.db.update_task(task)

    def complete_task(self, task_id: str, result: ScenarioResult) -> None:
        task = self._get_or_none(task_id)
        if not task:
            return
        task.status = "completed" if result.success else "failed"
        task.completed_at = datetime.now()
        clean_message = result.message if result.success else clean_error_message(result.message)
        task.result_message = clean_message
        task.result_data = json.dumps(result.data, ensure_ascii=False) if result.data else ""
        task.last_error = "" if result.success else clean_message
        task.recoverable = False
        task.requires_user_confirmation = False
        task.current_step = "completed" if result.success else task.current_step
        self.db.update_task(task)
        event_data = dict(result.data or {})
        event_data["scenario_type"] = task.scenario_type
        self._emit(
            task,
            clean_message,
            event_type="task_completed" if result.success else "task_failed",
            level="success" if result.success else "error",
            data=event_data,
        )

    def fail_task(self, task_id: str, error: str) -> None:
        task = self._get_or_none(task_id)
        if not task:
            return
        clean_error = clean_error_message(error)
        task.status = "failed"
        task.completed_at = datetime.now()
        task.result_message = clean_error
        task.last_error = clean_error
        task.recoverable = False
        task.requires_user_confirmation = False
        self.db.update_task(task)
        self._emit(task, clean_error, event_type="task_failed", level="error")

    def record_step(
        self,
        task_id: str,
        step: str,
        *,
        message: str = "",
        level: str = "info",
        data: dict[str, Any] | None = None,
    ) -> None:
        task = self._get_or_none(task_id)
        if not task:
            return
        task.current_step = step
        self.db.update_task(task)
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
        task = self._get_or_none(task_id)
        if not task:
            return
        task.status = "waiting_user"
        clean_error = clean_error_message(error)
        task.last_error = clean_error
        task.current_step = current_step or task.current_step
        task.recoverable = True
        task.requires_user_confirmation = True
        task.resume_data = json.dumps(resume_data or {}, ensure_ascii=False) if resume_data else ""
        self.db.update_task(task)
        self._emit(
            task,
            f"Task paused: {clean_error}",
            event_type="task_waiting_user",
            level="warning",
            data={"current_step": task.current_step},
        )

    def mark_retrying(self, task_id: str) -> None:
        task = self._get_or_none(task_id)
        if not task:
            return
        task.status = "retrying"
        task.retry_count += 1
        task.recoverable = False
        task.requires_user_confirmation = False
        self.db.update_task(task)
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
        tasks = self.db.get_recent_tasks(limit=100)
        for t in tasks:
            if t.id == task_id:
                return t
        return None

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
