from __future__ import annotations

import asyncio
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


def _scrape_sync(
    url: str,
    *,
    render: bool = True,
    super_proxy: bool = False,
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
    endpoint = f"{SCRAPE_DO_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        endpoint,
        headers={"User-Agent": "HSDataAPI/0.1 HSGuru collector"},
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=scrape_do_timeout_seconds(),
        ) as response:
            raw = response.read()
            headers = {key.lower(): value for key, value in response.headers.items()}
            status_code = int(response.status)
            final_url = str(headers.get("scrape.do-final-url") or url)
    except urllib.error.HTTPError as exc:
        # Do not include exc.url: Scrape.do puts the secret token in it.
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Scrape.do HTTP {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Scrape.do transport error: {exc.reason}") from exc
    html = raw.decode("utf-8", errors="replace")
    if not html.strip():
        raise RuntimeError("Scrape.do returned an empty body")
    request_cost = _header_int(headers, "scrape.do-request-cost")
    if request_cost is None:
        request_cost = 25 if render and super_proxy else 10 if super_proxy else 5 if render else 1
    return ScrapeDoScrape(
        html=html,
        status_code=status_code,
        final_url=final_url,
        request_cost=request_cost,
        credits_remaining=_header_int(headers, "scrape.do-remaining-credits"),
        super_proxy=super_proxy,
    )


async def scrape_url(
    url: str,
    *,
    render: bool = True,
    super_proxy: bool = False,
) -> ScrapeDoScrape:
    return await asyncio.to_thread(
        _scrape_sync,
        url,
        render=render,
        super_proxy=super_proxy,
    )
