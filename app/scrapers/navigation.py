from __future__ import annotations

import json
import logging
from typing import Any

from ..config import request_timeout_seconds
from ..sources import Source
from .base import FetchResult
from .hsreplay_snapshot import capture_hsreplay_snapshot

logger = logging.getLogger(__name__)

SITE_SELECTORS: dict[str, list[str]] = {
    "hsguru:meta": ["table tbody tr", "table tr"],
    "hsguru:streamer_decks": ["table tbody tr", "table tr"],
    "hsguru:matchups": ["table tbody tr", "table tr", "canvas"],
    "hsreplay:battlegrounds": ["script#userdata", "#react-root"],
    "hsreplay:arena": ["script#userdata", "#react-root"],
    "hsreplay:ranked": ["script#userdata", "#react-root", 'a[href*="/cards/"]'],
}


def _selectors_for(source: Source) -> list[str]:
    key = f"{source.site}:{source.category}"
    return SITE_SELECTORS.get(key, ["script#userdata", "table", "#react-root"])


def _capture_api_response(url: str) -> bool:
    lower = url.lower()
    if "hsreplay.net" not in lower:
        return False
    if "card_list" in lower or "/analytics/query/" in lower:
        return True
    return "/api/" in lower and any(h in lower for h in ("card", "analytics", "stats", "meta"))


async def _wait_cloudflare(page, timeout_ms: int) -> None:
    loops = max(timeout_ms // 3000, 5)
    for _ in range(loops):
        try:
            title = (await page.title()).lower()
        except Exception:
            title = ""

        if "just a moment" not in title and "attention required" not in title:
            url = page.url.lower()
            if "challenges.cloudflare.com" not in url:
                return

        try:
            html = (await page.content()).lower()
            if "just a moment" not in html and "challenges.cloudflare.com" not in html[:8000]:
                return
        except Exception:
            pass
        await page.wait_for_timeout(3000)


async def _wait_content(page, source: Source, timeout_ms: int) -> None:
    per_selector = min(max(timeout_ms // len(_selectors_for(source)) // 2, 8000), 15000)
    for selector in _selectors_for(source):
        try:
            await page.wait_for_selector(selector, timeout=per_selector, state="attached")
            return
        except Exception:
            continue
    await page.wait_for_timeout(3000)


async def _apply_cards_filters(page, source: Source) -> None:
    if "rankrange=gold" not in (source.fragment or "").lower():
        return
    for label in ("Gold", "GOLD", "Золото"):
        try:
            await page.click(f"text={label}", timeout=3000)
            await page.wait_for_timeout(2000)
            return
        except Exception:
            continue


async def navigate_page(page, source: Source) -> FetchResult:
    timeout_ms = int(request_timeout_seconds() * 1000)
    target_url = source.url if source.fragment else source.fetch_url
    api_payloads: list[tuple[str, Any]] = []

    async def on_response(response) -> None:
        if response.status != 200 or not _capture_api_response(response.url):
            return
        try:
            body = await response.json()
        except Exception:
            try:
                body = json.loads(await response.text())
            except Exception:
                return
        if isinstance(body, (dict, list)):
            api_payloads.append((response.url, body))

    if source.id.startswith("hsreplay_cards_"):
        page.on("response", on_response)

    wait_until = "commit" if source.id.startswith("hsreplay_cards_") else "domcontentloaded"
    try:
        await page.goto(target_url, wait_until=wait_until, timeout=timeout_ms)
    except Exception:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)

    await _wait_cloudflare(page, timeout_ms)
    await _wait_content(page, source, timeout_ms)

    if source.fragment and "#" not in page.url:
        await page.evaluate(
            "(hash) => { window.location.hash = hash; }",
            f"#{source.fragment}",
        )
        await page.wait_for_timeout(4000)
        await _wait_cloudflare(page, min(timeout_ms, 90000))
        await _wait_content(page, source, min(timeout_ms, 90000))

    if source.id.startswith("hsreplay_cards_"):
        await _apply_cards_filters(page, source)
        await page.wait_for_timeout(3000)

    try:
        await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 60000))
    except Exception:
        await page.wait_for_timeout(4000)

    if source.id.startswith("hsreplay_cards_") and not any(
        "card_list" in url for url, _ in api_payloads
    ):
        from ..hsreplay_cards_api import _analytics_card_list_url

        api_url = _analytics_card_list_url(source)
        try:
            payload = await page.evaluate(
                """async (url) => {
                    const r = await fetch(url, { credentials: 'include', headers: { Accept: 'application/json' } });
                    if (!r.ok) return null;
                    return await r.json();
                }""",
                api_url,
            )
            if isinstance(payload, dict):
                api_payloads.append((api_url, payload))
        except Exception as exc:
            logger.warning("direct card_list fetch failed: %s", exc)

    snapshot = await capture_hsreplay_snapshot(page, source)
    html = await page.content()
    return FetchResult(
        html=html,
        final_url=page.url,
        backend="patchright",
        http_status=200,
        snapshot=snapshot or None,
        api_payloads=tuple(api_payloads),
    )
