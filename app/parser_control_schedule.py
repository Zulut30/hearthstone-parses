from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from .parser_control_registry import SOURCE_TO_SECTION
from .source_tiers import LIGHT_API_IDS, MEDIUM_API_IDS
from .sources import SOURCE_BY_ID


SCHEDULE_INVENTORY_SCHEMA_VERSION = 1
SCHEDULE_INVENTORY_VERSION = "2026-07-21.1"
SCHEDULE_TIMEZONE = "Europe/Warsaw"


Recurrence = Literal["daily", "weekly", "odd-month-days", "explicit"]


@dataclass(frozen=True)
class _ScheduleSpec:
    id: str
    label: str
    systemd_unit: str
    on_calendar: tuple[str, ...]
    source_ids: frozenset[str]
    recurrence: Recurrence
    local_times: tuple[time, ...] = ()
    weekdays: tuple[int, ...] = ()
    explicit_local_datetimes: tuple[datetime, ...] = ()


def _times(*values: tuple[int, int]) -> tuple[time, ...]:
    return tuple(time(hour, minute) for hour, minute in values)


def _explicit_post_patch_datetimes() -> tuple[datetime, ...]:
    timezone = ZoneInfo(SCHEDULE_TIMEZONE)
    hours_by_day = {
        21: (0, 5, 10, 15, 20),
        22: (1, 6, 11, 16, 21),
        23: (2, 7, 12, 17, 22),
        24: (3, 8, 13, 18, 23),
        25: (4, 9, 14, 19),
        26: (0, 5, 10, 15, 20),
        27: (1, 6, 11, 16, 21),
    }
    return tuple(
        datetime(2026, 7, day, hour, 20, tzinfo=timezone)
        for day, hours in hours_by_day.items()
        for hour in hours
    )


_SCRAPE_SOURCE_IDS = frozenset(
    source_id for source_id, source in SOURCE_BY_ID.items() if source.kind == "scrape"
)


_SCHEDULES: tuple[_ScheduleSpec, ...] = (
    _ScheduleSpec(
        id="refresh-all-daily",
        label="Ежедневно в 07:00",
        systemd_unit="hs-data-api-docker-refresh.timer",
        on_calendar=("*-*-* 07:00:00 Europe/Warsaw",),
        source_ids=_SCRAPE_SOURCE_IDS,
        recurrence="daily",
        local_times=_times((7, 0)),
    ),
    _ScheduleSpec(
        id="refresh-api-daily",
        label="Ежедневно в 18:00",
        systemd_unit="hs-data-api-docker-refresh-api.timer",
        on_calendar=("*-*-* 18:00:00 Europe/Warsaw",),
        source_ids=frozenset(LIGHT_API_IDS | MEDIUM_API_IDS),
        recurrence="daily",
        local_times=_times((18, 0)),
    ),
    _ScheduleSpec(
        id="refresh-streamer-decks",
        label="Ежедневно в 03:15, 09:15, 15:15 и 21:15",
        systemd_unit="hs-data-api-docker-firecrawl-streamer.timer",
        on_calendar=(
            "*-*-* 03:15:00 Europe/Warsaw",
            "*-*-* 09:15:00 Europe/Warsaw",
            "*-*-* 15:15:00 Europe/Warsaw",
            "*-*-* 21:15:00 Europe/Warsaw",
        ),
        source_ids=frozenset({"hsguru_streamer_decks_legend_1000"}),
        recurrence="daily",
        local_times=_times((3, 15), (9, 15), (15, 15), (21, 15)),
    ),
    _ScheduleSpec(
        id="refresh-hsreplay-meta-firecrawl",
        label="Ежедневно в 03:05",
        systemd_unit="hs-data-api-docker-refresh-hsreplay-meta-firecrawl.timer",
        on_calendar=("*-*-* 03:05:00 Europe/Warsaw",),
        source_ids=frozenset(
            {
                "hsreplay_meta_top_1000_legend_1d_firecrawl",
                "hsreplay_meta_legend_1d_firecrawl",
                "hsreplay_meta_diamond_4to1_1d_firecrawl",
            }
        ),
        recurrence="daily",
        local_times=_times((3, 5)),
    ),
    _ScheduleSpec(
        id="refresh-hsreplay-arena-classes-firecrawl",
        label="По нечётным дням месяца в 03:35",
        systemd_unit="hs-data-api-docker-refresh-hsreplay-arena-classes-firecrawl.timer",
        on_calendar=("*-*-1/2 03:35:00 Europe/Warsaw",),
        source_ids=frozenset({"hsreplay_arena_class_pages_firecrawl"}),
        recurrence="odd-month-days",
        local_times=_times((3, 35)),
    ),
    _ScheduleSpec(
        id="refresh-vicious-syndicate",
        label="Каждые 2 часа в :20",
        systemd_unit="hs-data-api-docker-refresh-vicious-syndicate.timer",
        on_calendar=("*-*-* 00/2:20:00 Europe/Warsaw",),
        source_ids=frozenset(
            {"vicious_syndicate_live_beta", "vicious_syndicate_radars"}
        ),
        recurrence="daily",
        local_times=_times(*((hour, 20) for hour in range(0, 24, 2))),
    ),
    _ScheduleSpec(
        id="refresh-hsreplay-archetypes",
        label="По понедельникам и четвергам в 03:20",
        systemd_unit="hs-data-api-docker-refresh-hsreplay-archetypes.timer",
        on_calendar=("Mon,Thu *-*-* 03:20:00 Europe/Warsaw",),
        source_ids=frozenset({"hsreplay_archetypes"}),
        recurrence="weekly",
        local_times=_times((3, 20)),
        weekdays=(0, 3),
    ),
    _ScheduleSpec(
        id="refresh-bg-minions-db",
        label="По понедельникам и четвергам в 03:45",
        systemd_unit="hs-data-api-docker-refresh-bg-minions-db.timer",
        on_calendar=("Mon,Thu *-*-* 03:45:00 Europe/Warsaw",),
        source_ids=frozenset({"hsreplay_battlegrounds_minions"}),
        recurrence="weekly",
        local_times=_times((3, 45)),
        weekdays=(0, 3),
    ),
    _ScheduleSpec(
        id="refresh-bg-hero-details",
        label="По понедельникам и четвергам в 04:35",
        systemd_unit="hs-data-api-docker-refresh-bg-hero-details.timer",
        on_calendar=("Mon,Thu *-*-* 04:35:00 Europe/Warsaw",),
        source_ids=frozenset({"hsreplay_battlegrounds_hero_details"}),
        recurrence="weekly",
        local_times=_times((4, 35)),
        weekdays=(0, 3),
    ),
    _ScheduleSpec(
        id="refresh-post-patch-tierlists",
        label="Каждые 5 часов с 21 по 27 июля 2026 года",
        systemd_unit="hs-data-api-docker-refresh-post-patch-tierlists.timer",
        on_calendar=(
            "2026-07-21 00,05,10,15,20:20:00 Europe/Warsaw",
            "2026-07-22 01,06,11,16,21:20:00 Europe/Warsaw",
            "2026-07-23 02,07,12,17,22:20:00 Europe/Warsaw",
            "2026-07-24 03,08,13,18,23:20:00 Europe/Warsaw",
            "2026-07-25 04,09,14,19:20:00 Europe/Warsaw",
            "2026-07-26 00,05,10,15,20:20:00 Europe/Warsaw",
            "2026-07-27 01,06,11,16,21:20:00 Europe/Warsaw",
        ),
        source_ids=frozenset(
            {
                "hsreplay_arena_cards_advanced",
                "heartharena_tierlist",
                "firestone_arena_cards_normal",
            }
        ),
        recurrence="explicit",
        explicit_local_datetimes=_explicit_post_patch_datetimes(),
    ),
)


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _next_run(spec: _ScheduleSpec, *, at: datetime) -> datetime | None:
    moment = _as_utc(at)
    if spec.recurrence == "explicit":
        return next(
            (
                candidate.astimezone(UTC)
                for candidate in spec.explicit_local_datetimes
                if candidate.astimezone(UTC) > moment
            ),
            None,
        )

    timezone = ZoneInfo(SCHEDULE_TIMEZONE)
    local_day = moment.astimezone(timezone).date()
    scan_days = 15 if spec.recurrence == "weekly" else 40
    for offset in range(scan_days):
        candidate_day = local_day + timedelta(days=offset)
        if spec.recurrence == "weekly" and candidate_day.weekday() not in spec.weekdays:
            continue
        if spec.recurrence == "odd-month-days" and candidate_day.day % 2 == 0:
            continue
        for local_time in spec.local_times:
            candidate = datetime.combine(candidate_day, local_time, tzinfo=timezone)
            candidate_utc = candidate.astimezone(UTC)
            if candidate_utc > moment:
                return candidate_utc
    return None


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def _summary(schedule_rows: list[dict[str, Any]]) -> str:
    labels = [str(row["label"]) for row in schedule_rows]
    if not labels:
        return "Расписание не задано"
    if len(labels) == 1:
        return labels[0]
    return f"{labels[0]} · ещё расписаний: {len(labels) - 1}"


def _combined_view(schedule_rows: list[dict[str, Any]]) -> dict[str, Any]:
    next_runs = [
        str(row["nextRunAt"])
        for row in schedule_rows
        if row.get("nextRunAt") is not None
    ]
    return {
        "scheduleIds": [str(row["id"]) for row in schedule_rows],
        "schedule": _summary(schedule_rows),
        "nextRunAt": min(next_runs) if next_runs else None,
    }


def build_schedule_inventory(*, at: datetime | None = None) -> dict[str, Any]:
    """Return the versioned, read-only nominal schedule contract.

    The inventory describes version-controlled Docker timer configuration. It
    intentionally does not claim that a host timer is enabled or running; the
    actual unit state remains an infrastructure health concern.
    """

    moment = _as_utc(at or datetime.now(UTC))
    schedule_rows: list[dict[str, Any]] = []
    for spec in _SCHEDULES:
        source_ids = sorted(spec.source_ids)
        next_run = _next_run(spec, at=moment)
        last_explicit = (
            spec.explicit_local_datetimes[-1]
            if spec.explicit_local_datetimes
            else None
        )
        schedule_rows.append(
            {
                "id": spec.id,
                "label": spec.label,
                "systemdUnit": spec.systemd_unit,
                "onCalendar": list(spec.on_calendar),
                "timezone": SCHEDULE_TIMEZONE,
                "sourceIds": source_ids,
                "sectionIds": sorted(
                    {SOURCE_TO_SECTION[source_id] for source_id in source_ids}
                ),
                "nextRunAt": _iso(next_run),
                "validUntil": _iso(last_explicit),
                "isActive": next_run is not None,
            }
        )

    source_rows: dict[str, dict[str, Any]] = {}
    for source_id in SOURCE_BY_ID:
        rows = [row for row in schedule_rows if source_id in row["sourceIds"]]
        source_rows[source_id] = _combined_view(rows)

    section_rows: dict[str, dict[str, Any]] = {}
    for section_id in sorted(set(SOURCE_TO_SECTION.values())):
        rows = [row for row in schedule_rows if section_id in row["sectionIds"]]
        section_rows[section_id] = _combined_view(rows)

    return {
        "schemaVersion": SCHEDULE_INVENTORY_SCHEMA_VERSION,
        "inventoryVersion": SCHEDULE_INVENTORY_VERSION,
        "generatedAt": moment.isoformat(),
        "timeSemantics": "nominal",
        "runtimeTimerStateIncluded": False,
        "schedules": schedule_rows,
        "sources": source_rows,
        "sections": section_rows,
    }
