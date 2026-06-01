from __future__ import annotations

import asyncio
import fcntl
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .config import (
    data_dir,
    fetch_backends,
    fetch_direct_enabled,
    fetch_proxy_url,
    fetch_require_proxy,
    request_delay_seconds,
    request_timeout_seconds,
    user_agent,
)
from .parser import parse_html
from .scrapers.browser_pool import PatchrightPool
from .scrapers.flaresolverr import set_active_flaresolverr_session, set_flaresolverr_source
from .scrapers.flaresolverr_session import FlareSolverrSession
from .scrapers.proxy import check_proxy_health
from .scrapers.quality import is_cloudflare_challenge, validate_parsed_data
from .scrapers.rotator import fetch_html
from .sources import SOURCES, SOURCE_BY_ID, Source
from .storage import load_status, save_dataset, save_status

LOCK_PATH = Path(os.environ.get("HS_API_DATA_DIR", "/var/lib/hs-data-api")) / ".refresh.lock"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _status_payload(
    source: Source,
    state: str,
    *,
    fetched_at: str,
    http_status: int | None = None,
    final_url: str | None = None,
    error: str | None = None,
    detail: str | None = None,
    content_length: int | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_id": source.id,
        "site": source.site,
        "category": source.category,
        "url": source.url,
        "fetch_url": source.fetch_url,
        "fragment": source.fragment,
        "state": state,
        "fetched_at": fetched_at,
        "http_status": http_status,
        "final_url": final_url,
        "error": error,
        "detail": detail,
        "content_length": content_length,
    }
    if backend:
        payload["backend"] = backend
    return payload


class RefreshLock:
    def __init__(self, path: Path = LOCK_PATH) -> None:
        self.path = path
        self._fh = None

    def __enter__(self) -> RefreshLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another refresh is already running") from exc
        self._fh.write(f"pid={os.getpid()}\n")
        self._fh.flush()
        return self

    def __exit__(self, *args: object) -> None:
        if self._fh is not None:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self.path.unlink(missing_ok=True)


async def _fetch_direct(client: httpx.AsyncClient, source: Source) -> tuple[str, int, str]:
    response = await client.get(source.fetch_url)
    return response.text, response.status_code, str(response.url)


async def fetch_source(client: httpx.AsyncClient | None, source: Source) -> dict[str, Any]:
    fetched_at = now_iso()
    previous = load_status(source.id) or {}
    preferred_backend = previous.get("backend") if previous.get("state") == "ok" else None

    if fetch_require_proxy() and not fetch_proxy_url():
        status = _status_payload(
            source,
            "proxy_required",
            fetched_at=fetched_at,
            detail="Set HS_FETCH_PROXY_URL in /etc/hs-data-api.env",
        )
        save_status(source.id, status)
        return status

    set_flaresolverr_source(source.id)
    try:
        if fetch_direct_enabled() and client is not None:
            body, http_status, final_url = await _fetch_direct(client, source)
            backend = "direct"
        else:
            result = await fetch_html(
                source,
                preferred_backend=preferred_backend,
                parse_preview=lambda html: parse_html(source, html),
            )
            body = result.html
            http_status = result.http_status
            final_url = result.final_url
            backend = result.backend
    except Exception as exc:
        status = _status_payload(
            source,
            "fetch_error",
            fetched_at=fetched_at,
            error=type(exc).__name__,
            detail=str(exc)[:2000],
        )
        save_status(source.id, status)
        return status
    finally:
        set_flaresolverr_source(None)

    content_length = len(body.encode("utf-8", errors="replace"))
    if is_cloudflare_challenge(body):
        status = _status_payload(
            source,
            "blocked_by_protection",
            fetched_at=fetched_at,
            http_status=http_status,
            final_url=final_url,
            detail="Cloudflare challenge after all backends.",
            content_length=content_length,
            backend=backend,
        )
        save_status(source.id, status)
        return status

    if http_status >= 400:
        status = _status_payload(
            source,
            "http_error",
            fetched_at=fetched_at,
            http_status=http_status,
            final_url=final_url,
            detail="HTTP error from origin",
            content_length=content_length,
            backend=backend,
        )
        save_status(source.id, status)
        return status

    parsed = parse_html(source, body)
    ok, reason = validate_parsed_data(source, parsed)
    if not ok:
        status = _status_payload(
            source,
            "quality_error",
            fetched_at=fetched_at,
            http_status=http_status,
            final_url=final_url,
            detail=reason,
            content_length=content_length,
            backend=backend,
        )
        save_status(source.id, status)
        return status

    dataset = {
        "state": "ok",
        "fetched_at": fetched_at,
        "http_status": http_status,
        "final_url": final_url,
        "content_length": content_length,
        "backend": backend,
        "data": parsed,
    }
    save_dataset(source.id, dataset)
    status = _status_payload(
        source,
        "ok",
        fetched_at=fetched_at,
        http_status=http_status,
        final_url=final_url,
        content_length=content_length,
        backend=backend,
    )
    save_status(source.id, status)
    return status


async def refresh_sources(source_ids: list[str] | None = None) -> list[dict[str, Any]]:
    with RefreshLock():
        return await _refresh_sources_unlocked(source_ids)


async def _refresh_sources_unlocked(source_ids: list[str] | None = None) -> list[dict[str, Any]]:
    selected = list(SOURCES)
    if source_ids:
        selected = [SOURCE_BY_ID[source_id] for source_id in source_ids]

    proxy_info: dict[str, str] = {}
    if fetch_require_proxy() and not fetch_direct_enabled():
        proxy_info = await check_proxy_health()

    client: httpx.AsyncClient | None = None
    if fetch_direct_enabled():
        headers = {
            "User-Agent": user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        }
        timeout = httpx.Timeout(request_timeout_seconds())
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=0)
        client = httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
            limits=limits,
            http2=True,
        )

    use_flaresolverr = "flaresolverr" in [b.lower() for b in fetch_backends()]
    use_patchright = "patchright" in [b.lower() for b in fetch_backends()] or "playwright" in [
        b.lower() for b in fetch_backends()
    ]

    results: list[dict[str, Any]] = []
    fs_session: FlareSolverrSession | None = None
    try:
        if use_patchright and not fetch_direct_enabled():
            await PatchrightPool.get()
        if use_flaresolverr and not fetch_direct_enabled():
            fs_session = FlareSolverrSession()
            await fs_session.__aenter__()
            set_active_flaresolverr_session(fs_session)
        for source in selected:
            status = await fetch_source(client, source)
            if proxy_info and status.get("state") == "ok":
                status["proxy_egress_ip"] = proxy_info.get("egress_ip")
            results.append(status)
            await asyncio.sleep(request_delay_seconds())
    finally:
        if fs_session is not None:
            set_active_flaresolverr_session(None)
            await fs_session.__aexit__(None, None, None)
        if use_patchright and not fetch_direct_enabled():
            await PatchrightPool.shutdown()
        if client is not None:
            await client.aclose()
    return results
