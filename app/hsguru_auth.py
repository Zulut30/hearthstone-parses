from __future__ import annotations

import json
import logging
from typing import Any

from .config import hsguru_storage_path

logger = logging.getLogger(__name__)


def _cookies_from_storage(raw: dict[str, Any]) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for item in raw.get("cookies") or []:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "www.hsguru.com").lstrip(".").lower()
        if domain != "hsguru.com" and not domain.endswith(".hsguru.com"):
            continue
        name = item.get("name")
        value = item.get("value")
        if name and value is not None:
            cookies[str(name)] = str(value)
    return cookies


def hsguru_cookies_for_fetch() -> dict[str, str]:
    storage = hsguru_storage_path()
    if not storage.exists():
        return {}
    try:
        raw = json.loads(storage.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read HSGuru auth storage %s: %s", storage, exc)
        return {}
    if isinstance(raw, list):
        cookies: dict[str, str] = {}
        for item in raw:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            domain = str(item.get("domain") or "www.hsguru.com").lstrip(".").lower()
            if domain != "hsguru.com" and not domain.endswith(".hsguru.com"):
                continue
            cookies[str(item["name"])] = str(item.get("value") or "")
        return cookies
    if not isinstance(raw, dict):
        return {}
    return _cookies_from_storage(raw)


def hsguru_cookie_header() -> str | None:
    cookies = hsguru_cookies_for_fetch()
    if not cookies:
        return None
    # Keep raw cookie values as exported; only join name=value pairs.
    parts = [f"{name}={value}" for name, value in cookies.items() if name]
    return "; ".join(parts) if parts else None


def hsguru_firecrawl_headers() -> dict[str, str] | None:
    cookie = hsguru_cookie_header()
    if not cookie:
        return None
    return {"Cookie": cookie}
