from __future__ import annotations

import asyncio

from ..config import request_timeout_seconds
from ..sources import Source
from .base import FetchResult
from .proxy import assert_proxy_configured, proxy_url_for_source


def _fetch_sync(source: Source) -> FetchResult:
    from camoufox.sync_api import Camoufox

    assert_proxy_configured()
    proxy_url = proxy_url_for_source(source.id)
    options: dict = {"headless": True}
    if proxy_url:
        options["proxy"] = {"server": proxy_url}

    timeout_ms = int(request_timeout_seconds() * 1000)
    with Camoufox(**options) as browser:
        page = browser.new_page()
        try:
            page.goto(source.fetch_url, wait_until="domcontentloaded", timeout=timeout_ms)
            if source.fragment:
                page.evaluate(
                    "(h) => { window.location.hash = h; }",
                    f"#{source.fragment}",
                )
                page.wait_for_timeout(6000)
            else:
                page.wait_for_timeout(4000)
            return FetchResult(
                html=page.content(),
                final_url=page.url,
                backend="camoufox",
                http_status=200,
            )
        finally:
            page.close()


async def fetch_via_camoufox(source: Source) -> FetchResult:
    return await asyncio.to_thread(_fetch_sync, source)


def camoufox_available() -> bool:
    try:
        import camoufox  # noqa: F401

        return True
    except ImportError:
        return False
