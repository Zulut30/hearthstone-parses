from __future__ import annotations

from ..config import request_timeout_seconds
from ..sources import Source
from .base import FetchResult

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
        title = (await page.title()).lower()
        html = (await page.content()).lower()
        if "just a moment" not in title and "challenges.cloudflare.com" not in html[:8000]:
            return
        await page.wait_for_timeout(3000)


async def _wait_content(page, source: Source, timeout_ms: int) -> None:
    per_selector = max(timeout_ms // len(_selectors_for(source)) // 2, 8000)
    for selector in _selectors_for(source):
        try:
            await page.wait_for_selector(selector, timeout=per_selector, state="attached")
            return
        except Exception:
            continue
    await page.wait_for_timeout(5000)


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

    html = await page.content()
    return FetchResult(html=html, final_url=page.url, backend="patchright", http_status=200)
