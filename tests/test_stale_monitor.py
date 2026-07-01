from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app.stale_monitor import _stale_alert_state, find_stale_sources


class StaleMonitorTest(unittest.TestCase):
    def test_finds_ok_but_old_status(self) -> None:
        old = (datetime.now(UTC) - timedelta(hours=20)).isoformat()
        status = {
            "source_id": "heartharena_tierlist",
            "state": "ok",
            "fetched_at": old,
        }
        with patch("app.stale_monitor.load_status", return_value=status), patch(
            "app.stale_monitor.load_dataset", return_value={"fetched_at": old}
        ), patch("app.stale_monitor.stale_dataset_hours", return_value=12.0), patch(
            "app.stale_monitor.SOURCES",
            [type("S", (), {"id": "heartharena_tierlist"})()],
        ):
            found = find_stale_sources(include_ok=True)
        ids = [f["source_id"] for f in found]
        self.assertIn("heartharena_tierlist", ids)
        self.assertEqual(found[0].get("reason"), "ok_but_stale")

    def test_skips_fresh_ok(self) -> None:
        fresh = datetime.now(UTC).isoformat()
        status = {"state": "ok", "fetched_at": fresh}
        with patch("app.stale_monitor.load_status", return_value=status), patch(
            "app.stale_monitor.load_dataset", return_value={"fetched_at": fresh}
        ), patch("app.stale_monitor.stale_dataset_hours", return_value=12.0), patch(
            "app.stale_monitor.SOURCES",
            [type("S", (), {"id": "metastats_decks"})()],
        ):
            found = find_stale_sources(include_ok=True)
        self.assertEqual(found, [])

    def test_stale_alert_state_escalates_by_age(self) -> None:
        self.assertEqual(
            _stale_alert_state({"state": "ok", "dataset_age_hours": 20}),
            "stale_ok",
        )
        self.assertEqual(
            _stale_alert_state({"state": "ok", "dataset_age_hours": 25}),
            "stale_ok_24h",
        )
        self.assertEqual(
            _stale_alert_state({"state": "fetch_error", "dataset_age_hours": 50}),
            "stale_data_48h",
        )

    def test_cached_live_failure_alerts_as_stale_data(self) -> None:
        self.assertEqual(
            _stale_alert_state(
                {
                    "state": "ok",
                    "reason": "live_failed_cached",
                    "dataset_age_hours": 25,
                }
            ),
            "stale_data_24h",
        )


if __name__ == "__main__":
    unittest.main()
