#!/usr/bin/env bash
# Import migration bundle from export-bundle.sh
# Usage: sudo ./scripts/import-bundle.sh hs-data-api-bundle-YYYYMMDD.tar.gz
set -euo pipefail

ARCHIVE="${1:?Usage: import-bundle.sh <archive.tar.gz>}"
DATA_DIR="${HS_API_DATA_DIR:-/var/lib/hs-data-api}"
ENV_FILE="${HS_ENV_FILE:-/etc/hs-data-api.env}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

tar -xzf "$ARCHIVE" -C "$TMP"
B="$TMP/bundle"
[[ -d "$B" ]] || { echo "Invalid bundle layout"; exit 1; }

mkdir -p "$DATA_DIR/datasets" "$DATA_DIR/statuses"

if [[ -f "$B/hs-data-api.env" ]]; then
  if [[ -f "$ENV_FILE" ]]; then
    cp "$ENV_FILE" "${ENV_FILE}.bak.$(date +%s)"
  fi
  cp "$B/hs-data-api.env" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Installed $ENV_FILE"
fi

for sub in datasets statuses; do
  if [[ -d "$B/$sub" ]]; then
    cp -a "$B/$sub/." "$DATA_DIR/$sub/"
    echo "Restored $DATA_DIR/$sub"
  fi
done

for f in hsreplay-auth.json hearthstonejson.cards.enUS.json hearthstonejson.cards.ruRU.json; do
  [[ -f "$B/$f" ]] && cp "$B/$f" "$DATA_DIR/$f" && echo "Restored $DATA_DIR/$f"
done

echo "Import complete. Restart API and verify: python -m app.cli proxy-check && ./scripts/audit.sh"
