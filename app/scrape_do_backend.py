from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Mapping

from .config import scrape_do_timeout_seconds, scrape_do_token


SCRAPE_DO_URL = "https://api.scrape.do/"


@dataclass(frozen=True)
class ScrapeDoScrape:
    html: str
    status_code: int
    final_url: str
    request_cost: int
    credits_remaining: int | None
    super_proxy: bool
    screenshot: str | None = None

    @property
    def content_length(self) -> int:
        return len(self.html.encode("utf-8", errors="replace"))


def _header_int(headers: Mapping[str, str], name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def scrape_url_sync(
    url: str,
    *,
    render: bool = True,
    super_proxy: bool = False,
    headers: Mapping[str, str] | None = None,
    wait_ms: int | None = None,
    timeout_ms: int | None = None,
    screenshot: bool = False,
    full_screenshot: bool = False,
) -> ScrapeDoScrape:
    token = scrape_do_token()
    if not token:
        raise RuntimeError("Scrape.do token is not configured")
    params = {
        'token': token,
        'url': url,
        'render': str(bool(render)).lower(),
        **({'super': 'true'} if super_proxy else {}),
    }
    if headers:
        params["forwardHeaders"] = "true"
    if wait_ms is not None and render:
        params["customWait"] = str(max(0, int(wait_ms)))
    if timeout_ms is not None:
        params["timeout"] = str(max(1_000, int(timeout_ms)))
    if screenshot:
        params["returnJSON"] = "true"
        params["fullScreenShot" if full_screenshot else "screenShot"] = "true"
    endpoint = f"{SCRAPE_DO_URL}?{urllib.parse.urlencode(params)}"
    request_headers = dict(headers or {})
    request_headers.setdefault("User-Agent", "HSDataAPI/0.1 Scrape.do fallback")
    request = urllib.request.Request(
        endpoint,
        headers=request_headers,
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=scrape_do_timeout_seconds(),
        ) as response:
            raw = response.read()
            response_headers = {
                key.lower(): value for key, value in response.headers.items()
            }
            status_code = int(response.status)
            final_url = str(
                response_headers.get("scrape.do-resolved-url")
                or response_headers.get("scrape.do-final-url")
                or url
            )
    except urllib.error.HTTPError as exc:
        # Do not include exc.url: Scrape.do puts the secret token in it.
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Scrape.do HTTP {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Scrape.do transport error: {exc.reason}") from exc
    body = raw.decode("utf-8", errors="replace")
    image: str | None = None
    html = body
    if screenshot:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Scrape.do screenshot response is not valid JSON") from exc
        shots = payload.get("screenShots") if isinstance(payload, dict) else None
        if isinstance(shots, list) and shots and isinstance(shots[0], dict):
            value = shots[0].get("image")
            image = str(value) if value else None
        content = payload.get("content") if isinstance(payload, dict) else None
        html = str(content) if isinstance(content, str) else ""
        if not image:
            raise RuntimeError("Scrape.do screenshot response did not include an image")
    if not html.strip() and not image:
        raise RuntimeError("Scrape.do returned an empty body")
    request_cost = _header_int(response_headers, "scrape.do-request-cost")
    if request_cost is None:
        request_cost = 25 if render and super_proxy else 10 if super_proxy else 5 if render else 1
    return ScrapeDoScrape(
        html=html,
        status_code=status_code,
        final_url=final_url,
        request_cost=request_cost,
        credits_remaining=_header_int(
            response_headers,
            "scrape.do-remaining-credits",
        ),
        super_proxy=super_proxy,
        screenshot=image,
    )


async def scrape_url(
    url: str,
    *,
    render: bool = True,
    super_proxy: bool = False,
    headers: Mapping[str, str] | None = None,
    wait_ms: int | None = None,
    timeout_ms: int | None = None,
    screenshot: bool = False,
    full_screenshot: bool = False,
) -> ScrapeDoScrape:
    return await asyncio.to_thread(
        scrape_url_sync,
        url,
        render=render,
        super_proxy=super_proxy,
        headers=headers,
        wait_ms=wait_ms,
        timeout_ms=timeout_ms,
        screenshot=screenshot,
        full_screenshot=full_screenshot,
    )
