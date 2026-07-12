from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_uses_node24_compatible_official_actions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v6" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "persist-credentials: false" in workflow
    assert "contents: read" in workflow
    assert "pip install -r requirements-dev.txt" in workflow
    assert "docker build --no-cache --tag hs-data-api:ci ." in workflow
