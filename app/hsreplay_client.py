from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from .config import request_timeout_seconds, user_agent
from .scrapers.proxy import proxy_url_for_source

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


async def download_text(url: str, source_id: str | None = None) -> str:
    proxy = proxy_url_for_source(source_id)
    timeout = request_timeout_seconds()
    headers = {"User-Agent": user_agent(), "Accept": "application/json,text/plain,*/*"}
    async with httpx.AsyncClient(
        proxy=proxy,
        timeout=timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def fetch_hsreplay_json(
    api_url: str,
    *,
    source_id: str,
    cache_key: str | None = None,
) -> dict[str, Any]:
    """Fetch HSReplay JSON API (direct, then Jina reader fallback)."""
    errors: list[str] = []
    sources = [
        ("direct", api_url),
        ("jina", jina_url(api_url)),
    ]

    for label, fetch_url in sources:
        try:
            body = await download_text(fetch_url, source_id=source_id)
            payload = extract_json_payload(body)
            if isinstance(payload, dict):
                return payload
            if isinstance(payload, list):
                return {"data": payload}
            errors.append(f"{label}: payload is not JSON object")
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            logger.warning("HSReplay JSON fetch %s failed for %s: %s", label, api_url, exc)

    raise RuntimeError("Could not fetch HSReplay JSON: " + "; ".join(errors))


async def fetch_hsreplay_markdown(url: str, *, source_id: str) -> str:
    errors: list[str] = []
    for label, fetch_url in (("direct", url), ("jina", jina_url(url))):
        try:
            body = await download_text(fetch_url, source_id=source_id)
            if "Markdown Content:" in body or len(body) > 500:
                return body
            errors.append(f"{label}: body too short")
        except Exception as exc:
            errors.append(f"{label}: {exc}")
    raise RuntimeError("Could not fetch HSReplay markdown: " + "; ".join(errors))
