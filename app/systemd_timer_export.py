from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .parser_control_schedule import (
    _HOST_TIMER_STATE_FILENAME,
    _HOST_TIMER_STATE_SCHEMA_VERSION,
    _SCHEDULES,
    _probe_systemd_timer_states_direct,
)


def build_host_timer_snapshot(*, at: datetime | None = None) -> dict[str, Any]:
    moment = at or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    moment = moment.astimezone(UTC)
    units = tuple(spec.systemd_unit for spec in _SCHEDULES)
    runtime = _probe_systemd_timer_states_direct(units, checked_at=moment)
    if runtime.get("available") is not True:
        reason = str(runtime.get("reason") or "unavailable")
        raise RuntimeError(f"systemd timer state is unavailable: {reason}")
    return {
        "schemaVersion": _HOST_TIMER_STATE_SCHEMA_VERSION,
        "provider": "host-systemd",
        "generatedAt": str(runtime.get("checkedAt") or moment.isoformat()),
        "status": str(runtime.get("status") or "partial"),
        "timingAvailable": runtime.get("timingAvailable") is True,
        "units": runtime.get("units") if isinstance(runtime.get("units"), dict) else {},
    }


def write_host_timer_snapshot(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, path)
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    output = root / "data" / _HOST_TIMER_STATE_FILENAME
    payload = build_host_timer_snapshot()
    write_host_timer_snapshot(output, payload)
    print(f"Exported {len(payload['units'])} systemd timer states.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
