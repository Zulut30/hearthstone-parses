#!/usr/bin/env bash
# Virtual display for CloakBrowser headed mode (HS_CLOAKBROWSER_HEADLESS=false).
set -euo pipefail

DISPLAY_NUM="${HS_CLOAKBROWSER_DISPLAY:-:99}"
export DISPLAY="${DISPLAY_NUM#:}"
DISPLAY=":${DISPLAY}"

if pgrep -f "Xvfb ${DISPLAY}" >/dev/null 2>&1; then
  echo "Xvfb already running on ${DISPLAY}"
  exit 0
fi

if ! command -v Xvfb >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq xvfb
fi

Xvfb "${DISPLAY}" -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
sleep 1
echo "Xvfb started on ${DISPLAY}"
