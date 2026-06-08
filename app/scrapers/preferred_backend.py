from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..config import browser_preferred_sticky_backends, stale_dataset_hours


def preferred_browser_backend(previous: dict[str, Any] | None) -> str | None:
    """
    Reuse last successful backend only for fast/stable stacks (FlareSolverr, patchright).

    Scrapling/CloakBrowser successes do not stick — cron should try FlareSolverr first again.
    Stale ok status does not stick (forces full rotator retry).
    """
    if not previous or previous.get("state") != "ok":
        return None
    backend = (previous.get("backend") or "").strip().lower()
    if not backend or backend not in browser_preferred_sticky_backends():
        return None
    fetched_at = previous.get("fetched_at")
    if not fetched_at:
        return backend
    try:
        ts = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
        if age_hours > stale_dataset_hours():
            return None
    except (TypeError, ValueError):
        return backend
    return backend
