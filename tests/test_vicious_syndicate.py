from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.vicious_syndicate import fetch_with_retry


class _FakeAsyncClient:
    calls = 0
    last_kwargs: dict[str, object] = {}

    def __init__(self, *args: object, **kwargs: object) -> None:
        type(self).last_kwargs = dict(kwargs)

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
        type(self).calls += 1
        return httpx.Response(
            404,
            text="<html>missing optional radar</html>",
            request=httpx.Request("GET", url, headers=headers),
        )


class ViciousSyndicateFetchTest(unittest.TestCase):
    def setUp(self) -> None:
        _FakeAsyncClient.calls = 0
        _FakeAsyncClient.last_kwargs = {}

    def test_optional_fetch_404_does_not_use_error_logger(self) -> None:
        async def run() -> None:
            with (
                patch("app.vicious_syndicate.httpx.AsyncClient", _FakeAsyncClient),
                patch("app.vicious_syndicate.httpx_client_kwargs", return_value={}),
                patch("app.vicious_syndicate.log_http_error") as log_http_error,
                patch("app.vicious_syndicate.asyncio.sleep", new_callable=AsyncMock),
                self.assertLogs("app.vicious_syndicate", level="INFO") as logs,
            ):
                response = await fetch_with_retry(
                    _client=object(),  # type: ignore[arg-type]
                    url="https://www.vicioussyndicate.com/wp-content/datareaper/radars/missing/index.html",
                    semaphore=asyncio.Semaphore(1),
                    max_retries=1,
                    optional=True,
                    optional_context="radar_html",
                )

            self.assertIsNone(response)
            log_http_error.assert_not_called()
            self.assertTrue(
                any("Optional Vicious fetch failed" in message for message in logs.output)
            )

        asyncio.run(run())

    def test_fetch_uses_saved_vicious_cookies(self) -> None:
        async def run() -> None:
            with (
                patch("app.vicious_syndicate.httpx.AsyncClient", _FakeAsyncClient),
                patch("app.vicious_syndicate.httpx_client_kwargs", return_value={}),
                patch(
                    "app.vicious_syndicate.vicious_syndicate_cookies_for_fetch",
                    return_value={"wordpress_logged_in_test": "secret"},
                ),
                patch("app.vicious_syndicate.log_http_error"),
                patch("app.vicious_syndicate.asyncio.sleep", new_callable=AsyncMock),
                self.assertLogs("app.vicious_syndicate", level="WARNING"),
            ):
                await fetch_with_retry(
                    _client=object(),  # type: ignore[arg-type]
                    url="https://www.vicioussyndicate.com/deck-library/mage-decks/",
                    semaphore=asyncio.Semaphore(1),
                    max_retries=1,
                    optional=True,
                )

            self.assertEqual(
                _FakeAsyncClient.last_kwargs.get("cookies"),
                {"wordpress_logged_in_test": "secret"},
            )

        asyncio.run(run())

    def test_optional_fetch_caps_retries_to_reduce_traffic(self) -> None:
        async def run() -> None:
            with (
                patch("app.vicious_syndicate.httpx.AsyncClient", _FakeAsyncClient),
                patch("app.vicious_syndicate.httpx_client_kwargs", return_value={}),
                patch("app.vicious_syndicate.log_http_error"),
                patch("app.vicious_syndicate.asyncio.sleep", new_callable=AsyncMock) as sleep,
                self.assertLogs("app.vicious_syndicate", level="WARNING"),
            ):
                response = await fetch_with_retry(
                    _client=object(),  # type: ignore[arg-type]
                    url="https://www.vicioussyndicate.com/wp-content/datareaper/radars/missing/index.html",
                    semaphore=asyncio.Semaphore(1),
                    max_retries=5,
                    optional=True,
                    optional_context="radar_html",
                )

            self.assertIsNone(response)
            self.assertEqual(_FakeAsyncClient.calls, 2)
            self.assertGreaterEqual(sleep.await_count, 1)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
