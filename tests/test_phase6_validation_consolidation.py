from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_threshold_inventory_has_no_unresolved_rows() -> None:
    inventory = (ROOT / "plans/phase6-thresholds.md").read_text(encoding="utf-8")

    assert "| pending |" not in inventory
    assert "duplicated;" not in inventory


def test_quality_module_has_no_per_structured_type_dispatch() -> None:
    quality = (ROOT / "app/scrapers/quality.py").read_text(encoding="utf-8")

    assert 'structured.get("type") ==' not in quality


def test_browser_rotators_cannot_bypass_publish_gate() -> None:
    for relative_path in ("app/rotator.py", "app/scrapers/rotator.py"):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "validate_candidate_for_publish" in source
        assert "validate_parsed_data" not in source
