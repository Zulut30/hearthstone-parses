from __future__ import annotations

import unittest
from unittest.mock import patch

from app.canary import run_canary


async def _ok_check() -> dict:
    return {"name": "ok_check", "ok": True}


async def _fail_check() -> dict:
    return {"name": "fail_check", "ok": False, "detail": "temporary failure"}


class CanaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_canary_collects_failures(self) -> None:
        with patch("app.canary.CHECKS", (_ok_check, _fail_check)):
            result = await run_canary(strict=True)

        self.assertFalse(result["ok"])
        self.assertTrue(result["strict"])
        self.assertEqual(result["failures"], ["fail_check"])
        self.assertEqual(len(result["checks"]), 2)


if __name__ == "__main__":
    unittest.main()
