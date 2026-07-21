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
            self.assertEqual(payload["scheduleInventory"]["schemaVersion"], 1)

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
