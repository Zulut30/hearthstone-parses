#!/usr/bin/env bash
# Ensure FlareSolverr is running and healthy. Attempt one restart if unhealthy.
# Safe to run from ExecStartPre of refresh units. Exits non-zero only if final state is bad
# (so strict preflight will surface unrecoverable FS problems).
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/hs-data-api}"
COMPOSE_FILE="${COMPOSE_FILE:-$INSTALL_DIR/docker-compose.yml}"
VENV_PYTHON="${VENV_PYTHON:-$INSTALL_DIR/venv/bin/python}"
FS_URL="${HS_FLARESOLVERR_URL:-http://127.0.0.1:8191/v1}"

log() { echo "[ensure-flaresolverr] $*"; }

if [[ ! -x "$VENV_PYTHON" ]]; then
  log "venv python not found at $VENV_PYTHON, falling back to system python3"
  VENV_PYTHON=python3
fi

check_fs() {
  "$VENV_PYTHON" - "$FS_URL" <<'PY'
import asyncio, json, sys, httpx
url = sys.argv[1].rstrip("/")
async def main():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json={"cmd": "sessions.list"})
            r.raise_for_status()
            body = r.json()
        if body.get("status") != "ok":
            print(json.dumps({"ok": False, "detail": body.get("message") or "bad status"}))
            return
        # functional probe (no proxy)
        try:
            pr = await client.post(url, json={"cmd": "request.get", "url": "https://api.ipify.org?format=json", "maxTimeout": 15000}, timeout=20.0)
            pr.raise_for_status()
            pb = pr.json()
            sol = pb.get("solution") or {}
            func = (pb.get("status") == "ok" and int(sol.get("status") or 0) == 200 and "ip" in (sol.get("response") or ""))
            print(json.dumps({"ok": True, "version": body.get("version"), "sessions": len(body.get("sessions") or []), "functional": func}))
        except Exception as e:
            print(json.dumps({"ok": True, "version": body.get("version"), "sessions": len(body.get("sessions") or []), "functional": False, "functional_detail": str(e)[:200]}))
    except Exception as e:
        print(json.dumps({"ok": False, "detail": str(e)[:500]}))
asyncio.run(main())
PY
}

is_healthy() {
  local out
  out=$(check_fs 2>/dev/null || echo '{"ok":false}')
  echo "$out" | python3 -c '
import sys, json
d = json.load(sys.stdin)
ok = bool(d.get("ok"))
func = d.get("functional", True)
sys.exit(0 if (ok and func is not False) else 1)
' >/dev/null 2>&1
}

restart_fs() {
  log "attempting restart of flaresolverr via docker compose"
  if command -v docker >/dev/null 2>&1 && [[ -f "$COMPOSE_FILE" ]]; then
    (cd "$(dirname "$COMPOSE_FILE")" && docker compose -f "$COMPOSE_FILE" restart flaresolverr) || true
  else
    log "docker or compose file missing; cannot auto-restart"
    return 1
  fi
}

# Quick check
if is_healthy; then
  log "FlareSolverr is healthy"
  exit 0
fi

log "FlareSolverr unhealthy or unreachable — will attempt recovery (one restart)"
restart_fs

# Poll
for i in $(seq 1 18); do
  sleep 5
  if is_healthy; then
    log "FlareSolverr recovered after restart (attempt $i)"
    exit 0
  fi
  log "still unhealthy after $((i*5))s..."
done

log "FlareSolverr did not become healthy after recovery attempt"
# Exit non-zero so that strict preflight in the unit will fail the oneshot (visible in systemctl status / timer)
exit 1
