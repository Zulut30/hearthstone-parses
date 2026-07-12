from __future__ import annotations

from app.source_validators import validate_structured
from app.vicious_live import _without_placeholder_decks, live_upstream_availability
from app.vicious_syndicate import radar_upstream_state


def test_vicious_live_detects_post_expansion_unclassified_payload() -> None:
    archetypes = [[name, "Other"] for name in ("Mage", "Hunter", "Rogue", "Warrior")]

    availability = live_upstream_availability(archetypes)

    assert availability == {
        "state": "upstream_unclassified",
        "ready": False,
        "total_archetypes": 4,
        "named_archetypes": 0,
        "placeholder_archetypes": 4,
        "reason": "Vicious Firebase has not classified post-expansion archetypes yet",
    }


def test_vicious_live_ready_requires_multiple_named_archetypes() -> None:
    availability = live_upstream_availability(
        [["Mage", "Spell"], ["Hunter", "Discover"]],
        [["Rogue", "Starship"], ["Mage", "Other"]],
    )

    assert availability["state"] == "ready"
    assert availability["named_archetypes"] == 3
    assert availability["placeholder_archetypes"] == 1


def test_unclassified_payload_does_not_expose_placeholder_decks() -> None:
    decks, tiers = _without_placeholder_decks(
        [{"deck": "Other Mage"}, {"deck": "Spell Mage"}],
        [{"rank_bracket": "Legend", "decks": [{"deck": "Other Mage"}, {"deck": "Spell Mage"}]}],
    )

    assert decks == [{"deck": "Spell Mage"}]
    assert tiers[0]["decks"] == [{"deck": "Spell Mage"}]


def test_vicious_validator_reports_explicit_upstream_state() -> None:
    report = validate_structured(
        "vicious_syndicate_live_beta",
        {
            "type": "vicious_live",
            "upstream_state": "upstream_unclassified",
            "class_distribution": [{"class": f"Class {index}"} for index in range(11)],
            "deck_distribution": [],
            "tier_list": [],
        },
    )

    assert not report.ok
    assert "vicious_live.upstream_not_ready" in {issue.code for issue in report.issues}


def test_radar_upstream_state_distinguishes_current_stale_and_unknown() -> None:
    assert radar_upstream_state("352", "352") == "ready"
    assert radar_upstream_state("349", "352") == "upstream_stale"
    assert radar_upstream_state("Unknown", "352") == "upstream_unavailable"
