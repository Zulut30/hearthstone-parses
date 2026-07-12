from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cards_index import _load_raw_cards
from .config import data_dir
from .db import get_db_connection, init_db
from .hsreplay_bg_stats import BG_MMR, BG_TIME_RANGE, fetch_battlegrounds_minions

SOURCE = "hsreplay_battlegrounds_minions"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _parse_percent(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _ru_names_by_dbf() -> dict[int, str]:
    out: dict[int, str] = {}
    try:
        for card in _load_raw_cards("ruRU"):
            dbf_id = card.get("dbfId")
            name = card.get("name")
            if dbf_id is not None and name:
                out[int(dbf_id)] = str(name)
    except Exception:
        return {}
    return out


def _start_run(*, mmr_percentile: str, time_range: str) -> int:
    init_db()
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO bg_minion_refresh_runs
                  (source, mmr_percentile, time_range, started_at, state)
                VALUES (?, ?, ?, ?, ?)
                """,
                (SOURCE, mmr_percentile, time_range, _now(), "running"),
            )
            return int(cur.lastrowid)
    finally:
        conn.close()


def _finish_run(run_id: int, *, state: str, minions_total: int, minions_ok: int, error: str | None = None) -> None:
    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                """
                UPDATE bg_minion_refresh_runs
                SET completed_at = ?, state = ?, minions_total = ?, minions_ok = ?, error = ?
                WHERE id = ?
                """,
                (_now(), state, minions_total, minions_ok, error, run_id),
            )
    finally:
        conn.close()


def _store_minions(run_id: int, structured: dict[str, Any]) -> int:
    fetched_at = _now()
    minions = structured.get("minions") or []
    filters = structured.get("filters") or {}
    mmr = str(filters.get("mmr_percentile") or BG_MMR)
    time_range = str(filters.get("time_range") or BG_TIME_RANGE)
    ru_names = _ru_names_by_dbf()
    ok = 0
    conn = get_db_connection()
    try:
        with conn:
            for minion in minions:
                dbf_id = minion.get("minion_dbf_id") or minion.get("dbfId")
                if dbf_id is None:
                    continue
                dbf_id = int(dbf_id)
                name = str(minion.get("minion") or minion.get("name") or f"Minion {dbf_id}")
                tier = minion.get("tavern_tier")
                tier_int = int(tier) if tier is not None and str(tier).isdigit() else None
                conn.execute(
                    """
                    INSERT INTO bg_minions
                      (dbf_id, card_id, name, name_ru, tavern_tier, card_type, rarity,
                       first_seen_at, updated_at, raw_card_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(dbf_id) DO UPDATE SET
                      card_id = excluded.card_id,
                      name = excluded.name,
                      name_ru = excluded.name_ru,
                      tavern_tier = excluded.tavern_tier,
                      card_type = excluded.card_type,
                      rarity = excluded.rarity,
                      updated_at = excluded.updated_at,
                      raw_card_json = excluded.raw_card_json
                    """,
                    (
                        dbf_id,
                        minion.get("id") or minion.get("card_id"),
                        name,
                        ru_names.get(dbf_id),
                        tier_int,
                        minion.get("type"),
                        minion.get("rarity"),
                        fetched_at,
                        fetched_at,
                        json.dumps(minion, ensure_ascii=False),
                    ),
                )
                cur = conn.execute(
                    """
                    INSERT INTO bg_minion_snapshots
                      (run_id, dbf_id, source, mmr_percentile, time_range, fetched_at,
                       tavern_tier, impact, combat_winrate, popularity, games_with_minion,
                       games_without_minion, avg_placement_with, avg_placement_without, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        dbf_id,
                        SOURCE,
                        mmr,
                        time_range,
                        fetched_at,
                        tier_int,
                        minion.get("impact"),
                        minion.get("combat_winrate_value") or _parse_percent(minion.get("combat_winrate")),
                        minion.get("popularity_value") or _parse_percent(minion.get("popularity")),
                        minion.get("games_with_minion"),
                        minion.get("games_without_minion"),
                        minion.get("avg_placement_with"),
                        minion.get("avg_placement_without"),
                        json.dumps(minion, ensure_ascii=False),
                    ),
                )
                snapshot_id = int(cur.lastrowid)
                for round_row in minion.get("combat_rounds") or []:
                    combat_round = round_row.get("combat_round")
                    if combat_round is None:
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bg_minion_round_stats
                          (snapshot_id, combat_round, games_with_minion, games_without_minion,
                           avg_placement_with, avg_placement_without, impact, combat_winrate, wins, losses)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            snapshot_id,
                            int(combat_round),
                            round_row.get("games_with_minion"),
                            round_row.get("games_without_minion"),
                            round_row.get("avg_placement_with"),
                            round_row.get("avg_placement_without"),
                            round_row.get("impact"),
                            round_row.get("combat_winrate_value") or _parse_percent(round_row.get("combat_winrate")),
                            round_row.get("wins"),
                            round_row.get("losses"),
                        ),
                    )
                ok += 1
        return ok
    finally:
        conn.close()


async def refresh_bg_minion_database() -> dict[str, Any]:
    run_id = _start_run(mmr_percentile=BG_MMR, time_range=BG_TIME_RANGE)
    total = 0
    ok = 0
    try:
        structured = await fetch_battlegrounds_minions(SOURCE)
        minions = structured.get("minions") or []
        total = len(minions)
        ok = _store_minions(run_id, structured)
        # NOTE: SQLite run-state domain ("ok"/"partial"/"failed"/"running"), not app.source_state.SourceState.
        state = "ok" if ok == total and ok else "partial" if ok else "failed"
        _finish_run(run_id, state=state, minions_total=total, minions_ok=ok)
        return {"ok": state in {"ok", "partial"}, "state": state, "run_id": run_id, "minions_total": total, "minions_ok": ok, "source": structured.get("source")}
    except Exception as exc:
        _finish_run(run_id, state="failed", minions_total=total, minions_ok=ok, error=str(exc)[:1000])
        raise


def latest_run() -> dict[str, Any] | None:
    init_db()
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT * FROM bg_minion_refresh_runs
            WHERE source = ?
            ORDER BY COALESCE(completed_at, started_at) DESC
            LIMIT 1
            """,
            (SOURCE,),
        ).fetchone()
        return _row_dict(row) if row else None
    finally:
        conn.close()


def _current_snapshot_where() -> str:
    return """
        s.run_id = (
            SELECT r.id
            FROM bg_minion_refresh_runs r
            WHERE r.source = ?
              AND r.state = 'ok'
            ORDER BY COALESCE(r.completed_at, r.started_at) DESC, r.id DESC
            LIMIT 1
        )
    """


def list_minion_snapshots(
    *,
    q: str | None = None,
    tavern_tier: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    init_db()
    conn = get_db_connection()
    try:
        where = [_current_snapshot_where()]
        params: list[Any] = [SOURCE]
        if q:
            where.append("(m.name LIKE ? OR COALESCE(m.name_ru, '') LIKE ? OR m.card_id LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
        if tavern_tier is not None:
            where.append("COALESCE(s.tavern_tier, m.tavern_tier) = ?")
            params.append(tavern_tier)
        where_sql = " AND ".join(where)
        total = int(conn.execute(
            f"SELECT COUNT(*) FROM bg_minion_snapshots s JOIN bg_minions m ON m.dbf_id = s.dbf_id WHERE {where_sql}",
            params,
        ).fetchone()[0])
        rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT
                    s.id AS snapshot_id, s.run_id, s.fetched_at, s.dbf_id, m.card_id, m.name, m.name_ru,
                    COALESCE(s.tavern_tier, m.tavern_tier) AS tavern_tier,
                    s.impact, s.combat_winrate, s.popularity, s.games_with_minion,
                    s.games_without_minion, s.avg_placement_with, s.avg_placement_without
                FROM bg_minion_snapshots s
                JOIN bg_minions m ON m.dbf_id = s.dbf_id
                WHERE {where_sql}
                ORDER BY s.popularity DESC, s.games_with_minion DESC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        ]
        return {"total": total, "limit": limit, "offset": offset, "minions": rows}
    finally:
        conn.close()


def get_minion_detail(dbf_id: int) -> dict[str, Any] | None:
    init_db()
    conn = get_db_connection()
    try:
        query = (
            """
            SELECT
                s.id AS snapshot_id, s.*, m.card_id, m.name, m.name_ru, m.card_type, m.rarity
            FROM bg_minion_snapshots s
            JOIN bg_minions m ON m.dbf_id = s.dbf_id
            WHERE s.dbf_id = ?
              AND
            """
            + _current_snapshot_where()
        )
        row = conn.execute(
            query,
            (dbf_id, SOURCE),
        ).fetchone()
        if not row:
            return None
        detail = dict(row)
        detail["rounds"] = [
            dict(round_row)
            for round_row in conn.execute(
                """
                SELECT combat_round, games_with_minion, games_without_minion,
                       avg_placement_with, avg_placement_without, impact,
                       combat_winrate, wins, losses
                FROM bg_minion_round_stats
                WHERE snapshot_id = ?
                ORDER BY combat_round ASC
                """,
                (detail["snapshot_id"],),
            ).fetchall()
        ]
        try:
            detail["raw"] = json.loads(detail.get("raw_json") or "{}")
        except json.JSONDecodeError:
            detail["raw"] = {}
        detail.pop("raw_json", None)
        return detail
    finally:
        conn.close()


def get_minion_history(dbf_id: int, *, limit: int = 120) -> dict[str, Any] | None:
    init_db()
    conn = get_db_connection()
    try:
        minion = conn.execute("SELECT * FROM bg_minions WHERE dbf_id = ?", (dbf_id,)).fetchone()
        if not minion:
            return None
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT fetched_at, impact, combat_winrate, popularity, games_with_minion,
                       avg_placement_with, avg_placement_without, tavern_tier
                FROM bg_minion_snapshots
                WHERE dbf_id = ?
                ORDER BY fetched_at ASC
                LIMIT ?
                """,
                (dbf_id, limit),
            ).fetchall()
        ]
        chart_series = {
            "impact": [{"x": row["fetched_at"], "y": row["impact"]} for row in rows],
            "combat_winrate": [{"x": row["fetched_at"], "y": row["combat_winrate"]} for row in rows],
            "popularity": [{"x": row["fetched_at"], "y": row["popularity"]} for row in rows],
            "avg_placement_with": [{"x": row["fetched_at"], "y": row["avg_placement_with"]} for row in rows],
        }
        return {"minion": dict(minion), "history": rows, "chart_series": chart_series}
    finally:
        conn.close()


def export_latest_bg_minions_json(path: Path | None = None) -> Path:
    path = path or (Path(data_dir()) / "datasets" / "hsreplay_bg_minions_db_latest.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "bg_minions_db_latest",
        "exported_at": _now(),
        "latest_run": latest_run(),
        **list_minion_snapshots(limit=500),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def refresh_bg_minion_database_sync() -> dict[str, Any]:
    result = asyncio.run(refresh_bg_minion_database())
    result["export_path"] = str(export_latest_bg_minions_json())
    return result
