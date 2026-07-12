from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from app.scrapers.quality import validate_parsed_data
from app.source_validators import validate_structured
from app.sources import SOURCE_BY_ID


def _hero_row(idx: int, *, name: str | None = None, avg: str | None = None) -> dict:
    place_one = 20.0 + (idx % 5) * 0.1
    rest = round((100.0 - place_one) / 7, 2)
    distribution = [f"{place_one:.2f}%"] + [f"{rest:.2f}%"] * 6
    distribution.append(f"{100.0 - place_one - rest * 6:.2f}%")
    return {
        "hero": name or f"Герой {idx}",
        "dbfId": 50_000 + idx,
        "pick_rate": f"{10 + idx / 10:.2f}%",
        "avg_placement": avg or f"{3.5 + idx / 100:.2f}",
        "tier": ["S", "A", "B", "C"][idx % 4],
        "placement_distribution": distribution,
    }


class SourceValidatorsTest(unittest.TestCase):
    def test_bg_heroes_semantic_validator_accepts_diverse_rows(self) -> None:
        structured = {
            "type": "bg_heroes",
            "heroes": [_hero_row(idx) for idx in range(40)],
        }

        report = validate_structured("hsreplay_battlegrounds_heroes", structured)

        self.assertTrue(report.ok)
        self.assertGreaterEqual(report.score, 0.95)
        self.assertEqual(report.metrics["valid_names"], 40)
        self.assertEqual(report.metrics["valid_distributions"], 40)

    def test_bg_heroes_semantic_validator_rejects_formally_filled_placeholders(self) -> None:
        structured = {
            "type": "bg_heroes",
            "heroes": [_hero_row(idx, name="—", avg="7") for idx in range(40)],
        }

        report = validate_structured("hsreplay_battlegrounds_heroes", structured)

        self.assertFalse(report.ok)
        codes = {issue.code for issue in report.issues}
        self.assertIn("bg_heroes.bad_names", codes)
        self.assertIn("bg_heroes.low_avg_diversity", codes)

    def test_quality_validation_runs_semantic_validator(self) -> None:
        source = SOURCE_BY_ID["hsreplay_battlegrounds_heroes"]
        parsed = {
            "title": "HSReplay premium Battlegrounds heroes tier list.",
            "structured": {
                "type": "bg_heroes",
                "heroes": [
                    {
                        **_hero_row(idx, avg="7"),
                        "hero": f"Герой {idx}",
                    }
                    for idx in range(40)
                ],
            },
        }

        ok, reason = validate_parsed_data(source, parsed)

        self.assertFalse(ok)
        self.assertIn("source semantic validation failed", reason)
        self.assertIn("avg_placement diversity", reason)

    def test_vicious_live_rejects_class_placeholders_as_archetypes(self) -> None:
        placeholder_decks = [
            {"deck": f"Other {hs_class}", "class": hs_class, "frequency": "9.09%"}
            for hs_class in (
                "DeathKnight",
                "DemonHunter",
                "Druid",
                "Hunter",
                "Mage",
                "Paladin",
                "Priest",
                "Rogue",
                "Shaman",
                "Warlock",
                "Warrior",
            )
        ]
        structured = {
            "type": "vicious_live",
            "deck_distribution": placeholder_decks,
            "tier_list": [
                {
                    "rank_bracket": bracket,
                    "decks": [
                        {"deck": row["deck"], "winrate": "50.00%"}
                        for row in placeholder_decks
                    ],
                }
                for bracket in ("All ranks", "Legend", "Diamond 1-4")
            ],
        }

        report = validate_structured("vicious_syndicate_live_beta", structured)

        self.assertFalse(report.ok)
        self.assertEqual(report.metrics["named_archetypes"], 0)
        self.assertEqual(report.metrics["placeholder_ratio"], 1.0)
        codes = {issue.code for issue in report.issues}
        self.assertIn("vicious_live.too_few_named_archetypes", codes)
        self.assertIn("vicious_live.placeholder_dominated", codes)

    def test_vicious_live_accepts_meaningful_archetype_names(self) -> None:
        deck_names = [
            "Rainbow DeathKnight",
            "Discover Hunter",
            "Spell Mage",
            "Starship Rogue",
            "Control Warrior",
            "Other Priest",
        ]
        structured = {
            "type": "vicious_live",
            "deck_distribution": [{"deck": name} for name in deck_names],
            "tier_list": [
                {
                    "rank_bracket": "All ranks",
                    "decks": [{"deck": name, "winrate": "50.00%"} for name in deck_names],
                }
            ],
        }

        report = validate_structured("vicious_syndicate_live_beta", structured)

        self.assertTrue(report.ok)
        self.assertEqual(report.metrics["named_archetypes"], 5)

    def test_vicious_radars_reject_stale_issue_despite_fresh_fetch(self) -> None:
        structured = {
            "type": "vicious_syndicate_radars",
            "issue": "349",
            "latest_report_issue": "352",
            "latest_report_published_at": (datetime.now(UTC) - timedelta(days=10)).date().isoformat(),
        }

        report = validate_structured("vicious_syndicate_radars", structured)

        self.assertFalse(report.ok)
        self.assertIn("vicious_radars.outdated_issue", {issue.code for issue in report.issues})

    def test_vicious_radars_reject_old_content_even_when_issue_matches(self) -> None:
        structured = {
            "type": "vicious_syndicate_radars",
            "issue": "352",
            "latest_report_issue": "352",
            "latest_report_published_at": (datetime.now(UTC) - timedelta(days=30)).date().isoformat(),
        }

        report = validate_structured("vicious_syndicate_radars", structured)

        self.assertFalse(report.ok)
        self.assertIn("vicious_radars.stale_content", {issue.code for issue in report.issues})

    def test_vicious_radars_accept_current_recent_report(self) -> None:
        structured = {
            "type": "vicious_syndicate_radars",
            "issue": "353",
            "latest_report_issue": "353",
            "latest_report_published_at": (datetime.now(UTC) - timedelta(days=2)).date().isoformat(),
        }

        report = validate_structured("vicious_syndicate_radars", structured)

        self.assertTrue(report.ok)
        self.assertEqual(report.score, 1.0)


if __name__ == "__main__":
    unittest.main()
