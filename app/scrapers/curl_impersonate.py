from __future__ import annotations

import asyncio

from ..config import request_timeout_seconds
from ..sources import Source
from .base import FetchResult
from .proxy import assert_proxy_configured, proxy_url_for_source


def _fetch_sync(source: Source) -> FetchResult:
    from curl_cffi import requests as curl_requests

    assert_proxy_configured()
    proxy_url = proxy_url_for_source(source.id)
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    response = curl_requests.get(
        source.url,
        impersonate="chrome131",
        proxies=proxies,
        timeout=request_timeout_seconds(),
        allow_redirects=True,
    )
    if response.status_code >= 400:
        response.raise_for_status()
    return FetchResult(
        html=response.text,
        final_url=str(response.url),
        backend="curl_cffi",
        http_status=response.status_code,
    )


async def fetch_via_curl_cffi(source: Source) -> FetchResult:
    return await asyncio.to_thread(_fetch_sync, source)


def curl_cffi_available() -> bool:
    try:
        import curl_cffi  # noqa: F401

        return True
    except ImportError:
        return False
