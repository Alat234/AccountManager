from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AutomationTask:
    id: str
    account_email: str
    scenario_type: str
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    result_message: str = ""
    result_data: str = ""
    current_step: str = ""
    last_error: str = ""
    retry_count: int = 0
    recoverable: bool = False
    requires_user_confirmation: bool = False
    resume_data: str = ""
