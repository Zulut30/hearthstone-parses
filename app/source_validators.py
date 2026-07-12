from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable


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


def _validate_bg_heroes(structured: dict[str, Any]) -> ValidationReport:
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


def _validate_vicious_live(structured: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
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
        }
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
        min(len(named_archetypes) / 8.0, 1.0) * (1.0 - placeholder_ratio),
        4,
    )
    return report


_VALIDATORS: dict[str, Callable[[dict[str, Any]], ValidationReport]] = {
    "bg_heroes": _validate_bg_heroes,
    "vicious_live": _validate_vicious_live,
}


def validate_structured(source_id: str, structured: dict[str, Any]) -> ValidationReport:
    validator = _VALIDATORS.get(str(structured.get("type") or ""))
    if validator is None:
        return ValidationReport(metrics={"source_id": source_id, "structured_type": structured.get("type")})
    report = validator(structured)
    report.metrics["source_id"] = source_id
    report.metrics["structured_type"] = structured.get("type")
    return report
