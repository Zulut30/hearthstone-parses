from __future__ import annotations

import asyncio
from typing import ClassVar

from ..sources import Source
from .base import FetchResult
from .navigation import navigate_page
from .proxy import playwright_proxy


class PatchrightPool:
    _instance: ClassVar[PatchrightPool | None] = None
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._started = False

    @classmethod
    async def get(cls) -> PatchrightPool:
        async with cls._lock:
            if cls._instance is None:
                cls._instance = PatchrightPool()
            if not cls._instance._started:
                await cls._instance.start()
            return cls._instance

    @classmethod
    async def shutdown(cls) -> None:
        async with cls._lock:
            if cls._instance is not None:
                await cls._instance.stop()
                cls._instance = None

    async def start(self) -> None:
        from patchright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._started = True

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._started = False

    async def fetch(self, source: Source) -> FetchResult:
        if self._browser is None:
            raise RuntimeError("PatchrightPool is not started")
        proxy = playwright_proxy(source.id)
        context_kwargs: dict = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "viewport": {"width": 1440, "height": 900},
        }
        if proxy:
            context_kwargs["proxy"] = proxy
        context = await self._browser.new_context(**context_kwargs)
        page = await context.new_page()
        try:
            return await navigate_page(page, source)
        finally:
            await context.close()
