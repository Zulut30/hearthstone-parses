from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from .config import quality_thresholds_path

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_threshold_overrides() -> dict[str, dict[str, Any]]:
    path = quality_thresholds_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read quality thresholds: %s", exc)
        return {}
    sources = raw.get("sources") if isinstance(raw, dict) else None
    if not isinstance(sources, dict):
        return {}
    return {str(k): v for k, v in sources.items() if isinstance(v, dict)}


def season_scale_factor() -> float:
    """
    Scale minima after HS patches when total card count drops temporarily.
    Uses HearthstoneJSON catalog size as a coarse season proxy.
    """
    raw = load_threshold_overrides().get("_global") or {}
    fixed = raw.get("season_scale")
    if fixed is not None:
        try:
            return float(fixed)
        except (TypeError, ValueError):
            pass
    try:
        from .cards_index import cards_by_id

        total = len(cards_by_id())
        if total < 2200:
            return 0.75
        if total < 2800:
            return 0.88
        return 1.0
    except Exception:
        return 1.0


def threshold_for(source_id: str, key: str, default: int | float) -> int | float:
    overrides = load_threshold_overrides().get(source_id) or {}
    value = overrides.get(key)
    base = default
    if value is not None:
        try:
            base = type(default)(value)
        except (TypeError, ValueError):
            base = default
    if isinstance(base, (int, float)) and key.endswith("_min"):
        scaled = base * season_scale_factor()
        return type(default)(max(1, int(scaled))) if isinstance(default, int) else scaled
    return base
