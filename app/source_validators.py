from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import re
from typing import Any, Callable

from .quality_thresholds import threshold_for


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: str = "error"
    field: str | None = None


@dataclass
class ValidationReport:
    ok: bool = True
    score: float = 1.0
    issues: list[ValidationIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def add_issue(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
        severity: str = "error",
    ) -> None:
        self.issues.append(
            ValidationIssue(code=code, message=message, field=field, severity=severity)
        )
        if severity == "error":
            self.ok = False

    @property
    def reason(self) -> str:
        return "; ".join(issue.message for issue in self.issues) or "ok"


def _parse_percent(value: Any) -> float | None:
    raw = str(value or "").strip().replace(",", ".")
    if raw.endswith("%"):
        raw = raw[:-1]
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_decimal(value: Any) -> float | None:
    raw = str(value or "").strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _valid_name(value: Any) -> bool:
    return str(value or "").strip() not in {"", "-", "—", "Unknown"}


def _validate_bg_heroes(_source_id: str, structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    heroes = [row for row in (structured.get("heroes") or []) if isinstance(row, dict)]
    row_count = len(heroes)
    names = [str(row.get("hero") or "").strip() for row in heroes]
    dbf_ids = [row.get("dbfId") for row in heroes if row.get("dbfId") is not None]
    avg_values = [_parse_decimal(row.get("avg_placement")) for row in heroes]
    pick_rates = [_parse_percent(row.get("pick_rate")) for row in heroes]
    distributions = [
        row.get("placement_distribution")
        for row in heroes
        if isinstance(row.get("placement_distribution"), list)
    ]
    valid_names = sum(1 for name in names if _valid_name(name))
    valid_avg = sum(1 for value in avg_values if value is not None and 1.0 <= value <= 8.0)
    valid_pick = sum(1 for value in pick_rates if value is not None and value >= 0.0)
    valid_distributions = 0
    for dist in distributions:
        if len(dist) != 8:
            continue
        parsed = [_parse_percent(value) for value in dist]
        if any(value is None for value in parsed):
            continue
        total = sum(value for value in parsed if value is not None)
        if 98.0 <= total <= 102.0:
            valid_distributions += 1

    unique_names = len({name for name in names if _valid_name(name)})
    unique_avg = len({round(value, 2) for value in avg_values if value is not None})
    unique_tiers = len({str(row.get("tier") or "").upper() for row in heroes if row.get("tier")})
    unique_dbf = len({int(value) for value in dbf_ids if str(value).isdigit()})

    report.metrics.update(
        {
            "rows": row_count,
            "valid_names": valid_names,
            "unique_names": unique_names,
            "unique_dbf": unique_dbf,
            "valid_avg_placement": valid_avg,
            "unique_avg_placement": unique_avg,
            "valid_pick_rate": valid_pick,
            "valid_distributions": valid_distributions,
            "unique_tiers": unique_tiers,
        }
    )

    if row_count < 30:
        report.add_issue("bg_heroes.too_few_rows", f"bg heroes too few ({row_count} < 30)")
    if valid_names < max(20, int(row_count * 0.7)):
        report.add_issue(
            "bg_heroes.bad_names",
            f"bg heroes valid names too low ({valid_names}/{row_count})",
            field="hero",
        )
    if unique_names < 20:
        report.add_issue(
            "bg_heroes.low_name_diversity",
            f"bg heroes unique names too low ({unique_names})",
            field="hero",
        )
    if unique_dbf < max(20, int(row_count * 0.7)):
        report.add_issue(
            "bg_heroes.low_dbf_diversity",
            f"bg heroes unique dbfIds too low ({unique_dbf}/{row_count})",
            field="dbfId",
        )
    if valid_pick < max(20, int(row_count * 0.7)):
        report.add_issue(
            "bg_heroes.bad_pick_rate",
            f"bg heroes valid pick_rate too low ({valid_pick}/{row_count})",
            field="pick_rate",
        )
    if valid_avg < max(20, int(row_count * 0.7)):
        report.add_issue(
            "bg_heroes.bad_avg_placement",
            f"bg heroes valid avg_placement too low ({valid_avg}/{row_count})",
            field="avg_placement",
        )
    if unique_avg < 10:
        report.add_issue(
            "bg_heroes.low_avg_diversity",
            f"bg heroes avg_placement diversity too low ({unique_avg})",
            field="avg_placement",
        )
    if valid_distributions < max(20, int(row_count * 0.7)):
        report.add_issue(
            "bg_heroes.bad_distribution",
            f"bg heroes valid placement_distribution too low ({valid_distributions}/{row_count})",
            field="placement_distribution",
        )
    if unique_tiers < 2:
        report.add_issue(
            "bg_heroes.low_tier_diversity",
            f"bg heroes tier diversity too low ({unique_tiers})",
            field="tier",
        )

    denominator = max(row_count, 1)
    scores = [
        valid_names / denominator,
        valid_pick / denominator,
        valid_avg / denominator,
        valid_distributions / denominator,
        min(unique_names / 30.0, 1.0),
        min(unique_avg / 10.0, 1.0),
        min(unique_dbf / max(row_count, 1), 1.0),
    ]
    report.score = round(sum(scores) / len(scores), 4)
    return report


def _validate_vicious_live(_source_id: str, structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    class_distribution = [
        row for row in (structured.get("class_distribution") or []) if isinstance(row, dict)
    ]
    tier_list = [
        row for row in (structured.get("tier_list") or []) if isinstance(row, dict)
    ]
    tier_deck_count = sum(len(row.get("decks") or []) for row in tier_list)
    distribution_names = {
        str(row.get("deck") or "").strip()
        for row in (structured.get("deck_distribution") or [])
        if isinstance(row, dict) and _valid_name(row.get("deck"))
    }
    tier_names = {
        str(deck.get("deck") or "").strip()
        for bracket in (structured.get("tier_list") or [])
        if isinstance(bracket, dict)
        for deck in (bracket.get("decks") or [])
        if isinstance(deck, dict) and _valid_name(deck.get("deck"))
    }
    deck_names = distribution_names | tier_names
    placeholder_names = {
        name
        for name in deck_names
        if re.fullmatch(r"(?:Other|Unknown)\s+\S+", name, flags=re.IGNORECASE)
    }
    named_archetypes = deck_names - placeholder_names
    placeholder_ratio = len(placeholder_names) / max(len(deck_names), 1)
    report.metrics.update(
        {
            "unique_decks": len(deck_names),
            "named_archetypes": len(named_archetypes),
            "placeholder_decks": len(placeholder_names),
            "placeholder_ratio": round(placeholder_ratio, 4),
            "classes": len(class_distribution),
            "tier_brackets": len(tier_list),
            "tier_decks": tier_deck_count,
        }
    )

    if len(class_distribution) < 8:
        report.add_issue(
            "vicious_live.too_few_classes",
            f"vicious live too few classes ({len(class_distribution)} < 8)",
            field="class_distribution",
        )
    if len(tier_list) < 3 or tier_deck_count < 20:
        report.add_issue(
            "vicious_live.too_few_tier_decks",
            f"vicious live tier data too small ({len(tier_list)} brackets, {tier_deck_count} decks)",
            field="tier_list",
        )
    if len(named_archetypes) < 3:
        report.add_issue(
            "vicious_live.too_few_named_archetypes",
            f"vicious live named archetypes too few ({len(named_archetypes)} < 3)",
            field="deck",
        )
    if placeholder_ratio > 0.75:
        report.add_issue(
            "vicious_live.placeholder_dominated",
            f"vicious live placeholder decks dominate ({len(placeholder_names)}/{len(deck_names)})",
            field="deck",
        )
    report.score = round(
        sum(
            (
                min(len(class_distribution) / 8.0, 1.0),
                min(len(tier_list) / 3.0, 1.0),
                min(tier_deck_count / 20.0, 1.0),
                min(len(named_archetypes) / 8.0, 1.0) * (1.0 - placeholder_ratio),
            )
        )
        / 4,
        4,
    )
    return report


def _validate_vicious_radars(_source_id: str, structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    issue_raw = str(structured.get("issue") or "")
    latest_issue_raw = str(structured.get("latest_report_issue") or "")
    issue = int(issue_raw) if issue_raw.isdigit() else None
    latest_issue = int(latest_issue_raw) if latest_issue_raw.isdigit() else None
    published_raw = str(structured.get("latest_report_published_at") or "")
    content_age_days: int | None = None
    try:
        published_at = datetime.fromisoformat(published_raw)
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
        content_age_days = max(0, (datetime.now(UTC) - published_at).days)
    except ValueError:
        pass
    report.metrics.update(
        {
            "radar_issue": issue,
            "latest_report_issue": latest_issue,
            "latest_report_published_at": published_raw or None,
            "content_age_days": content_age_days,
        }
    )

    if issue is None or latest_issue is None:
        report.add_issue(
            "vicious_radars.missing_issue_freshness",
            "vicious radars missing active/latest report issue metadata",
            field="issue",
        )
    elif issue < latest_issue:
        report.add_issue(
            "vicious_radars.outdated_issue",
            f"vicious radar issue is outdated ({issue} < {latest_issue})",
            field="issue",
        )
    if content_age_days is None:
        report.add_issue(
            "vicious_radars.missing_published_at",
            "vicious latest report publication date is missing or invalid",
            field="latest_report_published_at",
        )
    elif content_age_days > 21:
        report.add_issue(
            "vicious_radars.stale_content",
            f"vicious latest report content is stale ({content_age_days} days > 21)",
            field="latest_report_published_at",
        )
    issue_score = 1.0 if issue is not None and issue == latest_issue else 0.0
    age_score = 1.0 if content_age_days is not None and content_age_days <= 21 else 0.0
    report.score = (issue_score + age_score) / 2
    return report


def _validate_arena_class_matrix(_source_id: str, structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    classes = [row for row in (structured.get("classes") or []) if isinstance(row, dict)]
    report.metrics["classes"] = len(classes)
    if len(classes) < 8:
        report.add_issue(
            "arena_class_matrix.too_few_classes",
            f"arena class stats too few ({len(classes)} < 8)",
            field="classes",
        )
    report.score = round(min(len(classes) / 8.0, 1.0), 4)
    return report


def _validate_arena_class_pages(_source_id: str, structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    classes = [row for row in (structured.get("classes") or []) if isinstance(row, dict)]
    with_stats = sum(
        1
        for row in classes
        if row.get("win_rate") is not None and row.get("pick_rate") is not None
    )
    report.metrics.update({"classes": len(classes), "classes_with_stats": with_stats})
    if len(classes) < 10:
        report.add_issue(
            "arena_class_pages.too_few_classes",
            f"arena class pages too few ({len(classes)} < 10)",
            field="classes",
        )
    if with_stats < 10:
        report.add_issue(
            "arena_class_pages.missing_stats",
            f"arena class pages missing stats ({with_stats}/{len(classes)}; minimum 10)",
            field="win_rate,pick_rate",
        )
    report.score = round(
        (min(len(classes) / 10.0, 1.0) + min(with_stats / 10.0, 1.0)) / 2,
        4,
    )
    return report


def _validate_arena_winning_decks(_source_id: str, structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    decks = [row for row in (structured.get("decks") or []) if isinstance(row, dict)]
    with_final_deck = sum(1 for row in decks if row.get("final_deck"))
    report.metrics.update({"decks": len(decks), "decks_with_final_deck": with_final_deck})
    if not decks:
        report.add_issue(
            "arena_winning_decks.empty",
            "arena winning decks empty",
            field="decks",
        )
    if with_final_deck < 1:
        report.add_issue(
            "arena_winning_decks.missing_final_deck",
            "arena winning decks missing final_deck",
            field="final_deck",
        )
    report.score = 1.0 if decks and with_final_deck else 0.0
    return report


def _validate_arena_legendary_groups(_source_id: str, structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    groups = [row for row in (structured.get("groups") or []) if isinstance(row, dict)]
    with_key_card = sum(1 for row in groups if row.get("key_card"))
    report.metrics.update({"groups": len(groups), "groups_with_key_card": with_key_card})
    if len(groups) < 10:
        report.add_issue(
            "arena_legendary_groups.too_few_groups",
            f"legendary groups too few ({len(groups)} < 10)",
            field="groups",
        )
    if with_key_card < 1:
        report.add_issue(
            "arena_legendary_groups.missing_key_card",
            "legendary groups missing key_card",
            field="key_card",
        )
    report.score = round(
        (min(len(groups) / 10.0, 1.0) + min(with_key_card, 1)) / 2,
        4,
    )
    return report


def _validate_bg_comps(_source_id: str, structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    comps = [row for row in (structured.get("comps") or []) if isinstance(row, dict)]
    with_cards = sum(
        1 for row in comps if row.get("main_cards") or row.get("additional_cards")
    )
    minimum_with_cards = max(3, len(comps) // 2)
    report.metrics.update(
        {
            "comps": len(comps),
            "comps_with_cards": with_cards,
            "minimum_with_cards": minimum_with_cards,
        }
    )
    if len(comps) < 3:
        report.add_issue(
            "bg_comps.too_few_comps",
            f"bg comps too few ({len(comps)} < 3)",
            field="comps",
        )
    if with_cards < minimum_with_cards:
        report.add_issue(
            "bg_comps.mostly_empty",
            f"bg comps mostly empty ({with_cards}/{len(comps)} with cards; minimum {minimum_with_cards})",
            field="main_cards,additional_cards",
        )
    report.score = round(
        (min(len(comps) / 3.0, 1.0) + min(with_cards / max(minimum_with_cards, 1), 1.0)) / 2,
        4,
    )
    return report


def _validate_bg_card_stats(_source_id: str, structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    tiers = structured.get("tiers") or {}
    cards = [
        card
        for tier_cards in tiers.values()
        if isinstance(tier_cards, list)
        for card in tier_cards
        if isinstance(card, dict)
    ] if isinstance(tiers, dict) else []
    with_stats = sum(
        1
        for card in cards
        if card.get("average_placement") is not None or card.get("total_played")
    )
    report.metrics.update({"cards": len(cards), "cards_with_stats": with_stats})
    if len(cards) < 50:
        report.add_issue(
            "bg_card_stats.too_few_cards",
            f"bg card stats too few ({len(cards)} < 50)",
            field="tiers",
        )
    if with_stats < 40:
        report.add_issue(
            "bg_card_stats.missing_stats",
            f"bg card stats missing placement stats ({with_stats}/{len(cards)}; minimum 40)",
            field="average_placement,total_played",
        )
    report.score = round(
        (min(len(cards) / 50.0, 1.0) + min(with_stats / 40.0, 1.0)) / 2,
        4,
    )
    return report


def _validate_bg_trinkets(_source_id: str, structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    trinkets = [row for row in (structured.get("trinkets") or []) if isinstance(row, dict)]
    valid = [
        row
        for row in trinkets
        if row.get("pick_rate")
        and len(str(row.get("name") or "")) >= 4
        and str(row.get("name") or "")[:1].isalnum()
    ]
    minimum_valid = max(6, len(trinkets) // 2)
    report.metrics.update(
        {
            "trinkets": len(trinkets),
            "valid_trinkets": len(valid),
            "minimum_valid": minimum_valid,
        }
    )
    if len(trinkets) < 8:
        report.add_issue(
            "bg_trinkets.too_few_rows",
            f"bg trinkets too few ({len(trinkets)} < 8)",
            field="trinkets",
        )
    if len(valid) < minimum_valid:
        report.add_issue(
            "bg_trinkets.invalid_names_or_stats",
            f"bg trinkets invalid names/stats ({len(valid)}/{len(trinkets)}; minimum {minimum_valid})",
            field="name,pick_rate",
        )
    report.score = round(
        (min(len(trinkets) / 8.0, 1.0) + min(len(valid) / max(minimum_valid, 1), 1.0)) / 2,
        4,
    )
    return report


def _validate_bg_minions(_source_id: str, structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    minions = [row for row in (structured.get("minions") or []) if isinstance(row, dict)]
    with_stats = sum(
        1
        for row in minions
        if row.get("impact") is not None and row.get("win_share") and row.get("popularity")
    )
    report.metrics.update({"minions": len(minions), "minions_with_stats": with_stats})
    if len(minions) < 50:
        report.add_issue(
            "bg_minions.too_few_rows",
            f"bg minions too few ({len(minions)} < 50)",
            field="minions",
        )
    if with_stats < 40:
        report.add_issue(
            "bg_minions.missing_stats",
            f"bg minions missing stats ({with_stats}/{len(minions)}; minimum 40)",
            field="impact,win_share,popularity",
        )
    report.score = round(
        (min(len(minions) / 50.0, 1.0) + min(with_stats / 40.0, 1.0)) / 2,
        4,
    )
    return report


def _validate_bg_compositions(_source_id: str, structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    compositions = [
        row for row in (structured.get("compositions") or []) if isinstance(row, dict)
    ]
    with_stats = sum(
        1
        for row in compositions
        if row.get("first_place")
        and row.get("avg_placement") is not None
        and row.get("popularity")
    )
    report.metrics.update(
        {"compositions": len(compositions), "compositions_with_stats": with_stats}
    )
    if len(compositions) < 5:
        report.add_issue(
            "bg_compositions.too_few_rows",
            f"bg compositions too few ({len(compositions)} < 5)",
            field="compositions",
        )
    if with_stats < 5:
        report.add_issue(
            "bg_compositions.missing_stats",
            f"bg compositions missing stats ({with_stats}/{len(compositions)}; minimum 5)",
            field="first_place,avg_placement,popularity",
        )
    report.score = round(
        (min(len(compositions) / 5.0, 1.0) + min(with_stats / 5.0, 1.0)) / 2,
        4,
    )
    return report


def _validate_arena_card_tiers(source_id: str, structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    cards = [row for row in (structured.get("cards") or []) if isinstance(row, dict)]
    default_min = 20 if "legendary" in source_id else 100
    minimum_cards = int(threshold_for(source_id, "arena_card_tiers_min", default_min))
    has_tier_labels = "firestone" in source_id or any(
        row.get("tier")
        or row.get("win_rate") is not None
        or row.get("deck_winrate")
        for row in cards[:50]
    )
    report.metrics.update(
        {
            "cards": len(cards),
            "minimum_cards": minimum_cards,
            "has_tier_labels": has_tier_labels,
        }
    )
    if len(cards) < minimum_cards:
        report.add_issue(
            "arena_card_tiers.too_few_cards",
            f"arena card tiers too few ({len(cards)} < {minimum_cards})",
            field="cards",
        )
    if not has_tier_labels:
        report.add_issue(
            "arena_card_tiers.missing_tier_labels",
            "arena card tiers missing tier labels",
            field="tier,win_rate,deck_winrate",
        )
    report.score = round(
        (min(len(cards) / max(minimum_cards, 1), 1.0) + float(has_tier_labels)) / 2,
        4,
    )
    return report


def _validate_heartharena_tierlist(
    _source_id: str,
    structured: dict[str, Any],
) -> ValidationReport:
    report = ValidationReport()
    classes = [row for row in (structured.get("classes") or []) if isinstance(row, dict)]
    total_cards = int(structured.get("total_cards") or 0)
    with_tier = sum(
        1
        for class_row in classes
        for card in (class_row.get("cards") or [])
        if isinstance(card, dict) and card.get("tier_id")
    )
    report.metrics.update(
        {"classes": len(classes), "total_cards": total_cards, "cards_with_tier_id": with_tier}
    )
    if len(classes) < 5:
        report.add_issue(
            "heartharena_tierlist.too_few_classes",
            f"heartharena classes too few ({len(classes)} < 5)",
            field="classes",
        )
    if total_cards < 300:
        report.add_issue(
            "heartharena_tierlist.too_few_cards",
            f"heartharena cards too few ({total_cards} < 300)",
            field="total_cards",
        )
    if with_tier < 200:
        report.add_issue(
            "heartharena_tierlist.missing_tier_ids",
            f"heartharena cards missing tier_id ({with_tier} < 200)",
            field="tier_id",
        )
    report.score = round(
        (
            min(len(classes) / 5.0, 1.0)
            + min(total_cards / 300.0, 1.0)
            + min(with_tier / 200.0, 1.0)
        )
        / 3,
        4,
    )
    return report


_VALIDATORS: dict[str, Callable[[str, dict[str, Any]], ValidationReport]] = {
    "bg_heroes": _validate_bg_heroes,
    "vicious_live": _validate_vicious_live,
    "vicious_syndicate_radars": _validate_vicious_radars,
    "arena_class_matrix": _validate_arena_class_matrix,
    "arena_class_pages": _validate_arena_class_pages,
    "arena_winning_decks": _validate_arena_winning_decks,
    "arena_legendary_groups": _validate_arena_legendary_groups,
    "bg_comps": _validate_bg_comps,
    "bg_card_stats": _validate_bg_card_stats,
    "bg_trinkets": _validate_bg_trinkets,
    "bg_minions": _validate_bg_minions,
    "bg_compositions": _validate_bg_compositions,
    "arena_card_tiers": _validate_arena_card_tiers,
    "heartharena_tierlist": _validate_heartharena_tierlist,
}


def validate_structured(source_id: str, structured: dict[str, Any]) -> ValidationReport:
    validator = _VALIDATORS.get(str(structured.get("type") or ""))
    if validator is None:
        return ValidationReport(metrics={"source_id": source_id, "structured_type": structured.get("type")})
    report = validator(source_id, structured)
    report.metrics["source_id"] = source_id
    report.metrics["structured_type"] = structured.get("type")
    return report
