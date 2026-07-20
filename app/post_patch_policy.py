from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import os
from zoneinfo import ZoneInfo


WINDOW_TIMEZONE = "Europe/Warsaw"
DEFAULT_WINDOW_START = date(2026, 7, 21)
DEFAULT_WINDOW_UNTIL = date(2026, 7, 28)


@dataclass(frozen=True)
class PostPatchPolicy:
    source_id: str
    minimum_rows: int = 20
    minimum_classes: int = 1
    minimum_tier_fill_rate: float = 0.80
    minimum_sample: int = 10


ARENA_EARLY_SOURCE_IDS = frozenset(
    {
        "hsreplay_arena_cards_advanced",
        "heartharena_tierlist",
        "firestone_arena_cards_normal",
    }
)


def current_time() -> datetime:
    return datetime.now(UTC)


def _enabled() -> bool:
    return os.environ.get("HS_ARENA_POST_PATCH_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _date_setting(name: str, default: date) -> date:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return default


def window_bounds() -> tuple[date, date]:
    return (
        _date_setting("HS_ARENA_POST_PATCH_FROM", DEFAULT_WINDOW_START),
        _date_setting("HS_ARENA_POST_PATCH_UNTIL", DEFAULT_WINDOW_UNTIL),
    )


def policy_for(source_id: str, *, at: datetime | None = None) -> PostPatchPolicy | None:
    if not _enabled() or source_id not in ARENA_EARLY_SOURCE_IDS:
        return None
    moment = at or current_time()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local_date = moment.astimezone(ZoneInfo(WINDOW_TIMEZONE)).date()
    start, until = window_bounds()
    if not start <= local_date < until:
        return None
    return PostPatchPolicy(source_id=source_id)


def effective_contract_min_rows(
    source_id: str,
    default: int,
    *,
    at: datetime | None = None,
) -> int:
    policy = policy_for(source_id, at=at)
    return policy.minimum_rows if policy else default


def effective_arena_card_minimum(
    source_id: str,
    default: int,
    *,
    at: datetime | None = None,
) -> int:
    policy = policy_for(source_id, at=at)
    return policy.minimum_rows if policy else default


def effective_heartharena_thresholds(
    source_id: str,
    *,
    total_cards: int,
    at: datetime | None = None,
) -> tuple[int, int, int]:
    policy = policy_for(source_id, at=at)
    if not policy:
        return 5, 300, 200
    minimum_tier_ids = max(
        1,
        int(policy.minimum_rows * policy.minimum_tier_fill_rate),
    )
    return policy.minimum_classes, policy.minimum_rows, minimum_tier_ids


def effective_firestone_minimum_sample(
    source_id: str,
    default: int,
    *,
    at: datetime | None = None,
) -> int:
    policy = policy_for(source_id, at=at)
    if policy is None or source_id != "firestone_arena_cards_normal":
        return default
    return policy.minimum_sample


def build_provisional_metadata(
    source_id: str,
    *,
    accepted_rows: int,
    baseline_rows: int,
    at: datetime | None = None,
) -> dict[str, object]:
    policy = policy_for(source_id, at=at)
    if policy is None:
        return {}
    start, until = window_bounds()
    coverage = accepted_rows / baseline_rows if baseline_rows > 0 else 1.0
    return {
        "data_phase": "post_patch_early",
        "provisional": True,
        "accepted_rows": accepted_rows,
        "baseline_rows": baseline_rows,
        "coverage_ratio": round(coverage, 4),
        "minimum_sample": policy.minimum_sample,
        "patch_window": {
            "from": start.isoformat(),
            "until": until.isoformat(),
            "timezone": WINDOW_TIMEZONE,
        },
    }
