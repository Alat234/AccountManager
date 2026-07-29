from __future__ import annotations

import uuid
from datetime import datetime

from automation.base import ScenarioResult
from models.task import AutomationTask
from storage.database import DatabaseManager


class TaskService:
    def __init__(self, db: DatabaseManager):
        self.db = db

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
            self.db.update_task(task)

    def complete_task(self, task_id: str, result: ScenarioResult) -> None:
        task = self._get_or_none(task_id)
        if not task:
            return
        task.status = "completed" if result.success else "failed"
        task.completed_at = datetime.now()
        task.result_message = result.message
        import json
        task.result_data = json.dumps(result.data, ensure_ascii=False) if result.data else ""
        self.db.update_task(task)

    def fail_task(self, task_id: str, error: str) -> None:
        task = self._get_or_none(task_id)
        if not task:
            return
        task.status = "failed"
        task.completed_at = datetime.now()
        task.result_message = error
        self.db.update_task(task)

    def get_recent_tasks(self, limit: int = 20) -> list[AutomationTask]:
        return self.db.get_recent_tasks(limit)

    def _get_or_none(self, task_id: str) -> AutomationTask | None:
        tasks = self.db.get_recent_tasks(limit=100)
        for t in tasks:
            if t.id == task_id:
                return t
        return None
