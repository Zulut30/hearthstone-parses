from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.parser_control import ParserControlStore, ParserRunWorker


class ParserControlApiTest(unittest.TestCase):
    def test_parser_runs_exposes_normalized_source_result_contract(self) -> None:
        class SecretError:
            def __repr__(self) -> str:
                return "SECRET_TOKEN_MUST_NOT_LEAK"

        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"HS_API_DATA_DIR": directory, "HS_API_KEY": "secret"},
            clear=False,
        ):
            store = ParserControlStore(Path(directory))
            store.enqueue_run(
                source_ids=["heartharena_tierlist"],
                requested_by="admin:7",
                reason="Проверка контракта",
            )

            async def executor(_source_ids: list[str]) -> list[dict[str, object]]:
                return [
                    {
                        "source_id": "heartharena_tierlist",
                        "state": "partial",
                        "fetched_at": "2026-07-21T12:00:00+00:00",
                        "detail": "Один источник недоступен",
                        "errors": [
                            {
                                "archetype_id": 17,
                                "access_token": "SECRET_DICT_TOKEN_MUST_NOT_LEAK",
                                "error": "origin timeout",
                            },
                            "  publisher returned stale data  ",
                            {"access_token": "SECRET_ONLY_TOKEN_MUST_NOT_LEAK"},
                            SecretError(),
                            "",
                            None,
                        ],
                        "rows_total": 137,
                        "serving_cached_dataset": True,
                    }
                ]

            worker = ParserRunWorker(store, executor=executor)
            with patch(
                "app.parser_control._monotonic_ms", side_effect=[1_000.0, 1_250.4]
            ):
                self.assertTrue(worker.process_next())

            with patch("app.parser_control._STORE", store), patch(
                "app.parser_control._RUN_WORKER"
            ), TestClient(app) as client:
                response = client.get(
                    "/admin/parser-runs", headers={"X-API-Key": "secret"}
                )

            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()["runs"][0]["results"][0]
            self.assertEqual(
                result,
                {
                    "sourceId": "heartharena_tierlist",
                    "label": "HearthArena · тир-лист карт",
                    "state": "partial",
                    "fetchedAt": "2026-07-21T12:00:00+00:00",
                    "detail": "Один источник недоступен",
                    "errors": [
                        "archetype_id=17: origin timeout",
                        "publisher returned stale data",
                        "Структурированная ошибка парсера",
                        "Неизвестная ошибка парсера",
                    ],
                    "errorsTotal": 4,
                    "errorsTruncated": False,
                    "servingCachedDataset": True,
                    "rowsTotal": 137,
                    "durationMs": 250,
                },
            )
            self.assertNotIn("SECRET_TOKEN_MUST_NOT_LEAK", response.text)
            self.assertNotIn("SECRET_DICT_TOKEN_MUST_NOT_LEAK", response.text)
            self.assertNotIn("SECRET_ONLY_TOKEN_MUST_NOT_LEAK", response.text)

    def test_parser_runs_limits_public_errors_and_reports_truncation(self) -> None:
        with TemporaryDirectory() as directory:
            store = ParserControlStore(Path(directory))
            run, _deduplicated = store.enqueue_run(
                source_ids=["heartharena_tierlist"],
                requested_by="admin:7",
                reason="Проверка ограничения ошибок",
            )
            store.record_run_result(
                run["id"],
                {
                    "sourceId": "heartharena_tierlist",
                    "state": "partial",
                    "errors": [f"error-{index:03d}" for index in range(75)],
                },
            )

            result = store.get_run(run["id"])["results"][0]

            self.assertEqual(len(result["errors"]), 50)
            self.assertEqual(result["errors"][0], "error-000")
            self.assertEqual(result["errors"][-1], "error-049")
            self.assertEqual(result["errorsTotal"], 75)
            self.assertTrue(result["errorsTruncated"])

    def test_control_plane_requires_admin_key_and_rejects_stale_revision(self) -> None:
        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"HS_API_DATA_DIR": directory, "HS_API_KEY": "secret"},
            clear=False,
        ), TestClient(app) as client:
            self.assertEqual(client.get("/admin/parser-control").status_code, 401)

            headers = {"X-API-Key": "secret"}
            initial = client.get("/admin/parser-control", headers=headers)
            self.assertEqual(initial.status_code, 200)
            self.assertEqual(initial.headers.get("cache-control"), "private, no-store")
            payload = initial.json()
            self.assertEqual(payload["revision"], 1)
            self.assertIn("sections", payload)
            self.assertEqual(payload["scheduleInventory"]["schemaVersion"], 2)

            changed = client.patch(
                "/admin/parser-control/policy",
                headers=headers,
                json={
                    "expectedRevision": 1,
                    "mode": "early",
                    "earlyUntil": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                    "reason": "Балансный патч",
                    "updatedBy": "admin:7",
                },
            )
            self.assertEqual(changed.status_code, 200, changed.text)
            self.assertEqual(changed.json()["revision"], 2)

            stale = client.patch(
                "/admin/parser-control/sections",
                headers=headers,
                json={
                    "expectedRevision": 1,
                    "sections": [{"id": "arena-tier-list", "enabled": False}],
                    "updatedBy": "admin:7",
                },
            )
            self.assertEqual(stale.status_code, 409, stale.text)

    def test_corrupted_control_file_does_not_prevent_public_api_startup(self) -> None:
        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"HS_API_DATA_DIR": directory, "HS_API_KEY": "secret"},
            clear=False,
        ):
            store = ParserControlStore(Path(directory))
            store.state_path.parent.mkdir(parents=True, exist_ok=True)
            store.state_path.write_text("{broken", encoding="utf-8")
            worker = ParserRunWorker(store)
            with patch("app.parser_control._RUN_WORKER", worker), patch(
                "app.refresh_log.log_action"
            ) as log_action, TestClient(app) as client:
                self.assertEqual(client.get("/health").status_code, 200)
                admin = client.get(
                    "/admin/parser-control", headers={"X-API-Key": "secret"}
                )

            self.assertEqual(admin.status_code, 503)
            self.assertTrue(
                any(
                    call.args and call.args[0] == "parser_control.storage_fallback"
                    and call.kwargs.get("extra", {}).get("operation")
                    == "parser_run_worker_start"
                    for call in log_action.call_args_list
                )
            )

    def test_saved_control_mutations_return_warning_when_audit_write_fails(self) -> None:
        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"HS_API_DATA_DIR": directory, "HS_API_KEY": "secret"},
            clear=False,
        ), TestClient(app) as client:
            headers = {"X-API-Key": "secret"}
            with patch(
                "app.refresh_log.log_action",
                side_effect=OSError("audit volume is read-only"),
            ), self.assertLogs("app.parser_control", level="ERROR") as policy_logs:
                policy = client.patch(
                    "/admin/parser-control/policy",
                    headers=headers,
                    json={
                        "expectedRevision": 1,
                        "mode": "stable",
                        "reason": "Достаточная выборка",
                        "updatedBy": "admin:7",
                    },
                )

            self.assertEqual(policy.status_code, 200, policy.text)
            self.assertEqual(policy.json()["revision"], 2)
            self.assertEqual(policy.json()["warnings"][0]["code"], "AUDIT_WRITE_FAILED")
            self.assertIn("parser_control.policy.update", " ".join(policy_logs.output))

            with patch(
                "app.refresh_log.log_action",
                side_effect=OSError("audit volume is read-only"),
            ), self.assertLogs("app.parser_control", level="ERROR") as section_logs:
                sections = client.patch(
                    "/admin/parser-control/sections",
                    headers=headers,
                    json={
                        "expectedRevision": 2,
                        "sections": [
                            {"id": "arena-tier-list", "enabled": False}
                        ],
                        "updatedBy": "admin:7",
                    },
                )

            self.assertEqual(sections.status_code, 200, sections.text)
            self.assertEqual(sections.json()["revision"], 3)
            self.assertEqual(
                sections.json()["warnings"][0]["code"], "AUDIT_WRITE_FAILED"
            )
            self.assertIn("parser_control.sections.update", " ".join(section_logs.output))

            persisted = client.get("/admin/parser-control", headers=headers)
            self.assertEqual(persisted.status_code, 200, persisted.text)
            self.assertEqual(persisted.json()["revision"], 3)
            arena = next(
                row
                for row in persisted.json()["sections"]
                if row["id"] == "arena-tier-list"
            )
            self.assertFalse(arena["enabled"])


if __name__ == "__main__":
    unittest.main()
