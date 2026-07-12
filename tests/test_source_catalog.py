from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.sources import SOURCES


ROOT = Path(__file__).resolve().parent.parent


def test_generated_source_catalog_is_current_and_complete() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/generate-source-catalog.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    catalog = (ROOT / "docs" / "SOURCES.md").read_text(encoding="utf-8")
    assert catalog.count("| `") == len(SOURCES)
    assert "44 scrape + 2 pipeline" in catalog
