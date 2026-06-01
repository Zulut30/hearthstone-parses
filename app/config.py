from __future__ import annotations

import os
from pathlib import Path


DEFAULT_DATA_DIR = "/var/lib/hs-data-api"
DEFAULT_BACKENDS = "patchright,flaresolverr,curl_cffi,cloudscraper"


def data_dir() -> Path:
    return Path(os.environ.get("HS_API_DATA_DIR", DEFAULT_DATA_DIR))


def bind_host() -> str:
    return os.environ.get("HS_API_BIND_HOST", "0.0.0.0")


def bind_port() -> int:
    return int(os.environ.get("HS_API_PORT", "8000"))


def api_key() -> str | None:
    value = os.environ.get("HS_API_KEY", "").strip()
    return value or None


def request_delay_seconds() -> float:
    return float(os.environ.get("HS_API_REQUEST_DELAY_SECONDS", "8.0"))


def request_timeout_seconds() -> float:
    return float(os.environ.get("HS_API_REQUEST_TIMEOUT_SECONDS", "150.0"))


def user_agent() -> str:
    return os.environ.get(
        "HS_API_USER_AGENT",
        "HSDataAPI/0.1 (+https://example.invalid/contact)",
    )


def fetch_proxy_url() -> str | None:
    value = os.environ.get("HS_FETCH_PROXY_URL", "").strip()
    return value or None


def fetch_require_proxy() -> bool:
    return os.environ.get("HS_FETCH_REQUIRE_PROXY", "true").strip().lower() in {
        "1", "true", "yes", "on",
    }


def fetch_direct_enabled() -> bool:
    return os.environ.get("HS_FETCH_DIRECT_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def fetch_backends() -> list[str]:
    raw = os.environ.get("HS_FETCH_BACKENDS", DEFAULT_BACKENDS)
    return [part.strip() for part in raw.split(",") if part.strip()]


def flaresolverr_url() -> str:
    return os.environ.get("HS_FLARESOLVERR_URL", "http://127.0.0.1:8191/v1").strip()


def fetch_max_retries() -> int:
    return max(1, int(os.environ.get("HS_FETCH_MAX_RETRIES", "3")))


def iproyal_session_per_source() -> bool:
    return os.environ.get("HS_IPROYAL_SESSION_PER_SOURCE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def iproyal_rotate_per_fetch() -> bool:
    """Append a unique IPRoyal session suffix per request (fresh IP). Off if your plan returns 407."""
    return os.environ.get("HS_IPROYAL_ROTATE_PER_FETCH", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def flaresolverr_session_per_source() -> bool:
    """New FlareSolverr browser session per source during refresh (better IP/cookie isolation)."""
    return os.environ.get("HS_FLARESOLVERR_SESSION_PER_SOURCE", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def proxy_check_url() -> str:
    return os.environ.get("HS_PROXY_CHECK_URL", "https://api.ipify.org").strip()


def hsreplay_email() -> str | None:
    value = os.environ.get("HSREPLAY_EMAIL", "").strip()
    return value or None


def hsreplay_password() -> str | None:
    value = os.environ.get("HSREPLAY_PASSWORD", "").strip()
    return value or None


def hsreplay_storage_path() -> Path:
    return Path(os.environ.get("HSREPLAY_STORAGE_PATH", str(data_dir() / "hsreplay-auth.json")))


def telegram_bot_token() -> str | None:
    value = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    return value or None


def telegram_chat_id() -> str | None:
    value = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return value or None
