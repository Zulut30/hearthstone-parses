from __future__ import annotations

from ..config import request_timeout_seconds
from ..sources import Source
from .base import FetchResult
from .hsreplay_snapshot import capture_hsreplay_snapshot

SITE_SELECTORS: dict[str, list[str]] = {
    "hsguru:meta": ["table tbody tr", "table tr"],
    "hsguru:streamer_decks": ["table tbody tr", "table tr"],
    "hsguru:matchups": ["table tbody tr", "table tr", "canvas"],
    "hsreplay:battlegrounds": ["script#userdata", "#react-root"],
    "hsreplay:arena": ["script#userdata", "#react-root"],
    "hsreplay:ranked": ["script#userdata", "#react-root"],
}


def _selectors_for(source: Source) -> list[str]:
    key = f"{source.site}:{source.category}"
    return SITE_SELECTORS.get(key, ["script#userdata", "table", "#react-root"])


async def _wait_cloudflare(page, timeout_ms: int) -> None:
    loops = max(timeout_ms // 3000, 5)
    for _ in range(loops):
        try:
            title = (await page.title()).lower()
        except Exception:
            title = ""
        
        # Avoid heavy page.content() if title and URL don't look like Cloudflare
        if "just a moment" not in title and "attention required" not in title:
            url = page.url.lower()
            if "challenges.cloudflare.com" not in url:
                return
        
        # If we suspect Cloudflare, do a more thorough check
        try:
            html = (await page.content()).lower()
            if "just a moment" not in html and "challenges.cloudflare.com" not in html[:8000]:
                return
        except Exception:
            pass
        await page.wait_for_timeout(3000)


async def _wait_content(page, source: Source, timeout_ms: int) -> None:
    # Cap selector timeout to 15 seconds to avoid huge delays when selectors don't match
    per_selector = min(max(timeout_ms // len(_selectors_for(source)) // 2, 8000), 15000)
    for selector in _selectors_for(source):
        try:
            await page.wait_for_selector(selector, timeout=per_selector, state="attached")
            return
        except Exception:
            continue
    await page.wait_for_timeout(3000)


async def navigate_page(page, source: Source) -> FetchResult:
    timeout_ms = int(request_timeout_seconds() * 1000)
    target_url = source.url if source.fragment else source.fetch_url

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

    try:
        await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 60000))
    except Exception:
        await page.wait_for_timeout(4000)

    snapshot = await capture_hsreplay_snapshot(page, source)
    html = await page.content()
    return FetchResult(
        html=html,
        final_url=page.url,
        backend="patchright",
        http_status=200,
        snapshot=snapshot or None,
    )
