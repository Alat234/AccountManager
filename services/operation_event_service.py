from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from models.operation_event import OperationEvent
from storage.database import DatabaseManager


class OperationEventService:
    def __init__(self, db: DatabaseManager, *, keep_per_account: int = 1000):
        self.db = db
        self.keep_per_account = keep_per_account
        self._listeners: list[Callable[[OperationEvent], None]] = []

    def register_listener(self, callback: Callable[[OperationEvent], None]) -> None:
        self._listeners.append(callback)

    def emit(
        self,
        message: str,
        *,
        account_email: str = "",
        task_id: str = "",
        event_type: str = "general",
        level: str = "info",
        title: str = "",
        data: dict[str, Any] | None = None,
    ) -> OperationEvent:
        event = OperationEvent(
            task_id=task_id,
            account_email=account_email,
            event_type=event_type,
            level=level,
            title=title,
            message=message,
            created_at=datetime.now(),
            data=json.dumps(data or {}, ensure_ascii=False) if data else "",
        )
        event.id = self.db.add_operation_event(event)
        if account_email:
            self.db.prune_operation_events(account_email, keep=self.keep_per_account)
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                pass
        return event

    def recent_for_account(self, account_email: str, limit: int = 100) -> list[OperationEvent]:
        return self.db.get_operation_events(account_email=account_email, limit=limit)

    def recent_for_task(self, task_id: str, limit: int = 100) -> list[OperationEvent]:
        return self.db.get_operation_events(task_id=task_id, limit=limit)
