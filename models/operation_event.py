from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class OperationEvent:
    id: int | None = None
    task_id: str = ""
    account_email: str = ""
    event_type: str = "general"
    level: str = "info"
    title: str = ""
    message: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    read_at: datetime | None = None
    data: str = ""
