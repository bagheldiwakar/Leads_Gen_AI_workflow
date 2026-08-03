"""Persistent on/off state for the low-frequency Gmail reply and learning monitor."""
import json
from datetime import datetime
from pathlib import Path

STATE_PATH = Path(__file__).resolve().parent / "data" / "learning_monitor_state.json"
DEFAULT = {"enabled": False, "interval_seconds": 60, "last_checked_at": "", "last_reply_count": 0, "last_error": ""}


def state() -> dict:
    if not STATE_PATH.exists():
        return DEFAULT.copy()
    try:
        return {**DEFAULT, **json.loads(STATE_PATH.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError):
        return DEFAULT.copy()


def save(values: dict) -> dict:
    current = {**state(), **values}
    STATE_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def set_enabled(enabled: bool) -> dict:
    return save({"enabled": enabled, "last_error": ""})


def record_check(reply_count: int = 0, error: str = "") -> dict:
    return save({"last_checked_at": datetime.now().isoformat(timespec="seconds"), "last_reply_count": reply_count, "last_error": error})
