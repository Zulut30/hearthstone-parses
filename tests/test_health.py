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
            "last_refresh_state": "fetch_error",
            "fetched_at": "2026-06-04T00:00:00+00:00",
        }
        stale = [{"source_id": "src1", "reason": "ok_but_stale"}]

        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "SOURCES", [source]), patch.object(
            main, "load_status", return_value=status
        ), patch.object(main, "load_dataset", return_value=None), patch.object(
            main, "root_dir", return_value=Path(tmp)
        ), patch.object(
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
        self.assertEqual(payload["cached_after_failure_sources"], ["src1"])
        self.assertEqual(payload["cached_after_failure_count"], 1)
        self.assertEqual(payload["stale_sources"], ["src1"])

    def test_ops_health_detects_semantically_invalid_cached_dataset(self) -> None:
        source = type("SourceStub", (), {"id": "vicious_syndicate_live_beta"})()
        status = {"source_id": source.id, "state": "ok", "fetched_at": "2026-07-12T00:00:00Z"}
        placeholders = [{"deck": f"Other Class{idx}"} for idx in range(11)]
        dataset = {
            "data": {
                "structured": {
                    "type": "vicious_live",
                    "deck_distribution": placeholders,
                    "tier_list": [{"rank_bracket": "All", "decks": placeholders}],
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "SOURCES", [source]), patch.object(
            main, "load_status", return_value=status
        ), patch.object(main, "load_dataset", return_value=dataset), patch.object(
            main, "root_dir", return_value=Path(tmp)
        ), patch.object(main, "api_key", return_value="secret"), patch(
            "app.stale_monitor.find_stale_sources", return_value=[]
        ):
            response = TestClient(main.app).get("/ops/health", headers={"X-API-Key": "secret"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["serving_ok"])
        self.assertTrue(payload["degraded"])
        self.assertEqual(payload["semantic_failed_sources"], [source.id])
        self.assertIn(
            "vicious_live.too_few_named_archetypes",
            {
                issue["code"]
                for issue in payload["semantic_failures"][0]["issues"]
            },
        )


if __name__ == "__main__":
    unittest.main()
