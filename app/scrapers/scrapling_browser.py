from __future__ import annotations

import asyncio

from ..config import (
    scrapling_disable_resources,
    scrapling_solve_cloudflare,
    scrapling_timeout_ms,
)
from ..sources import Source
from .base import FetchResult
from .proxy import assert_proxy_configured, residential_proxy_url


def _scrapling_wait_selector(source: Source) -> str | None:
    if source.site == "hsguru" and source.category == "meta":
        return "table tbody tr"
    if source.site == "hsguru" and source.category == "matchups":
        return "table tbody tr, canvas"
    if source.site == "hsreplay":
        return "script#userdata, #react-root"
    return None


def _scrapling_fetch_sync(source: Source, proxy: str | None) -> FetchResult:
    from scrapling.fetchers import StealthyFetcher

    target = source.fetch_url
    wait_ms = 8_000 if source.site == "hsguru" else 3_000
    kwargs: dict = {
        "headless": True,
        "solve_cloudflare": scrapling_solve_cloudflare(),
        "network_idle": True,
        "timeout": scrapling_timeout_ms(),
        "wait": wait_ms,
        "disable_resources": scrapling_disable_resources(),
        "block_ads": True,
        "retries": 2 if source.site == "hsguru" else 1,
        "retry_delay": 5,
    }
    selector = _scrapling_wait_selector(source)
    if selector:
        kwargs["wait_selector"] = selector
        kwargs["wait_selector_state"] = "attached"
    if proxy:
        kwargs["proxy"] = proxy
    page = StealthyFetcher.fetch(target, **kwargs)
    html = str(getattr(page, "html_content", "") or "")
    if not html.strip():
        raise RuntimeError("scrapling returned empty html")
    status = getattr(page, "status", None) or getattr(page, "status_code", None)
    http_status = int(status) if status else 200
    final_url = getattr(page, "url", None) or source.url
    return FetchResult(
        html=html,
        final_url=str(final_url),
        backend="scrapling",
        http_status=http_status,
    )


async def fetch_via_scrapling(source: Source) -> FetchResult:
    assert_proxy_configured()
    proxy = residential_proxy_url(source.id, page_url=source.fetch_url or source.url)
    return await asyncio.to_thread(_scrapling_fetch_sync, source, proxy)


def scrapling_available() -> bool:
    try:
        from scrapling.fetchers import StealthyFetcher  # noqa: F401

        return True
    except ImportError:
        return False
