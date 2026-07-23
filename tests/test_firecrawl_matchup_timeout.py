from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.firecrawl_backend import scrape_source
from app.sources import SOURCE_BY_ID


class FirecrawlMatchupTimeoutTest(unittest.TestCase):
    def test_hsguru_matchups_receive_extended_timeout(self) -> None:
        source = SOURCE_BY_ID["hsguru_matchups_legend"]

        with patch(
            "app.firecrawl_backend.firecrawl_hsguru_matchups_timeout_ms",
            return_value=180_000,
        ), patch("app.firecrawl_backend._scrape_sync", return_value=object()) as scrape:
            asyncio.run(scrape_source(source))

        scrape.assert_called_once_with(source, timeout_ms=180_000)

    def test_other_sources_keep_the_default_timeout_path(self) -> None:
        source = SOURCE_BY_ID["hsguru_streamer_decks_legend_1000"]

        with patch("app.firecrawl_backend._scrape_sync", return_value=object()) as scrape:
            asyncio.run(scrape_source(source))

        scrape.assert_called_once_with(source)


if __name__ == "__main__":
    unittest.main()
