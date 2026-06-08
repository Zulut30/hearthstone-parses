from __future__ import annotations

import json
import time
from pathlib import Path

from .config import data_dir, telegram_alert_dedup_seconds


def _dedup_path() -> Path:
    return data_dir() / ".telegram-alert-dedup.json"


def _dedup_key(source_id: str, state: str) -> str:
    return f"{source_id}:{state}"


def _read_recent_alerts(now: float | None = None) -> dict[str, float]:
    path = _dedup_path()
    current = time.time() if now is None else now
    ttl = telegram_alert_dedup_seconds()
    data: dict[str, float] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = {k: float(v) for k, v in raw.items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            data = {}
    return {k: v for k, v in data.items() if current - v < ttl}


def should_send_alert(source_id: str, state: str) -> bool:
    """Return False if the same source+state was successfully alerted within the TTL."""
    return _dedup_key(source_id, state) not in _read_recent_alerts()


def mark_alert_sent(source_id: str, state: str) -> None:
    """Record a sent alert after Telegram accepted it."""
    path = _dedup_path()
    now = time.time()
    data = _read_recent_alerts(now)
    data[_dedup_key(source_id, state)] = now
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
