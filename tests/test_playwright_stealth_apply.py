from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.scrapers.playwright_stealth_apply import apply_playwright_stealth


def test_applies_v2_stealth_api_to_page() -> None:
    page = object()
    apply = AsyncMock()
    with patch(
        "app.config.fetch_playwright_stealth_enabled",
        return_value=True,
    ), patch("playwright_stealth.Stealth") as stealth:
        stealth.return_value.apply_stealth_async = apply

        result = asyncio.run(apply_playwright_stealth(page))

    assert result is True
    stealth.assert_called_once_with()
    apply.assert_awaited_once_with(page)


def test_skips_stealth_when_disabled() -> None:
    with patch(
        "app.config.fetch_playwright_stealth_enabled",
        return_value=False,
    ), patch("playwright_stealth.Stealth") as stealth:
        result = asyncio.run(apply_playwright_stealth(object()))

    assert result is False
    stealth.assert_not_called()
