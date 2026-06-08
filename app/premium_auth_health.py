from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from .hsreplay_auth import hsreplay_cookies_for_fetch
from .hsreplay_auth_status import hsreplay_auth_status
from .refresh_log import log_action


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    for marker in ("auth=", "idToken", "sessionid"):
        if marker in text:
            return "premium probe failed with sanitized auth error"
    return text[:240]


def _hsreplay_local_status() -> dict[str, Any]:
    status = hsreplay_auth_status()
    return {
        "configured": bool(status.get("credentials_configured") or status.get("present")),
        "storage_present": bool(status.get("present")),
        "has_session": bool(status.get("has_sessionid") or status.get("is_authenticated")),
        "age_hours": status.get("age_hours"),
        "warning": status.get("warning"),
    }


async def _probe_hsreplay() -> dict[str, Any]:
    cookies = hsreplay_cookies_for_fetch()
    if not any(cookie.get("name") == "sessionid" for cookie in cookies):
        return {"ok": False, "endpoint_readable": False, "detail": "session cookie missing"}
    checks: list[dict[str, Any]] = []

    async def _record(name: str, probe) -> None:  # type: ignore[no-untyped-def]
        try:
            checks.append(await probe())
        except Exception as exc:
            checks.append({"name": name, "ok": False, "detail": _safe_error(exc)})

    async def _bg_heroes_page() -> dict[str, Any]:
        from .hsreplay_client import fetch_text_via_flaresolverr

        body = await fetch_text_via_flaresolverr(
            "https://hsreplay.net/battlegrounds/heroes/",
            source_id="premium_auth_health_hsreplay",
        )
        lower = body.lower()
        ok = "battlegrounds" in lower and "could not load data" not in lower
        return {"name": "bg_heroes_page", "ok": ok, "bytes": len(body.encode("utf-8", errors="replace"))}

    async def _bg_hero_stats_api() -> dict[str, Any]:
        from .hsreplay_bg_heroes import _HERO_STATS_API, parse_hsreplay_bg_hero_stats_text
        from .hsreplay_client import fetch_text_via_flaresolverr

        body = await fetch_text_via_flaresolverr(
            _HERO_STATS_API,
            source_id="premium_auth_health_hsreplay",
        )
        stats = parse_hsreplay_bg_hero_stats_text(body)
        return {"name": "bg_hero_stats_api", "ok": bool(stats), "records": len(stats)}

    async def _arena_card_stats_api() -> dict[str, Any]:
        from .hsreplay_arena_api import fetch_arena_card_tiers

        payload = await fetch_arena_card_tiers(source_id="hsreplay_arena_cards_advanced")
        cards = payload.get("cards") or []
        has_hidden = any(
            card.get("winrate_when_drawn") is not None or card.get("winrate_when_played") is not None
            for card in cards
            if isinstance(card, dict)
        )
        return {"name": "arena_card_stats_api", "ok": len(cards) >= 100 and has_hidden, "records": len(cards)}

    async def _ranked_cards_api() -> dict[str, Any]:
        from .hsreplay_cards_api import fetch_hsreplay_ranked_cards
        from .sources import SOURCE_BY_ID

        payload = await fetch_hsreplay_ranked_cards(SOURCE_BY_ID["hsreplay_cards_legend_1d"])
        cards = payload.get("cards") or []
        return {"name": "ranked_cards_api", "ok": len(cards) >= 100, "records": len(cards)}

    async def _meta_archetypes_api() -> dict[str, Any]:
        from .hsreplay_meta_api import fetch_hsreplay_meta_archetypes
        from .sources import SOURCE_BY_ID

        payload = await fetch_hsreplay_meta_archetypes(SOURCE_BY_ID["hsreplay_meta_archetypes_legend_eu_1d"])
        rows = sum(len(group.get("archetypes") or []) for group in (payload.get("classes") or []))
        return {"name": "meta_archetypes_api", "ok": rows >= 20, "records": rows}

    await _record("bg_heroes_page", _bg_heroes_page)
    await _record("bg_hero_stats_api", _bg_hero_stats_api)
    await _record("arena_card_stats_api", _arena_card_stats_api)
    await _record("ranked_cards_api", _ranked_cards_api)
    await _record("meta_archetypes_api", _meta_archetypes_api)
    failures = [check for check in checks if not check.get("ok")]
    records = sum(int(check.get("records") or 0) for check in checks)
    if failures:
        return {
            "ok": False,
            "endpoint_readable": False,
            "records": records,
            "endpoint_checks": checks,
            "detail": f"{len(failures)} HSReplay premium/API endpoint checks failed",
        }
    return {
        "ok": True,
        "endpoint_readable": True,
        "records": records,
        "endpoint_checks": checks,
        "probe": "hsreplay_premium_endpoints",
    }

async def _probe_vicious_syndicate() -> dict[str, Any]:
    try:
        from .vicious_live import _firebase_json, _firebase_token

        async with httpx.AsyncClient(timeout=45.0) as client:
            token = await _firebase_token(client)
            payload = await _firebase_json(client, "premiumData/ladderData/Standard", token)
        readable = isinstance(payload.get("lastDay"), dict)
        return {
            "ok": readable,
            "endpoint_readable": readable,
            "probe": "premium_ladder_data",
            "has_last_day": readable,
        }
    except Exception as exc:
        return {"ok": False, "endpoint_readable": False, "detail": _safe_error(exc)}


async def build_premium_auth_health(*, live: bool = False) -> dict[str, Any]:
    hsreplay: dict[str, Any] = {
        "provider": "hsreplay",
        "live_checked": False,
        **_hsreplay_local_status(),
    }
    vicious: dict[str, Any] = {
        "provider": "vicious_syndicate",
        "live_checked": False,
        "configured": True,
        "storage_present": None,
        "has_session": None,
        "warning": None,
    }
    if live:
        hsreplay.update(await _probe_hsreplay(), live_checked=True)
        vicious.update(await _probe_vicious_syndicate(), live_checked=True)
        for provider in (hsreplay, vicious):
            for check in provider.get("endpoint_checks") or []:
                if not check.get("ok"):
                    log_action(
                        "premium_auth.endpoint.fail",
                        source_id=str(provider.get("provider") or "premium_auth"),
                        level="warn",
                        detail=str(check.get("detail") or check.get("name"))[:500],
                        extra={"provider": provider.get("provider"), "endpoint": check.get("name")},
                    )
    else:
        hsreplay["ok"] = bool(hsreplay["has_session"])
        vicious["ok"] = None
        vicious["warning"] = "live=true required to verify premium Firebase endpoint"

    providers = [hsreplay, vicious]
    live_failures = [item["provider"] for item in providers if item.get("live_checked") and not item.get("ok")]
    local_failures = [item["provider"] for item in providers if not item.get("live_checked") and item.get("ok") is False]
    return {
        "ok": not live_failures and not local_failures,
        "live": live,
        "checked_at": datetime.now(UTC).isoformat(),
        "providers": providers,
        "failures": live_failures or local_failures,
    }
