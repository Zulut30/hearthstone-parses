from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class HealthEndpointTest(unittest.TestCase):
    def test_public_health_is_minimal_liveness(self) -> None:
        response = TestClient(main.app).get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertNotIn("data_dir", payload)
        self.assertNotIn("stale_sources", payload)

    def test_ops_health_reports_stale_cached_source(self) -> None:
        source = type("SourceStub", (), {"id": "src1"})()
        status = {
            "source_id": "src1",
            "state": "ok",
            "serving_cached_dataset": True,
            "fetched_at": "2026-06-04T00:00:00+00:00",
        }
        stale = [{"source_id": "src1", "reason": "ok_but_stale"}]

        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "SOURCES", [source]), patch.object(
            main, "load_status", return_value=status
        ), patch.object(main, "root_dir", return_value=Path(tmp)), patch.object(
            main, "api_key", return_value="secret"
        ), patch(
            "app.stale_monitor.find_stale_sources", return_value=stale
        ):
            response = TestClient(main.app).get("/ops/health", headers={"X-API-Key": "secret"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["serving_ok"])
        self.assertFalse(payload["freshness_ok"])
        self.assertTrue(payload["degraded"])
        self.assertEqual(payload["cached_sources"], ["src1"])
        self.assertEqual(payload["stale_sources"], ["src1"])


if __name__ == "__main__":
    unittest.main()
