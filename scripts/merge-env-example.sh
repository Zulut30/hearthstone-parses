#!/usr/bin/env bash
# Append keys from .env.example to /etc/hs-data-api.env when missing (never overwrite values).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${1:-/etc/hs-data-api.env}"
EXAMPLE="${ROOT}/.env.example"

if [[ ! -f "$EXAMPLE" ]]; then
  echo "Missing $EXAMPLE" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$EXAMPLE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE from .env.example"
  exit 0
fi

declare -A existing=()
while IFS= read -r line || [[ -n "$line" ]]; do
  stripped="${line%%#*}"
  stripped="${stripped#"${stripped%%[![:space:]]*}"}"
  [[ -z "$stripped" || "$stripped" != *=* ]] && continue
  key="${stripped%%=*}"
  key="${key%"${key##*[![:space:]]}"}"
  existing["$key"]=1
done < "$ENV_FILE"

added=0
buffer=""
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "${line// }" ]]; then
    continue
  fi
  if [[ "$line" != *=* ]]; then
    continue
  fi
  key="${line%%=*}"
  key="${key%"${key##*[![:space:]]}"}"
  if [[ -z "${existing[$key]:-}" ]]; then
    buffer+="$line"$'\n'
    ((added++)) || true
  fi
done < "$EXAMPLE"

if [[ "$added" -gt 0 ]]; then
  {
    echo ""
    echo "# --- merged from .env.example $(date -u +%Y-%m-%dT%H:%M:%SZ) ---"
    printf "%s" "$buffer"
  } >> "$ENV_FILE"
  echo "Added $added key(s) to $ENV_FILE"
else
  echo "No new keys to add in $ENV_FILE"
fi
