import unittest
from datetime import datetime, timezone, timedelta

from app.scrapers.preferred_backend import preferred_browser_backend


class PreferredBackendTests(unittest.TestCase):
    def test_no_stick_after_error(self) -> None:
        self.assertIsNone(
            preferred_browser_backend({"state": "fetch_error", "backend": "flaresolverr"})
        )

    def test_stick_flaresolverr_when_fresh(self) -> None:
        ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.assertEqual(
            preferred_browser_backend({"state": "ok", "backend": "flaresolverr", "fetched_at": ts}),
            "flaresolverr",
        )

    def test_no_stick_scrapling(self) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        self.assertIsNone(
            preferred_browser_backend({"state": "ok", "backend": "scrapling", "fetched_at": ts})
        )


if __name__ == "__main__":
    unittest.main()
