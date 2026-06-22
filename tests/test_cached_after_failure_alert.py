from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from app.fetcher import _maybe_cached_after_failure_alert, _preserve_cached_ok_status
from app.sources import SOURCE_BY_ID
from app.storage import save_dataset


class CachedAfterFailureAlertTest(unittest.TestCase):
    def test_preserved_cache_marks_ok_cached_with_age(self) -> None:
        source = SOURCE_BY_ID["hsguru_matchups_legend"]
        fetched_at = (datetime.now(UTC) - timedelta(hours=4)).isoformat()

        with TemporaryDirectory() as td:
            with patch("app.storage.data_dir", return_value=Path(td)), patch(
                "app.fetcher.validate_parsed_data", return_value=(True, "ok")
            ):
                save_dataset(
                    source.id,
                    {
                        "source_id": source.id,
                        "fetched_at": fetched_at,
                        "http_status": 200,
                        "final_url": source.url,
                        "backend": "flaresolverr",
                        "data": {
                            "structured": {
                                "type": "matchups",
                                "matchups": [
                                    {"archetype": f"Deck {idx}", "vs": "Other", "winrate": "50%"}
                                    for idx in range(120)
                                ],
                            }
                        },
                    },
                )
                status = _preserve_cached_ok_status(
                    source,
                    {
                        "state": "fetch_error",
                        "fetched_at": datetime.now(UTC).isoformat(),
                        "detail": "live refresh failed",
                    },
                )

        self.assertIsNotNone(status)
        self.assertTrue(status["serving_cached_dataset"])  # type: ignore[index]
        self.assertEqual(status["effective_state"], "ok_cached")  # type: ignore[index]
        self.assertEqual(status["last_refresh_state"], "fetch_error")  # type: ignore[index]
        self.assertGreaterEqual(status["cached_dataset_age_hours"], 3.9)  # type: ignore[index]

    def test_cached_after_failure_alert_is_sent(self) -> None:
        source = SOURCE_BY_ID["hsguru_matchups_legend"]
        status = {
            "serving_cached_dataset": True,
            "cached_dataset_age_hours": 31.0,
            "last_refresh_state": "fetch_error",
            "last_refresh_at": datetime.now(UTC).isoformat(),
            "last_refresh_error": "blocked 403",
        }

        with TemporaryDirectory() as td, patch(
            "app.storage.data_dir", return_value=Path(td)
        ), patch("app.fetcher.send_telegram_alert", new_callable=AsyncMock) as alert:
            asyncio.run(_maybe_cached_after_failure_alert(source, status))

        alert.assert_awaited_once()
        self.assertEqual(alert.await_args.args[1], "cached_after_failure")


if __name__ == "__main__":
    unittest.main()
