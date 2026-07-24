from __future__ import annotations

from unittest.mock import patch

import pytest

from app.firecrawl_backend import _scrape_sync
from app.scrape_do_backend import ScrapeDoScrape
from app.sources import Source


SOURCE = Source(
    id="fallback_test",
    url="https://example.com/page",
    site="example",
    category="test",
)


def scrape_do_result(
    *,
    html: str = "<html><body><a href='/deck/1'>Deck</a></body></html>",
    screenshot: str | None = None,
) -> ScrapeDoScrape:
    return ScrapeDoScrape(
        html=html,
        status_code=200,
        final_url=SOURCE.url,
        request_cost=5,
        credits_remaining=249_995,
        super_proxy=False,
        screenshot=screenshot,
    )


def test_exhausted_firecrawl_pool_falls_back_to_scrape_do() -> None:
    with (
        patch(
            "app.firecrawl_backend.acquire_firecrawl_key",
            side_effect=RuntimeError("All Firecrawl API keys are exhausted"),
        ),
        patch("app.firecrawl_backend.scrape_do_token", return_value="configured"),
        patch(
            "app.firecrawl_backend.scrape_url_sync",
            return_value=scrape_do_result(),
        ) as fallback,
    ):
        result = _scrape_sync(
            SOURCE,
            formats=["html", "markdown"],
            wait_ms=5_000,
            timeout_ms=30_000,
        )

    assert result.backend == "scrape_do"
    assert result.firecrawl_credits_used == 0
    assert result.scrape_do_credits_used == 5
    assert result.request_credits == 5
    assert "[Deck](/deck/1)" in result.markdown
    fallback.assert_called_once()
    assert fallback.call_args.kwargs["wait_ms"] == 5_000
    assert fallback.call_args.kwargs["timeout_ms"] == 30_000


def test_screenshot_request_is_preserved_during_scrape_do_fallback() -> None:
    with (
        patch(
            "app.firecrawl_backend.acquire_firecrawl_key",
            side_effect=RuntimeError("All Firecrawl API keys are exhausted"),
        ),
        patch("app.firecrawl_backend.scrape_do_token", return_value="configured"),
        patch(
            "app.firecrawl_backend.scrape_url_sync",
            return_value=scrape_do_result(html="", screenshot="base64-image"),
        ) as fallback,
    ):
        result = _scrape_sync(
            SOURCE,
            formats=["markdown", {"type": "screenshot", "fullPage": True}],
        )

    assert result.backend == "scrape_do"
    assert result.screenshot == "base64-image"
    assert fallback.call_args.kwargs["screenshot"] is True
    assert fallback.call_args.kwargs["full_screenshot"] is True


def test_non_credit_firecrawl_error_does_not_switch_provider() -> None:
    lease = type(
        "Lease",
        (),
        {
            "key": type(
                "Key",
                (),
                {
                    "key": "fc-test",
                    "label": "primary",
                    "fingerprint": "fc-test…test",
                },
            )()
        },
    )()
    with (
        patch("app.firecrawl_backend.acquire_firecrawl_key", return_value=lease),
        patch(
            "app.firecrawl_backend._scrape_once",
            side_effect=RuntimeError("target timed out"),
        ),
        patch("app.firecrawl_backend.scrape_url_sync") as fallback,
    ):
        with pytest.raises(RuntimeError, match="target timed out"):
            _scrape_sync(SOURCE)

    fallback.assert_not_called()


def test_exhausted_pool_without_scrape_do_keeps_explicit_error() -> None:
    with (
        patch(
            "app.firecrawl_backend.acquire_firecrawl_key",
            side_effect=RuntimeError("All Firecrawl API keys are exhausted"),
        ),
        patch("app.firecrawl_backend.scrape_do_token", return_value=None),
    ):
        with pytest.raises(RuntimeError, match="All Firecrawl API keys are exhausted"):
            _scrape_sync(SOURCE)
