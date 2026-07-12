from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.hsreplay_bg_minions_db import (
    _snapshot_quality_errors,
    refresh_bg_minion_database,
)


def _minions(count: int, *, with_stats: int | None = None) -> list[dict]:
    with_stats = count if with_stats is None else with_stats
    return [
        {
            "minion_dbf_id": 100_000 + idx,
            "games_with_minion": 100 if idx < with_stats else None,
            "combat_winrate_value": 50.0 if idx < with_stats else None,
            "popularity_value": 2.0 if idx < with_stats else None,
        }
        for idx in range(count)
    ]


def test_snapshot_quality_rejects_small_formally_complete_response() -> None:
    errors = _snapshot_quality_errors({"minions": _minions(20)}, stored_count=20)

    assert any("snapshot too small" in error for error in errors)


def test_snapshot_quality_rejects_missing_stats() -> None:
    errors = _snapshot_quality_errors(
        {"minions": _minions(200, with_stats=100)},
        stored_count=200,
    )

    assert any("stats fill too low" in error for error in errors)


def test_partial_bg_minion_run_is_not_reported_as_success() -> None:
    structured = {"minions": _minions(20), "source": {"backend": "test"}}

    with (
        patch("app.hsreplay_bg_minions_db._start_run", return_value=7),
        patch(
            "app.hsreplay_bg_minions_db.fetch_battlegrounds_minions",
            new=AsyncMock(return_value=structured),
        ),
        patch("app.hsreplay_bg_minions_db._store_minions", return_value=20),
        patch("app.hsreplay_bg_minions_db._finish_run") as finish_run,
    ):
        result = asyncio.run(refresh_bg_minion_database())

    assert result["ok"] is False
    assert result["published"] is False
    assert result["state"] == "partial"
    assert result["quality_errors"]
    assert finish_run.call_args.kwargs["state"] == "partial"


def test_complete_bg_minion_run_is_publishable() -> None:
    structured = {"minions": _minions(200), "source": {"backend": "test"}}

    with (
        patch("app.hsreplay_bg_minions_db._start_run", return_value=8),
        patch(
            "app.hsreplay_bg_minions_db.fetch_battlegrounds_minions",
            new=AsyncMock(return_value=structured),
        ),
        patch("app.hsreplay_bg_minions_db._store_minions", return_value=200),
        patch("app.hsreplay_bg_minions_db._finish_run") as finish_run,
    ):
        result = asyncio.run(refresh_bg_minion_database())

    assert result["ok"] is True
    assert result["published"] is True
    assert result["state"] == "ok"
    assert finish_run.call_args.kwargs["state"] == "ok"
