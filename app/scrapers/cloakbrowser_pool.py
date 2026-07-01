from __future__ import annotations

import os

from ..config import (
    cloakbrowser_fingerprint_seed,
    cloakbrowser_geoip,
    cloakbrowser_headless,
    cloakbrowser_hsguru_headless,
    cloakbrowser_humanize,
    hsreplay_storage_path,
)
from ..sources import Source
from .base import FetchResult
from .fingerprint_profile import browser_context_kwargs
from .navigation import navigate_page
from .proxy import assert_proxy_configured, residential_proxy_url


def _ensure_display_for_headed() -> None:
    if os.environ.get("DISPLAY"):
        return
    display = os.environ.get("HS_CLOAKBROWSER_DISPLAY", ":99")
    os.environ["DISPLAY"] = display


def _headless_for(source: Source) -> bool:
    if source.site == "hsguru":
        return cloakbrowser_hsguru_headless()
    return cloakbrowser_headless()


async def fetch_via_cloakbrowser(source: Source) -> FetchResult:
    """Per-fetch CloakBrowser context with proxy + geoip (recommended for HSGuru)."""
    assert_proxy_configured()
    from cloakbrowser import launch_context_async

    proxy_url = residential_proxy_url(source.id, page_url=source.fetch_url or source.url)
    if not proxy_url:
        raise RuntimeError("CloakBrowser requires HS_FETCH_PROXY_URL for residential egress")

    headless = _headless_for(source)
    if not headless:
        _ensure_display_for_headed()

    profile = await browser_context_kwargs(source)
    user_agent = profile.get("user_agent")
    viewport = profile.get("viewport")
    locale = profile.get("locale")
    timezone = profile.get("timezone_id")
    extra_headers = profile.get("extra_http_headers")
    storage_state = profile.get("storage_state")

    seed = cloakbrowser_fingerprint_seed(source.id)
    chromium_args = [
        f"--fingerprint={seed}",
        "--fingerprint-noise=false",
        "--fingerprint-screen-width=1920",
        "--fingerprint-screen-height=1080",
    ]
    launch_kwargs: dict = {
        "headless": headless,
        "proxy": proxy_url,
        "geoip": cloakbrowser_geoip(),
        "humanize": cloakbrowser_humanize() or source.site == "hsguru",
        "args": chromium_args,
        "user_agent": user_agent,
        "viewport": viewport,
        "locale": locale,
        "timezone": timezone,
    }
    if extra_headers:
        launch_kwargs["extra_http_headers"] = extra_headers
    if storage_state:
        launch_kwargs["storage_state"] = storage_state
    elif source.site == "hsreplay" and hsreplay_storage_path().exists():
        launch_kwargs["storage_state"] = str(hsreplay_storage_path())

    context = await launch_context_async(**launch_kwargs)
    page = await context.new_page()
    try:
        return await navigate_page(page, source, backend="cloakbrowser")
    finally:
        await context.close()


def cloakbrowser_available() -> bool:
    try:
        from cloakbrowser import launch_context_async  # noqa: F401

        return True
    except ImportError:
        return False


async def shutdown_cloakbrowser_pool() -> None:
    """No-op: contexts are closed per fetch."""
