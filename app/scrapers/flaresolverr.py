from __future__ import annotations

import httpx

from ..config import flaresolverr_url, request_timeout_seconds
from ..sources import Source
from .base import FetchResult
from .flaresolverr_session import FlareSolverrSession, flaresolverr_request_timeout_ms
from .proxy import assert_proxy_configured, proxy_dict_for_flaresolverr

# source_id passed via module-level for current fetch (set by fetcher)
_current_source_id: str | None = None


def set_flaresolverr_source(source_id: str | None) -> None:
    global _current_source_id
    _current_source_id = source_id

_active_session: FlareSolverrSession | None = None


def set_active_flaresolverr_session(session: FlareSolverrSession | None) -> None:
    global _active_session
    _active_session = session


async def fetch_via_flaresolverr(source: Source) -> FetchResult:
    assert_proxy_configured()
    payload: dict = {
        "cmd": "request.get",
        "url": source.url,
        "maxTimeout": flaresolverr_request_timeout_ms(),
    }
    if _active_session and _active_session.session_id:
        payload["session"] = _active_session.session_id
    proxy = proxy_dict_for_flaresolverr(_current_source_id)
    if proxy:
        payload["proxy"] = proxy

    timeout = httpx.Timeout(request_timeout_seconds() + 30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(flaresolverr_url(), json=payload)
        response.raise_for_status()
        body = response.json()

    if body.get("status") != "ok":
        message = body.get("message") or str(body)
        raise RuntimeError(f"FlareSolverr error: {message}")

    solution = body.get("solution") or {}
    html = solution.get("response") or ""
    final_url = solution.get("url") or source.url
    status = int(solution.get("status") or 200)
    if not html.strip():
        raise RuntimeError("FlareSolverr returned empty HTML")
    return FetchResult(
        html=html,
        final_url=final_url,
        backend="flaresolverr",
        http_status=status,
    )
