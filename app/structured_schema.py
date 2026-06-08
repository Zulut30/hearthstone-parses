from __future__ import annotations

from typing import Any


class StructuredSchemaError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StructuredSchemaError(message)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_card_stats(data: dict[str, Any]) -> None:
    cards = data.get("cards")
    _require(isinstance(cards, list), "card_stats.cards must be a list")
    metric_keys = {
        "deck_popularity",
        "deck_winrate",
        "games_played",
        "copies",
        "winrate_when_drawn",
        "winrate_when_played",
    }
    for idx, card in enumerate(cards):
        _require(isinstance(card, dict), f"card_stats.cards[{idx}] must be an object")
        _require(
            card.get("id") is not None or card.get("dbfId") is not None,
            f"card_stats.cards[{idx}] missing id/dbfId",
        )
    _require(
        any(any(card.get(key) is not None for key in metric_keys) for card in cards if isinstance(card, dict)),
        "card_stats.cards missing all card metrics",
    )


def _validate_bg_heroes(data: dict[str, Any]) -> None:
    heroes = data.get("heroes")
    _require(isinstance(heroes, list), "bg_heroes.heroes must be a list")
    for idx, hero in enumerate(heroes):
        _require(isinstance(hero, dict), f"bg_heroes.heroes[{idx}] must be an object")
        _require(hero.get("hero") or hero.get("name"), f"bg_heroes.heroes[{idx}] missing hero")
        if hero.get("placement_distribution") is not None:
            _require(
                isinstance(hero["placement_distribution"], list),
                f"bg_heroes.heroes[{idx}].placement_distribution must be a list",
            )


def _validate_bg_minions(data: dict[str, Any]) -> None:
    minions = data.get("minions")
    _require(isinstance(minions, list), "bg_minions.minions must be a list")
    for idx, minion in enumerate(minions):
        _require(isinstance(minion, dict), f"bg_minions.minions[{idx}] must be an object")
        _require(minion.get("minion") or minion.get("name"), f"bg_minions.minions[{idx}] missing name")
        _require("impact" in minion, f"bg_minions.minions[{idx}] missing impact")


def _validate_bg_compositions(data: dict[str, Any]) -> None:
    comps = data.get("compositions")
    _require(isinstance(comps, list), "bg_compositions.compositions must be a list")
    for idx, comp in enumerate(comps):
        _require(isinstance(comp, dict), f"bg_compositions.compositions[{idx}] must be an object")
        _require(comp.get("type"), f"bg_compositions.compositions[{idx}] missing type")
        _require("avg_placement" in comp, f"bg_compositions.compositions[{idx}] missing avg_placement")
        if comp.get("placement_distribution") is not None:
            _require(
                isinstance(comp["placement_distribution"], list),
                f"bg_compositions.compositions[{idx}].placement_distribution must be a list",
            )


def _validate_arena_card_tiers(data: dict[str, Any]) -> None:
    cards = data.get("cards")
    _require(isinstance(cards, list), "arena_card_tiers.cards must be a list")
    for idx, card in enumerate(cards):
        _require(isinstance(card, dict), f"arena_card_tiers.cards[{idx}] must be an object")
        _require(card.get("name"), f"arena_card_tiers.cards[{idx}] missing name")


def _validate_vicious_live(data: dict[str, Any]) -> None:
    _require(isinstance(data.get("class_distribution"), list), "vicious_live.class_distribution must be a list")
    _require(isinstance(data.get("deck_distribution"), list), "vicious_live.deck_distribution must be a list")
    tier_list = data.get("tier_list")
    _require(isinstance(tier_list, list), "vicious_live.tier_list must be a list")
    for idx, bracket in enumerate(tier_list):
        _require(isinstance(bracket, dict), f"vicious_live.tier_list[{idx}] must be an object")
        _require(bracket.get("rank_bracket"), f"vicious_live.tier_list[{idx}] missing rank_bracket")
        _require(isinstance(bracket.get("decks"), list), f"vicious_live.tier_list[{idx}].decks must be a list")


def _validate_hsreplay_meta_archetypes(data: dict[str, Any]) -> None:
    classes = data.get("classes")
    _require(isinstance(classes, list), "hsreplay_meta_archetypes.classes must be a list")
    for class_idx, class_group in enumerate(classes):
        _require(isinstance(class_group, dict), f"hsreplay_meta_archetypes.classes[{class_idx}] must be an object")
        _require(_is_non_empty_string(class_group.get("class")), f"classes[{class_idx}] missing class")
        archetypes = class_group.get("archetypes")
        _require(isinstance(archetypes, list), f"classes[{class_idx}].archetypes must be a list")
        for arch_idx, archetype in enumerate(archetypes):
            _require(isinstance(archetype, dict), f"classes[{class_idx}].archetypes[{arch_idx}] must be an object")
            _require(archetype.get("archetype_id") is not None, f"classes[{class_idx}].archetypes[{arch_idx}] missing archetype_id")
            _require(archetype.get("archetype"), f"classes[{class_idx}].archetypes[{arch_idx}] missing archetype")
            _require(archetype.get("winrate"), f"classes[{class_idx}].archetypes[{arch_idx}] missing winrate")
            _require(archetype.get("popularity"), f"classes[{class_idx}].archetypes[{arch_idx}] missing popularity")
            _require(archetype.get("games") is not None, f"classes[{class_idx}].archetypes[{arch_idx}] missing games")


_VALIDATORS = {
    "arena_card_tiers": _validate_arena_card_tiers,
    "bg_compositions": _validate_bg_compositions,
    "bg_heroes": _validate_bg_heroes,
    "bg_minions": _validate_bg_minions,
    "card_stats": _validate_card_stats,
    "hsreplay_meta_archetypes": _validate_hsreplay_meta_archetypes,
    "vicious_live": _validate_vicious_live,
}


def validate_structured_schema(structured: dict[str, Any]) -> dict[str, Any]:
    stype = structured.get("type")
    _require(_is_non_empty_string(stype), "structured.type is required")
    validator = _VALIDATORS.get(str(stype))
    if validator is None:
        return {"ok": True, "type": stype, "validated": False, "reason": "no schema registered"}
    validator(structured)
    return {"ok": True, "type": stype, "validated": True}
