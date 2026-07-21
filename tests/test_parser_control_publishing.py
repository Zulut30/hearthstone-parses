from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.parser_control import ParserControlStore, resolve_public_dataset
from app.post_patch_policy import (
    POST_PATCH_BASELINE_LABEL,
    capture_publication_policy,
)
from app.fetcher import _save_dataset_with_checks
from app.sources import SOURCE_BY_ID
from app.storage import dataset_path, save_baseline_once, write_json


class ParserControlPublishingTest(unittest.TestCase):
    def test_early_candidate_is_not_saved_if_admin_switches_to_stable_mid_fetch(self) -> None:
        source_id = "hsreplay_arena_cards_advanced"
        candidate = {
            "source_id": source_id,
            "fetched_at": "2026-07-21T12:00:00+00:00",
            "data": {"structured": {"cards": [{"card_id": "EARLY"}]}},
        }
        previous = {
            "source_id": source_id,
            "fetched_at": "2026-07-20T12:00:00+00:00",
            "data": {"structured": {"cards": [{"card_id": "STABLE"}]}},
        }
        with TemporaryDirectory() as directory, patch.dict(
            os.environ, {"HS_API_DATA_DIR": directory}, clear=False
        ):
            store = ParserControlStore(Path(directory))
            early = store.update_policy(
                expected_revision=1,
                mode="early",
                early_until=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
                reason="Балансный патч",
                updated_by="admin:7",
            )
            with patch("app.fetcher.load_dataset", return_value=previous), patch(
                "app.fetcher.save_dataset"
            ) as save_dataset, patch(
                "app.fetcher.check_dataset_regression", return_value=(False, None, {})
            ), patch("app.fetcher.log_action"):
                with capture_publication_policy(source_id):
                    store.update_policy(
                        expected_revision=early["revision"],
                        mode="stable",
                        early_until=None,
                        reason="Достаточная выборка",
                        updated_by="admin:7",
                    )
                    blocked, message, _ = _save_dataset_with_checks(
                        SOURCE_BY_ID[source_id],
                        candidate,
                        fetched_at=candidate["fetched_at"],
                    )

            self.assertTrue(blocked)
            self.assertIn("Publication policy changed", message or "")
            save_dataset.assert_not_called()
    def test_switching_back_to_stable_serves_non_provisional_baseline(self) -> None:
        source_id = "hsreplay_arena_cards_advanced"
        stable = {
            "fetched_at": "2026-07-20T00:00:00+00:00",
            "data": {"structured": {"cards": [{"card_id": "STABLE"}]}}
        }
        provisional = {
            "fetched_at": "2026-07-21T00:00:00+00:00",
            "data": {
                "structured": {
                    "cards": [{"card_id": "EARLY"}],
                    "provisional": True,
                    "data_phase": "post_patch_early",
                }
            },
        }

        with TemporaryDirectory() as directory, patch.dict(
            os.environ, {"HS_API_DATA_DIR": directory}, clear=False
        ):
            save_baseline_once(source_id, POST_PATCH_BASELINE_LABEL, stable)
            store = ParserControlStore(Path(directory))
            store.update_policy(
                expected_revision=1,
                mode="early",
                early_until=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
                reason="Балансный патч",
                updated_by="admin:7",
            )
            state = store.snapshot()
            store.update_policy(
                expected_revision=state["revision"],
                mode="stable",
                early_until=None,
                reason="Выборка стабилизировалась",
                updated_by="admin:7",
            )

            published = resolve_public_dataset(source_id, provisional, store=store)

        self.assertIsNotNone(published)
        structured = published["data"]["structured"]
        self.assertEqual(structured["cards"][0]["card_id"], "STABLE")
        self.assertFalse(structured.get("provisional", False))

    def test_demo_view_uses_stable_baseline_after_mode_switch(self) -> None:
        source_id = "hsreplay_arena_cards_advanced"
        stable = {
            "fetched_at": "2026-07-20T00:00:00+00:00",
            "data": {
                "title": "Stable",
                "structured": {
                    "type": "arena_card_tiers",
                    "cards": [{"card_id": "STABLE", "name": "Stable card"}],
                },
            },
        }
        provisional = {
            "fetched_at": "2026-07-21T00:00:00+00:00",
            "data": {
                "title": "Early",
                "structured": {
                    "type": "arena_card_tiers",
                    "cards": [{"card_id": "EARLY", "name": "Early card"}],
                    "provisional": True,
                },
            },
        }

        with TemporaryDirectory() as directory, patch.dict(
            os.environ, {"HS_API_DATA_DIR": directory}, clear=False
        ):
            save_baseline_once(source_id, POST_PATCH_BASELINE_LABEL, stable)
            write_json(dataset_path(source_id), provisional)
            ParserControlStore(Path(directory)).update_policy(
                expected_revision=1,
                mode="stable",
                early_until=None,
                reason="Стабильный режим",
                updated_by="admin:7",
            )
            with TestClient(app) as client:
                response = client.get(f"/demo/view/{source_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["view"]["cards"][0]["card_id"], "STABLE")
        self.assertEqual(payload["fetched_at"], stable["fetched_at"])


if __name__ == "__main__":
    unittest.main()
