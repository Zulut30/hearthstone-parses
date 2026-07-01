from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from ..config import data_dir, fingerprint_node_enabled, hsreplay_storage_path
from ..sources import Source

logger = logging.getLogger(__name__)

_FALLBACK_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
)

_FINGERPRINT_CACHE: dict[str, Any] | None = None


def _fingerprint_script_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "fingerprint-node"


def _load_fingerprint_from_node() -> dict[str, Any] | None:
    script_dir = _fingerprint_script_dir()
    generate = script_dir / "generate.mjs"
    if not generate.is_file():
        return None
    node_modules = script_dir / "node_modules"
    if not node_modules.is_dir():
        return None
    try:
        proc = subprocess.run(
            ["node", str(generate)],
            cwd=str(script_dir),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("fingerprint-suite node script failed: %s", exc)
        return None
    if proc.returncode != 0:
        logger.warning(
            "fingerprint-suite node script exit %s: %s",
            proc.returncode,
            (proc.stderr or proc.stdout or "")[:500],
        )
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        logger.warning("fingerprint-suite returned invalid JSON")
        return None


def _cached_fingerprint_profile() -> dict[str, Any]:
    global _FINGERPRINT_CACHE
    if _FINGERPRINT_CACHE is not None:
        return _FINGERPRINT_CACHE
    if fingerprint_node_enabled():
        loaded = _load_fingerprint_from_node()
        if loaded:
            _FINGERPRINT_CACHE = loaded
            return loaded
    _FINGERPRINT_CACHE = {
        "user_agent": _FALLBACK_USER_AGENTS[0],
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "viewport": {"width": 1440, "height": 900},
        "extra_http_headers": {},
    }
    return _FINGERPRINT_CACHE


def _source_user_agent(source: Source, profile: dict[str, Any]) -> str:
    base = profile.get("user_agent") or _FALLBACK_USER_AGENTS[0]
    if source.site != "hsreplay":
        return str(base)
    idx = int(hashlib.md5(source.id.encode("utf-8")).hexdigest(), 16) % len(_FALLBACK_USER_AGENTS)
    return _FALLBACK_USER_AGENTS[idx]


async def browser_context_kwargs(source: Source) -> dict[str, Any]:
    """Playwright/CloakBrowser new_context() kwargs with optional Apify fingerprint."""
    profile = _cached_fingerprint_profile()
    kwargs: dict[str, Any] = {
        "user_agent": _source_user_agent(source, profile),
        "locale": profile.get("locale", "en-US"),
        "timezone_id": profile.get("timezone_id", "America/New_York"),
        "viewport": dict(profile.get("viewport") or {"width": 1440, "height": 900}),
    }
    extra = profile.get("extra_http_headers")
    if isinstance(extra, dict) and extra:
        kwargs["extra_http_headers"] = {str(k): str(v) for k, v in extra.items()}
    storage = hsreplay_storage_path()
    if source.site == "hsreplay" and storage.exists():
        kwargs["storage_state"] = str(storage)
    return kwargs


def persist_fingerprint_cache() -> Path:
    """Write generated profile for ops/debug."""
    path = data_dir() / "browser-fingerprint.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_cached_fingerprint_profile(), indent=2), encoding="utf-8")
    return path
