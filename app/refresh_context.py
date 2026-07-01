from __future__ import annotations

from contextvars import ContextVar
from typing import Any

# Per-refresh-run in-memory cache for HSReplay JSON API responses.
_hsreplay_json_cache: ContextVar[dict[str, Any] | None] = ContextVar(
    "hsreplay_json_cache", default=None
)


def begin_refresh_run() -> None:
    _hsreplay_json_cache.set({})


def end_refresh_run() -> None:
    _hsreplay_json_cache.set(None)


def get_hsreplay_json_cache() -> dict[str, Any] | None:
    return _hsreplay_json_cache.get()


def get_cached_hsreplay_json(key: str) -> dict[str, Any] | None:
    cache = _hsreplay_json_cache.get()
    if not cache:
        return None
    entry = cache.get(key)
    if isinstance(entry, dict):
        return entry
    return None


def set_cached_hsreplay_json(key: str, payload: dict[str, Any]) -> None:
    cache = _hsreplay_json_cache.get()
    if cache is None:
        return
    cache[key] = payload
