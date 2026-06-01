from __future__ import annotations

import asyncio

from ..sources import Source
from .base import FetchResult
from .proxy import assert_proxy_configured, cloudscraper_proxies


def _fetch_sync(source: Source) -> FetchResult:
    import cloudscraper

    assert_proxy_configured()
    session = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "linux", "mobile": False},
    )
    proxies = cloudscraper_proxies(source.id)
    response = session.get(source.url, proxies=proxies, timeout=60)
    response.raise_for_status()
    return FetchResult(
        html=response.text,
        final_url=str(response.url),
        backend="cloudscraper",
        http_status=response.status_code,
    )


async def fetch_via_cloudscraper(source: Source) -> FetchResult:
    return await asyncio.to_thread(_fetch_sync, source)
