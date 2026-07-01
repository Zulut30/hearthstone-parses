from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.premium_auth_health import build_premium_auth_health


class PremiumAuthHealthTest(unittest.TestCase):
    def test_local_health_reports_hsreplay_session_without_live_probe(self) -> None:
        with patch(
            "app.premium_auth_health.hsreplay_auth_status",
            return_value={
                "present": True,
                "credentials_configured": True,
                "has_sessionid": True,
                "is_authenticated": True,
                "age_hours": 12.5,
                "warning": None,
            },
        ):
            health = asyncio.run(build_premium_auth_health(live=False))

        self.assertTrue(health["ok"])
        self.assertFalse(health["live"])
        hsreplay = next(item for item in health["providers"] if item["provider"] == "hsreplay")
        self.assertTrue(hsreplay["ok"])
        self.assertFalse(hsreplay["live_checked"])
        self.assertEqual(hsreplay["age_hours"], 12.5)

    def test_local_health_flags_missing_hsreplay_session(self) -> None:
        with patch(
            "app.premium_auth_health.hsreplay_auth_status",
            return_value={
                "present": False,
                "credentials_configured": False,
                "has_sessionid": False,
                "is_authenticated": False,
                "age_hours": None,
                "warning": "missing",
            },
        ):
            health = asyncio.run(build_premium_auth_health(live=False))

        self.assertFalse(health["ok"])
        self.assertEqual(health["failures"], ["hsreplay"])


if __name__ == "__main__":
    unittest.main()
