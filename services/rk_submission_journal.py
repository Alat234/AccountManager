"""Account-local submission receipt; no verification codes or credentials."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from storage.atomic_files import write_json

FILENAME = 'rk_submission_state.json'


def read_submission_state(account_dir: Path) -> dict:
    path = account_dir / FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('status') not in {'pending', 'unknown', 'rejected', 'submitted'}:
            raise ValueError('Invalid receipt')
        return data
    except (OSError, ValueError):
        return {'status': 'unknown', 'reason': 'Could not read previous submission status'}


def write_submission_state(account_dir: Path, status: str, task_id: str = '', reason: str = '') -> None:
    data = {'status': status, 'task_id': task_id, 'timestamp': datetime.now(timezone.utc).isoformat(),
            'reason': re.sub(r'\b\d{6}\b', '***', reason[:500])}
    path = account_dir / FILENAME
    write_json(path, data)
