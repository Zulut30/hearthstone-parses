from __future__ import annotations

from datetime import UTC, datetime
import json
import sqlite3
from typing import Any

from .db import get_db_connection


PATCH_COLUMNS = """
    version,
    display_version,
    wiki_rank,
    wiki_title,
    wiki_url,
    official_title,
    official_url,
    official_published_at,
    official_modified_at,
    official_summary,
    hs_manacost_version,
    title,
    slug,
    source_url,
    match_state,
    published_at,
    modified_at,
    excerpt,
    summary,
    sections_json,
    categories_json,
    tags_json,
    content_text,
    fetched_at
"""


def _create_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hearthstone_patches (
            version TEXT PRIMARY KEY,
            display_version TEXT NOT NULL,
            wiki_rank INTEGER,
            wiki_title TEXT NOT NULL,
            wiki_url TEXT NOT NULL,
            official_title TEXT,
            official_url TEXT,
            official_published_at TEXT,
            official_modified_at TEXT,
            official_summary TEXT,
            hs_manacost_version TEXT,
            title TEXT,
            slug TEXT,
            source_url TEXT,
            match_state TEXT NOT NULL DEFAULT 'missing_manacost',
            published_at TEXT,
            modified_at TEXT,
            excerpt TEXT,
            summary TEXT,
            sections_json TEXT NOT NULL DEFAULT '[]',
            categories_json TEXT NOT NULL DEFAULT '[]',
            tags_json TEXT NOT NULL DEFAULT '[]',
            content_text TEXT,
            fetched_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hearthstone_patches_published
        ON hearthstone_patches(published_at DESC, version DESC);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hearthstone_patches_match_state
        ON hearthstone_patches(match_state);
        """
    )


def _table_columns(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {str(row["name"]): row for row in conn.execute("PRAGMA table_info(hearthstone_patches)")}


def _table_exists(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'hearthstone_patches'"
        ).fetchone()
        is not None
    )


def _needs_rebuild(conn: sqlite3.Connection) -> bool:
    if not _table_exists(conn):
        return False
    columns = _table_columns(conn)
    required = {
        "wiki_title",
        "wiki_url",
        "wiki_rank",
        "match_state",
        "hs_manacost_version",
        "source_url",
        "official_url",
    }
    if not required.issubset(columns):
        return True
    # v1 required hs_manacost/source_url/title. v2 allows wiki-only rows.
    if any(columns[name]["notnull"] for name in ("hs_manacost_version", "source_url", "title") if name in columns):
        return True
    create_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'hearthstone_patches'"
    ).fetchone()
    return bool(create_sql and "slug TEXT UNIQUE" in str(create_sql["sql"]))


def _normalize_patch_payload(patch: dict[str, Any]) -> dict[str, Any]:
    version = str(patch["version"])
    wiki_url = patch.get("wiki_url") or f"https://hearthstone.wiki.gg/wiki/Patch_{version}"
    source_url = patch.get("source_url")
    return {
        "version": version,
        "display_version": patch.get("display_version") or version,
        "wiki_rank": patch.get("wiki_rank"),
        "wiki_title": patch.get("wiki_title") or f"Patch {version}",
        "wiki_url": wiki_url,
        "official_title": patch.get("official_title"),
        "official_url": patch.get("official_url"),
        "official_published_at": patch.get("official_published_at"),
        "official_modified_at": patch.get("official_modified_at"),
        "official_summary": patch.get("official_summary"),
        "hs_manacost_version": patch.get("hs_manacost_version"),
        "title": patch.get("title"),
        "slug": patch.get("slug"),
        "source_url": source_url,
        "match_state": patch.get("match_state") or ("matched" if source_url else "missing_manacost"),
        "published_at": patch.get("published_at"),
        "modified_at": patch.get("modified_at"),
        "excerpt": patch.get("excerpt"),
        "summary": patch.get("summary"),
        "sections": patch.get("sections"),
        "categories": patch.get("categories"),
        "tags": patch.get("tags"),
        "content_text": patch.get("content_text"),
        "fetched_at": patch.get("fetched_at") or datetime.now(UTC).isoformat(),
    }


def _dump(value: Any, fallback: str = "[]") -> str:
    if value is None:
        return fallback
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _insert_patch(conn: sqlite3.Connection, patch: dict[str, Any]) -> None:
    normalized = _normalize_patch_payload(patch)
    conn.execute(
        f"""
        INSERT INTO hearthstone_patches ({PATCH_COLUMNS})
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(version) DO UPDATE SET
            display_version = excluded.display_version,
            wiki_rank = excluded.wiki_rank,
            wiki_title = excluded.wiki_title,
            wiki_url = excluded.wiki_url,
            official_title = excluded.official_title,
            official_url = excluded.official_url,
            official_published_at = excluded.official_published_at,
            official_modified_at = excluded.official_modified_at,
            official_summary = excluded.official_summary,
            hs_manacost_version = excluded.hs_manacost_version,
            title = excluded.title,
            slug = excluded.slug,
            source_url = excluded.source_url,
            match_state = excluded.match_state,
            published_at = excluded.published_at,
            modified_at = excluded.modified_at,
            excerpt = excluded.excerpt,
            summary = excluded.summary,
            sections_json = excluded.sections_json,
            categories_json = excluded.categories_json,
            tags_json = excluded.tags_json,
            content_text = excluded.content_text,
            fetched_at = excluded.fetched_at
        """,
        (
            normalized["version"],
            normalized["display_version"],
            normalized["wiki_rank"],
            normalized["wiki_title"],
            normalized["wiki_url"],
            normalized["official_title"],
            normalized["official_url"],
            normalized["official_published_at"],
            normalized["official_modified_at"],
            normalized["official_summary"],
            normalized["hs_manacost_version"],
            normalized["title"],
            normalized["slug"],
            normalized["source_url"],
            normalized["match_state"],
            normalized["published_at"],
            normalized["modified_at"],
            normalized["excerpt"],
            normalized["summary"],
            _dump(normalized["sections"]),
            _dump(normalized["categories"]),
            _dump(normalized["tags"]),
            normalized["content_text"],
            normalized["fetched_at"],
        ),
    )


def _rebuild_table(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn)
    old_rows = [dict(row) for row in conn.execute("SELECT * FROM hearthstone_patches").fetchall()]
    conn.execute("ALTER TABLE hearthstone_patches RENAME TO hearthstone_patches_v1")
    _create_table(conn)
    for row in old_rows:
        version = str(row["version"])
        patch = {
            "version": version,
            "display_version": row.get("display_version") or version,
            "wiki_rank": row.get("wiki_rank") if "wiki_rank" in columns else None,
            "wiki_title": row.get("wiki_title") if "wiki_title" in columns else f"Patch {version}",
            "wiki_url": row.get("wiki_url") or f"https://hearthstone.wiki.gg/wiki/Patch_{version}",
            "official_title": row.get("official_title"),
            "official_url": row.get("official_url"),
            "official_published_at": row.get("official_published_at"),
            "official_modified_at": row.get("official_modified_at"),
            "official_summary": row.get("official_summary"),
            "hs_manacost_version": row.get("hs_manacost_version"),
            "title": row.get("title"),
            "slug": row.get("slug"),
            "source_url": row.get("source_url"),
            "match_state": row.get("match_state") if "match_state" in columns else "matched",
            "published_at": row.get("published_at"),
            "modified_at": row.get("modified_at"),
            "excerpt": row.get("excerpt"),
            "summary": row.get("summary"),
            "sections": _load_json(row.get("sections_json"), []),
            "categories": _load_json(row.get("categories_json"), []),
            "tags": _load_json(row.get("tags_json"), []),
            "content_text": row.get("content_text"),
            "fetched_at": row.get("fetched_at") or datetime.now(UTC).isoformat(),
        }
        _insert_patch(conn, patch)
    conn.execute("DROP TABLE hearthstone_patches_v1")


def init_patches_db(conn: sqlite3.Connection | None = None) -> None:
    own_conn = conn is None
    conn = conn or get_db_connection()
    try:
        with conn:
            if _needs_rebuild(conn):
                _rebuild_table(conn)
            else:
                _create_table(conn)
    finally:
        if own_conn:
            conn.close()


def _row_to_patch(row: sqlite3.Row, *, include_content: bool = False) -> dict[str, Any]:
    patch = dict(row)
    patch["sections"] = _load_json(patch.pop("sections_json", None), [])
    patch["categories"] = _load_json(patch.pop("categories_json", None), [])
    patch["tags"] = _load_json(patch.pop("tags_json", None), [])
    if not include_content:
        patch.pop("content_text", None)
    return patch


def upsert_patch(patch: dict[str, Any]) -> None:
    init_patches_db()
    conn = get_db_connection()
    try:
        with conn:
            _insert_patch(conn, patch)
    finally:
        conn.close()


def delete_patches_not_in(versions: set[str]) -> int:
    init_patches_db()
    if not versions:
        return 0
    conn = get_db_connection()
    try:
        placeholders = ",".join("?" for _ in versions)
        with conn:
            cursor = conn.execute(
                f"DELETE FROM hearthstone_patches WHERE version NOT IN ({placeholders})",
                tuple(sorted(versions)),
            )
        return int(cursor.rowcount or 0)
    finally:
        conn.close()


def list_patches(
    *,
    q: str | None = None,
    match_state: str | None = None,
    limit: int = 20,
    offset: int = 0,
    include_content: bool = False,
) -> dict[str, Any]:
    init_patches_db()
    conn = get_db_connection()
    try:
        where = "1=1"
        params: list[Any] = []
        if q:
            where += (
                " AND (version LIKE ? OR hs_manacost_version LIKE ? OR "
                "wiki_title LIKE ? OR title LIKE ? OR summary LIKE ?)"
            )
            like = f"%{q}%"
            params.extend([like, like, like, like, like])
        if match_state:
            where += " AND match_state = ?"
            params.append(match_state)
        total = conn.execute(f"SELECT COUNT(*) FROM hearthstone_patches WHERE {where}", params).fetchone()[0]
        matched = conn.execute(
            "SELECT COUNT(*) FROM hearthstone_patches WHERE match_state = 'matched'"
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT {PATCH_COLUMNS}
            FROM hearthstone_patches
            WHERE {where}
            ORDER BY wiki_rank IS NULL, wiki_rank ASC, published_at DESC, version DESC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        return {
            "total": total,
            "matched_total": matched,
            "missing_manacost_total": max(0, total - matched) if not match_state else None,
            "limit": limit,
            "offset": offset,
            "patches": [_row_to_patch(row, include_content=include_content) for row in rows],
        }
    finally:
        conn.close()


def get_patch(version: str, *, include_content: bool = True) -> dict[str, Any] | None:
    init_patches_db()
    conn = get_db_connection()
    try:
        row = conn.execute(
            f"""
            SELECT {PATCH_COLUMNS}
            FROM hearthstone_patches
            WHERE version = ? OR hs_manacost_version = ?
            ORDER BY wiki_rank IS NULL, wiki_rank ASC, published_at DESC, version DESC
            LIMIT 1
            """,
            (version, version),
        ).fetchone()
        if row is None:
            return None
        return _row_to_patch(row, include_content=include_content)
    finally:
        conn.close()
