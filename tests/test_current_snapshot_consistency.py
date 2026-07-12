from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from app.db import get_db_connection, init_db
from app.hsreplay_archetypes_db import (
    get_latest_archetype_snapshot,
    list_archetype_snapshots,
)
from app.hsreplay_bg_minions_db import get_minion_detail, list_minion_snapshots


class CurrentSnapshotConsistencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"HS_API_DATA_DIR": self.tmp.name})
        self.env.start()
        init_db()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def _insert_archetype_run(self, *, state: str, archetype_ids: list[int]) -> int:
        conn = get_db_connection()
        try:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO archetype_refresh_runs
                      (source, game_type, rank_range, region, summary_time_range,
                       deck_time_range, started_at, completed_at, state,
                       archetypes_total, archetypes_ok)
                    VALUES (?, 'RANKED_STANDARD', 'LEGEND', 'REGION_EU',
                            'LAST_7_DAYS', 'LAST_30_DAYS', ?, ?, ?, ?, ?)
                    """,
                    (
                        "hsreplay_archetypes",
                        "2026-07-12T00:00:00Z",
                        "2026-07-12T00:05:00Z",
                        state,
                        len(archetype_ids),
                        len(archetype_ids),
                    ),
                )
                run_id = int(cur.lastrowid)
                for archetype_id in archetype_ids:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO hsreplay_archetypes
                          (archetype_id, name, player_class, first_seen_at, updated_at)
                        VALUES (?, ?, 'MAGE', '2026-07-01T00:00:00Z', '2026-07-12T00:00:00Z')
                        """,
                        (archetype_id, f"Archetype {archetype_id}"),
                    )
                    conn.execute(
                        """
                        INSERT INTO archetype_snapshots
                          (run_id, archetype_id, source, game_type, rank_range, region,
                           summary_time_range, deck_time_range, mulligan_time_range,
                           fetched_at, total_games, win_rate, pct_of_total)
                        VALUES (?, ?, 'hsreplay_archetypes', 'RANKED_STANDARD', 'LEGEND',
                                'REGION_EU', 'LAST_7_DAYS', 'LAST_30_DAYS', 'LAST_7_DAYS',
                                ?, 1000, 52.0, 10.0)
                        """,
                        (run_id, archetype_id, f"2026-07-{10 + run_id:02d}T00:05:00Z"),
                    )
                return run_id
        finally:
            conn.close()

    def _insert_bg_run(self, *, state: str, dbf_ids: list[int]) -> int:
        conn = get_db_connection()
        try:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO bg_minion_refresh_runs
                      (source, mmr_percentile, time_range, started_at, completed_at,
                       state, minions_total, minions_ok)
                    VALUES ('hsreplay_battlegrounds_minions', 'TOP_50_PERCENT',
                            'LAST_7_DAYS', ?, ?, ?, ?, ?)
                    """,
                    (
                        "2026-07-12T01:00:00Z",
                        "2026-07-12T01:05:00Z",
                        state,
                        len(dbf_ids),
                        len(dbf_ids),
                    ),
                )
                run_id = int(cur.lastrowid)
                for dbf_id in dbf_ids:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO bg_minions
                          (dbf_id, card_id, name, first_seen_at, updated_at)
                        VALUES (?, ?, ?, '2026-07-01T00:00:00Z', '2026-07-12T00:00:00Z')
                        """,
                        (dbf_id, f"BG_{dbf_id}", f"Minion {dbf_id}"),
                    )
                    conn.execute(
                        """
                        INSERT INTO bg_minion_snapshots
                          (run_id, dbf_id, source, mmr_percentile, time_range,
                           fetched_at, tavern_tier, impact, popularity, raw_json)
                        VALUES (?, ?, 'hsreplay_battlegrounds_minions',
                                'TOP_50_PERCENT', 'LAST_7_DAYS', ?, 3, 0.5, 10.0, '{}')
                        """,
                        (run_id, dbf_id, f"2026-07-{10 + run_id:02d}T01:05:00Z"),
                    )
                return run_id
        finally:
            conn.close()

    def test_archetypes_use_one_latest_successful_run(self) -> None:
        first_ok = self._insert_archetype_run(state="ok", archetype_ids=[101, 102])
        self._insert_archetype_run(state="partial", archetype_ids=[101])

        payload = list_archetype_snapshots(limit=100)

        self.assertEqual(payload["total"], 2)
        self.assertEqual({row["archetype_id"] for row in payload["archetypes"]}, {101, 102})
        self.assertEqual({row["run_id"] for row in payload["archetypes"]}, {first_ok})
        self.assertEqual(get_latest_archetype_snapshot(101)["run_id"], first_ok)

    def test_archetype_missing_from_new_successful_run_is_not_current(self) -> None:
        self._insert_archetype_run(state="ok", archetype_ids=[101, 102])
        latest_ok = self._insert_archetype_run(state="ok", archetype_ids=[101])

        payload = list_archetype_snapshots(limit=100)

        self.assertEqual([row["archetype_id"] for row in payload["archetypes"]], [101])
        self.assertEqual(payload["archetypes"][0]["run_id"], latest_ok)
        self.assertIsNone(get_latest_archetype_snapshot(102))

    def test_bg_minions_use_one_latest_successful_run(self) -> None:
        first_ok = self._insert_bg_run(state="ok", dbf_ids=[201, 202])
        self._insert_bg_run(state="partial", dbf_ids=[201])

        payload = list_minion_snapshots(limit=100)

        self.assertEqual(payload["total"], 2)
        self.assertEqual({row["dbf_id"] for row in payload["minions"]}, {201, 202})
        self.assertEqual({row["run_id"] for row in payload["minions"]}, {first_ok})
        self.assertEqual(get_minion_detail(201)["run_id"], first_ok)

    def test_bg_minion_missing_from_new_successful_run_is_not_current(self) -> None:
        self._insert_bg_run(state="ok", dbf_ids=[201, 202])
        latest_ok = self._insert_bg_run(state="ok", dbf_ids=[201])

        payload = list_minion_snapshots(limit=100)

        self.assertEqual([row["dbf_id"] for row in payload["minions"]], [201])
        self.assertEqual(payload["minions"][0]["run_id"], latest_ok)
        self.assertIsNone(get_minion_detail(202))


if __name__ == "__main__":
    unittest.main()
