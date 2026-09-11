from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Callable

from models.operation_event import OperationEvent
from storage.database import DatabaseManager


class OperationEventService:
    def __init__(self, db: DatabaseManager, *, keep_per_account: int = 1000):
        self.db = db
        self.keep_per_account = keep_per_account
        self._listeners: list[Callable[[OperationEvent], None]] = []
        self._lock = threading.RLock()

    def register_listener(self, callback: Callable[[OperationEvent], None]) -> None:
        with self._lock:
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
        with self._lock:
            event.id = self.db.add_operation_event(event)
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                pass
        return event

    def recent_for_account(self, account_email: str, limit: int = 100) -> list[OperationEvent]:
        return self.db.get_operation_events(account_email=account_email, limit=min(limit, self.keep_per_account)) if account_email else []

    def recent_for_task(self, task_id: str, limit: int = 100) -> list[OperationEvent]:
        return self.db.get_operation_events(task_id=task_id, limit=limit) if task_id else []

    def clear_account(self, account_email: str) -> None:
        # UI lifecycle must never delete the durable operation journal.
        pass

    def clear_all(self) -> None:
        # Closing the window preserves history for recovery on the next launch.
        pass
