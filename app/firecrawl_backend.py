from __future__ import annotations

import asyncio
import json
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import (
    firecrawl_api_key,
    firecrawl_max_age_ms,
    firecrawl_timeout_ms,
    firecrawl_wait_ms,
)
from .sources import Source


FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v2/scrape"


@dataclass(frozen=True)
class FirecrawlScrape:
    html: str
    markdown: str
    screenshot: str | None
    metadata: dict[str, Any]
    status_code: int
    final_url: str

    @property
    def content_length(self) -> int:
        return len(self.html.encode("utf-8", errors="replace"))


def _scrape_sync(
    source: Source,
    *,
    formats: list[Any] | None = None,
    only_main_content: bool = True,
    headers: dict[str, str] | None = None,
    max_age_ms: int | None = None,
    wait_ms: int | None = None,
    timeout_ms: int | None = None,
) -> FirecrawlScrape:
    api_key = firecrawl_api_key()
    if not api_key:
        raise RuntimeError("FIRECRAWL_API_KEY/HS_FIRECRAWL_API_KEY is not configured")

    effective_timeout_ms = firecrawl_timeout_ms() if timeout_ms is None else timeout_ms
    payload = {
        "url": source.url,
        "formats": formats or ["html", "markdown"],
        "onlyMainContent": only_main_content,
        "maxAge": firecrawl_max_age_ms() if max_age_ms is None else max_age_ms,
        "waitFor": firecrawl_wait_ms() if wait_ms is None else wait_ms,
        "timeout": effective_timeout_ms,
    }
    if headers:
        payload["headers"] = headers
    request = urllib.request.Request(
        FIRECRAWL_SCRAPE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=(effective_timeout_ms / 1000) + 30) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("success"):
        raise RuntimeError(f"Firecrawl scrape failed: {body}")

    data = body.get("data") or {}
    html = data.get("html") or ""
    if not html and any(fmt == "html" for fmt in (formats or ["html", "markdown"])):
        raise RuntimeError("Firecrawl response did not include html")
    metadata = dict(data.get("metadata") or {})
    if body.get("creditsUsed") is not None and metadata.get("creditsUsed") is None:
        metadata["creditsUsed"] = body.get("creditsUsed")
    return FirecrawlScrape(
        html=html,
        markdown=data.get("markdown") or "",
        screenshot=data.get("screenshot"),
        metadata=metadata,
        status_code=int(metadata.get("statusCode") or 200),
        final_url=str(metadata.get("ogUrl") or metadata.get("sourceURL") or source.fetch_url),
    )


async def scrape_source(source: Source) -> FirecrawlScrape:
    return await asyncio.to_thread(_scrape_sync, source)


async def scrape_source_with_options(
    source: Source,
    *,
    formats: list[Any] | None = None,
    only_main_content: bool = True,
    headers: dict[str, str] | None = None,
    max_age_ms: int | None = None,
    wait_ms: int | None = None,
    timeout_ms: int | None = None,
) -> FirecrawlScrape:
    return await asyncio.to_thread(
        _scrape_sync,
        source,
        formats=formats,
        only_main_content=only_main_content,
        headers=headers,
        max_age_ms=max_age_ms,
        wait_ms=wait_ms,
        timeout_ms=timeout_ms,
    )
