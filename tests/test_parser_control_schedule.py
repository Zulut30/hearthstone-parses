from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path

from app import cli


class ParserControlScheduleTest(unittest.TestCase):
    def test_scheduled_refresh_enables_section_filtering(self) -> None:
        with patch("app.cli.refresh_sources", return_value=[]) as refresh:
            exit_code = cli.main(
                [
                    "refresh",
                    "--source",
                    "heartharena_tierlist",
                    "--scheduled",
                ]
            )

        self.assertEqual(exit_code, 0)
        refresh.assert_called_once_with(
            ["heartharena_tierlist"],
            tier=None,
            respect_section_controls=True,
        )

    def test_scheduled_pipeline_is_skipped_when_its_section_is_disabled(self) -> None:
        with patch(
            "app.parser_control.is_source_scheduled_enabled", return_value=False
        ), patch(
            "app.hsreplay_archetypes_db.refresh_hsreplay_archetype_database"
        ) as refresh:
            exit_code = cli.main(["refresh-hsreplay-archetypes", "--scheduled"])

        self.assertEqual(exit_code, 0)
        refresh.assert_not_called()

    def test_scheduled_bg_minion_database_is_skipped_with_cards_section(self) -> None:
        with patch(
            "app.parser_control.is_source_scheduled_enabled", return_value=False
        ), patch(
            "app.hsreplay_bg_minions_db.refresh_bg_minion_database_sync"
        ) as refresh:
            exit_code = cli.main(["refresh-bg-minions-db", "--scheduled"])

        self.assertEqual(exit_code, 0)
        refresh.assert_not_called()

    def test_scheduled_check_is_safe_allowlisted_section_guard(self) -> None:
        with patch(
            "app.parser_control.is_source_scheduled_enabled", return_value=False
        ):
            disabled = cli.main([
                "scheduled-check",
                "--source",
                "hsguru_streamer_decks_legend_1000",
            ])
        unknown = cli.main(["scheduled-check", "--source", "not-a-source"])

        self.assertEqual(disabled, 1)
        self.assertEqual(unknown, 2)

    def test_direct_streamer_services_use_scheduled_exec_condition(self) -> None:
        root = Path(__file__).resolve().parent.parent / "systemd"
        for filename in (
            "hs-data-api-docker-firecrawl-streamer.service",
            "hs-data-api-firecrawl-streamer.service",
        ):
            text = (root / filename).read_text(encoding="utf-8")
            self.assertIn("ExecCondition=", text)
            self.assertIn(
                "app.cli scheduled-check --source hsguru_streamer_decks_legend_1000",
                text,
            )

    def test_all_systemd_generic_refreshes_honor_section_controls(self) -> None:
        root = Path(__file__).resolve().parent.parent / "systemd"
        offenders: list[str] = []
        for path in root.glob("*.service"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if "app.cli refresh " in line and " --scheduled" not in line:
                    offenders.append(f"{path.name}: {line}")
                if any(
                    command in line
                    for command in (
                        "app.cli refresh-hsreplay-archetypes",
                        "app.cli refresh-bg-hero-details",
                        "app.cli refresh-bg-minions-db",
                    )
                ) and " --scheduled" not in line:
                    offenders.append(f"{path.name}: {line}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
