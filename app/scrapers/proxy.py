from __future__ import annotations

import re
from urllib.parse import quote, urlparse, urlunparse

import httpx

from ..config import (
    fetch_proxy_url,
    fetch_require_proxy,
    iproyal_session_per_source,
    proxy_check_url,
)

_IPROYAL_HOSTS = ("iproyal.com", "geo.iproyal.com")


def _is_iproyal(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return any(part in host for part in _IPROYAL_HOSTS)


def proxy_url_for_source(source_id: str | None = None) -> str | None:
    base = fetch_proxy_url()
    if not base:
        return None
    if not source_id or not iproyal_session_per_source() or not _is_iproyal(base):
        return base

    parsed = urlparse(base)
    username = parsed.username or ""
    password = parsed.password or ""
    if not username:
        return base

    session_key = re.sub(r"[^a-zA-Z0-9_-]", "_", source_id)[:48]
    if "_session-" in username:
        return base
    session_user = f"{username}_session-{session_key}"
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{session_user}:{password}@{host}{port}"
    return urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def proxy_dict_for_flaresolverr(source_id: str | None = None) -> dict[str, str] | None:
    url = proxy_url_for_source(source_id)
    if not url:
        return None
    return {"url": url}


def playwright_proxy(source_id: str | None = None) -> dict[str, str] | None:
    url = proxy_url_for_source(source_id)
    if not url:
        return None
    return {"server": url}


def cloudscraper_proxies(source_id: str | None = None) -> dict[str, str] | None:
    url = proxy_url_for_source(source_id)
    if not url:
        return None
    return {"http": url, "https": url}


def assert_proxy_configured() -> None:
    if fetch_require_proxy() and not fetch_proxy_url():
        raise RuntimeError(
            "HS_FETCH_PROXY_URL is required (HS_FETCH_REQUIRE_PROXY=true). "
            "Configure a residential proxy so the origin never sees this server's IP."
        )


async def check_proxy_health() -> dict[str, str]:
    assert_proxy_configured()
    url = proxy_url_for_source("healthcheck")
    if not url:
        raise RuntimeError("HS_FETCH_PROXY_URL is empty")
    async with httpx.AsyncClient(proxy=url, timeout=30.0) as client:
        response = await client.get(proxy_check_url())
        response.raise_for_status()
        ip = response.text.strip()
    return {"proxy_url_host": urlparse(url).hostname or "", "egress_ip": ip}
