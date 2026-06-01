from __future__ import annotations

from typing import Any

from .deck_decode import decode_all_codes_in_text, decode_deck_code, first_deck_code_from_text
from .sources import SOURCE_BY_ID, SOURCES
from .storage import load_dataset, load_status


def _meta_view(data: dict[str, Any]) -> dict[str, Any]:
    tables = data.get("tables") or []
    archetypes: list[dict[str, Any]] = []
    for table in tables:
        for row in table.get("objects") or []:
            archetypes.append(
                {
                    "strategy": row.get("Archetype") or row.get("column_1"),
                    "winrate": row.get("Winrate↓") or row.get("Winrate"),
                    "popularity": row.get("Popularity"),
                    "details": row,
                }
            )
    return {
        "kind": "meta",
        "title": data.get("title"),
        "strategies": archetypes[:40],
        "total": len(archetypes),
    }


def _matchups_view(data: dict[str, Any]) -> dict[str, Any]:
    tables = data.get("tables") or []
    rows: list[dict[str, Any]] = []
    for table in tables:
        rows.extend(table.get("objects") or [])
    preview = [
        line
        for line in data.get("text_preview") or []
        if "%" in line or "vs" in line.lower()
    ][:40]
    return {
        "kind": "matchups",
        "title": data.get("title"),
        "matrix_rows": rows[:30],
        "highlights": preview,
    }


def _streamer_decks_view(data: dict[str, Any]) -> dict[str, Any]:
    decks: list[dict[str, Any]] = []
    for table in data.get("tables") or []:
        for row in table.get("objects") or []:
            raw_deck = str(row.get("Deck") or "")
            decoded = decode_all_codes_in_text(raw_deck) or {"ok": False, "cards": []}
            code = decoded.get("code") or first_deck_code_from_text(raw_deck) or ""
            name = str(row.get("Streamer") or "Unknown")
            if "###" in raw_deck:
                parts = raw_deck.split("###")
                if len(parts) > 1:
                    name = parts[1].strip()[:80] or name
            elif " AAEC" in raw_deck or " AAE" in raw_deck:
                name = raw_deck.split("AAE")[0].strip()[:80] or name
            decks.append(
                {
                    "strategy": name,
                    "streamer": row.get("Streamer"),
                    "format": row.get("Format"),
                    "record": row.get("Win - Loss"),
                    "deck_code": code or None,
                    "cards": decoded.get("cards") if decoded.get("ok") else [],
                    "hero": decoded.get("hero"),
                    "decode_ok": decoded.get("ok", False),
                }
            )
    for code in data.get("deck_codes") or []:
        if any(d.get("deck_code") == code for d in decks):
            continue
        decoded = decode_deck_code(code)
        decks.append(
            {
                "strategy": "Deck",
                "streamer": None,
                "format": None,
                "record": None,
                "deck_code": code,
                "cards": decoded.get("cards") if decoded.get("ok") else [],
                "hero": decoded.get("hero"),
                "decode_ok": decoded.get("ok", False),
            }
        )
    return {"kind": "streamer_decks", "title": data.get("title"), "decks": decks[:25]}


def _hsreplay_view(data: dict[str, Any], source_id: str) -> dict[str, Any]:
    tables = data.get("tables") or []
    class_matrix: list[dict[str, Any]] = []
    for table in tables:
        for row in table.get("objects") or []:
            if any("%" in str(v) for v in row.values()):
                class_matrix.append(row)

    highlights = [
        line
        for line in data.get("text_preview") or []
        if any(
            k in line.lower()
            for k in ("tier", "winrate", "hero", "deck", "arena", "class", "%", "pick")
        )
    ][:50]

    deck_links = [
        link
        for link in data.get("links") or []
        if "deck" in (link.get("href") or "").lower() and link.get("text")
    ][:20]

    return {
        "kind": "hsreplay",
        "source_id": source_id,
        "title": data.get("title"),
        "class_matrix": class_matrix[:15],
        "highlights": highlights,
        "deck_links": deck_links,
        "note": "Карты с id/dbfId — из deck codes HSGuru; HSReplay SPA — текст и ссылки со страницы.",
    }


def build_demo_view(source_id: str) -> dict[str, Any]:
    source = SOURCE_BY_ID[source_id]
    status = load_status(source_id)
    dataset = load_dataset(source_id)
    if dataset is None:
        return {
            "source_id": source_id,
            "ok": False,
            "status": status,
            "message": "Нет кэшированного датасета",
        }

    data = dataset.get("data") or {}
    if source.category == "meta":
        view = _meta_view(data)
    elif source.category == "matchups":
        view = _matchups_view(data)
    elif source.category == "streamer_decks":
        view = _streamer_decks_view(data)
    else:
        view = _hsreplay_view(data, source_id)

    return {
        "source_id": source_id,
        "ok": True,
        "site": source.site,
        "category": source.category,
        "url": source.url,
        "fetched_at": dataset.get("fetched_at"),
        "backend": dataset.get("backend"),
        "status": status,
        "view": view,
    }


def build_overview() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for source in SOURCES:
        status = load_status(source.id) or {}
        dataset = load_dataset(source.id)
        items.append(
            {
                "source_id": source.id,
                "site": source.site,
                "category": source.category,
                "description": source.description,
                "state": status.get("state", "never_fetched"),
                "fetched_at": dataset.get("fetched_at") if dataset else None,
                "has_dataset": dataset is not None,
            }
        )
    ok = sum(1 for i in items if i["state"] == "ok")
    return {"sources": items, "ok_count": ok, "total": len(items)}
