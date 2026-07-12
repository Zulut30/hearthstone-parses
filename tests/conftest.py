from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile

# Make `app` importable when pytest is run from any cwd (repo root layout).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# Collection imports can initialize storage-backed modules before fixtures run.
# Give every pytest session an isolated data root up front so tests never read or
# write production parser state from /var/lib/hs-data-api.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="hs-data-api-tests-")
os.environ["HS_API_DATA_DIR"] = _TEST_DATA_DIR
os.environ["PYTHON_ENV"] = "test"


def pytest_sessionfinish(session, exitstatus) -> None:  # type: ignore[no-untyped-def]
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)
