from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import data_dir

logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    db_dir = data_dir()
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "hs_parses.db"


def get_db_connection() -> sqlite3.Connection:
    path = get_db_path()
    conn = sqlite3.connect(str(path), timeout=15.0)
    # Enable WAL mode for high concurrency and fast writes
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_decks_column(conn: sqlite3.Connection, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(decks)")}
    if column not in columns:
        conn.execute(f"ALTER TABLE decks ADD COLUMN {column} {definition}")


def _normalize_class_name(cls: str) -> str:
    return (
        (cls or "Unknown")
        .replace("Demonhunter", "DemonHunter")
        .replace("Deathknight", "DeathKnight")
    )


def _win_rate_from_record(record: str | None) -> float | None:
    if not record:
        return None
    match = re.match(r"(\d+)\s*-\s*(\d+)", str(record).strip())
    if not match:
        return None
    wins, losses = int(match.group(1)), int(match.group(2))
    total = wins + losses
    if total <= 0:
        return None
    return round(wins / total * 100, 2)


def init_db() -> None:
    """Initialize SQLite database tables and indices if they do not exist."""
    conn = get_db_connection()
    try:
        with conn:
            # 1. Fetch Log table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fetch_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    content_length INTEGER
                );
            """)

            # 2. Decks table (Unique constraint on deck_code only, to guarantee absolutely NO duplicate decks across different sources or updates)
            # URL is optional, so we place the UNIQUE on deck_code (if populated).
            # To handle records with null deck_code but unique URLs, we use a unique index where appropriate,
            # or handle duplicates explicitly during ingestion (checking for existing codes/URLs and doing an upsert).
            conn.execute("""
                CREATE TABLE IF NOT EXISTS decks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    class TEXT NOT NULL,
                    archetype TEXT NOT NULL,
                    deck_code TEXT UNIQUE,
                    win_rate REAL,
                    score TEXT,
                    title TEXT,
                    url TEXT,
                    format TEXT,
                    added_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # 3. Card Popularity History table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS card_popularity_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    class TEXT,
                    archetype TEXT,
                    card_name TEXT NOT NULL,
                    popularity REAL NOT NULL,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(source_id, class, archetype, card_name, recorded_at)
                );
            """)

            # Create indexing for super fast search and queries
            _ensure_decks_column(conn, "draft_id", "TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_decks_source_class ON decks(source_id, class);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_decks_code ON decks(deck_code);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_decks_url ON decks(url);")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_decks_draft_id "
                "ON decks(draft_id) WHERE draft_id IS NOT NULL"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_decks_format_updated ON decks(format, updated_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_card_pop_history ON card_popularity_history(source_id, card_name, recorded_at);")
            
            logger.info("SQLite database tables initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize SQLite database: {e}")
        raise
    finally:
        conn.close()


def _parse_percent(val: Any) -> float | None:
    if val is None:
        return None
    val_str = str(val).strip()
    match = re.search(r"([\d.]+)", val_str)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def store_dataset_to_db(source_id: str, payload: dict[str, Any]) -> None:
    """Parse structured data from a dataset payload and store it in SQLite."""
    init_db() # Ensure tables exist

    fetched_at = payload.get("fetched_at") or datetime.now(timezone.utc).isoformat()
    state = payload.get("state") or "ok"
    
    # Safely get structured dict
    data_dict = payload.get("data") or {}
    structured = data_dict.get("structured") or payload.get("structured") or {}
    
    # Calculate content length
    content_length = data_dict.get("content_length") or len(str(payload))

    conn = get_db_connection()
    try:
        with conn:
            # 1. Log the fetch run
            conn.execute("""
                INSERT INTO fetch_log (source_id, fetched_at, state, content_length)
                VALUES (?, ?, ?, ?)
            """, (source_id, fetched_at, state, content_length))

            # 2. Extract and store decks
            # Source: hearthstone_decks (Hearthstone-Decks.net)
            if source_id == "hearthstone_decks":
                decks_list = structured.get("decks") or []
                for d in decks_list:
                    fmt = d.get("format") or "Standard"
                    cls = d.get("class") or ""
                    if not cls:
                        url = d.get("url") or ""
                        for c in ("death-knight", "demon-hunter", "druid", "hunter", "mage", "paladin", "priest", "rogue", "shaman", "warlock", "warrior"):
                            if c in url.lower():
                                cls = c.replace("-", "").title()
                                break
                    if not cls:
                        cls = "Neutral"

                    # Normalize Class capitalization
                    cls = cls.replace("Demonhunter", "DemonHunter").replace("Deathknight", "DeathKnight")

                    arch = d.get("archetype") or "Unknown"
                    deck_code = d.get("deck_code")
                    score = d.get("score")
                    title = d.get("title")
                    url = d.get("url")

                    if not deck_code:
                        continue

                    # Search if deck code is already saved from ANY source
                    row = conn.execute("""
                        SELECT id, source_id, url FROM decks WHERE deck_code = ?
                    """, (deck_code,)).fetchone()

                    if row:
                        # Deck code exists. Update it (keep original source_id, update stats/score/title/format if newer)
                        conn.execute("""
                            UPDATE decks
                            SET class = ?, archetype = ?, score = ?, title = ?, format = ?, url = ?, updated_at = ?
                            WHERE id = ?
                        """, (cls, arch, score, title, fmt, url or row["url"], fetched_at, row["id"]))
                    else:
                        # No duplicate code. Check if URL exists for deck without code (or update it)
                        if url:
                            row_url = conn.execute("SELECT id FROM decks WHERE url = ?", (url,)).fetchone()
                            if row_url:
                                conn.execute("""
                                    UPDATE decks
                                    SET class = ?, archetype = ?, deck_code = ?, score = ?, title = ?, format = ?, updated_at = ?
                                    WHERE id = ?
                                """, (cls, arch, deck_code, score, title, fmt, fetched_at, row_url["id"]))
                                continue
                        
                        conn.execute("""
                            INSERT INTO decks (source_id, class, archetype, deck_code, score, title, url, format, added_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (source_id, cls, arch, deck_code, score, title, url, fmt, fetched_at, fetched_at))

            # Source: metastats_decks (MetaStats.net)
            elif source_id == "metastats_decks":
                decks_list = structured.get("decks") or []
                for d in decks_list:
                    cls = d.get("class") or "Neutral"
                    cls = cls.replace("Demonhunter", "DemonHunter").replace("Deathknight", "DeathKnight")
                    arch = d.get("archetype_name") or "Unknown"
                    deck_code = d.get("deck_code")
                    win_rate = _parse_percent(d.get("win_rate"))
                    title = d.get("title")
                    games = d.get("games")
                    score = f"{games} games" if games else None

                    if not deck_code:
                        continue

                    # Search by unique deck_code
                    row = conn.execute("""
                        SELECT id FROM decks WHERE deck_code = ?
                    """, (deck_code,)).fetchone()

                    if row:
                        conn.execute("""
                            UPDATE decks
                            SET class = ?, archetype = ?, win_rate = ?, score = ?, title = ?, updated_at = ?
                            WHERE id = ?
                        """, (cls, arch, win_rate, score, title, fetched_at, row["id"]))
                    else:
                        conn.execute("""
                            INSERT INTO decks (source_id, class, archetype, deck_code, win_rate, score, title, added_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (source_id, cls, arch, deck_code, win_rate, score, title, fetched_at, fetched_at))

            # Source: hsreplay_arena_winning_decks (accumulating Arena feed, deduped)
            elif source_id == "hsreplay_arena_winning_decks":
                decks_list = structured.get("decks") or []
                for d in decks_list:
                    deck_code = (d.get("final_deckstring") or "").strip()
                    if not deck_code:
                        continue

                    draft_id = d.get("draft_id")
                    draft_id_s = str(draft_id).strip() if draft_id is not None else None
                    cls = _normalize_class_name(d.get("main_class") or d.get("class") or "Unknown")
                    arch = (d.get("legendary_group") or "Arena").strip() or "Arena"
                    player = (d.get("player") or "Unknown").strip() or "Unknown"
                    record = d.get("record")
                    title = f"{player} · {record}" if record else player
                    url = d.get("url")
                    win_rate = _win_rate_from_record(record)
                    score = record

                    row = None
                    if draft_id_s:
                        row = conn.execute(
                            "SELECT id FROM decks WHERE draft_id = ?",
                            (draft_id_s,),
                        ).fetchone()
                    if not row:
                        row = conn.execute(
                            "SELECT id FROM decks WHERE deck_code = ?",
                            (deck_code,),
                        ).fetchone()

                    if row:
                        conn.execute(
                            """
                            UPDATE decks
                            SET source_id = ?, class = ?, archetype = ?,
                                draft_id = COALESCE(?, draft_id),
                                win_rate = ?, score = ?, title = ?,
                                url = COALESCE(?, url), format = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                source_id,
                                cls,
                                arch,
                                draft_id_s,
                                win_rate,
                                score,
                                title,
                                url,
                                "Arena",
                                fetched_at,
                                row["id"],
                            ),
                        )
                    else:
                        conn.execute(
                            """
                            INSERT INTO decks (
                                source_id, class, archetype, deck_code, draft_id,
                                win_rate, score, title, url, format, added_at, updated_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                source_id,
                                cls,
                                arch,
                                deck_code,
                                draft_id_s,
                                win_rate,
                                score,
                                title,
                                url,
                                "Arena",
                                fetched_at,
                                fetched_at,
                            ),
                        )

            # Source: vicious_syndicate_radars (Vicious Syndicate Radars)
            elif source_id == "vicious_syndicate_radars":
                radars_list = structured.get("radars") or []
                recorded_date = fetched_at.split("T")[0]

                for r in radars_list:
                    cls = r.get("class") or "Neutral"
                    cls = cls.replace("Demonhunter", "DemonHunter").replace("Deathknight", "DeathKnight")
                    arch = r.get("archetype") or "Overall"
                    deck_code = r.get("deck_code")
                    url = r.get("url")

                    if deck_code:
                        row = conn.execute("""
                            SELECT id FROM decks WHERE deck_code = ?
                        """, (deck_code,)).fetchone()

                        if row:
                            conn.execute("""
                                UPDATE decks
                                SET class = ?, archetype = ?, url = ?, updated_at = ?
                                WHERE id = ?
                            """, (cls, arch, url, fetched_at, row["id"]))
                        else:
                            conn.execute("""
                                INSERT INTO decks (source_id, class, archetype, deck_code, url, added_at, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (source_id, cls, arch, deck_code, url, fetched_at, fetched_at))

                    # Save card popularity nodes to trend history
                    nodes_list = r.get("nodes") or []
                    for n in nodes_list:
                        card_name = n.get("name")
                        popularity = n.get("radius") or 0.0

                        if card_name:
                            conn.execute("""
                                INSERT INTO card_popularity_history (source_id, class, archetype, card_name, popularity, recorded_at)
                                VALUES (?, ?, ?, ?, ?, ?)
                                ON CONFLICT(source_id, class, archetype, card_name, recorded_at) DO UPDATE SET
                                    popularity = excluded.popularity
                            """, (source_id, cls, arch, card_name, popularity, recorded_date))

            # Source: any card stats (HSReplay, Arena, etc.)
            elif source_id.startswith("hsreplay_cards_") or source_id == "hsreplay_arena_cards_advanced":
                cards_list = structured.get("cards") or []
                recorded_date = fetched_at.split("T")[0]

                for c in cards_list:
                    card_name = c.get("name")
                    pop = _parse_percent(c.get("deck_popularity") or c.get("avg_copies") or c.get("popularity"))
                    if pop is None:
                        pop = 0.0

                    cls = c.get("cardClass") or "Neutral"
                    cls = cls.replace("Demonhunter", "DemonHunter").replace("Deathknight", "DeathKnight")

                    if card_name:
                        conn.execute("""
                            INSERT INTO card_popularity_history (source_id, class, archetype, card_name, popularity, recorded_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(source_id, class, archetype, card_name, recorded_at) DO UPDATE SET
                                popularity = excluded.popularity
                            """, (source_id, cls, "Overall", card_name, pop, recorded_date))

        logger.info(f"Successfully saved structured dataset for {source_id} to SQLite DB.")
    except Exception as e:
        logger.error(f"Error storing dataset {source_id} in SQLite database: {e}", exc_info=True)
    finally:
        conn.close()
