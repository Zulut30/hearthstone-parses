from __future__ import annotations

import re
from typing import Any

from hearthstone.deckstrings import Deck

from .cards_index import card_label, cards_by_dbfid

DECK_CODE_RE = re.compile(r"\bAAE[A-Za-z0-9+/=]{24,}\b")


def decode_deck_code(code: str) -> dict[str, Any]:
    by_dbf = cards_by_dbfid()
    try:
        deck = Deck.from_deckstring(code.strip())
    except Exception as exc:
        return {"ok": False, "error": str(exc), "code": code, "cards": []}

    cards_out: list[dict[str, Any]] = []
    for dbfid, count in deck.get_dbf_id_list():
        meta = card_label(by_dbf.get(int(dbfid)))
        cards_out.append({**meta, "count": count})

    heroes: list[dict[str, Any]] = []
    raw_heroes = getattr(deck, "heroes", None) or []
    if isinstance(raw_heroes, list):
        for item in raw_heroes:
            dbfid = item[0] if isinstance(item, tuple) else item
            heroes.append(card_label(by_dbf.get(int(dbfid))))

    return {
        "ok": True,
        "code": code,
        "hero": heroes[0] if heroes else None,
        "cards": cards_out,
        "card_count": sum(c["count"] for c in cards_out),
    }


def _fix_base64_padding(code: str) -> str:
    return code + "=" * ((4 - len(code) % 4) % 4)


def first_deck_code_from_text(text: str) -> str | None:
    for match in DECK_CODE_RE.finditer(text):
        candidate = _fix_base64_padding(match.group(0))
        try:
            Deck.from_deckstring(candidate)
            return candidate
        except Exception:
            continue
    return None


def decode_all_codes_in_text(text: str) -> dict[str, Any] | None:
    for match in DECK_CODE_RE.finditer(text):
        result = decode_deck_code(_fix_base64_padding(match.group(0)))
        if result.get("ok"):
            return result
    return None
