from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import telegram_alerts


class TelegramDedupTest(unittest.TestCase):
    def test_dedup_within_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dedup_path = Path(tmp) / ".telegram-alert-dedup.json"
            with patch.object(telegram_alerts, "data_dir", return_value=Path(tmp)):
                with patch.object(telegram_alerts, "telegram_alert_dedup_seconds", return_value=3600):
                    self.assertTrue(telegram_alerts.should_send_alert("src1", "fetch_error"))
                    self.assertFalse(dedup_path.exists())
                    telegram_alerts.mark_alert_sent("src1", "fetch_error")
                    self.assertFalse(telegram_alerts.should_send_alert("src1", "fetch_error"))
                    self.assertTrue(telegram_alerts.should_send_alert("src1", "quality_error"))
            self.assertTrue(dedup_path.exists())

    def test_check_does_not_write_dedup_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dedup_path = Path(tmp) / ".telegram-alert-dedup.json"
            with patch.object(telegram_alerts, "data_dir", return_value=Path(tmp)):
                self.assertTrue(telegram_alerts.should_send_alert("src1", "fetch_error"))
            self.assertFalse(dedup_path.exists())


if __name__ == "__main__":
    unittest.main()
