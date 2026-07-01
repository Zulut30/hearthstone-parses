from __future__ import annotations

import unittest

from app.main import app


class HealthRoutesTest(unittest.TestCase):
    def test_premium_health_requires_admin_dependency(self) -> None:
        route = next(route for route in app.routes if getattr(route, "path", None) == "/health/premium")

        self.assertTrue(getattr(route, "dependencies", None))


if __name__ == "__main__":
    unittest.main()
