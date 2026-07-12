from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .config import vicious_syndicate_storage_path

logger = logging.getLogger(__name__)


def _same_site(value: Any) -> str:
    raw = str(value or "Lax").strip().lower()
    if raw in {"none", "no_restriction", "no-restriction"}:
        return "None"
    if raw == "strict":
        return "Strict"
    return "Lax"


def cookie_editor_to_playwright(items: list[Any]) -> dict[str, Any]:
    cookies: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("name") or not item.get("value"):
            continue
        expiration = item.get("expirationDate")
        cookies.append(
            {
                "name": str(item["name"]),
                "value": str(item["value"]),
                "domain": str(item.get("domain") or "www.vicioussyndicate.com"),
                "path": str(item.get("path") or "/"),
                "expires": -1 if item.get("session") or expiration is None else float(expiration),
                "httpOnly": bool(item.get("httpOnly")),
                "secure": bool(item.get("secure", True)),
                "sameSite": _same_site(item.get("sameSite")),
            }
        )
    if not cookies:
        raise ValueError("No valid Vicious Syndicate cookies found")
    return {"cookies": cookies, "origins": []}


def import_vicious_syndicate_storage(path: Path) -> Path:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        raw = cookie_editor_to_playwright(raw)
    if not isinstance(raw, dict) or not isinstance(raw.get("cookies"), list):
        raise ValueError("Expected Playwright storage_state or Cookie-Editor cookie array")
    # Validate before replacing the known-good session file.
    cookies = _cookies_from_storage(raw)
    if not cookies:
        raise ValueError("No valid Vicious Syndicate cookies found")
    destination = vicious_syndicate_storage_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(destination)
    return destination


def _cookies_from_storage(raw: dict[str, Any]) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for item in raw.get("cookies") or []:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "www.vicioussyndicate.com").lstrip(".").lower()
        if domain != "vicioussyndicate.com" and not domain.endswith(".vicioussyndicate.com"):
            continue
        name = item.get("name")
        value = item.get("value")
        if name and value:
            cookies[str(name)] = str(value)
    return cookies


def vicious_syndicate_cookies_for_fetch() -> dict[str, str]:
    storage = vicious_syndicate_storage_path()
    try:
        raw = json.loads(storage.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring invalid Vicious Syndicate storage file %s: %s", storage, exc)
        return {}
    if not isinstance(raw, dict):
        logger.warning("Ignoring invalid Vicious Syndicate storage structure in %s", storage)
        return {}
    return _cookies_from_storage(raw)
