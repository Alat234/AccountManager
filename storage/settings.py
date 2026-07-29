import json
from pathlib import Path

from storage.constants import BASE_DIR

SETTINGS_PATH = BASE_DIR / "settings.json"


class SettingsManager:
    def __init__(self):
        self._data = self._load()

    def _load(self):
        if SETTINGS_PATH.exists():
            try:
                return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self):
        SETTINGS_PATH.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value
        self._save()
