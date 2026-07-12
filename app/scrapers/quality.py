from __future__ import annotations

import re
from typing import Any

from ..quality_thresholds import threshold_for
from ..refresh_log import log_action
from ..source_contracts import contract_quality_ok, contract_quality_report, get_contract
from ..source_validators import validate_structured
from ..sources import Source

CF_MARKERS = (
    "just a moment",
    "challenges.cloudflare.com",
    "cf-chl",
    "cloudflare challenge",
    "attention required",
)


def _log_quality_action(action: str, **kwargs: Any) -> None:
    try:
        log_action(action, **kwargs)
    except Exception:
        return


def is_cloudflare_challenge(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in CF_MARKERS)


def looks_like_real_page(html: str, source: Source) -> bool:
    if is_cloudflare_challenge(html):
        return False
    contract = get_contract(source.id)
    min_html_bytes = contract.min_html_bytes if contract else 2_000
    if len(html) < min_html_bytes:
        return False
    if source.site == "hsreplay":
        return bool(
            re.search(
                r"hsreplay\.net|userdata|__NEXT_DATA__|react-root|battlegrounds|arena",
                html,
                re.I,
            )
        )
    if source.site == "hsguru":
        return bool(
            re.search(r"hsguru\.com|archetype|matchup|streamer|meta|canvas", html, re.I)
        ) and "just a moment" not in html.lower()
    return True


def quality_metrics(source: Source, parsed: dict[str, Any]) -> dict[str, Any]:
    tables = parsed.get("tables") or []
    structured = parsed.get("structured") or parsed.get("hsreplay_extracted") or {}
    cards = structured.get("cards") or []
    radars = structured.get("radars") or []
    contract_report = contract_quality_report(source.id, structured) if structured else {}
    semantic_report = validate_structured(source.id, structured) if structured else None
    return {
        "table_rows": sum(len(t.get("objects") or t.get("rows") or []) for t in tables),
        "deck_codes": len(parsed.get("deck_codes") or []),
        "json_scripts": len(parsed.get("json_scripts") or []),
        "text_lines": len(parsed.get("text_preview") or []),
        "structured_type": structured.get("type"),
        "cards": len(cards),
        "cards_with_metrics": sum(
            1 for c in cards if c.get("deck_winrate") or c.get("deck_popularity")
        ),
        "radars": len(radars),
        "radars_with_graph": sum(1 for r in radars if r.get("nodes") or r.get("edges")),
        "blocked_marker": bool(structured.get("blocked")),
        "rows_total": contract_report.get("rows_total"),
        "critical_fields": contract_report.get("critical_fields"),
        "quality_score": contract_report.get("quality_score"),
        "missing_critical_fields": contract_report.get("warnings"),
        "semantic_score": semantic_report.score if semantic_report else None,
        "semantic_metrics": semantic_report.metrics if semantic_report else None,
        "semantic_issues": [
            {
                "code": issue.code,
                "field": issue.field,
                "severity": issue.severity,
                "message": issue.message,
            }
            for issue in (semantic_report.issues if semantic_report else [])
        ],
    }


def validate_parsed_data(source: Source, parsed: dict[str, Any]) -> tuple[bool, str]:
    title = (parsed.get("title") or "").lower()
    if "just a moment" in title or not title:
        return False, "invalid title"

    tables = parsed.get("tables") or []
    table_rows = sum(len(t.get("objects") or t.get("rows") or []) for t in tables)
    deck_codes = parsed.get("deck_codes") or []
    json_scripts = parsed.get("json_scripts") or []
    text_lines = parsed.get("text_preview") or []
    structured = parsed.get("structured") or parsed.get("hsreplay_extracted") or {}
    if structured:
        contract_ok, contract_reason, _contract_report = contract_quality_ok(
            source.id, structured
        )
        if not contract_ok:
            _log_quality_action(
                "source_contract.validate.fail",
                source_id=source.id,
                level="warn",
                detail=contract_reason,
                extra={"quality_report": _contract_report},
            )
            if _contract_report.get("critical_fields"):
                _log_quality_action(
                    "quality.field_fill.warn",
                    source_id=source.id,
                    level="warn",
                    detail=contract_reason,
                    extra={"critical_fields": _contract_report.get("critical_fields")},
                )
            return False, f"source contract failed: {contract_reason}"
        semantic_report = validate_structured(source.id, structured)
        if not semantic_report.ok:
            _log_quality_action(
                "source_semantic.validate.fail",
                source_id=source.id,
                level="warn",
                detail=semantic_report.reason,
                extra={
                    "semantic_score": semantic_report.score,
                    "semantic_metrics": semantic_report.metrics,
                    "semantic_issues": [
                        {
                            "code": issue.code,
                            "field": issue.field,
                            "severity": issue.severity,
                            "message": issue.message,
                        }
                        for issue in semantic_report.issues
                    ],
                },
            )
            return False, f"source semantic validation failed: {semantic_report.reason}"

    if source.site == "hsguru":
        if source.category == "meta":
            min_rows = int(threshold_for(source.id, "meta_table_rows_min", 5))
            if table_rows < min_rows:
                return False, f"meta table too small ({table_rows} rows)"
            return True, "ok"
        if source.category == "streamer_decks":
            if len(deck_codes) < 2 and table_rows < 3:
                return False, "streamer decks missing codes/rows"
            return True, "ok"
        if source.category == "matchups":
            if table_rows < 3 and len(text_lines) < 30:
                return False, "matchups data too sparse"
            if not any("matchup" in line.lower() or "%" in line for line in text_lines[:80]):
                return False, "matchups content not detected"
            return True, "ok"

    if source.site == "vicious-syndicate":
        return True, "ok"

    if source.site in ("hsreplay", "firestone", "heartharena"):
        if structured.get("type") == "card_stats":
            cards = structured.get("cards") or []
            if structured.get("blocked") and len(cards) < 10:
                return False, "card stats blocked or empty"
            if len(cards) < 30:
                return False, f"card stats too few ({len(cards)})"
            with_metrics = sum(
                1 for c in cards if c.get("deck_winrate") or c.get("deck_popularity")
            )
            if with_metrics < 20:
                return False, f"card stats missing metrics ({with_metrics}/{len(cards)})"
            return True, "ok"
        if structured.get("type") == "hsreplay_meta_archetypes":
            classes = structured.get("classes") or []
            archetypes = [
                archetype
                for class_group in classes
                for archetype in (class_group.get("archetypes") or [])
            ]
            if len(classes) < 8:
                return False, f"meta archetypes too few classes ({len(classes)})"
            if len(archetypes) < 20:
                return False, f"meta archetypes too few rows ({len(archetypes)})"
            with_metrics = sum(
                1
                for archetype in archetypes
                if archetype.get("winrate") and archetype.get("popularity") and archetype.get("games")
            )
            if with_metrics < 20:
                return False, f"meta archetypes missing metrics ({with_metrics}/{len(archetypes)})"
            return True, "ok"
        if structured and get_contract(source.id) is not None:
            return True, "ok"
        if any("could not load data" in line.lower() for line in text_lines):
            return False, "hsreplay premium data not loaded (login required)"
        if source.id.startswith("hsreplay_cards_"):
            if "rankrange=gold" not in (source.fragment or "").lower():
                for script in json_scripts:
                    if script.get("id") != "userdata":
                        continue
                    user = (script.get("value") or {})
                    if isinstance(user, str):
                        continue
                    if not (user.get("user") or {}).get("is_authenticated"):
                        return False, "hsreplay session not authenticated"
                if not any("%" in line for line in text_lines[100:200]):
                    return False, "hsreplay cards stats not found in page"
        has_userdata = any(s.get("id") == "userdata" for s in json_scripts)
        if has_userdata or table_rows >= 3 or len(text_lines) >= 40:
            return True, "ok"
        return False, "hsreplay page missing userdata/tables/content"

    if structured and get_contract(source.id) is not None:
        return True, "ok"
    return len(text_lines) >= 10, "minimal content check"
