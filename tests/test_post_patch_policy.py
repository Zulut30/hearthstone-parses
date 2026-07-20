from __future__ import annotations

from datetime import UTC, datetime
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.dataset_regression import check_dataset_regression
from app.fetcher import _attach_provisional_status, _save_dataset_with_checks
from app.post_patch_policy import (
    build_provisional_metadata,
    effective_contract_min_rows,
    effective_firestone_minimum_sample,
    policy_for,
)
from app.source_contracts import contract_quality_report
from app.source_validators import validate_structured
from app.sources import SOURCE_BY_ID
from app.storage import load_baseline, save_baseline_once


WINDOW_TIME = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
BEFORE_WINDOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
AFTER_WINDOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _arena_cards(count: int) -> list[dict]:
    return [
        {
            "card_id": f"CARD_{idx}",
            "name": f"Card {idx}",
            "tier": "B",
            "deck_winrate": "51.0%",
            "winrate_when_drawn": "52.0%",
            "winrate_when_played": "53.0%",
            "in_runs": "1.0%",
            "avg_copies": 1.1,
        }
        for idx in range(count)
    ]


class PostPatchPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._enabled = patch.dict(
            "os.environ", {"HS_ARENA_POST_PATCH_ENABLED": "true"}
        )
        self._enabled.start()

    def tearDown(self) -> None:
        self._enabled.stop()

    def test_policy_is_scoped_to_configured_sources_and_date_window(self) -> None:
        self.assertIsNotNone(policy_for("hsreplay_arena_cards_advanced", at=WINDOW_TIME))
        self.assertIsNotNone(policy_for("heartharena_tierlist", at=WINDOW_TIME))
        self.assertIsNotNone(policy_for("firestone_arena_cards_normal", at=WINDOW_TIME))
        self.assertIsNone(policy_for("hsreplay_cards_legend_1d", at=WINDOW_TIME))
        self.assertIsNone(policy_for("hsreplay_arena_cards_advanced", at=BEFORE_WINDOW))
        self.assertIsNone(policy_for("hsreplay_arena_cards_advanced", at=AFTER_WINDOW))

    def test_policy_can_be_disabled_from_environment(self) -> None:
        with patch.dict("os.environ", {"HS_ARENA_POST_PATCH_ENABLED": "false"}):
            self.assertIsNone(policy_for("hsreplay_arena_cards_advanced", at=WINDOW_TIME))

    def test_contract_accepts_twenty_valid_hsreplay_rows_during_window(self) -> None:
        structured = {"type": "arena_card_tiers", "cards": _arena_cards(20)}

        with patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME):
            report = contract_quality_report("hsreplay_arena_cards_advanced", structured)

        self.assertTrue(report["ok"], report["warnings"])
        self.assertEqual(report["minimum_rows"], 20)

    def test_contract_keeps_normal_threshold_outside_window(self) -> None:
        structured = {"type": "arena_card_tiers", "cards": _arena_cards(20)}

        with patch("app.post_patch_policy.current_time", return_value=BEFORE_WINDOW):
            report = contract_quality_report("hsreplay_arena_cards_advanced", structured)

        self.assertFalse(report["ok"])
        self.assertEqual(report["minimum_rows"], 900)

    def test_heartharena_accepts_short_structurally_valid_list_during_window(self) -> None:
        cards = [
            {
                "card_id": f"CARD_{idx}",
                "name": f"Card {idx}",
                "tier_id": "B" if idx < 16 else None,
            }
            for idx in range(20)
        ]
        structured = {
            "type": "heartharena_tierlist",
            "classes": [{"class": "Mage", "cards": cards}],
            "total_cards": 20,
            "total_classes": 1,
        }

        with patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME):
            report = validate_structured("heartharena_tierlist", structured)

        self.assertTrue(report.ok, report.reason)
        self.assertEqual(report.metrics["minimum_cards"], 20)
        self.assertEqual(report.metrics["minimum_classes"], 1)
        self.assertEqual(report.metrics["minimum_tier_ids"], 16)

    def test_heartharena_requires_tier_ids_for_eighty_percent_of_larger_payload(self) -> None:
        cards = [
            {
                "card_id": f"CARD_{idx}",
                "name": f"Card {idx}",
                "tier_id": "B" if idx < 16 else None,
            }
            for idx in range(100)
        ]
        structured = {
            "type": "heartharena_tierlist",
            "classes": [{"class": "Mage", "cards": cards}],
            "total_cards": 100,
            "total_classes": 1,
        }

        with patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME):
            report = validate_structured("heartharena_tierlist", structured)

        self.assertFalse(report.ok)
        self.assertEqual(report.metrics["minimum_tier_ids"], 80)
        self.assertIn(
            "heartharena_tierlist.missing_tier_ids",
            {issue.code for issue in report.issues},
        )

    def test_heartharena_uses_flattened_rows_instead_of_declared_total(self) -> None:
        cards = [
            {
                "card_id": f"CARD_{idx}",
                "name": f"Card {idx}",
                "tier_id": "B" if idx < 20 else None,
            }
            for idx in range(100)
        ]
        structured = {
            "type": "heartharena_tierlist",
            "classes": [{"class": "Mage", "cards": cards}],
            "total_cards": 20,
            "total_classes": 1,
        }

        with patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME):
            report = validate_structured("heartharena_tierlist", structured)

        self.assertFalse(report.ok)
        self.assertEqual(report.metrics["actual_cards"], 100)
        self.assertEqual(report.metrics["minimum_tier_ids"], 80)
        self.assertIn(
            "heartharena_tierlist.card_count_mismatch",
            {issue.code for issue in report.issues},
        )

    def test_heartharena_rejects_early_rows_without_card_identifiers(self) -> None:
        cards = [
            {"name": f"Card {idx}", "tier_id": "B"}
            for idx in range(20)
        ]
        structured = {
            "type": "heartharena_tierlist",
            "classes": [{"class": "Mage", "cards": cards}],
            "total_cards": 20,
            "total_classes": 1,
        }

        with patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME):
            report = validate_structured("heartharena_tierlist", structured)

        self.assertFalse(report.ok)
        self.assertIn(
            "heartharena_tierlist.missing_card_ids",
            {issue.code for issue in report.issues},
        )

    def test_short_arena_list_rejects_duplicate_card_identifiers(self) -> None:
        cards = _arena_cards(20)
        for card in cards:
            card["card_id"] = "DUPLICATE"

        with patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME):
            report = validate_structured(
                "hsreplay_arena_cards_advanced",
                {"type": "arena_card_tiers", "cards": cards},
            )

        self.assertFalse(report.ok)
        self.assertIn(
            "arena_card_tiers.low_id_diversity",
            {issue.code for issue in report.issues},
        )

    def test_short_firestone_list_rejects_rows_below_minimum_sample(self) -> None:
        cards = _arena_cards(20)
        for card in cards:
            card["total_games"] = 1

        with patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME):
            report = validate_structured(
                "firestone_arena_cards_normal",
                {"type": "arena_card_tiers", "cards": cards},
            )

        self.assertFalse(report.ok)
        self.assertIn(
            "arena_card_tiers.low_sample",
            {issue.code for issue in report.issues},
        )

    def test_short_arena_list_rejects_out_of_range_winrates(self) -> None:
        cards = _arena_cards(20)
        for card in cards:
            card["deck_winrate"] = "151%"

        with patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME):
            report = validate_structured(
                "hsreplay_arena_cards_advanced",
                {"type": "arena_card_tiers", "cards": cards},
            )

        self.assertFalse(report.ok)
        self.assertIn(
            "arena_card_tiers.invalid_winrates",
            {issue.code for issue in report.issues},
        )

    def test_short_arena_list_rejects_even_a_minority_of_impossible_winrates(self) -> None:
        cards = _arena_cards(20)
        for card in cards[-4:]:
            card["deck_winrate"] = "151%"

        with patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME):
            report = validate_structured(
                "hsreplay_arena_cards_advanced",
                {"type": "arena_card_tiers", "cards": cards},
            )

        self.assertFalse(report.ok)
        self.assertEqual(report.metrics["invalid_winrates"], 4)

    def test_short_arena_list_rejects_impossible_secondary_percentage(self) -> None:
        cards = _arena_cards(20)
        cards[0]["winrate_when_drawn"] = "999%"

        with patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME):
            report = validate_structured(
                "hsreplay_arena_cards_advanced",
                {"type": "arena_card_tiers", "cards": cards},
            )

        self.assertFalse(report.ok)
        self.assertEqual(report.metrics["invalid_percent_values"], 1)
        self.assertIn(
            "arena_card_tiers.impossible_percentages",
            {issue.code for issue in report.issues},
        )

    def test_short_arena_list_accepts_numeric_zero_percentages(self) -> None:
        cards = _arena_cards(20)
        cards[0]["deck_winrate"] = None
        cards[0]["win_rate"] = 0.0
        cards[0]["pick_rate"] = 0

        with patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME):
            report = validate_structured(
                "hsreplay_arena_cards_advanced",
                {"type": "arena_card_tiers", "cards": cards},
            )

        self.assertTrue(report.ok, report.reason)
        self.assertEqual(report.metrics["invalid_percent_values"], 0)

    def test_short_arena_list_rejects_duplicate_ids_even_with_eighty_percent_unique(self) -> None:
        cards = _arena_cards(20)
        for card in cards[-4:]:
            card["card_id"] = "CARD_0"

        with patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME):
            report = validate_structured(
                "hsreplay_arena_cards_advanced",
                {"type": "arena_card_tiers", "cards": cards},
            )

        self.assertFalse(report.ok)
        self.assertEqual(report.metrics["duplicate_card_ids"], 4)

    def test_large_regression_is_allowed_only_for_patch_sources_in_window(self) -> None:
        source = SOURCE_BY_ID["hsreplay_arena_cards_advanced"]
        previous = {
            "structured": {"type": "arena_card_tiers", "cards": _arena_cards(1000)}
        }
        candidate = {
            "structured": {"type": "arena_card_tiers", "cards": _arena_cards(20)}
        }

        with patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME):
            regression, message, details = check_dataset_regression(
                source,
                previous_data=previous,
                new_data=candidate,
            )

        self.assertFalse(regression)
        self.assertIsNone(message)
        self.assertTrue(details["post_patch_regression_bypass"])
        self.assertEqual(details["rows_before"], 1000)
        self.assertEqual(details["rows_after"], 20)

    def test_firestone_minimum_sample_drops_to_ten_only_during_window(self) -> None:
        self.assertEqual(
            effective_firestone_minimum_sample(
                "firestone_arena_cards_normal", 30, at=WINDOW_TIME
            ),
            10,
        )
        self.assertEqual(
            effective_firestone_minimum_sample(
                "firestone_arena_cards_normal", 30, at=BEFORE_WINDOW
            ),
            30,
        )

    def test_provisional_metadata_describes_coverage_and_window(self) -> None:
        metadata = build_provisional_metadata(
            "hsreplay_arena_cards_advanced",
            accepted_rows=20,
            baseline_rows=1000,
            at=WINDOW_TIME,
        )

        self.assertEqual(metadata["data_phase"], "post_patch_early")
        self.assertTrue(metadata["provisional"])
        self.assertEqual(metadata["accepted_rows"], 20)
        self.assertEqual(metadata["baseline_rows"], 1000)
        self.assertEqual(metadata["coverage_ratio"], 0.02)
        self.assertEqual(metadata["minimum_sample"], 10)
        self.assertEqual(metadata["patch_window"]["until"], "2026-07-28")

    def test_provisional_metadata_is_exposed_in_status_and_quality(self) -> None:
        metadata = build_provisional_metadata(
            "hsreplay_arena_cards_advanced",
            accepted_rows=20,
            baseline_rows=1000,
            at=WINDOW_TIME,
        )
        status = {"state": "ok", "quality": {"rows_total": 20}}

        _attach_provisional_status(status, metadata)

        self.assertEqual(status["data_phase"], "post_patch_early")
        self.assertTrue(status["provisional"])
        self.assertEqual(status["quality"]["coverage_ratio"], 0.02)
        self.assertEqual(status["quality"]["baseline_rows"], 1000)

    def test_saved_patch_dataset_carries_provisional_metadata_and_stable_baseline(self) -> None:
        source = SOURCE_BY_ID["hsreplay_arena_cards_advanced"]
        previous = {
            "data": {
                "structured": {
                    "type": "arena_card_tiers",
                    "cards": _arena_cards(50),
                    "data_phase": "post_patch_early",
                    "provisional": True,
                    "baseline_rows": 1000,
                }
            }
        }
        candidate = {
            "data": {
                "structured": {
                    "type": "arena_card_tiers",
                    "cards": _arena_cards(20),
                }
            }
        }

        with (
            patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME),
            patch("app.fetcher.load_dataset", return_value=previous),
            patch("app.fetcher.save_dataset") as save_dataset,
            patch("app.fetcher.save_baseline_once") as save_baseline,
            patch("app.fetcher.log_action"),
        ):
            regression, message, provisional_metadata = _save_dataset_with_checks(
                source,
                candidate,
                fetched_at=WINDOW_TIME.isoformat(),
            )

        self.assertFalse(regression)
        self.assertIsNone(message)
        self.assertEqual(provisional_metadata["data_phase"], "post_patch_early")
        saved = save_dataset.call_args.args[1]
        structured = saved["data"]["structured"]
        self.assertTrue(structured["provisional"])
        self.assertEqual(structured["accepted_rows"], 20)
        self.assertEqual(structured["baseline_rows"], 1000)
        self.assertEqual(structured["coverage_ratio"], 0.02)
        save_baseline.assert_not_called()

    def test_first_provisional_publish_preserves_previous_stable_dataset(self) -> None:
        source = SOURCE_BY_ID["hsreplay_arena_cards_advanced"]
        previous = {
            "fetched_at": "2026-07-20T16:00:00Z",
            "data": {
                "structured": {
                    "type": "arena_card_tiers",
                    "cards": _arena_cards(1000),
                }
            },
        }
        candidate = {
            "data": {
                "structured": {
                    "type": "arena_card_tiers",
                    "cards": _arena_cards(20),
                }
            }
        }

        with (
            patch("app.post_patch_policy.current_time", return_value=WINDOW_TIME),
            patch("app.fetcher.load_dataset", return_value=previous),
            patch("app.fetcher.save_dataset"),
            patch("app.fetcher.save_baseline_once", return_value=True) as save_baseline,
            patch("app.fetcher.log_action"),
        ):
            regression, _, provisional_metadata = _save_dataset_with_checks(
                source,
                candidate,
                fetched_at=WINDOW_TIME.isoformat(),
            )

        self.assertFalse(regression)
        self.assertEqual(provisional_metadata["accepted_rows"], 20)
        save_baseline.assert_called_once_with(
            "hsreplay_arena_cards_advanced",
            "arena-post-patch-2026-07-21",
            previous,
        )

    def test_stable_baseline_is_written_once_outside_rotating_backups(self) -> None:
        with TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "HS_API_DATA_DIR": directory,
                "PYTHON_ENV": "test",
            },
        ):
            first = {"fetched_at": "before", "data": {"cards": [1, 2, 3]}}
            replacement = {"fetched_at": "after", "data": {"cards": [4]}}

            self.assertTrue(
                save_baseline_once(
                    "hsreplay_arena_cards_advanced",
                    "arena-post-patch-2026-07-21",
                    first,
                )
            )
            self.assertFalse(
                save_baseline_once(
                    "hsreplay_arena_cards_advanced",
                    "arena-post-patch-2026-07-21",
                    replacement,
                )
            )
            self.assertEqual(
                load_baseline(
                    "hsreplay_arena_cards_advanced",
                    "arena-post-patch-2026-07-21",
                ),
                first,
            )

    def test_effective_contract_rows_helper_retains_defaults_for_other_sources(self) -> None:
        self.assertEqual(
            effective_contract_min_rows("hsreplay_cards_legend_1d", 600, at=WINDOW_TIME),
            600,
        )


if __name__ == "__main__":
    unittest.main()
