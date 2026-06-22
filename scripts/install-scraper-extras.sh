#!/usr/bin/env bash
# Optional stealth backends: CloakBrowser, Scrapling, Apify fingerprint-suite (Node).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${VENV:-$ROOT/venv}"

if [[ ! -x "$VENV/bin/pip" ]]; then
  python3 -m venv "$VENV"
fi

echo "=== pip: scraper extras ==="
"$VENV/bin/pip" install -U pip -q
"$VENV/bin/pip" install -r "$ROOT/requirements-scraper.txt" -q

echo "=== patchright chromium ==="
"$VENV/bin/patchright" install chromium 2>/dev/null || "$VENV/bin/python" -m patchright install chromium

echo "=== CloakBrowser binary ==="
"$VENV/bin/python" -m cloakbrowser install 2>/dev/null || true

echo "=== Scrapling browsers ==="
if command -v "$VENV/bin/scrapling" >/dev/null 2>&1; then
  "$VENV/bin/scrapling" install 2>/dev/null || true
fi

echo "=== fingerprint-suite (Node) ==="
FP_DIR="$ROOT/scripts/fingerprint-node"
if command -v npm >/dev/null 2>&1 && [[ -f "$FP_DIR/package.json" ]]; then
  (cd "$FP_DIR" && npm install --omit=dev -q 2>/dev/null) || true
  node "$FP_DIR/generate.mjs" >/dev/null && echo "fingerprint-suite OK" || echo "fingerprint-suite skipped (run npm install in scripts/fingerprint-node)"
fi

echo "=== Xvfb (headed CloakBrowser) ==="
"$(dirname "$0")/ensure-xvfb.sh" 2>/dev/null || true

echo "=== Done ==="
