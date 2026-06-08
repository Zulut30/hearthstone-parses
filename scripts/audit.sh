#!/usr/bin/env bash
# Audit parser cache health and re-run quality checks on stored datasets.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV="${VENV_PYTHON:-$ROOT/venv/bin/python}"
if [[ ! -x "$VENV" ]]; then
  VENV=python3
fi

export HS_API_DATA_DIR="${HS_API_DATA_DIR:-/var/lib/hs-data-api}"

echo "=== HS Data API audit ==="
echo "Data dir: $HS_API_DATA_DIR"
echo

echo "=== Unit tests ==="
if "$VENV" -m unittest discover -s tests -p 'test_*.py' -q 2>/dev/null; then
  echo "tests: OK"
else
  echo "tests: FAILED or skipped (install dependencies in venv)"
fi
echo

"$VENV" -m app.cli proxy-check 2>/dev/null || echo "(proxy-check skipped)"
"$VENV" -m app.cli preflight 2>/dev/null || echo "(preflight skipped)"

echo
"$VENV" <<'PY'
from app.cli import load_env_file
load_env_file()

from pathlib import Path

from app.config import data_dir
from app.sources import SOURCES
from app.storage import load_dataset, load_status
from app.scrapers.quality import validate_parsed_data

ok_n = fail_n = missing_n = 0
rows = []

for source in SOURCES:
    st = load_status(source.id) or {}
    ds = load_dataset(source.id)
    if not ds:
        rows.append((source.id, "missing", "-", "no dataset"))
        missing_n += 1
        continue
    data = ds.get("data") or {}
    valid, reason = validate_parsed_data(source, data)
    state = st.get("state", "?")
    backend = st.get("backend") or data.get("_backend") or "-"
    flag = "OK" if valid and state == "ok" else "WARN"
    if not valid or state != "ok":
        fail_n += 1
    else:
        ok_n += 1
    rows.append((source.id, flag, state, f"{backend} | {reason if not valid else 'ok'}"))

print(f"Data dir: {Path(data_dir())}")
print(f"Sources in config: {len(SOURCES)}")
print(f"Strict quality OK: {ok_n} | Issues: {fail_n} | Missing cache: {missing_n}")
print()
for sid, flag, state, detail in rows:
    if flag != "OK":
        print(f"  [{flag}] {sid}: status={state} - {detail}")

try:
    import httpx
    r = httpx.get("http://127.0.0.1:8000/health", timeout=3.0)
    print()
    print("HTTP /health:", r.status_code, r.text[:200])
except Exception as e:
    print()
    print("HTTP /health: not reachable (%s)" % e)
PY
