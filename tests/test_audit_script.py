from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent.parent


def test_audit_propagates_pytest_failure(tmp_path: Path) -> None:
    failing_python = tmp_path / "failing-python"
    failing_python.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
    failing_python.chmod(0o755)
    env = dict(os.environ)
    env["VENV_PYTHON"] = str(failing_python)

    result = subprocess.run(
        ["bash", "scripts/audit.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "tests: FAILED (pytest exit 2)" in result.stdout
