from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.parser_control import (
    ParserControlStore,
    ParserRunWorker,
    RevisionConflict,
    enabled_section_ids,
    effective_publication_mode,
    filter_scheduled_source_ids,
    _run_pipeline_source,
)
from app.parser_control_registry import (
    EARLY_SOURCE_IDS,
    SECTION_BY_ID,
    SOURCE_TO_SECTION,
)
from app.post_patch_policy import STABLE_PUBLICATION_BASELINE_LABEL
from app.sources import SOURCE_BY_ID


class ParserControlRegistryTest(unittest.TestCase):
    def test_every_configured_source_belongs_to_exactly_one_section(self) -> None:
        self.assertEqual(set(SOURCE_BY_ID), set(SOURCE_TO_SECTION))
        self.assertTrue(all(section_id in SECTION_BY_ID for section_id in SOURCE_TO_SECTION.values()))

    def test_early_mode_is_only_advertised_for_implemented_sources(self) -> None:
        self.assertEqual(
            EARLY_SOURCE_IDS,
            {
                "hsreplay_arena_cards_advanced",
                "heartharena_tierlist",
                "firestone_arena_cards_normal",
            },
        )


class ParserControlStoreTest(unittest.TestCase):
    def test_policy_update_is_persisted_and_uses_optimistic_revision(self) -> None:
        with TemporaryDirectory() as directory:
            store = ParserControlStore(Path(directory))
            until = datetime.now(UTC) + timedelta(days=2)

            updated = store.update_policy(
                expected_revision=1,
                mode="early",
                early_until=until.isoformat(),
                reason="Балансный патч",
                updated_by="admin:7",
            )

            self.assertEqual(updated["revision"], 2)
            self.assertEqual(updated["policy"]["mode"], "early")
            self.assertEqual(ParserControlStore(Path(directory)).snapshot()["revision"], 2)
            with self.assertRaises(RevisionConflict):
                store.update_policy(
                    expected_revision=1,
                    mode="stable",
                    early_until=None,
                    reason="",
                    updated_by="admin:8",
                )

    def test_section_update_filters_only_scheduled_runs(self) -> None:
        with TemporaryDirectory() as directory:
            store = ParserControlStore(Path(directory))
            updated = store.update_sections(
                expected_revision=1,
                changes={"arena-tier-list": False},
                updated_by="admin:7",
            )

            selected = [
                "hsreplay_arena_cards_advanced",
                "hsguru_meta_standard_legend",
            ]
            filtered = filter_scheduled_source_ids(selected, store=store)

            self.assertEqual(updated["revision"], 2)
            self.assertEqual(filtered, ["hsguru_meta_standard_legend"])
            # A manual run uses the original allow-listed selection and is not filtered.
            self.assertEqual(selected, [
                "hsreplay_arena_cards_advanced",
                "hsguru_meta_standard_legend",
            ])

    def test_expired_early_policy_falls_back_to_stable(self) -> None:
        with TemporaryDirectory() as directory:
            store = ParserControlStore(Path(directory))
            now = datetime.now(UTC)
            store.update_policy(
                expected_revision=1,
                mode="early",
                early_until=(now + timedelta(hours=1)).isoformat(),
                reason="Первые данные",
                updated_by="admin:7",
            )

            self.assertEqual(
                effective_publication_mode(
                    "hsreplay_arena_cards_advanced", at=now, store=store
                ),
                "early",
            )
            self.assertEqual(
                effective_publication_mode(
                    "hsreplay_arena_cards_advanced",
                    at=now + timedelta(hours=2),
                    store=store,
                ),
                "stable",
            )
            self.assertEqual(
                effective_publication_mode("hsreplay_cards_legend_1d", at=now, store=store),
                "stable",
            )

    def test_persisted_stable_mode_overrides_early_environment_fallback(self) -> None:
        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "HS_ARENA_POST_PATCH_ENABLED": "true",
                "HS_ARENA_POST_PATCH_FROM": "2026-07-21",
                "HS_ARENA_POST_PATCH_UNTIL": "2026-07-28",
            },
            clear=False,
        ):
            store = ParserControlStore(Path(directory))
            store.update_policy(
                expected_revision=1,
                mode="stable",
                early_until=None,
                reason="Достаточная выборка",
                updated_by="admin:7",
            )

            self.assertEqual(
                effective_publication_mode(
                    "hsreplay_arena_cards_advanced",
                    at=datetime(2026, 7, 23, 12, tzinfo=UTC),
                    store=store,
                ),
                "stable",
            )

    def test_section_edits_and_run_enqueue_preserve_environment_policy_provenance(self) -> None:
        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "HS_ARENA_POST_PATCH_ENABLED": "true",
                "HS_ARENA_POST_PATCH_FROM": "2026-07-21",
                "HS_ARENA_POST_PATCH_UNTIL": "2026-07-28",
            },
            clear=False,
        ):
            store = ParserControlStore(Path(directory))
            section_snapshot = store.update_sections(
                expected_revision=1,
                changes={"traditional-wild-meta": False},
                updated_by="admin:7",
            )
            store.enqueue_run(
                source_ids=["heartharena_tierlist"],
                requested_by="admin:7",
                reason="Проверка",
            )

            policy = store.snapshot(
                at=datetime(2026, 7, 23, 12, tzinfo=UTC)
            )["policy"]

            self.assertFalse(section_snapshot["policyConfigured"])
            self.assertFalse(policy["policyConfigured"])
            self.assertEqual(policy["managedBy"], "environment")
            self.assertEqual(policy["effectiveMode"], "early")
            self.assertEqual(
                effective_publication_mode(
                    "hsreplay_arena_cards_advanced",
                    at=datetime(2026, 7, 23, 12, tzinfo=UTC),
                    store=store,
                ),
                "early",
            )

    def test_run_queue_is_persisted_and_deduplicates_equal_active_selection(self) -> None:
        with TemporaryDirectory() as directory:
            store = ParserControlStore(Path(directory))
            first, first_deduplicated = store.enqueue_run(
                source_ids=["heartharena_tierlist", "hsreplay_arena_cards_advanced"],
                requested_by="admin:7",
                reason="После патча",
            )
            second, second_deduplicated = ParserControlStore(Path(directory)).enqueue_run(
                source_ids=["hsreplay_arena_cards_advanced", "heartharena_tierlist"],
                requested_by="admin:7",
                reason="Повтор",
            )

            self.assertFalse(first_deduplicated)
            self.assertTrue(second_deduplicated)
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(first["totalSources"], 2)
            self.assertEqual(first["completedSources"], 0)
            self.assertEqual(first["failedSources"], 0)
            self.assertEqual(store.list_runs()["activeRun"]["status"], "queued")

    def test_run_queue_deduplicates_sources_already_covered_by_other_active_runs(self) -> None:
        with TemporaryDirectory() as directory:
            store = ParserControlStore(Path(directory))
            first, _ = store.enqueue_run(
                source_ids=["heartharena_tierlist", "hsreplay_arena_cards_advanced"],
                requested_by="admin:7",
                reason="Первый запуск",
            )
            second, deduplicated = store.enqueue_run(
                source_ids=["hsreplay_arena_cards_advanced", "hsguru_meta_standard_legend"],
                requested_by="admin:7",
                reason="Пересекающийся запуск",
            )

            self.assertTrue(deduplicated)
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(second["sourceIds"], ["hsguru_meta_standard_legend"])
            self.assertEqual(
                second["requestedSourceIds"],
                ["hsguru_meta_standard_legend", "hsreplay_arena_cards_advanced"],
            )
            self.assertEqual(
                second["deduplicatedSourceIds"],
                ["hsreplay_arena_cards_advanced"],
            )

    def test_worker_persists_each_result_and_recovery_skips_completed_sources(self) -> None:
        with TemporaryDirectory() as directory:
            store = ParserControlStore(Path(directory))
            run, _ = store.enqueue_run(
                source_ids=["heartharena_tierlist", "hsreplay_arena_cards_advanced"],
                requested_by="admin:7",
                reason="Проверка восстановления",
            )
            store.claim_next_run()
            store.record_run_result(
                run["id"],
                {"sourceId": "heartharena_tierlist", "state": "ok"},
            )
            store.recover_interrupted_runs()
            calls: list[list[str]] = []

            async def executor(source_ids: list[str]) -> list[dict[str, object]]:
                calls.append(source_ids)
                return [{"source_id": source_ids[0], "state": "ok"}]

            worker = ParserRunWorker(store, executor=executor)
            self.assertTrue(worker.process_next())

            finished = store.list_runs()["runs"][0]
            self.assertEqual(calls, [["hsreplay_arena_cards_advanced"]])
            self.assertEqual(finished["status"], "succeeded")
            self.assertEqual(finished["completedSources"], 2)
            self.assertEqual(
                {row["sourceId"] for row in finished["results"]},
                {"heartharena_tierlist", "hsreplay_arena_cards_advanced"},
            )

    def test_terminal_run_counts_missing_results_as_failed(self) -> None:
        with TemporaryDirectory() as directory:
            store = ParserControlStore(Path(directory))
            run, _ = store.enqueue_run(
                source_ids=["heartharena_tierlist", "hsreplay_arena_cards_advanced"],
                requested_by="admin:7",
                reason="Проверка",
            )
            store.claim_next_run()
            store.finish_run(
                run["id"],
                status="partial",
                results=[{"sourceId": "heartharena_tierlist", "state": "ok"}],
            )

            finished = store.list_runs()["runs"][0]

            self.assertEqual(finished["totalSources"], 2)
            self.assertEqual(finished["completedSources"], 2)
            self.assertEqual(finished["failedSources"], 1)

    def test_corrupted_control_file_fails_open_for_scheduled_sections_and_logs(self) -> None:
        with TemporaryDirectory() as directory:
            store = ParserControlStore(Path(directory))
            store.state_path.parent.mkdir(parents=True, exist_ok=True)
            store.state_path.write_text("{broken", encoding="utf-8")

            with patch("app.refresh_log.log_action") as log_action:
                enabled = enabled_section_ids(store=store)
                filtered = filter_scheduled_source_ids(
                    ["heartharena_tierlist", "hsguru_meta_standard_legend"],
                    store=store,
                )

            self.assertEqual(enabled, set(SECTION_BY_ID))
            self.assertEqual(
                filtered,
                ["heartharena_tierlist", "hsguru_meta_standard_legend"],
            )
            self.assertTrue(
                any(
                    call.args and call.args[0] == "parser_control.storage_fallback"
                    and call.kwargs.get("extra", {}).get("fallback") == "all_sections_enabled"
                    for call in log_action.call_args_list
                )
            )

    def test_snapshot_reports_cached_failure_and_effective_stable_publication(self) -> None:
        source_id = "hsreplay_arena_cards_advanced"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = ParserControlStore(root)
            store.update_policy(
                expected_revision=1,
                mode="stable",
                early_until=None,
                reason="Стабильная публикация",
                updated_by="admin:7",
            )
            (root / "datasets").mkdir(parents=True)
            (root / "statuses").mkdir(parents=True)
            (root / "baselines").mkdir(parents=True)
            (root / "datasets" / f"{source_id}.json").write_text(
                '{"fetched_at":"2026-07-21T10:00:00+00:00","data":{"structured":{"cards":[{"card_id":"EARLY"}],"provisional":true}}}',
                encoding="utf-8",
            )
            (root / "baselines" / f"{source_id}.{STABLE_PUBLICATION_BASELINE_LABEL}.json").write_text(
                '{"fetched_at":"2026-07-20T08:00:00+00:00","data":{"structured":{"cards":[{"card_id":"STABLE"}]}}}',
                encoding="utf-8",
            )
            (root / "statuses" / f"{source_id}.json").write_text(
                '{"state":"ok","fetched_at":"2026-07-20T08:00:00+00:00","serving_cached_dataset":true,"last_refresh_state":"fetch_error","last_refresh_at":"2026-07-21T11:00:00+00:00","last_refresh_error":"origin timeout","rows_total":20}',
                encoding="utf-8",
            )

            snapshot = store.snapshot()
            row = next(
                source
                for section in snapshot["sections"]
                for source in section["sources"]
                if source["id"] == source_id
            )

            self.assertEqual(row["state"], "warning")
            self.assertEqual(row["health"], "warning")
            self.assertEqual(row["sourceState"], "ok")
            self.assertEqual(row["candidateFetchedAt"], "2026-07-21T10:00:00+00:00")
            self.assertEqual(row["publishedFetchedAt"], "2026-07-20T08:00:00+00:00")
            self.assertEqual(row["lastSuccessAt"], "2026-07-20T08:00:00+00:00")
            self.assertEqual(row["lastAttemptAt"], "2026-07-21T11:00:00+00:00")
            self.assertEqual(row["lastError"], "origin timeout")
            self.assertEqual(row["publicationChannel"], "stable_baseline")
            self.assertTrue(row["stableBaselineAvailable"])
            self.assertEqual(row["rowsTotal"], 1)


class ParserPipelineStateTest(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_preserves_partial_state_errors_and_cached_flag(self) -> None:
        upstream = {
            "ok": True,
            "state": "partial",
            "errors": ["один источник недоступен"],
            "serving_cached_dataset": True,
        }
        with patch(
            "app.hsreplay_bg_hero_details.refresh_bg_hero_details",
            new=AsyncMock(return_value=upstream),
        ):
            result = await _run_pipeline_source(
                "hsreplay_battlegrounds_hero_details"
            )

        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["errors"], upstream["errors"])
        self.assertTrue(result["serving_cached_dataset"])
        self.assertIn("один источник", result["detail"])


if __name__ == "__main__":
    unittest.main()
