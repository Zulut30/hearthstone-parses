from __future__ import annotations

import os
from pathlib import Path


DEFAULT_DATA_DIR = "/var/lib/hs-data-api"
DEFAULT_BACKENDS = "flaresolverr,scrapling,patchright,curl_cffi,cloudscraper"
DEFAULT_HSGURU_BACKENDS = "flaresolverr,scrapling,curl_cffi,cloudscraper,patchright"
DEFAULT_BACKENDS_LAB = "cloakbrowser,flaresolverr,scrapling,patchright,curl_cffi,cloudscraper"
DEFAULT_HSREPLAY_JSON_CHANNELS = "curl_cffi,flaresolverr"
DEFAULT_HSREPLAY_MARKDOWN_CHANNELS = "flaresolverr,curl_cffi"


def data_dir() -> Path:
    return Path(os.environ.get("HS_API_DATA_DIR", DEFAULT_DATA_DIR))


def bind_host() -> str:
    return os.environ.get("HS_API_BIND_HOST", "0.0.0.0")


def bind_port() -> int:
    return int(os.environ.get("HS_API_PORT", "8000"))


def api_key() -> str | None:
    value = os.environ.get("HS_API_KEY", "").strip()
    return value or None


def cors_allowed_origins() -> list[str]:
    raw = os.environ.get("HS_CORS_ALLOWED_ORIGINS", "https://api.hs-manacost.ru")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["https://api.hs-manacost.ru"]


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


def hsguru_fetch_backends() -> list[str]:
    raw = os.environ.get("HS_HSGURU_FETCH_BACKENDS", DEFAULT_HSGURU_BACKENDS)
    return [part.strip() for part in raw.split(",") if part.strip()]


def fetch_backends_lab() -> list[str]:
    raw = os.environ.get("HS_FETCH_BACKENDS_LAB", DEFAULT_BACKENDS_LAB)
    return [part.strip() for part in raw.split(",") if part.strip()]


def flaresolverr_url() -> str:
    return os.environ.get("HS_FLARESOLVERR_URL", "http://127.0.0.1:8191/v1").strip()


def hsreplay_cookie_path() -> Path:
    return Path(os.environ.get("HSREPLAY_COOKIE_PATH", "/etc/hs-data-api-hsreplay-cookies.json"))


def fetch_max_retries() -> int:
    return max(1, int(os.environ.get("HS_FETCH_MAX_RETRIES", "3")))


def proxy_sticky_mode() -> str:
    """
    Sticky proxy session key strategy for residential providers (IPRoyal).
    domain — one IP per site (hsreplay.net, hsguru.com); recommended default.
    source — one IP per source_id (HS_IPROYAL_SESSION_PER_SOURCE=true equivalent).
    rotate — new session per fetch (only for debugging; causes day-2 bans).
    """
    raw = os.environ.get("HS_PROXY_STICKY_MODE", "domain").strip().lower()
    if raw in {"domain", "source", "rotate"}:
        return raw
    return "domain"


def iproyal_session_per_source() -> bool:
    """Legacy flag; when true, forces source-level sticky (overrides domain mode)."""
    return os.environ.get("HS_IPROYAL_SESSION_PER_SOURCE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def http_retry_attempts() -> int:
    return max(1, int(os.environ.get("HS_HTTP_RETRY_ATTEMPTS", "3")))


def iproyal_session_lifetime() -> str:
    """IPRoyal sticky lifetime tag, e.g. 30m or 2h."""
    return os.environ.get("HS_IPROYAL_SESSION_LIFETIME", "30m").strip() or "30m"


def iproyal_api_token() -> str | None:
    value = os.environ.get("HS_IPROYAL_API_TOKEN", "").strip()
    return value or None


def iproyal_rotate_per_fetch() -> bool:
    """Append a unique IPRoyal session suffix per request (fresh IP). Off if your plan returns 407."""
    return os.environ.get("HS_IPROYAL_ROTATE_PER_FETCH", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def flaresolverr_hsguru_wait_ms() -> int:
    """Extra wait after page load for HSGuru React tables (FlareSolverr `wait` param).
    Higher values help with slow hydration on residential IPs; 30-60s typical for meta.
    """
    return max(0, int(os.environ.get("HS_FLARESOLVERR_HSGURU_WAIT_MS", "30000")))


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


def refresh_parallel_light() -> int:
    v = max(1, int(os.environ.get("HS_REFRESH_PARALLEL_LIGHT", "2")))
    if v > 3:
        # Guard: elevated parallelism increases chance of 429/407/CF rate limits and FS contention.
        # Only raise after 7+ days of clean crons (no proxy 407, FS stable, low "table too small").
        import logging

        logging.getLogger(__name__).warning(
            "HS_REFRESH_PARALLEL_LIGHT=%s >3 — monitor /ops/summary and logs for 407/429/FS errors before keeping this value",
            v,
        )
    return v


def refresh_parallel_medium() -> int:
    v = max(1, int(os.environ.get("HS_REFRESH_PARALLEL_MEDIUM", "1")))
    if v > 2:
        import logging

        logging.getLogger(__name__).warning(
            "HS_REFRESH_PARALLEL_MEDIUM=%s >2 — elevated API concurrency; watch for source throttling", v
        )
    return v


def refresh_preflight_strict() -> bool:
    return os.environ.get("HS_REFRESH_PREFLIGHT_STRICT", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def refresh_preflight_probe_hsreplay() -> bool:
    return os.environ.get("HS_REFRESH_PREFLIGHT_PROBE_HSREPLAY", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def api_json_attempts_per_channel() -> int:
    return max(1, int(os.environ.get("HS_API_JSON_ATTEMPTS_PER_CHANNEL", "2")))


def api_json_retry_delay_seconds() -> float:
    return float(os.environ.get("HS_API_JSON_RETRY_DELAY_SECONDS", "2.0"))


def refresh_parallel_stagger_min() -> float:
    return float(os.environ.get("HS_REFRESH_PARALLEL_STAGGER_MIN", "0.3"))


def refresh_parallel_stagger_max() -> float:
    return float(os.environ.get("HS_REFRESH_PARALLEL_STAGGER_MAX", "1.0"))


def refresh_delay_browser_only() -> bool:
    return os.environ.get("HS_REFRESH_DELAY_BROWSER_ONLY", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def hsreplay_json_channels() -> list[str]:
    raw = os.environ.get("HS_HSREPLAY_JSON_CHANNELS", DEFAULT_HSREPLAY_JSON_CHANNELS)
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def hsreplay_markdown_channels() -> list[str]:
    """Channels for HSReplay markdown pages (BG comps); Jina omitted by default (451)."""
    raw = os.environ.get("HS_HSREPLAY_MARKDOWN_CHANNELS", DEFAULT_HSREPLAY_MARKDOWN_CHANNELS)
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def stale_dataset_hours() -> float:
    return float(os.environ.get("HS_STALE_HOURS", "12"))


def bg_comp_detail_cache_ttl_hours() -> float:
    """TTL for cached HSReplay battlegrounds comps detail markdown."""
    return max(0.1, float(os.environ.get("HS_BG_COMP_DETAIL_CACHE_TTL_HOURS", "6")))


def telegram_alert_dedup_seconds() -> int:
    return max(60, int(os.environ.get("HS_TELEGRAM_ALERT_DEDUP_SECONDS", "3600")))


def log_rotate_max_bytes() -> int:
    return max(1_000_000, int(os.environ.get("HS_LOG_ROTATE_MAX_BYTES", str(50 * 1024 * 1024))))


def log_rotate_max_age_days() -> int:
    return max(1, int(os.environ.get("HS_LOG_ROTATE_MAX_AGE_DAYS", "7")))


def quality_thresholds_path() -> Path:
    return Path(
        os.environ.get(
            "HS_QUALITY_THRESHOLDS_PATH",
            str(Path(__file__).resolve().parent.parent / "config" / "quality_thresholds.json"),
        )
    )


def dataset_regression_drop_ratio() -> float:
    return float(os.environ.get("HS_DATASET_REGRESSION_DROP_RATIO", "0.30"))


def firecrawl_api_key() -> str | None:
    value = (
        os.environ.get("FIRECRAWL_API_KEY")
        or os.environ.get("HS_FIRECRAWL_API_KEY")
        or ""
    ).strip()
    return value or None


def firecrawl_max_age_ms() -> int:
    return max(0, int(os.environ.get("HS_FIRECRAWL_MAX_AGE_MS", "172800000")))


def firecrawl_wait_ms() -> int:
    return max(0, int(os.environ.get("HS_FIRECRAWL_WAIT_MS", "5000")))


def firecrawl_timeout_ms() -> int:
    return max(1000, int(os.environ.get("HS_FIRECRAWL_TIMEOUT_MS", "30000")))


def firecrawl_primary_source_ids() -> set[str]:
    raw = os.environ.get(
        "HS_FIRECRAWL_PRIMARY_SOURCE_IDS",
        "hsguru_streamer_decks_legend_1000",
    )
    return {part.strip() for part in raw.split(",") if part.strip()}


def firecrawl_fallback_source_ids() -> set[str]:
    raw = os.environ.get(
        "HS_FIRECRAWL_FALLBACK_SOURCE_IDS",
        ",".join(
            [
                "hsguru_meta_standard_legend",
                "hsguru_meta_standard_diamond_4to1",
                "hsguru_meta_wild_legend",
                "hsguru_meta_wild_diamond_4to1",
                "hsguru_meta_standard_top_5k",
                "hsguru_meta_standard_top_legend",
                "hsguru_meta_wild_top_legend",
                "hsguru_meta_wild_top_5k",
                "hsguru_matchups_legend",
                "hsguru_matchups_diamond_4to1",
                "hsreplay_battlegrounds_trinkets_lesser",
                "hsreplay_battlegrounds_trinkets_greater",
                "hsreplay_decks_trending",
                "heartharena_tierlist",
                "vicious_syndicate_radars",
            ]
        ),
    )
    return {part.strip() for part in raw.split(",") if part.strip()}


def firecrawl_fallback_max_attempts_per_refresh() -> int:
    return max(0, int(os.environ.get("HS_FIRECRAWL_FALLBACK_MAX_ATTEMPTS_PER_REFRESH", "8")))


def fingerprint_node_enabled() -> bool:
    return os.environ.get("HS_FINGERPRINT_SUITE_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def cloakbrowser_humanize() -> bool:
    return os.environ.get("HS_CLOAKBROWSER_HUMANIZE", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def cloakbrowser_geoip() -> bool:
    return os.environ.get("HS_CLOAKBROWSER_GEOIP", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def cloakbrowser_headless() -> bool:
    return os.environ.get("HS_CLOAKBROWSER_HEADLESS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def cloakbrowser_hsguru_headless() -> bool:
    """HSGuru often needs headed mode even with CloakBrowser patches."""
    return os.environ.get("HS_CLOAKBROWSER_HSGURU_HEADLESS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def cloakbrowser_fingerprint_seed(source_id: str) -> int:
    """Stable per-source seed so repeat visits look like the same device."""
    import hashlib

    digest = hashlib.md5(source_id.encode("utf-8")).hexdigest()
    offset = int(digest[:8], 16) % 89_999
    return 10_000 + offset


def scrapling_solve_cloudflare() -> bool:
    return os.environ.get("HS_SCRAPLING_SOLVE_CLOUDFLARE", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def scrapling_disable_resources() -> bool:
    return os.environ.get("HS_SCRAPLING_DISABLE_RESOURCES", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def scrapling_timeout_ms() -> int:
    return max(30_000, int(os.environ.get("HS_SCRAPLING_TIMEOUT_MS", "180000")))


def fetch_backend_max_seconds() -> float | None:
    """Per-backend wall clock cap in rotator (unset = no extra cap beyond fetch timeouts)."""
    raw = os.environ.get("HS_FETCH_BACKEND_MAX_SECONDS", "").strip()
    if not raw:
        return None
    return max(45.0, float(raw))


def browser_preferred_sticky_backends() -> frozenset[str]:
    raw = os.environ.get(
        "HS_BROWSER_PREFERRED_STICKY_BACKENDS",
        "flaresolverr,patchright,playwright",
    )
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def fetch_playwright_stealth_enabled() -> bool:
    return os.environ.get("HS_FETCH_PLAYWRIGHT_STEALTH", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
