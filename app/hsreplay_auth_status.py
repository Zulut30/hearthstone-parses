from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import hsreplay_email, hsreplay_password, hsreplay_storage_path


def hsreplay_auth_status() -> dict[str, Any]:
    """Summary for /ops/summary — cookie age and authentication hints."""
    storage: Path = hsreplay_storage_path()
    out: dict[str, Any] = {
        "storage_path": str(storage),
        "present": storage.exists(),
        "credentials_configured": bool(hsreplay_email() and hsreplay_password()),
        "is_authenticated": False,
        "age_hours": None,
        "age_days": None,
        "warning": None,
        "cookie_names": [],
    }
    if not storage.exists():
        out["warning"] = "hsreplay-auth.json missing; Gold card pages may be empty"
        return out

    try:
        mtime = storage.stat().st_mtime
        age_sec = time.time() - mtime
        out["age_hours"] = round(age_sec / 3600, 1)
        out["age_days"] = round(age_sec / 86400, 1)
        out["updated_at"] = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
        raw = json.loads(storage.read_text(encoding="utf-8"))
        cookies = raw.get("cookies") or []
        names = [c.get("name") for c in cookies if c.get("name")]
        out["cookie_names"] = names[:20]
        has_session = "sessionid" in names
        out["has_sessionid"] = has_session
        for c in cookies:
            if c.get("name") == "sessionid" and c.get("value"):
                out["is_authenticated"] = True
                break
        if out["age_days"] and out["age_days"] > 5:
            out["warning"] = (
                f"hsreplay-auth.json is {out['age_days']:.1f} days old; run 'python -m app.cli hsreplay-login' soon"
            )
        elif not out["is_authenticated"]:
            out["warning"] = "sessionid cookie not found in storage"
    except (OSError, json.JSONDecodeError) as exc:
        out["warning"] = f"failed to read auth storage: {exc}"
    return out
