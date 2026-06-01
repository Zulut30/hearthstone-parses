from __future__ import annotations

import asyncio
import fcntl
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .config import (
    data_dir,
    fetch_backends,
    fetch_direct_enabled,
    fetch_proxy_url,
    fetch_require_proxy,
    request_delay_seconds,
    request_timeout_seconds,
    user_agent,
)
from .parser import parse_html
from .scrapers.browser_pool import PatchrightPool
from .scrapers.flaresolverr import set_active_flaresolverr_session, set_flaresolverr_source
from .scrapers.flaresolverr_session import FlareSolverrSession
from .scrapers.proxy import check_proxy_health
from .scrapers.quality import is_cloudflare_challenge, validate_parsed_data
from .scrapers.rotator import fetch_html
from .sources import SOURCES, SOURCE_BY_ID, Source
from .storage import load_status, save_dataset, save_status

LOCK_PATH = Path(os.environ.get("HS_API_DATA_DIR", "/var/lib/hs-data-api")) / ".refresh.lock"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _status_payload(
    source: Source,
    state: str,
    *,
    fetched_at: str,
    http_status: int | None = None,
    final_url: str | None = None,
    error: str | None = None,
    detail: str | None = None,
    content_length: int | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_id": source.id,
        "site": source.site,
        "category": source.category,
        "url": source.url,
        "fetch_url": source.fetch_url,
        "fragment": source.fragment,
        "state": state,
        "fetched_at": fetched_at,
        "http_status": http_status,
        "final_url": final_url,
        "error": error,
        "detail": detail,
        "content_length": content_length,
    }
    if backend:
        payload["backend"] = backend
    return payload


async def send_telegram_alert(source_id: str, state: str, detail: str, url: str) -> None:
    from .config import telegram_bot_token, telegram_chat_id
    token = telegram_bot_token()
    chat_id = telegram_chat_id()
    if not token or not chat_id:
        return
    
    text_message = (
        f"⚠️ <b>Hearthstone Parser Alert</b>\n\n"
        f"<b>Source ID:</b> <code>{source_id}</code>\n"
        f"<b>URL:</b> {url}\n"
        f"<b>State:</b> 🟥 <code>{state}</code>\n"
        f"<b>Detail:</b> {detail or 'N/A'}\n"
        f"<b>Time:</b> {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text_message,
        "parse_mode": "HTML",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(api_url, json=payload)
            response.raise_for_status()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Failed to send Telegram notification: %s", e)


class RefreshLock:
    def __init__(self, path: Path = LOCK_PATH) -> None:
        self.path = path
        self._fh = None

    def __enter__(self) -> RefreshLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another refresh is already running") from exc
        self._fh.write(f"pid={os.getpid()}\n")
        self._fh.flush()
        return self

    def __exit__(self, *args: object) -> None:
        if self._fh is not None:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self.path.unlink(missing_ok=True)


async def _fetch_direct(client: httpx.AsyncClient, source: Source) -> tuple[str, int, str]:
    response = await client.get(source.fetch_url)
    return response.text, response.status_code, str(response.url)


def _dataset_from_structured(source: Source, structured: dict[str, Any], *, backend: str) -> dict[str, Any]:
    import json as json_mod

    body = json_mod.dumps(structured, ensure_ascii=False)
    return {
        "source_id": source.id,
        "site": source.site,
        "category": source.category,
        "url": source.url,
        "fetch_url": source.fetch_url,
        "fragment": source.fragment,
        "title": source.description or source.id,
        "tables": [],
        "json_scripts": [],
        "hsreplay_bootstrap": None,
        "structured": structured,
        "hsreplay_extracted": structured,
        "deck_codes": [],
        "links": [],
        "text_preview": [],
        "counts": {
            "tables": 0,
            "json_scripts": 0,
            "deck_codes": 0,
            "links": 0,
            "text_lines": 0,
            "api_bytes": len(body.encode("utf-8")),
        },
        "_backend": backend,
    }


async def _fetch_hsreplay_api_source(source: Source) -> dict[str, Any] | None:
    if source.id == "hsreplay_arena_winning_decks":
        from .hsreplay_arena_api import fetch_winning_decks

        structured = await fetch_winning_decks(source_id=source.id, limit=20)
        backend = structured.get("source", {}).get("backend", "hsreplay_api")
        return _dataset_from_structured(source, structured, backend=backend)
    if source.id == "hsreplay_battlegrounds_comps":
        from .battlegrounds_comps_parse import fetch_battlegrounds_comps

        structured = await fetch_battlegrounds_comps(source_id=source.id, detail_limit=24)
        backend = structured.get("source", {}).get("backend", "hsreplay_jina_markdown")
        return _dataset_from_structured(source, structured, backend=backend)
    if source.id == "hsreplay_arena_legendaries":
        from .hsreplay_legendaries_api import fetch_legendary_groups

        structured = await fetch_legendary_groups(source_id=source.id)
        backend = structured.get("source", {}).get("backend", "hsreplay_api")
        return _dataset_from_structured(source, structured, backend=backend)
    if source.id == "hsreplay_arena":
        from .hsreplay_arena_api import fetch_class_stats

        structured = await fetch_class_stats(source_id=source.id)
        backend = structured.get("source", {}).get("backend", "hsreplay_api")
        return _dataset_from_structured(source, structured, backend=backend)
    if source.id == "hsreplay_arena_cards_advanced":
        from .hsreplay_arena_api import fetch_arena_card_tiers

        structured = await fetch_arena_card_tiers(source_id=source.id)
        backend = structured.get("source", {}).get("backend", "hsreplay_api")
        return _dataset_from_structured(source, structured, backend=backend)
    if source.id == "firestone_battlegrounds_comps":
        from .firestone_comps import fetch_firestone_comps

        structured = await fetch_firestone_comps(source)
        return _dataset_from_structured(source, structured, backend="firestone_api")
    if source.id == "firestone_battlegrounds_cards":
        from .firestone_comps import fetch_firestone_cards

        structured = await fetch_firestone_cards(source)
        return _dataset_from_structured(source, structured, backend="firestone_api")
    if source.id == "firestone_battlegrounds_spells":
        from .firestone_comps import fetch_firestone_cards

        structured = await fetch_firestone_cards(source)
        return _dataset_from_structured(source, structured, backend="firestone_api")
    if source.id in (
        "firestone_arena_cards_normal",
        "firestone_arena_cards_underground",
        "firestone_arena_legendaries_underground",
        "firestone_arena_legendaries_normal",
    ):
        from .firestone_comps import fetch_firestone_arena

        structured = await fetch_firestone_arena(source)
        return _dataset_from_structured(source, structured, backend="firestone_api")
    if source.id == "heartharena_tierlist":
        from .heartharena import fetch_heartharena_tierlist

        structured = await fetch_heartharena_tierlist(source)
        return _dataset_from_structured(source, structured, backend="heartharena_api")
    if source.id == "metastats_decks":
        from .metastats import fetch_metastats_decks

        structured = await fetch_metastats_decks(source)
        return _dataset_from_structured(source, structured, backend="metastats_api")
    if source.id == "metastats_matchups":
        from .metastats import fetch_metastats_matchups

        structured = await fetch_metastats_matchups(source)
        return _dataset_from_structured(source, structured, backend="metastats_api")
    if source.id == "hearthstone_decks":
        from .hearthstone_decks import fetch_hearthstone_decks

        structured = await fetch_hearthstone_decks(source)
        return _dataset_from_structured(source, structured, backend="hearthstone_decks_api")
    if source.id == "vicious_syndicate_radars":
        from .vicious_syndicate import fetch_vicious_syndicate_radars

        structured = await fetch_vicious_syndicate_radars(source)
        return _dataset_from_structured(source, structured, backend="vicious_syndicate_api")
    return None


async def fetch_source(client: httpx.AsyncClient | None, source: Source, retry_on_auth_failure: bool = True) -> dict[str, Any]:
    fetched_at = now_iso()
    previous = load_status(source.id) or {}
    preferred_backend = previous.get("backend") if previous.get("state") == "ok" else None

    if fetch_require_proxy() and not fetch_proxy_url():
        status = _status_payload(
            source,
            "proxy_required",
            fetched_at=fetched_at,
            detail="Set HS_FETCH_PROXY_URL in /etc/hs-data-api.env",
        )
        save_status(source.id, status)
        await send_telegram_alert(source.id, "proxy_required", status["detail"], source.url)
        return status

    if source.id in (
        "hsreplay_arena",
        "hsreplay_arena_cards_advanced",
        "hsreplay_arena_winning_decks",
        "hsreplay_arena_legendaries",
        "hsreplay_battlegrounds_comps",
        "firestone_battlegrounds_comps",
        "firestone_battlegrounds_cards",
        "firestone_battlegrounds_spells",
        "firestone_arena_cards_normal",
        "firestone_arena_cards_underground",
        "firestone_arena_legendaries_underground",
        "firestone_arena_legendaries_normal",
        "heartharena_tierlist",
        "metastats_decks",
        "metastats_matchups",
        "hearthstone_decks",
        "vicious_syndicate_radars",
    ):
        try:
            parsed = await _fetch_hsreplay_api_source(source)
            if parsed is not None:
                ok, reason = validate_parsed_data(source, parsed)
                backend = parsed.pop("_backend", "hsreplay_api")
                content_length = parsed.get("counts", {}).get("api_bytes", 0)
                if ok:
                    dataset = {
                        "source_id": source.id,
                        "fetched_at": fetched_at,
                        "data": parsed,
                    }
                    save_dataset(source.id, dataset)
                    status = _status_payload(
                        source,
                        "ok",
                        fetched_at=fetched_at,
                        http_status=200,
                        final_url=source.url,
                        content_length=content_length,
                        backend=backend,
                    )
                    save_status(source.id, status)
                    return status
                status = _status_payload(
                    source,
                    "quality_error",
                    fetched_at=fetched_at,
                    http_status=200,
                    final_url=source.url,
                    detail=reason,
                    content_length=content_length,
                    backend=backend,
                )
                save_status(source.id, status)
                await send_telegram_alert(source.id, "quality_error", status["detail"], source.url)
                return status
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "HSReplay API fetch failed for %s, falling back to browser: %s",
                source.id,
                exc,
            )

    set_flaresolverr_source(source.id)
    page_snapshot = None
    try:
        if fetch_direct_enabled() and client is not None:
            body, http_status, final_url = await _fetch_direct(client, source)
            backend = "direct"
        else:
            result = await fetch_html(
                source,
                preferred_backend=preferred_backend,
                parse_preview=lambda html: parse_html(source, html),
            )
            body = result.html
            http_status = result.http_status
            final_url = result.final_url
            backend = result.backend
            page_snapshot = result.snapshot
    except Exception as exc:
        status = _status_payload(
            source,
            "fetch_error",
            fetched_at=fetched_at,
            error=type(exc).__name__,
            detail=str(exc)[:2000],
        )
        save_status(source.id, status)
        await send_telegram_alert(source.id, "fetch_error", status["detail"], source.url)
        return status
    finally:
        set_flaresolverr_source(None)

    content_length = len(body.encode("utf-8", errors="replace"))
    if is_cloudflare_challenge(body):
        status = _status_payload(
            source,
            "blocked_by_protection",
            fetched_at=fetched_at,
            http_status=http_status,
            final_url=final_url,
            detail="Cloudflare challenge after all backends.",
            content_length=content_length,
            backend=backend,
        )
        save_status(source.id, status)
        await send_telegram_alert(source.id, "blocked_by_protection", status["detail"], source.url)
        return status

    if http_status >= 400:
        status = _status_payload(
            source,
            "http_error",
            fetched_at=fetched_at,
            http_status=http_status,
            final_url=final_url,
            detail="HTTP error from origin",
            content_length=content_length,
            backend=backend,
        )
        save_status(source.id, status)
        await send_telegram_alert(source.id, "http_error", status["detail"], source.url)
        return status

    parsed = parse_html(source, body, page_snapshot)
    ok, reason = validate_parsed_data(source, parsed)
    if not ok:
        is_auth_error = source.site == "hsreplay" and any(
            k in reason.lower() for k in ("session not authenticated", "premium data", "login required")
        )
        if is_auth_error and retry_on_auth_failure:
            from .hsreplay_auth import force_relogin_hsreplay, hsreplay_email, hsreplay_password
            if hsreplay_email() and hsreplay_password():
                import logging
                logging.getLogger(__name__).warning(
                    "Detected invalid/expired HSReplay session for %s (%s). Forcing automatic relogin and retry...",
                    source.id,
                    reason,
                )
                relogin_success = await force_relogin_hsreplay()
                if relogin_success:
                    logging.getLogger(__name__).info("Relogin successful, retrying fetch for %s...", source.id)
                    return await fetch_source(client, source, retry_on_auth_failure=False)

        status = _status_payload(
            source,
            "quality_error",
            fetched_at=fetched_at,
            http_status=http_status,
            final_url=final_url,
            detail=reason,
            content_length=content_length,
            backend=backend,
        )
        save_status(source.id, status)
        await send_telegram_alert(source.id, "quality_error", reason, source.url)
        return status

    dataset = {
        "state": "ok",
        "fetched_at": fetched_at,
        "http_status": http_status,
        "final_url": final_url,
        "content_length": content_length,
        "backend": backend,
        "data": parsed,
    }
    save_dataset(source.id, dataset)
    status = _status_payload(
        source,
        "ok",
        fetched_at=fetched_at,
        http_status=http_status,
        final_url=final_url,
        content_length=content_length,
        backend=backend,
    )
    save_status(source.id, status)
    return status


async def refresh_sources(source_ids: list[str] | None = None) -> list[dict[str, Any]]:
    with RefreshLock():
        return await _refresh_sources_unlocked(source_ids)


async def _refresh_sources_unlocked(source_ids: list[str] | None = None) -> list[dict[str, Any]]:
    selected = list(SOURCES)
    if source_ids:
        selected = [SOURCE_BY_ID[source_id] for source_id in source_ids]

    proxy_info: dict[str, str] = {}
    if fetch_require_proxy() and not fetch_direct_enabled():
        proxy_info = await check_proxy_health()

    client: httpx.AsyncClient | None = None
    if fetch_direct_enabled():
        headers = {
            "User-Agent": user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        }
        timeout = httpx.Timeout(request_timeout_seconds())
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=0)
        client = httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
            limits=limits,
            http2=True,
        )

    api_sources = {
        "hsreplay_arena",
        "hsreplay_arena_cards_advanced",
        "hsreplay_arena_winning_decks",
        "hsreplay_arena_legendaries",
        "hsreplay_battlegrounds_comps",
        "firestone_battlegrounds_comps",
        "firestone_battlegrounds_cards",
        "firestone_battlegrounds_spells",
        "firestone_arena_cards_normal",
        "firestone_arena_cards_underground",
        "firestone_arena_legendaries_underground",
        "firestone_arena_legendaries_normal",
        "heartharena_tierlist",
        "metastats_decks",
        "metastats_matchups",
        "hearthstone_decks",
        "vicious_syndicate_radars",
    }
    non_api_selected = [s for s in selected if s.id not in api_sources]

    use_flaresolverr = bool(non_api_selected) and "flaresolverr" in [b.lower() for b in fetch_backends()]
    use_patchright = bool(non_api_selected) and ("patchright" in [b.lower() for b in fetch_backends()] or "playwright" in [
        b.lower() for b in fetch_backends()
    ])

    results: list[dict[str, Any]] = []
    fs_session: FlareSolverrSession | None = None
    try:
        if use_patchright and not fetch_direct_enabled():
            await PatchrightPool.get()
        if use_flaresolverr and not fetch_direct_enabled():
            fs_session = FlareSolverrSession()
            await fs_session.__aenter__()
            set_active_flaresolverr_session(fs_session)
        for source in selected:
            status = await fetch_source(client, source)
            if proxy_info and status.get("state") == "ok":
                status["proxy_egress_ip"] = proxy_info.get("egress_ip")
            results.append(status)
            import random
            delay_seconds = request_delay_seconds()
            jitter_delay = delay_seconds * random.uniform(0.75, 1.25)
            await asyncio.sleep(jitter_delay)
    finally:
        if fs_session is not None:
            set_active_flaresolverr_session(None)
            await fs_session.__aexit__(None, None, None)
        if use_patchright and not fetch_direct_enabled():
            await PatchrightPool.shutdown()
        if client is not None:
            await client.aclose()
    return results
