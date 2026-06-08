from __future__ import annotations

"""Sources that must use dedicated JSON/API fetchers — no HTML browser fallback."""

from .source_contracts import allows_browser_fallback
from .source_tiers import LIGHT_API_IDS, MEDIUM_API_IDS

# HTML/API via httpx but browser fallback helps when proxy or markup fails.
HTML_API_FALLBACK_ALLOWED: frozenset[str] = frozenset(
    {
        "metastats_decks",
        "metastats_matchups",
        "heartharena_tierlist",
        "hearthstone_decks",
        "vicious_syndicate_radars",
    }
)

# True JSON/static API — browser fallback hits wrong sites (HSReplay HTML on Firestone URL).
API_ONLY_NO_BROWSER_FALLBACK: frozenset[str] = frozenset(
    sid
    for sid in (LIGHT_API_IDS | MEDIUM_API_IDS)
    if sid not in HTML_API_FALLBACK_ALLOWED
)


def blocks_browser_fallback(source_id: str) -> bool:
    if not allows_browser_fallback(source_id, default=True):
        return True
    if source_id.startswith("hsreplay_cards_"):
        return True
    if source_id in HTML_API_FALLBACK_ALLOWED:
        return False
    return source_id in API_ONLY_NO_BROWSER_FALLBACK
