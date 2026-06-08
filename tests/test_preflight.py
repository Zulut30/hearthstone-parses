from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from app.preflight import PreflightResult, run_refresh_preflight


class PreflightTest(unittest.IsolatedAsyncioTestCase):
    @patch("app.preflight.fetch_proxy_url", return_value="http://proxy:1@example.com:1")
    @patch("app.preflight.fetch_require_proxy", return_value=True)
    @patch("app.preflight.check_proxy_health", new_callable=AsyncMock)
    @patch("app.preflight.refresh_preflight_probe_hsreplay", return_value=False)
    async def test_proxy_ok(
        self, _probe: object, mock_proxy: AsyncMock, _req: object, _url: object
    ) -> None:
        mock_proxy.return_value = {"egress_ip": "1.2.3.4", "rotation_ok": "True"}
        with TemporaryDirectory() as td, patch("app.storage.data_dir", return_value=Path(td)):
            result = await run_refresh_preflight(needs_proxy=True, needs_flaresolverr=False)
        self.assertTrue(result.ok)
        self.assertEqual(result.proxy_info.get("egress_ip"), "1.2.3.4")

    @patch("app.preflight.fetch_proxy_url", return_value="http://proxy:1@example.com:1")
    @patch("app.preflight.fetch_require_proxy", return_value=True)
    @patch("app.preflight.check_proxy_health", new_callable=AsyncMock, side_effect=RuntimeError("fail"))
    @patch("app.preflight.refresh_preflight_probe_hsreplay", return_value=False)
    async def test_proxy_fail(
        self, _probe: object, _mock_proxy: AsyncMock, _req: object, _url: object
    ) -> None:
        with TemporaryDirectory() as td, patch("app.storage.data_dir", return_value=Path(td)):
            result = await run_refresh_preflight(needs_proxy=True, needs_flaresolverr=False)
        self.assertFalse(result.ok)
        self.assertTrue(any("proxy" in e for e in result.errors))

    @patch("app.preflight.fetch_require_proxy", return_value=False)
    @patch("app.preflight.refresh_preflight_probe_hsreplay", return_value=False)
    async def test_proxy_skipped_when_not_required(
        self, _probe: object, _req: object
    ) -> None:
        with TemporaryDirectory() as td, patch("app.storage.data_dir", return_value=Path(td)):
            result = await run_refresh_preflight(needs_proxy=True, needs_flaresolverr=False)
        self.assertTrue(result.ok)
        self.assertEqual(result.checks[0]["name"], "proxy")
        self.assertTrue(result.checks[0]["skipped"])


class PreflightResultTest(unittest.TestCase):
    def test_to_dict(self) -> None:
        pf = PreflightResult(ok=True, warnings=["w"])
        d = pf.to_dict()
        self.assertTrue(d["ok"])
        self.assertEqual(d["warnings"], ["w"])


class FlaresolverrCheckTest(unittest.IsolatedAsyncioTestCase):
    @patch("app.preflight.httpx.AsyncClient")
    async def test_check_flaresolverr_functional_ok(self, mock_client: AsyncMock) -> None:
        # sessions.list ok + functional probe ok
        inst = mock_client.return_value.__aenter__.return_value
        inst.post.side_effect = [
            # sessions
            type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: {"status": "ok", "version": "3.5.0", "sessions": []}})(),
            # probe
            type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: {"status": "ok", "solution": {"status": 200, "response": '{"ip":"1.2.3.4"}' }}})(),
        ]
        from app.preflight import check_flaresolverr

        res = await check_flaresolverr(probe_functional=True)
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("functional"))

    @patch("app.preflight.httpx.AsyncClient")
    async def test_check_flaresolverr_functional_fail_still_basic_ok(self, mock_client: AsyncMock) -> None:
        inst = mock_client.return_value.__aenter__.return_value
        inst.post.side_effect = [
            type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: {"status": "ok", "version": "3.5.0", "sessions": [1]}})(),
            type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: {"status": "ok", "solution": {"status": 403}}})(),
        ]
        from app.preflight import check_flaresolverr

        res = await check_flaresolverr(probe_functional=True)
        self.assertTrue(res["ok"])
        self.assertFalse(res.get("functional"))


if __name__ == "__main__":
    unittest.main()
