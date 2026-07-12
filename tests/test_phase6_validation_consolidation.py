from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_threshold_inventory_has_no_unresolved_rows() -> None:
    inventory = (ROOT / "plans/phase6-thresholds.md").read_text(encoding="utf-8")

    statuses = [
        cells[3].strip().lower()
        for line in inventory.splitlines()
        if line.startswith("|")
        if (cells := [cell for cell in line.strip("|").split("|")])
        and len(cells) == 4
        and cells[0].strip() not in {"Existing rule", "---"}
    ]
    approved_prefixes = (
        "transferred + tested",
        "old weaker branch removed",
        "old branch removed",
        "remains in",
    )

    assert statuses
    assert all(status.startswith(approved_prefixes) for status in statuses)


def test_quality_module_has_no_per_structured_type_dispatch() -> None:
    tree = ast.parse((ROOT / "app/scrapers/quality.py").read_text(encoding="utf-8"))
    structured_type_comparisons = [
        comparison
        for comparison in ast.walk(tree)
        if isinstance(comparison, ast.Compare)
        for node in ast.walk(comparison)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "structured"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "type"
    ]

    assert not structured_type_comparisons


def test_browser_rotators_cannot_bypass_publish_gate() -> None:
    for relative_path in ("app/rotator.py", "app/scrapers/rotator.py"):
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "validate_candidate_for_publish" in calls
        assert "validate_parsed_data" not in calls
