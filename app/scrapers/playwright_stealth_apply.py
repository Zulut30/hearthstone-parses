from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)
_applied_once = False


async def apply_playwright_stealth(page: Any) -> bool:
    """Apply puppeteer-extra stealth patches to a Playwright/Patchright page."""
    from ..config import fetch_playwright_stealth_enabled

    global _applied_once
    if not fetch_playwright_stealth_enabled():
        return False
    try:
        from playwright_stealth import stealth_async
    except ImportError:
        if not _applied_once:
            logger.info("playwright-stealth not installed; skip stealth patches")
            _applied_once = True
        return False

    await stealth_async(page)
    return True
