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

"$VENV" -m app.cli proxy-check 2>/dev/null || echo "(proxy-check skipped)"

echo
"$VENV" <<'PY'
from app.cli import load_env_file
load_env_file()
import json
from pathlib import Path
from app.sources import SOURCES, SOURCE_BY_ID
from app.storage import load_dataset, load_status
from app.scrapers.quality import validate_parsed_data

data_dir = Path(__import__("app.config").config.data_dir())
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
    if not valid:
        fail_n += 1
    elif state == "ok":
        ok_n += 1
    else:
        fail_n += 1
    rows.append((source.id, flag, state, f"{backend} | {reason if not valid else 'ok'}"))

print(f"Sources in config: {len(SOURCES)}")
print(f"Strict quality OK: {ok_n} | Issues: {fail_n} | Missing cache: {missing_n}")
print()
for sid, flag, state, detail in rows:
    if flag != "OK":
        print(f"  [{flag}] {sid}: status={state} — {detail}")

# API health if running
try:
    import httpx
    r = httpx.get("http://127.0.0.1:8000/health", timeout=3.0)
    print()
    print("HTTP /health:", r.status_code, r.text[:200])
except Exception as e:
    print()
    print("HTTP /health: not reachable (%s)" % e)
PY
