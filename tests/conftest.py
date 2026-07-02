from __future__ import annotations

import pathlib
import sys

# Make `app` importable when pytest is run from any cwd (repo root layout).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
