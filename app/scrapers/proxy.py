from __future__ import annotations

import re
import secrets
from urllib.parse import urlparse, urlunparse

import httpx

from ..config import (
    fetch_proxy_url,
    fetch_require_proxy,
    iproyal_rotate_per_fetch,
    iproyal_session_per_source,
    proxy_check_url,
)

_IPROYAL_HOSTS = ("iproyal.com", "geo.iproyal.com")


def _is_iproyal(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return any(part in host for part in _IPROYAL_HOSTS)


def _iproyal_url_with_session(base: str, session_key: str) -> str:
    parsed = urlparse(base)
    username = parsed.username or ""
    password = parsed.password or ""
    if not username or "_session-" in username:
        return base
    session_user = f"{username}_session-{session_key}"
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{session_user}:{password}@{host}{port}"
    return urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def proxy_url_for_source(source_id: str | None = None, *, fetch_id: str | None = None) -> str | None:
    """
    Resolve proxy URL for a fetch.

    IPRoyal modes (see /etc/hs-data-api.env):
    - Default (both flags false): rotating pool, new IP per connection.
    - HS_IPROYAL_SESSION_PER_SOURCE=true: sticky IP per source_id (may 407 on some plans).
    - HS_IPROYAL_ROTATE_PER_FETCH=true: unique session per call (max rotation; may 407).
    """
    base = fetch_proxy_url()
    if not base or not _is_iproyal(base):
        return base
    if iproyal_rotate_per_fetch():
        key = fetch_id or secrets.token_hex(8)
        return _iproyal_url_with_session(base, key)
    if source_id and iproyal_session_per_source():
        session_key = re.sub(r"[^a-zA-Z0-9_-]", "_", source_id)[:48]
        return _iproyal_url_with_session(base, session_key)
    return base


def httpx_client_kwargs(
    source_id: str | None = None,
    *,
    timeout: float = 45.0,
    fetch_id: str | None = None,
) -> dict:
    """httpx.AsyncClient kwargs: proxy + no keep-alive (helps residential IP rotation)."""
    proxy = proxy_url_for_source(source_id, fetch_id=fetch_id)
    kwargs: dict = {
        "timeout": timeout,
        "follow_redirects": True,
        "limits": httpx.Limits(max_connections=4, max_keepalive_connections=0),
    }
    if proxy:
        kwargs["proxy"] = proxy
    return kwargs


def proxy_dict_for_flaresolverr(source_id: str | None = None) -> dict[str, str] | None:
    url = proxy_url_for_source(source_id)
    if not url:
        return None
    return {"url": url}


def playwright_proxy(source_id: str | None = None) -> dict[str, str] | None:
    url = proxy_url_for_source(source_id)
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.hostname:
        return {"server": url}
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    server = f"{parsed.scheme}://{parsed.hostname}:{port}"
    out: dict[str, str] = {"server": server}
    if parsed.username:
        out["username"] = parsed.username
        out["password"] = parsed.password or ""
    return out


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


async def check_proxy_rotation(samples: int = 5) -> dict[str, object]:
    """Sample egress IPs via proxy (different session keys) to verify rotation."""
    assert_proxy_configured()
    ips: list[str] = []
    errors: list[str] = []
    for i in range(max(1, samples)):
        url = proxy_url_for_source(f"rotation_test_{i}", fetch_id=secrets.token_hex(6))
        if not url:
            break
        try:
            async with httpx.AsyncClient(
                proxy=url,
                timeout=30.0,
                limits=httpx.Limits(max_keepalive_connections=0),
            ) as client:
                response = await client.get(proxy_check_url())
                response.raise_for_status()
                ips.append(response.text.strip())
        except Exception as exc:
            errors.append(f"sample_{i}: {exc}")
    unique = sorted(set(ips))
    return {
        "samples": len(ips),
        "unique_ips": len(unique),
        "ips": unique[:20],
        "rotating": len(unique) > 1,
        "errors": errors[:5],
    }


async def check_proxy_health() -> dict[str, str]:
    assert_proxy_configured()
    url = proxy_url_for_source("healthcheck")
    if not url:
        raise RuntimeError("HS_FETCH_PROXY_URL is empty")
    async with httpx.AsyncClient(
        proxy=url,
        timeout=30.0,
        limits=httpx.Limits(max_keepalive_connections=0),
    ) as client:
        response = await client.get(proxy_check_url())
        response.raise_for_status()
        ip = response.text.strip()
    rotation = await check_proxy_rotation(3)
    return {
        "proxy_url_host": urlparse(url).hostname or "",
        "egress_ip": ip,
        "rotation_unique_ips": str(rotation.get("unique_ips", 0)),
        "rotation_ok": str(rotation.get("rotating", False)),
    }
