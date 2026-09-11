import json
import threading
from copy import deepcopy
from storage.atomic_files import write_json
from pathlib import Path

from storage.constants import BASE_DIR

SETTINGS_PATH = BASE_DIR / "settings.json"


class SettingsManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self):
        if SETTINGS_PATH.exists():
            try:
                return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self):
        write_json(SETTINGS_PATH, self._data)

    def get(self, key: str, default=None):
        with self._lock:
            return deepcopy(self._data.get(key, default))

    def set(self, key: str, value):
        with self._lock:
            self._data[key] = deepcopy(value)
            self._save()
