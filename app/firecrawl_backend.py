from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, NavigableString

from .config import (
    firecrawl_hsguru_matchups_timeout_ms,
    firecrawl_max_age_ms,
    firecrawl_timeout_ms,
    firecrawl_wait_ms,
    scrape_do_token,
)
from .firecrawl_keys import (
    acquire_firecrawl_key,
    is_firecrawl_credit_error,
    is_firecrawl_pool_unavailable,
    mark_firecrawl_key_exhausted,
    parse_firecrawl_api_keys,
    record_firecrawl_credits,
)
from .scrape_do_backend import scrape_url_sync
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

    @property
    def backend(self) -> str:
        return str(self.metadata.get("backend") or "firecrawl")

    @property
    def firecrawl_credits_used(self) -> int:
        if self.backend != "firecrawl":
            return 0
        try:
            return int(self.metadata.get("creditsUsed") or 1)
        except (TypeError, ValueError):
            return 1

    @property
    def scrape_do_credits_used(self) -> int:
        if not self.backend.startswith("scrape_do"):
            return 0
        try:
            return int(self.metadata.get("scrapeDoCreditsUsed") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def request_credits(self) -> int:
        return self.scrape_do_credits_used or self.firecrawl_credits_used


def _html_to_markdown(html: str) -> str:
    if not html.strip():
        return ""
    soup = BeautifulSoup(html, "lxml")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    for node in soup.find_all("br"):
        node.replace_with(NavigableString("\n"))
    for node in soup.find_all("a"):
        text = node.get_text(" ", strip=True)
        href = str(node.get("href") or "").strip()
        node.replace_with(
            NavigableString(f"[{text}]({href})" if text and href else text)
        )
    for level in range(1, 7):
        for node in soup.find_all(f"h{level}"):
            text = node.get_text(" ", strip=True)
            node.replace_with(NavigableString(f"\n{'#' * level} {text}\n"))
    for node in soup.find_all("li"):
        text = node.get_text(" ", strip=True)
        node.replace_with(NavigableString(f"\n- {text}"))
    for node in soup.find_all("tr"):
        cells = [
            cell.get_text(" ", strip=True)
            for cell in node.find_all(["th", "td"], recursive=False)
        ]
        if cells:
            node.replace_with(NavigableString("\n" + " | ".join(cells)))
    lines = [
        " ".join(line.split())
        for line in soup.get_text("\n").splitlines()
        if line.strip()
    ]
    return "\n".join(lines)


def _screenshot_options(formats: list[Any] | None) -> tuple[bool, bool]:
    for item in formats or []:
        if isinstance(item, dict) and item.get("type") == "screenshot":
            return True, bool(item.get("fullPage"))
    return False, False


def _scrape_via_scrape_do(
    source: Source,
    *,
    formats: list[Any] | None,
    headers: dict[str, str] | None,
    wait_ms: int | None,
    timeout_ms: int | None,
    reason: str,
) -> FirecrawlScrape:
    if not scrape_do_token():
        raise RuntimeError(reason)
    screenshot, full_screenshot = _screenshot_options(formats)
    profiles = (True,) if source.site == "hsguru" else (False, True)
    errors: list[str] = []
    scraped = None
    for super_proxy in profiles:
        try:
            scraped = scrape_url_sync(
                source.url,
                render=True,
                super_proxy=super_proxy,
                headers=headers,
                wait_ms=wait_ms,
                timeout_ms=timeout_ms,
                screenshot=screenshot,
                full_screenshot=full_screenshot,
            )
            break
        except Exception as exc:
            errors.append(
                f"{'super' if super_proxy else 'standard'}: "
                f"{type(exc).__name__}: {str(exc)[:300]}"
            )
    if scraped is None:
        raise RuntimeError(
            f"{reason}; Scrape.do fallback failed: {'; '.join(errors)}"
        )
    html = scraped.html
    requested = formats or ["html", "markdown"]
    markdown = _html_to_markdown(html) if "markdown" in requested else ""
    return FirecrawlScrape(
        html=html,
        markdown=markdown,
        screenshot=scraped.screenshot,
        metadata={
            "backend": (
                "scrape_do_super" if scraped.super_proxy else "scrape_do"
            ),
            "creditsUsed": 0,
            "scrapeDoCreditsUsed": scraped.request_cost,
            "scrapeDoRemainingCredits": scraped.credits_remaining,
            "firecrawlFallbackReason": reason[:500],
        },
        status_code=scraped.status_code,
        final_url=scraped.final_url,
    )


def _scrape_once(
    source: Source,
    *,
    api_key: str,
    formats: list[Any] | None = None,
    only_main_content: bool = True,
    headers: dict[str, str] | None = None,
    max_age_ms: int | None = None,
    wait_ms: int | None = None,
    timeout_ms: int | None = None,
) -> FirecrawlScrape:
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
    try:
        with urllib.request.urlopen(request, timeout=(effective_timeout_ms / 1000) + 30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Firecrawl HTTP {exc.code}: {detail[:500]}") from exc

    if not body.get("success"):
        raise RuntimeError(f"Firecrawl scrape failed: {body}")

    data = body.get("data") or {}
    html = data.get("html") or ""
    if not html and any(fmt == "html" for fmt in (formats or ["html", "markdown"])):
        raise RuntimeError("Firecrawl response did not include html")
    metadata = dict(data.get("metadata") or {})
    metadata.setdefault("backend", "firecrawl")
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
    errors: list[str] = []
    attempt_limit = max(8, len(parse_firecrawl_api_keys()))
    for _ in range(attempt_limit):
        try:
            lease = acquire_firecrawl_key()
        except Exception as exc:
            if is_firecrawl_pool_unavailable(exc):
                return _scrape_via_scrape_do(
                    source,
                    formats=formats,
                    headers=headers,
                    wait_ms=wait_ms,
                    timeout_ms=timeout_ms,
                    reason=str(exc),
                )
            raise
        try:
            scraped = _scrape_once(
                source,
                api_key=lease.key.key,
                formats=formats,
                only_main_content=only_main_content,
                headers=headers,
                max_age_ms=max_age_ms,
                wait_ms=wait_ms,
                timeout_ms=timeout_ms,
            )
        except Exception as exc:
            if is_firecrawl_credit_error(exc):
                mark_firecrawl_key_exhausted(lease.key.label, reason=str(exc))
                errors.append(f"{lease.key.label}: {exc}")
                continue
            raise

        credits = scraped.metadata.get("creditsUsed")
        try:
            credits_int = int(credits) if credits is not None else 1
        except (TypeError, ValueError):
            credits_int = 1
        rotation = record_firecrawl_credits(lease.key.label, credits_int)
        metadata = dict(scraped.metadata)
        metadata["firecrawl_key_label"] = lease.key.label
        metadata["firecrawl_key_fingerprint"] = lease.key.fingerprint
        metadata["firecrawl_key_rotation"] = rotation
        return FirecrawlScrape(
            html=scraped.html,
            markdown=scraped.markdown,
            screenshot=scraped.screenshot,
            metadata=metadata,
            status_code=scraped.status_code,
            final_url=scraped.final_url,
        )

    detail = "; ".join(errors) if errors else "no available keys"
    reason = f"Firecrawl scrape failed after key rotation attempts: {detail}"
    return _scrape_via_scrape_do(
        source,
        formats=formats,
        headers=headers,
        wait_ms=wait_ms,
        timeout_ms=timeout_ms,
        reason=reason,
    )


async def scrape_source(source: Source) -> FirecrawlScrape:
    if source.site == "hsguru" and source.category == "matchups":
        return await asyncio.to_thread(
            _scrape_sync,
            source,
            timeout_ms=firecrawl_hsguru_matchups_timeout_ms(),
        )
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
