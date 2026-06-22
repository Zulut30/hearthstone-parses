from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from .config import (
    api_json_attempts_per_channel,
    api_json_retry_delay_seconds,
    flaresolverr_url,
    hsreplay_json_channels,
    hsreplay_markdown_channels,
    request_timeout_seconds,
    user_agent,
)
from .hsreplay_auth import hsreplay_cookies_for_fetch
from .refresh_context import get_cached_hsreplay_json, set_cached_hsreplay_json
from .refresh_log import log_action
from .proxy_errors import ProxyPaymentRequiredError
from .scrapers.proxy import assert_proxy_configured, httpx_client_kwargs, proxy_url_for_source

logger = logging.getLogger(__name__)

JINA_PREFIX = "https://r.jina.ai/"


def jina_url(url: str) -> str:
    return JINA_PREFIX + url


def extract_json_payload(body: str) -> dict[str, Any] | list[Any] | None:
    text = body.strip()
    marker = "Markdown Content:\n"
    if marker in text:
        text = text.split(marker, 1)[1].strip()
    start = text.find("{")
    if start < 0:
        start = text.find("[")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text, start)
        return value
    except json.JSONDecodeError:
        return None


def _http_error_is_407(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 407:
        return True
    return "407" in str(exc)


async def download_text(url: str, source_id: str | None = None) -> str:
    headers = {"User-Agent": user_agent(), "Accept": "application/json,text/plain,*/*"}
    kwargs = httpx_client_kwargs(source_id, timeout=request_timeout_seconds())
    attempts = api_json_attempts_per_channel()
    delay = api_json_retry_delay_seconds()
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        log_action(
            "http.request.begin",
            source_id=source_id,
            url=url,
            attempt=attempt,
            extra={"via": "proxy" if kwargs.get("proxy") else "direct"},
        )
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(headers=headers, **kwargs) as client:
                response = await client.get(url)
                if response.status_code == 407:
                    raise ProxyPaymentRequiredError(
                        f"Proxy payment required (407) for {url[:120]}"
                    )
                response.raise_for_status()
                log_action(
                    "http.request.ok",
                    source_id=source_id,
                    url=url,
                    http_status=response.status_code,
                    bytes_out=len(response.content),
                    duration_ms=(time.monotonic() - started) * 1000,
                    attempt=attempt,
                )
                return response.text
        except ProxyPaymentRequiredError:
            raise
        except Exception as exc:
            last_exc = exc
            if _http_error_is_407(exc):
                raise ProxyPaymentRequiredError(str(exc)) from exc
            log_action(
                "http.request.fail",
                source_id=source_id,
                url=url,
                error_type=type(exc).__name__,
                detail=str(exc)[:1000],
                level="warn" if attempt < attempts else "error",
                attempt=attempt,
            )
            if attempt < attempts:
                await asyncio.sleep(delay * attempt)
    assert last_exc is not None
    raise last_exc


def _fetch_text_via_curl_cffi_sync(url: str, source_id: str | None) -> str:
    from curl_cffi import requests as curl_requests

    assert_proxy_configured()
    proxy_url = proxy_url_for_source(source_id)
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    response = curl_requests.get(
        url,
        impersonate="chrome131",
        proxies=proxies,
        timeout=request_timeout_seconds(),
        allow_redirects=True,
        headers={"Accept": "application/json,text/plain,*/*"},
    )
    if response.status_code == 407:
        raise ProxyPaymentRequiredError(f"Proxy payment required (407) for {url[:120]}")
    if response.status_code >= 400:
        response.raise_for_status()
    return response.text


async def fetch_text_via_curl_cffi(url: str, *, source_id: str | None = None) -> str:
    return await asyncio.to_thread(_fetch_text_via_curl_cffi_sync, url, source_id)


async def fetch_text_via_flaresolverr(url: str, *, source_id: str | None = None) -> str:
    from .scrapers.proxy import proxy_dict_for_flaresolverr

    payload: dict[str, Any] = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": int(request_timeout_seconds() * 1000),
    }
    proxy = proxy_dict_for_flaresolverr(source_id, page_url=url)
    if proxy:
        payload["proxy"] = proxy
    cookies = hsreplay_cookies_for_fetch()
    if cookies:
        payload["cookies"] = cookies

    timeout = httpx.Timeout(request_timeout_seconds() + 30.0)
    started = time.monotonic()
    log_action(
        "http.request.begin",
        source_id=source_id,
        url=url,
        extra={"via": "flaresolverr"},
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(flaresolverr_url(), json=payload)
        response.raise_for_status()
        body = response.json()

    if body.get("status") != "ok":
        message = body.get("message") or str(body)
        raise RuntimeError(f"FlareSolverr error: {message}")

    solution = body.get("solution") or {}
    text = solution.get("response") or ""
    status = int(solution.get("status") or 0)
    if status == 407:
        raise ProxyPaymentRequiredError(f"FlareSolverr proxy 407 for {url[:120]}")
    if not text.strip():
        raise RuntimeError("FlareSolverr returned empty response")
    log_action(
        "http.request.ok",
        source_id=source_id,
        url=url,
        http_status=status or 200,
        bytes_out=len(text.encode("utf-8", errors="replace")),
        duration_ms=(time.monotonic() - started) * 1000,
        backend="flaresolverr",
    )
    return text


def _channel_urls_for_labels(api_url: str, labels: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for label in labels:
        if label == "direct":
            out.append(("direct", api_url))
        elif label == "jina":
            out.append(("jina", jina_url(api_url)))
        elif label == "flaresolverr":
            out.append(("flaresolverr", api_url))
        elif label == "curl_cffi":
            out.append(("curl_cffi", api_url))
    return out


def _channel_urls(api_url: str) -> list[tuple[str, str]]:
    out = _channel_urls_for_labels(api_url, hsreplay_json_channels())
    if not out:
        out = _channel_urls_for_labels(api_url, ["flaresolverr", "curl_cffi"])
    return out


def _markdown_channel_urls(page_url: str) -> list[tuple[str, str]]:
    out = _channel_urls_for_labels(page_url, hsreplay_markdown_channels())
    if not out:
        out = _channel_urls_for_labels(page_url, ["flaresolverr", "curl_cffi"])
    return out


async def _fetch_body_for_channel(
    label: str,
    fetch_url: str,
    *,
    source_id: str,
) -> str:
    if label == "flaresolverr":
        return await fetch_text_via_flaresolverr(fetch_url, source_id=source_id)
    if label == "curl_cffi":
        try:
            return await fetch_text_via_curl_cffi(fetch_url, source_id=source_id)
        except ImportError as exc:
            raise RuntimeError("curl_cffi not installed") from exc
    return await download_text(fetch_url, source_id=source_id)


def _payload_to_dict(payload: dict[str, Any] | list[Any]) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"data": payload}
    return payload


async def fetch_hsreplay_json(
    api_url: str,
    *,
    source_id: str,
    cache_key: str | None = None,
) -> dict[str, Any]:
    """Fetch HSReplay JSON API via configured channels with retries and per-run cache."""
    key = cache_key or api_url
    cached = get_cached_hsreplay_json(key)
    if cached is not None:
        log_action(
            "api.route.ok",
            source_id=source_id,
            backend="hsreplay_cache",
            extra={"channel": "cache", "api_url": api_url},
        )
        return cached

    errors: list[str] = []
    channels = _channel_urls(api_url)

    for label, fetch_url in channels:
        try:
            body = await _fetch_body_for_channel(label, fetch_url, source_id=source_id)
            payload = extract_json_payload(body)
            if isinstance(payload, (dict, list)):
                result = _payload_to_dict(payload)
                log_action(
                    "api.route.ok",
                    source_id=source_id,
                    backend=f"hsreplay_{label}",
                    bytes_out=len(body.encode("utf-8", errors="replace")),
                    extra={"channel": label, "api_url": api_url},
                )
                set_cached_hsreplay_json(key, result)
                return result
            err = f"{label}: payload is not JSON object"
            errors.append(err)
            log_action(
                "api.route.fail",
                source_id=source_id,
                detail=err,
                level="warn",
                extra={"channel": label},
            )
        except ProxyPaymentRequiredError:
            raise
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            logger.warning("HSReplay JSON fetch %s failed for %s: %s", label, api_url, exc)
        await asyncio.sleep(api_json_retry_delay_seconds())

    detail = "Could not fetch HSReplay JSON: " + "; ".join(errors)
    log_action("api.route.fail", source_id=source_id, detail=detail, level="error")
    raise RuntimeError(detail)


def _is_bg_comps_listing_url(page_url: str) -> bool:
    normalized = page_url.rstrip("/")
    return normalized.endswith("hsreplay.net/battlegrounds/comps") or normalized.endswith(
        "/battlegrounds/comps"
    )


def _markdown_body_usable(body: str, page_url: str) -> bool:
    """Reject FlareSolverr listing HTML; accept Jina markdown or comp detail pages."""
    if not body:
        return False
    lower = body.lower()
    if "just a moment" in lower or "cf-chl" in lower:
        return False
    if "Markdown Content:" in body:
        return len(body) >= 200
    try:
        from .battlegrounds_comps_parse import _find_comp_headers

        header_count = len(_find_comp_headers(body))
        if _is_bg_comps_listing_url(page_url):
            return header_count >= 3
        if header_count >= 1:
            return True
    except Exception:
        pass
    if "hearthstonejson.com" in lower or "battlegrounds/minions/" in lower:
        return len(body) >= 200
    return len(body) >= 400


async def fetch_hsreplay_markdown(url: str, *, source_id: str) -> tuple[str, str]:
    """Return (body, backend label e.g. hsreplay_jina)."""
    errors: list[str] = []
    for label, fetch_url in _markdown_channel_urls(url):
        try:
            if label == "flaresolverr":
                body = await fetch_text_via_flaresolverr(fetch_url, source_id=source_id)
            elif label == "curl_cffi":
                body = await fetch_text_via_curl_cffi(fetch_url, source_id=source_id)
            else:
                body = await download_text(fetch_url, source_id=source_id)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            await asyncio.sleep(api_json_retry_delay_seconds())
            continue
        if _markdown_body_usable(body, url):
            return body, f"hsreplay_{label}"
        errors.append(f"{label}: body not usable markdown ({len(body)} bytes)")
        await asyncio.sleep(api_json_retry_delay_seconds())
    raise RuntimeError("Could not fetch HSReplay markdown: " + "; ".join(errors))


async def fetch_hsreplay_html(url: str, *, source_id: str) -> tuple[str, str]:
    """Rendered HTML for HSReplay pages (FlareSolverr first)."""
    errors: list[str] = []
    order = [("flaresolverr", url), ("curl_cffi", url)]
    for label, fetch_url in order:
        try:
            if label == "flaresolverr":
                body = await fetch_text_via_flaresolverr(fetch_url, source_id=source_id)
            else:
                body = await fetch_text_via_curl_cffi(fetch_url, source_id=source_id)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            continue
        if len(body) > 5000 and "just a moment" not in body.lower():
            return body, f"hsreplay_{label}"
        errors.append(f"{label}: html too short")
    raise RuntimeError("Could not fetch HSReplay HTML: " + "; ".join(errors))
