from __future__ import annotations

from typing import Final


TRINKET_MMR_OPTIONS: Final[tuple[str, ...]] = (
    "ALL",
    "TOP_50_PERCENT",
    "TOP_20_PERCENT",
    "TOP_5_PERCENT",
    "TOP_1_PERCENT",
)
TRINKET_TIME_RANGE_OPTIONS: Final[tuple[str, ...]] = (
    "CURRENT_BATTLEGROUNDS_PATCH",
    "LAST_7_DAYS",
)
DEFAULT_TRINKET_MMR: Final[str] = "TOP_1_PERCENT"
DEFAULT_TRINKET_TIME_RANGE: Final[str] = "LAST_7_DAYS"
LEGACY_DEFAULT_TRINKET_SOURCE_IDS: Final[tuple[str, str]] = (
    "hsreplay_battlegrounds_trinkets_lesser",
    "hsreplay_battlegrounds_trinkets_greater",
)


def normalize_trinket_mmr(value: str | None) -> str:
    normalized = str(value or DEFAULT_TRINKET_MMR).strip().upper()
    if normalized not in TRINKET_MMR_OPTIONS:
        raise ValueError(f"Unsupported Battlegrounds trinket MMR slice: {normalized}")
    return normalized


def normalize_trinket_time_range(value: str | None) -> str:
    normalized = str(value or DEFAULT_TRINKET_TIME_RANGE).strip().upper()
    if normalized not in TRINKET_TIME_RANGE_OPTIONS:
        raise ValueError(f"Unsupported Battlegrounds trinket time range: {normalized}")
    return normalized


def trinket_slice_source_id(mmr: str, time_range: str) -> str:
    normalized_mmr = normalize_trinket_mmr(mmr)
    normalized_time_range = normalize_trinket_time_range(time_range)
    return (
        "hsreplay_battlegrounds_trinkets_"
        f"{normalized_mmr.lower()}_{normalized_time_range.lower()}"
    )


TRINKET_SLICE_PARAMETERS: Final[tuple[tuple[str, str], ...]] = tuple(
    (mmr, time_range)
    for mmr in TRINKET_MMR_OPTIONS
    for time_range in TRINKET_TIME_RANGE_OPTIONS
    if (mmr, time_range) != (DEFAULT_TRINKET_MMR, DEFAULT_TRINKET_TIME_RANGE)
)
TRINKET_SLICE_SOURCE_IDS: Final[frozenset[str]] = frozenset(
    trinket_slice_source_id(mmr, time_range)
    for mmr, time_range in TRINKET_SLICE_PARAMETERS
)
TRINKET_SLICE_BY_SOURCE_ID: Final[dict[str, tuple[str, str]]] = {
    trinket_slice_source_id(mmr, time_range): (mmr, time_range)
    for mmr, time_range in TRINKET_SLICE_PARAMETERS
}


def source_ids_for_trinket_slice(mmr: str | None, time_range: str | None) -> tuple[str, ...]:
    normalized_mmr = normalize_trinket_mmr(mmr)
    normalized_time_range = normalize_trinket_time_range(time_range)
    if (
        normalized_mmr == DEFAULT_TRINKET_MMR
        and normalized_time_range == DEFAULT_TRINKET_TIME_RANGE
    ):
        return LEGACY_DEFAULT_TRINKET_SOURCE_IDS
    return (trinket_slice_source_id(normalized_mmr, normalized_time_range),)
