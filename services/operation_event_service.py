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
        self._events: list[OperationEvent] = []
        self._next_id = 1

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
        event.id = self._next_id
        self._next_id += 1
        self._events.append(event)
        if account_email:
            self._prune_account_events(account_email)
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                pass
        return event

    def recent_for_account(self, account_email: str, limit: int = 100) -> list[OperationEvent]:
        if not account_email:
            return []
        return [
            event
            for event in reversed(self._events)
            if event.account_email == account_email
        ][:limit]

    def recent_for_task(self, task_id: str, limit: int = 100) -> list[OperationEvent]:
        if not task_id:
            return []
        return [
            event
            for event in reversed(self._events)
            if event.task_id == task_id
        ][:limit]

    def clear_account(self, account_email: str) -> None:
        if not account_email:
            return
        self._events = [
            event for event in self._events
            if event.account_email != account_email
        ]

    def clear_all(self) -> None:
        self._events.clear()

    def _prune_account_events(self, account_email: str) -> None:
        matching = [
            event for event in self._events
            if event.account_email == account_email
        ]
        if len(matching) <= self.keep_per_account:
            return
        keep_ids = {event.id for event in matching[-self.keep_per_account:]}
        self._events = [
            event for event in self._events
            if event.account_email != account_email or event.id in keep_ids
        ]
