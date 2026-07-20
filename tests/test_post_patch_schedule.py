from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = (
    ROOT / "systemd" / "hs-data-api-docker-refresh-post-patch-tierlists.service"
)
TIMER_PATH = ROOT / "systemd" / "hs-data-api-docker-refresh-post-patch-tierlists.timer"


def _scheduled_moments() -> list[datetime]:
    moments: list[datetime] = []
    for line in TIMER_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("OnCalendar="):
            continue
        calendar = line.removeprefix("OnCalendar=")
        date_text, time_text, timezone_name = calendar.split()
        hours_text, minute_text, second_text = time_text.split(":")
        timezone = ZoneInfo(timezone_name)
        for hour_text in hours_text.split(","):
            moments.append(
                datetime.fromisoformat(
                    f"{date_text}T{hour_text}:{minute_text}:{second_text}"
                ).replace(tzinfo=timezone)
            )
    return sorted(moments)


def test_timer_has_exact_five_hour_schedule_through_july_27() -> None:
    moments = _scheduled_moments()

    assert len(moments) == 34
    assert moments[0].isoformat() == "2026-07-21T00:20:00+02:00"
    assert moments[-1].isoformat() == "2026-07-27T21:20:00+02:00"
    assert all(
        right - left == timedelta(hours=5)
        for left, right in zip(moments, moments[1:])
    )


def test_timer_never_catches_up_after_the_explicit_window() -> None:
    timer = TIMER_PATH.read_text(encoding="utf-8")

    assert "Persistent=false" in timer
    assert "Persistent=true" not in timer
    assert all(moment.date().isoformat() <= "2026-07-27" for moment in _scheduled_moments())


def test_refresh_retries_failures_and_always_attempts_all_cache_busts() -> None:
    service_lines = SERVICE_PATH.read_text(encoding="utf-8").splitlines()
    service = "\n".join(service_lines)
    cache_busts = [line for line in service_lines if line.startswith("ExecStopPost=")]

    assert "--require-all-ok" in service
    assert "Restart=on-failure" in service
    assert len(cache_busts) == 3
    assert all(line.startswith("ExecStopPost=-/usr/bin/curl ") for line in cache_busts)
    assert {line.rsplit("=", 1)[-1] for line in cache_busts} == {
        "hsreplay",
        "heartharena",
        "firestone",
    }


def test_compose_shares_date_bounded_policy_with_api_and_regular_jobs() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'HS_ARENA_POST_PATCH_ENABLED: "true"' in compose
    assert 'HS_ARENA_POST_PATCH_FROM: "2026-07-21"' in compose
    assert 'HS_ARENA_POST_PATCH_UNTIL: "2026-07-28"' in compose
