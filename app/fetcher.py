from __future__ import annotations

import asyncio
import fcntl
import html
import logging
import os
import random
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import httpx

from .config import (
    data_dir,
    fetch_backends,
    fetch_direct_enabled,
    fetch_proxy_url,
    fetch_require_proxy,
    firecrawl_fallback_max_attempts_per_refresh,
    firecrawl_fallback_source_ids,
    firecrawl_primary_source_ids,
    flaresolverr_session_per_source,
    refresh_delay_browser_only,
    refresh_parallel_light,
    refresh_parallel_medium,
    refresh_parallel_stagger_max,
    refresh_parallel_stagger_min,
    request_delay_seconds,
    request_timeout_seconds,
    user_agent,
)
from .source_tiers import (
    API_FIRST_TIERS,
    SourceTier,
    partition_sources,
    tier_for,
    validate_tier_registry,
)
from .parser import parse_html
from .scrapers.browser_pool import PatchrightPool
from .scrapers.flaresolverr import set_active_flaresolverr_session, set_flaresolverr_source
from .scrapers.flaresolverr_session import FlareSolverrSession
from .config import http_retry_attempts, proxy_check_url
from .scrapers.http_resilience import is_session_blocked, resilient_http_get
from .scrapers.proxy import burn_proxy_session, check_proxy_health, proxy_url_for_source
from .scrapers.quality import is_cloudflare_challenge, quality_metrics, validate_parsed_data
from .scrapers.rotator import fetch_html
from .sources import SOURCES, SOURCE_BY_ID, Source
from .api_only_sources import blocks_browser_fallback
from .refresh_log import (
    activate_source_trace,
    complete_source_trace,
    deactivate_source_trace,
    log_action,
    log_event,
    new_run_id,
    runtime_version_info,
    set_refresh_context,
)
from .dataset_regression import check_dataset_regression
from .proxy_errors import ProxyPaymentRequiredError
from .storage import load_dataset, load_status, save_dataset, save_status
from .telegram_alerts import mark_alert_sent, should_send_alert

logger = logging.getLogger(__name__)
_firecrawl_fallback_attempts = 0


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
    used_residential_proxy: bool | None = None,
    quality: dict[str, Any] | None = None,
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
        "runtime": runtime_version_info(),
    }
    if backend:
        payload["backend"] = backend
    if used_residential_proxy is not None:
        payload["used_residential_proxy"] = used_residential_proxy
    if quality:
        payload["quality"] = quality
        if quality.get("quality_score") is not None:
            payload["quality_score"] = quality.get("quality_score")
        if quality.get("rows_total") is not None:
            payload["rows_total"] = quality.get("rows_total")
    return payload


def _source_uses_residential_proxy(source: Source, backend: str | None) -> bool:
    if not fetch_proxy_url() or not backend:
        return False
    if backend == "flaresolverr":
        from .scrapers.proxy import source_can_use_flaresolverr_without_proxy

        return not source_can_use_flaresolverr_without_proxy(source)
    if backend == "hsreplay_premium_flaresolverr":
        return False
    if backend in {"direct", "patchright", "scrapling", "curl_cffi", "cloudscraper", "cloakbrowser"}:
        return True
    if backend == "firestone_api":
        return False
    return backend in {
        "heartharena_api",
        "metastats_api",
        "hearthstone_decks_api",
        "vicious_syndicate_api",
        "hsreplay_api",
        "hsreplay_cards_api",
        "hsreplay_jina_markdown",
    } or backend.startswith("hsreplay_")


def _looks_like_hsreplay_auth_error(message: str) -> bool:
    lower = message.lower()
    return any(
        marker in lower
        for marker in (
            "session not authenticated",
            "not authenticated",
            "premium data",
            "premium data unavailable",
            "login required",
            "subscription",
        )
    )


def _preserve_cached_ok_status(source: Source, failed_status: dict[str, Any]) -> dict[str, Any] | None:
    """Keep the last valid dataset visible when a live refresh attempt fails.

    The refresh job should not turn /health red just because a temporary proxy/CF
    failure prevented a fresh snapshot, as long as we still have a valid cached dataset.
    """
    dataset = load_dataset(source.id)
    if not dataset:
        return None
    parsed = dataset.get("data")
    if not isinstance(parsed, dict) or not parsed:
        return None
    try:
        ok, reason = validate_parsed_data(source, parsed)
    except Exception as exc:
        ok, reason = False, f"cached validation raised {type(exc).__name__}: {exc}"
    if not ok:
        log_action(
            "dataset.cached.invalid",
            source_id=source.id,
            level="warn",
            detail=reason,
        )
        return None

    cached_at = str(dataset.get("fetched_at") or failed_status.get("fetched_at") or now_iso())
    status = _status_payload(
        source,
        "ok",
        fetched_at=cached_at,
        http_status=dataset.get("http_status"),
        final_url=dataset.get("final_url") or source.url,
        content_length=dataset.get("content_length"),
        backend=dataset.get("backend"),
        detail="Serving cached dataset; latest live refresh failed.",
    )
    status["serving_cached_dataset"] = True
    status["effective_state"] = "ok_cached"
    status["last_refresh_state"] = failed_status.get("state")
    status["last_refresh_at"] = failed_status.get("fetched_at")
    status["last_refresh_error"] = (
        failed_status.get("detail") or failed_status.get("error") or "live refresh failed"
    )
    save_status(source.id, status)
    log_action(
        "dataset.preserve_previous_good",
        source_id=source.id,
        state="ok",
        backend=status.get("backend"),
        level="warn",
        detail=str(status["last_refresh_error"])[:500],
        extra={"last_refresh_state": status.get("last_refresh_state")},
    )
    return status


def _save_failure_status(source: Source, status: dict[str, Any]) -> dict[str, Any]:
    preserved = _preserve_cached_ok_status(source, status)
    if preserved is not None:
        return preserved
    save_status(source.id, status)
    return status


async def send_telegram_alert(source_id: str, state: str, detail: str, url: str) -> None:
    from .config import telegram_bot_token, telegram_chat_id

    token = telegram_bot_token()
    chat_id = telegram_chat_id()
    if not token or not chat_id:
        log_action(
            "alert.skipped",
            source_id=source_id,
            level="warn",
            detail="Telegram token/chat_id not configured",
            extra={"state": state},
        )
        return
    if not should_send_alert(source_id, state):
        log_action(
            "alert.skipped",
            source_id=source_id,
            detail="Telegram alert deduped",
            extra={"state": state},
        )
        return

    safe_source_id = html.escape(source_id)
    safe_url = html.escape(url)
    safe_state = html.escape(state)
    safe_detail = html.escape(detail or "N/A")
    text_message = (
        f"⚠️ <b>Hearthstone Parser Alert</b>\n\n"
        f"<b>Source ID:</b> <code>{safe_source_id}</code>\n"
        f"<b>URL:</b> {safe_url}\n"
        f"<b>State:</b> 🟥 <code>{safe_state}</code>\n"
        f"<b>Detail:</b> {safe_detail}\n"
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
        mark_alert_sent(source_id, state)
        log_action(
            "alert.sent",
            source_id=source_id,
            detail="Telegram alert sent",
            extra={"state": state},
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Failed to send Telegram notification: %s", e)
        log_action(
            "alert.failed",
            source_id=source_id,
            level="error",
            detail=str(e)[:500],
            extra={"state": state},
        )


async def _maybe_cached_after_failure_alert(source: Source, status: dict[str, Any]) -> None:
    if not status.get("serving_cached_dataset"):
        return
    if status.get("last_refresh_state") in (None, "ok"):
        return
    detail = (
        "Serving cached dataset after live refresh failed; "
        f"last_state={status.get('last_refresh_state')}; "
        f"reason={status.get('last_refresh_error') or status.get('detail') or 'unknown'}"
    )
    log_action(
        "dataset.cached_after_failure.alert",
        source_id=source.id,
        level="warn",
        detail=detail[:1000],
        extra={
            "last_refresh_state": status.get("last_refresh_state"),
            "last_refresh_at": status.get("last_refresh_at"),
            "cached_dataset_age_hours": status.get("cached_dataset_age_hours"),
        },
    )
    await send_telegram_alert(source.id, "cached_after_failure", detail, source.url)


class RefreshLock:
    def __init__(self, path: Any | None = None) -> None:
        self.path = path if path is not None else data_dir() / ".refresh.lock"
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


async def _fetch_direct(_client: httpx.AsyncClient, source: Source) -> tuple[str, int, str]:
    """FIX: resilient direct fetch — sticky proxy, session burn, exponential backoff."""
    from .scrapers.http_resilience import build_fetch_headers
    from .scrapers.proxy import httpx_client_kwargs

    url = source.fetch_url
    def _client_kwargs() -> dict[str, Any]:
        if fetch_proxy_url():
            return httpx_client_kwargs(
                source.id, page_url=url, timeout=request_timeout_seconds()
            )
        return {
            "timeout": request_timeout_seconds(),
            "follow_redirects": True,
        }

    kwargs = _client_kwargs()
    proxy_url = proxy_url_for_source(source.id, page_url=url) if fetch_proxy_url() else None

    headers = build_fetch_headers(url, extra={"User-Agent": user_agent()})

    def _burn() -> None:
        nonlocal proxy_url
        burn_proxy_session(source.id, page_url=url, reason="direct_fetch_blocked")
        kwargs.clear()
        kwargs.update(_client_kwargs())
        proxy_url = proxy_url_for_source(source.id, page_url=url) if fetch_proxy_url() else None

    return await resilient_http_get(
        url,
        source_id=source.id,
        client_kwargs=kwargs,
        headers=headers,
        max_attempts=http_retry_attempts(),
        proxy_url=proxy_url,
        proxy_check_url=proxy_check_url(),
        on_session_burn=_burn,
        validate_body=lambda code, body: not is_session_blocked(code, body),
    )


def _save_dataset_with_checks(
    source: Source,
    dataset: dict[str, Any],
    *,
    fetched_at: str,
) -> tuple[bool, str | None]:
    """
    Save dataset; run regression check against previous snapshot.
    Returns (regression_detected, regression_message).
    """
    previous = load_dataset(source.id)
    dataset.setdefault("runtime", runtime_version_info())
    prev_data = (previous or {}).get("data")
    new_data = dataset.get("data") or {}
    reg, msg, extra = check_dataset_regression(
        source, previous_data=prev_data, new_data=new_data
    )
    if reg:
        log_action(
            "quality.regression.warn",
            source_id=source.id,
            level="warn",
            detail=msg,
            extra=extra,
        )
        log_action(
            "dataset.preserve_previous_good",
            source_id=source.id,
            level="warn",
            detail=msg,
            extra={**extra, "reason": "regression_gate"},
        )
        log_action(
            "dataset.save.skip_regression",
            source_id=source.id,
            level="warn",
            detail=msg,
            extra=extra,
        )
        return reg, msg
    save_dataset(source.id, dataset)
    log_action(
        "dataset.save",
        source_id=source.id,
        state="ok",
        backend=dataset.get("backend"),
        bytes_out=dataset.get("content_length"),
        extra=extra if extra else None,
    )
    return reg, msg


async def _maybe_stale_data_alert(source: Source, status: dict[str, Any]) -> None:
    if status.get("state") not in {
        "fetch_error",
        "blocked_by_protection",
        "http_error",
        "quality_error",
        "proxy_required",
    }:
        return
    from .config import stale_dataset_hours

    dataset = load_dataset(source.id)
    if not dataset:
        return
    fetched_at = dataset.get("fetched_at")
    if not fetched_at:
        return
    try:
        prev_ts = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        if prev_ts.tzinfo is None:
            prev_ts = prev_ts.replace(tzinfo=UTC)
        age_hours = (datetime.now(UTC) - prev_ts).total_seconds() / 3600
    except ValueError:
        return
    if age_hours >= stale_dataset_hours():
        detail = (
            f"Serving stale dataset ({age_hours:.1f}h old); latest fetch failed: "
            f"{status.get('detail', '')[:500]}"
        )
        log_action(
            "dataset.stale.warn",
            source_id=source.id,
            level="warn",
            detail=detail,
            extra={"age_hours": round(age_hours, 1)},
        )
        await send_telegram_alert(source.id, "stale_data", detail, source.url)


def _dataset_from_structured(source: Source, structured: dict[str, Any], *, backend: str) -> dict[str, Any]:
    import json as json_mod

    from .structured_schema import validate_structured_schema

    schema_validation = validate_structured_schema(structured)
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
        "schema_validation": schema_validation,
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


def _dedupe_streamer_decks_parsed(parsed: dict[str, Any]) -> dict[str, Any]:
    from .deck_decode import first_deck_code_from_text

    tables = parsed.get("tables") or []
    if not tables:
        return parsed
    table = tables[0]
    headers = table.get("headers") or []
    objects = table.get("objects") or []
    if not isinstance(objects, list):
        return parsed

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in objects:
        if not isinstance(row, dict):
            continue
        deck_text = str(row.get("Deck") or "")
        deck_code = str(row.get("deck_code") or "").strip() or (first_deck_code_from_text(deck_text) or "")
        if deck_code:
            row["deck_code"] = deck_code
            key = f"code:{deck_code}"
        else:
            key = "|".join(
                [
                    str(row.get("Format") or "").strip().lower(),
                    str(row.get("Streamer") or "").strip().lower(),
                    deck_text[:160].strip().lower(),
                ]
            )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    table["objects"] = deduped
    if headers:
        table["rows"] = [[row.get(header, "") for header in headers] for row in deduped]
    structured = parsed.get("structured")
    if isinstance(structured, dict) and structured.get("type") == "streamer_decks":
        structured["rows"] = deduped
    return parsed


def _enrich_firecrawl_trinkets_from_cache(source: Source, parsed: dict[str, Any]) -> dict[str, Any]:
    from .structured import (
        enrich_trinket_variant_fields,
        normalize_trinket_tribe,
        trinket_identity_key,
        trinket_variant_key,
    )

    if source.id not in {
        "hsreplay_battlegrounds_trinkets_lesser",
        "hsreplay_battlegrounds_trinkets_greater",
    }:
        return parsed
    structured = parsed.get("structured")
    if not isinstance(structured, dict) or structured.get("type") != "bg_trinkets":
        return parsed
    rows = structured.get("trinkets") or []
    if not isinstance(rows, list) or not rows:
        return parsed

    previous = load_dataset(source.id) or {}
    previous_structured = (previous.get("data") or {}).get("structured") or {}
    canonical_rows = previous_structured.get("trinkets") or []
    trinket_type = "Lesser" if source.id.endswith("_lesser") else "Greater"
    normalized_canonical = [
        enrich_trinket_variant_fields(dict(row), trinket_type=trinket_type)
        for row in canonical_rows
        if isinstance(row, dict) and row.get("name")
    ]
    by_id = {
        str(row.get("trinket_id") or row.get("id") or "").strip().lower(): row
        for row in normalized_canonical
        if row.get("trinket_id") or row.get("id")
    }
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in normalized_canonical:
        by_name.setdefault(str(row.get("name") or "").strip().lower(), []).append(row)

    previous_active = [
        enrich_trinket_variant_fields(dict(row), trinket_type=trinket_type)
        for row in normalized_canonical
        if isinstance(row, dict) and (row.get("pick_rate") or row.get("avg_placement"))
    ]
    enriched_by_key: dict[str, dict[str, Any]] = {
        trinket_variant_key(row, trinket_type): row
        for row in previous_active
        if row.get("name")
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        row = enrich_trinket_variant_fields(dict(row), trinket_type=trinket_type)
        name_key = str(row.get("name") or "").strip().lower()
        id_key = str(row.get("trinket_id") or row.get("id") or "").strip().lower()
        tribe, _ = normalize_trinket_tribe(row.get("tribe") or row.get("race"))
        candidates = by_name.get(name_key) or []
        canonical = by_id.get(id_key) if id_key else None
        if not canonical and tribe:
            canonical = next((item for item in candidates if item.get("tribe") == tribe), None)
        if not canonical and len(candidates) == 1:
            canonical = candidates[0]
        canonical = canonical or {}
        if not canonical:
            continue
        merged = {**canonical, **row}
        if not merged.get("id") and merged.get("trinket_id"):
            merged["id"] = merged["trinket_id"]
        if not merged.get("type"):
            merged["type"] = trinket_type
        if canonical.get("trinket_id") and not merged.get("trinket_id"):
            merged["trinket_id"] = canonical["trinket_id"]
        if canonical.get("id") and not merged.get("id"):
            merged["id"] = canonical["id"]
        if canonical.get("dbfId") and not merged.get("dbfId"):
            merged["dbfId"] = canonical["dbfId"]
        if canonical.get("type") and not merged.get("type"):
            merged["type"] = canonical["type"]
        if canonical.get("localized_name") and not merged.get("localized_name"):
            merged["localized_name"] = canonical["localized_name"]
        if canonical.get("description") and not merged.get("description"):
            merged["description"] = canonical["description"]
        merged = enrich_trinket_variant_fields(merged, trinket_type=trinket_type)
        if merged.get("trinket_id") and (merged.get("pick_rate") or merged.get("avg_placement")):
            identity = trinket_identity_key(merged, trinket_type)
            for existing_key, existing in list(enriched_by_key.items()):
                if trinket_identity_key(existing, trinket_type) == identity:
                    enriched_by_key.pop(existing_key, None)
            enriched_by_key[trinket_variant_key(merged, trinket_type)] = merged

    enriched = list(enriched_by_key.values())
    if enriched:
        structured["trinkets"] = enriched
        structured["active_trinkets"] = len(enriched)
        structured["source"] = {
            **(structured.get("source") or {}),
            "backend": "firecrawl",
            "canonical_enriched_from_cache": True,
            "firecrawl_rows_merged_with_previous_active_cache": True,
        }
    return parsed


async def _try_firecrawl_html(
    source: Source,
    *,
    fetched_at: str,
    reason: str,
) -> dict[str, Any] | None:
    global _firecrawl_fallback_attempts
    is_primary = reason == "primary"
    if source.id not in (firecrawl_primary_source_ids() | firecrawl_fallback_source_ids()):
        return None
    if not is_primary:
        max_attempts = firecrawl_fallback_max_attempts_per_refresh()
        if _firecrawl_fallback_attempts >= max_attempts:
            log_action(
                "firecrawl.fetch.skip",
                source_id=source.id,
                backend="firecrawl",
                level="warn",
                detail=f"Firecrawl fallback attempt cap reached ({max_attempts})",
                extra={"reason": reason},
            )
            return None
        _firecrawl_fallback_attempts += 1
    try:
        from .firecrawl_backend import scrape_source

        log_action(
            "firecrawl.fetch.begin",
            source_id=source.id,
            backend="firecrawl",
            level="warn" if reason != "primary" else "info",
            detail=reason,
        )
        scraped = await scrape_source(source)
        snapshot = None
        if scraped.markdown:
            snapshot = {
                "lines": [
                    line.strip()
                    for line in scraped.markdown.splitlines()
                    if line.strip()
                ]
            }
        parsed = parse_html(source, scraped.html, snapshot=snapshot)
        if not parsed.get("title"):
            parsed["title"] = source.description or source.id
        if source.id == "hsguru_streamer_decks_legend_1000":
            parsed = _dedupe_streamer_decks_parsed(parsed)
        parsed = _enrich_firecrawl_trinkets_from_cache(source, parsed)
        ok, validation_reason = validate_parsed_data(source, parsed)
        qmetrics = quality_metrics(source, parsed)
        if not ok:
            log_action(
                "firecrawl.validate.fail",
                source_id=source.id,
                backend="firecrawl",
                state="quality_error",
                level="warn",
                detail=validation_reason,
                extra={"quality_metrics": qmetrics},
            )
            return None

        dataset = {
            "state": "ok",
            "fetched_at": fetched_at,
            "http_status": scraped.status_code,
            "final_url": scraped.final_url,
            "content_length": scraped.content_length,
            "backend": "firecrawl",
            "used_residential_proxy": False,
            "data": parsed,
        }
        reg, reg_msg = _save_dataset_with_checks(source, dataset, fetched_at=fetched_at)
        state = "partial" if reg else "ok"
        status = _status_payload(
            source,
            state,
            fetched_at=fetched_at,
            http_status=scraped.status_code,
            final_url=scraped.final_url,
            content_length=scraped.content_length,
            backend="firecrawl",
            detail=reg_msg if reg else None,
            used_residential_proxy=False,
            quality=qmetrics,
        )
        status["firecrawl_credits_used"] = scraped.metadata.get("creditsUsed")
        status["firecrawl_cache_state"] = scraped.metadata.get("cacheState")
        if reg:
            status = _save_failure_status(source, status)
        else:
            save_status(source.id, status)
        log_action(
            "firecrawl.fetch.ok",
            source_id=source.id,
            backend="firecrawl",
            state=state,
            bytes_out=scraped.content_length,
            extra={
                "credits_used": scraped.metadata.get("creditsUsed"),
                "cache_state": scraped.metadata.get("cacheState"),
                "reason": reason,
                "quality_metrics": qmetrics,
            },
        )
        return status
    except Exception as exc:
        log_action(
            "firecrawl.fetch.fail",
            source_id=source.id,
            backend="firecrawl",
            state="fetch_error",
            level="warn",
            error_type=type(exc).__name__,
            detail=str(exc)[:1000],
            extra={"reason": reason},
        )
        return None


async def _fetch_hsreplay_api_source(source: Source) -> dict[str, Any] | None:
    if source.id == "hsreplay_arena_winning_decks":
        from .hsreplay_arena_api import fetch_winning_decks

        structured = await fetch_winning_decks(source_id=source.id)
        backend = structured.get("source", {}).get("backend", "hsreplay_api")
        return _dataset_from_structured(source, structured, backend=backend)
    if source.id == "hsreplay_battlegrounds_comps":
        from .battlegrounds_comps_parse import fetch_battlegrounds_comps

        structured = await fetch_battlegrounds_comps(source_id=source.id, detail_limit=40)
        backend = structured.get("source", {}).get("backend", "hsreplay_jina_markdown")
        return _dataset_from_structured(source, structured, backend=backend)
    if source.id == "hsreplay_battlegrounds_heroes":
        from .hsreplay_bg_heroes import fetch_hsreplay_battlegrounds_heroes

        structured = await fetch_hsreplay_battlegrounds_heroes(source)
        backend = structured.get("source", {}).get("backend", "hsreplay_premium_flaresolverr")
        return _dataset_from_structured(source, structured, backend=backend)
    if source.id == "hsreplay_battlegrounds_minions":
        from .hsreplay_bg_stats import fetch_battlegrounds_minions

        structured = await fetch_battlegrounds_minions(source.id)
        backend = structured.get("source", {}).get("backend", "hsreplay_bg_api")
        return _dataset_from_structured(source, structured, backend=backend)
    if source.id == "hsreplay_battlegrounds_compositions":
        from .hsreplay_bg_stats import fetch_battlegrounds_compositions

        structured = await fetch_battlegrounds_compositions(source.id)
        backend = structured.get("source", {}).get("backend", "hsreplay_bg_api")
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
    if source.id == "hsreplay_arena_class_pages_firecrawl":
        from .hsreplay_arena_classes_firecrawl import fetch_arena_class_pages_firecrawl

        structured = await fetch_arena_class_pages_firecrawl(source.id)
        backend = structured.get("source", {}).get("backend", "firecrawl+hsreplay_arena_api")
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
    if source.id == "vicious_syndicate_live_beta":
        from .vicious_live import fetch_vicious_live

        structured = await fetch_vicious_live(source)
        return _dataset_from_structured(source, structured, backend="vicious_live_firebase")
    if source.id.startswith("hsreplay_cards_"):
        from .hsreplay_cards_api import fetch_hsreplay_ranked_cards

        structured = await fetch_hsreplay_ranked_cards(source)
        backend = structured.get("source", {}).get("backend", "hsreplay_cards_browser")
        return _dataset_from_structured(source, structured, backend=backend)
    if source.id in {
        "hsreplay_meta_archetypes_legend_eu_1d",
        "hsreplay_meta_top_1000_legend_1d_firecrawl",
        "hsreplay_meta_legend_1d_firecrawl",
        "hsreplay_meta_diamond_4to1_1d_firecrawl",
    }:
        from .hsreplay_meta_api import fetch_hsreplay_meta_archetypes

        structured = await fetch_hsreplay_meta_archetypes(source)
        backend = structured.get("source", {}).get("backend", "hsreplay_meta_api")
        return _dataset_from_structured(source, structured, backend=backend)
    return None


async def fetch_source(client: httpx.AsyncClient | None, source: Source, retry_on_auth_failure: bool = True) -> dict[str, Any]:
    started = time.monotonic()
    fetched_at = now_iso()
    previous = load_status(source.id) or {}
    from .scrapers.preferred_backend import preferred_browser_backend

    preferred_backend = preferred_browser_backend(previous)
    source_tier = tier_for(source.id).value
    _trace_id, _tok_trace, _tok_source, _tok_step = activate_source_trace(
        source.id, tier=source_tier, url=source.fetch_url
    )

    def _finish(status: dict[str, Any]) -> dict[str, Any]:
        complete_source_trace(
            source.id,
            status,
            tier=source_tier,
            started_monotonic=started,
            trace_id=_trace_id,
        )
        deactivate_source_trace((_tok_trace, _tok_source, _tok_step))
        return status

    if fetch_require_proxy() and not fetch_proxy_url():
        log_action(
            "proxy.health.fail",
            level="error",
            source_id=source.id,
            state="proxy_required",
            detail="HS_FETCH_PROXY_URL not configured",
        )
        status = _status_payload(
            source,
            "proxy_required",
            fetched_at=fetched_at,
            detail="Set HS_FETCH_PROXY_URL in /etc/hs-data-api.env",
        )
        status = _save_failure_status(source, status)
        if status.get("state") != "ok":
            await send_telegram_alert(source.id, "proxy_required", status["detail"], source.url)
        return _finish(status)

    if source.id in firecrawl_primary_source_ids():
        firecrawl_status = await _try_firecrawl_html(
            source,
            fetched_at=fetched_at,
            reason="primary",
        )
        if firecrawl_status is not None:
            return _finish(firecrawl_status)

    if tier_for(source.id) in API_FIRST_TIERS:
        log_action("api.route.begin", source_id=source.id, tier=source_tier)
        try:
            parsed = await _fetch_hsreplay_api_source(source)
            if parsed is not None:
                ok, reason = validate_parsed_data(source, parsed)
                backend = parsed.pop("_backend", "hsreplay_api")
                content_length = parsed.get("counts", {}).get("api_bytes", 0)
                qmetrics = quality_metrics(source, parsed)
                if ok:
                    log_action(
                        "api.validate.ok",
                        source_id=source.id,
                        backend=backend,
                        bytes_out=content_length,
                        extra={"quality_metrics": qmetrics},
                    )
                    dataset = {
                        "source_id": source.id,
                        "fetched_at": fetched_at,
                        "data": parsed,
                        "backend": backend,
                        "content_length": content_length,
                        "used_residential_proxy": _source_uses_residential_proxy(source, backend),
                    }
                    reg, reg_msg = _save_dataset_with_checks(
                        source, dataset, fetched_at=fetched_at
                    )
                    state = "partial" if reg else "ok"
                    status = _status_payload(
                        source,
                        state,
                        fetched_at=fetched_at,
                        http_status=200,
                        final_url=source.url,
                        content_length=content_length,
                        backend=backend,
                        detail=reg_msg if reg else None,
                        used_residential_proxy=_source_uses_residential_proxy(source, backend),
                        quality=qmetrics,
                    )
                    if reg:
                        status = _save_failure_status(source, status)
                    else:
                        save_status(source.id, status)
                    log_action(
                        "api.route.ok",
                        source_id=source.id,
                        state=state,
                        backend=backend,
                        tier=source_tier,
                        bytes_out=content_length,
                    )
                    if reg and reg_msg:
                        await send_telegram_alert(
                            source.id, "dataset_regression", reg_msg, source.url
                        )
                    return _finish(status)
                if (
                    source.site == "hsreplay"
                    and retry_on_auth_failure
                    and _looks_like_hsreplay_auth_error(reason)
                ):
                    from .hsreplay_auth import force_relogin_hsreplay, hsreplay_email, hsreplay_password

                    if hsreplay_email() and hsreplay_password() and await force_relogin_hsreplay():
                        deactivate_source_trace((_tok_trace, _tok_source, _tok_step))
                        return await fetch_source(client, source, retry_on_auth_failure=False)
                status = _status_payload(
                    source,
                    "quality_error",
                    fetched_at=fetched_at,
                    http_status=200,
                    final_url=source.url,
                    detail=reason,
                    content_length=content_length,
                    backend=backend,
                    used_residential_proxy=_source_uses_residential_proxy(source, backend),
                )
                status = _save_failure_status(source, status)
                log_action(
                    "api.validate.fail",
                    source_id=source.id,
                    state="quality_error",
                    backend=backend,
                    detail=reason,
                    tier=source_tier,
                    level="warn",
                )
                if status.get("state") != "ok":
                    await send_telegram_alert(source.id, "quality_error", status["detail"], source.url)
                return _finish(status)
            log_action(
                "api.route.skip",
                source_id=source.id,
                detail="no API handler for this source_id",
                tier=source_tier,
                level="warn",
            )
        except ProxyPaymentRequiredError:
            deactivate_source_trace((_tok_trace, _tok_source, _tok_step))
            raise
        except Exception as exc:
            import logging

            api_detail = str(exc)[:2000]
            if (
                source.site == "hsreplay"
                and retry_on_auth_failure
                and _looks_like_hsreplay_auth_error(api_detail)
            ):
                from .hsreplay_auth import force_relogin_hsreplay, hsreplay_email, hsreplay_password

                if hsreplay_email() and hsreplay_password() and await force_relogin_hsreplay():
                    deactivate_source_trace((_tok_trace, _tok_source, _tok_step))
                    return await fetch_source(client, source, retry_on_auth_failure=False)
            log_action(
                "api.route.fail",
                source_id=source.id,
                state="fetch_error",
                error_type=type(exc).__name__,
                detail=api_detail,
                tier=source_tier,
                level="error",
            )
            if blocks_browser_fallback(source.id):
                logging.getLogger(__name__).warning(
                    "API-only source %s failed (no browser fallback): %s",
                    source.id,
                    exc,
                )
                status = _status_payload(
                    source,
                    "fetch_error",
                    fetched_at=fetched_at,
                    error=type(exc).__name__,
                    detail=f"API fetch failed (browser fallback disabled): {api_detail}",
                )
                status = _save_failure_status(source, status)
                log_action(
                    "api.fallback.blocked",
                    source_id=source.id,
                    state="fetch_error",
                    detail=api_detail,
                    tier=source_tier,
                    level="error",
                )
                if status.get("state") != "ok":
                    await send_telegram_alert(source.id, "fetch_error", status["detail"], source.url)
                    await _maybe_stale_data_alert(source, status)
                return _finish(status)
            logging.getLogger(__name__).warning(
                "API fetch failed for %s, falling back to browser: %s",
                source.id,
                exc,
            )
            log_action(
                "api.fallback.browser",
                source_id=source.id,
                detail=api_detail,
                tier=source_tier,
                level="warn",
            )

    set_flaresolverr_source(source.id)
    page_snapshot = None
    log_action(
        "browser.fetch.begin",
        source_id=source.id,
        tier=source_tier,
        extra={"preferred_backend": preferred_backend, "direct": fetch_direct_enabled()},
    )
    try:
        if fetch_direct_enabled() and client is not None:
            log_action("http.request.begin", source_id=source.id, backend="direct", url=source.fetch_url)
            body, http_status, final_url = await _fetch_direct(client, source)
            backend = "direct"
            log_action(
                "http.request.ok",
                source_id=source.id,
                backend="direct",
                http_status=http_status,
                url=str(final_url),
                bytes_out=len(body.encode("utf-8", errors="replace")),
            )
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
    except ProxyPaymentRequiredError:
        deactivate_source_trace((_tok_trace, _tok_source, _tok_step))
        raise
    except Exception as exc:
        log_action(
            "browser.fetch.end",
            source_id=source.id,
            state="fetch_error",
            error_type=type(exc).__name__,
            detail=str(exc)[:2000],
            level="error",
        )
        firecrawl_status = await _try_firecrawl_html(
            source,
            fetched_at=fetched_at,
            reason=f"browser_exception:{type(exc).__name__}",
        )
        if firecrawl_status is not None:
            return _finish(firecrawl_status)
        status = _status_payload(
            source,
            "fetch_error",
            fetched_at=fetched_at,
            error=type(exc).__name__,
            detail=str(exc)[:2000],
        )
        status = _save_failure_status(source, status)
        if status.get("state") != "ok":
            await send_telegram_alert(source.id, "fetch_error", status["detail"], source.url)
            await _maybe_stale_data_alert(source, status)
        return _finish(status)
    finally:
        set_flaresolverr_source(None)

    log_action(
        "browser.fetch.end",
        source_id=source.id,
        state="ok",
        backend=backend,
        http_status=http_status,
        bytes_out=len(body.encode("utf-8", errors="replace")),
    )

    content_length = len(body.encode("utf-8", errors="replace"))
    if is_cloudflare_challenge(body):
        log_action(
            "protection.cloudflare",
            source_id=source.id,
            state="blocked_by_protection",
            backend=backend,
            level="error",
        )
        firecrawl_status = await _try_firecrawl_html(
            source,
            fetched_at=fetched_at,
            reason="cloudflare_challenge",
        )
        if firecrawl_status is not None:
            return _finish(firecrawl_status)
        status = _status_payload(
            source,
            "blocked_by_protection",
            fetched_at=fetched_at,
            http_status=http_status,
            final_url=final_url,
            detail="Cloudflare challenge after all backends.",
            content_length=content_length,
            backend=backend,
            used_residential_proxy=_source_uses_residential_proxy(source, backend),
        )
        status = _save_failure_status(source, status)
        if status.get("state") != "ok":
            await send_telegram_alert(source.id, "blocked_by_protection", status["detail"], source.url)
        return _finish(status)

    if http_status >= 400:
        log_action(
            "http.status.error",
            source_id=source.id,
            http_status=http_status,
            backend=backend,
            level="error",
        )
        firecrawl_status = await _try_firecrawl_html(
            source,
            fetched_at=fetched_at,
            reason=f"http_status:{http_status}",
        )
        if firecrawl_status is not None:
            return _finish(firecrawl_status)
        status = _status_payload(
            source,
            "http_error",
            fetched_at=fetched_at,
            http_status=http_status,
            final_url=final_url,
            detail="HTTP error from origin",
            content_length=content_length,
            backend=backend,
            used_residential_proxy=_source_uses_residential_proxy(source, backend),
        )
        status = _save_failure_status(source, status)
        if status.get("state") != "ok":
            await send_telegram_alert(source.id, "http_error", status["detail"], source.url)
        return _finish(status)

    log_action("parse.html", source_id=source.id, backend=backend, bytes_out=content_length)
    parsed = parse_html(source, body, page_snapshot)
    ok, reason = validate_parsed_data(source, parsed)
    qmetrics = quality_metrics(source, parsed)
    if not ok:
        log_action(
            "quality.validate.fail",
            source_id=source.id,
            state="quality_error",
            backend=backend,
            detail=reason,
            level="warn",
            extra={"quality_metrics": qmetrics},
        )
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
                log_action(
                    "auth.hsreplay.relogin",
                    source_id=source.id,
                    level="warn",
                    detail=reason,
                )
                relogin_success = await force_relogin_hsreplay()
                if relogin_success:
                    logging.getLogger(__name__).info("Relogin successful, retrying fetch for %s...", source.id)
                    deactivate_source_trace((_tok_trace, _tok_source, _tok_step))
                    return await fetch_source(client, source, retry_on_auth_failure=False)

        firecrawl_status = await _try_firecrawl_html(
            source,
            fetched_at=fetched_at,
            reason=f"quality_error:{reason[:120]}",
        )
        if firecrawl_status is not None:
            return _finish(firecrawl_status)

        status = _status_payload(
            source,
            "quality_error",
            fetched_at=fetched_at,
            http_status=http_status,
            final_url=final_url,
            detail=reason,
            content_length=content_length,
            backend=backend,
            used_residential_proxy=_source_uses_residential_proxy(source, backend),
        )
        status = _save_failure_status(source, status)
        if status.get("state") != "ok":
            await send_telegram_alert(source.id, "quality_error", reason, source.url)
        return _finish(status)

    dataset = {
        "state": "ok",
        "fetched_at": fetched_at,
        "http_status": http_status,
        "final_url": final_url,
        "content_length": content_length,
        "backend": backend,
        "used_residential_proxy": _source_uses_residential_proxy(source, backend),
        "data": parsed,
    }
    reg, reg_msg = _save_dataset_with_checks(source, dataset, fetched_at=fetched_at)
    log_action(
        "quality.validate.ok",
        source_id=source.id,
        backend=backend,
        extra={"quality_metrics": qmetrics},
    )
    state = "partial" if reg else "ok"
    status = _status_payload(
        source,
        state,
        fetched_at=fetched_at,
        http_status=http_status,
        final_url=final_url,
        content_length=content_length,
        backend=backend,
        detail=reg_msg if reg else None,
        used_residential_proxy=_source_uses_residential_proxy(source, backend),
        quality=qmetrics,
    )
    if reg:
        status = _save_failure_status(source, status)
    else:
        save_status(source.id, status)
    if reg and reg_msg:
        await send_telegram_alert(source.id, "dataset_regression", reg_msg, source.url)
    return _finish(status)


def _attach_proxy_egress(status: dict[str, Any], proxy_info: dict[str, str]) -> dict[str, Any]:
    if proxy_info and status.get("state") == "ok" and status.get("used_residential_proxy"):
        status["proxy_egress_ip"] = proxy_info.get("egress_ip")
    return status


def _refresh_traffic_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Best-effort refresh traffic lower bound from final source statuses.

    This measures response bodies that reached parser code. Provider billing can be
    higher because proxy plans count protocol overhead, redirects, retries, and
    browser assets that are not represented by a final dataset/status body.
    """
    body_bytes = 0
    iproyal_marked_bytes = 0
    by_tier: Counter[str] = Counter()
    by_backend: Counter[str] = Counter()
    by_site: Counter[str] = Counter()
    top_sources: list[dict[str, Any]] = []
    skipped_cached_sources = 0

    for status in results:
        if status.get("serving_cached_dataset"):
            skipped_cached_sources += 1
            continue
        raw_bytes = status.get("content_length")
        if not isinstance(raw_bytes, int) or raw_bytes <= 0:
            continue

        source_id = str(status.get("source_id") or "")
        site = str(status.get("site") or "unknown")
        backend = str(status.get("backend") or "unknown")
        try:
            tier = tier_for(source_id).value
        except KeyError:
            tier = "unknown"

        body_bytes += raw_bytes
        by_tier[tier] += raw_bytes
        by_backend[backend] += raw_bytes
        by_site[site] += raw_bytes
        if status.get("used_residential_proxy"):
            iproyal_marked_bytes += raw_bytes
        top_sources.append(
            {
                "source_id": source_id,
                "site": site,
                "tier": tier,
                "backend": backend,
                "body_bytes": raw_bytes,
                "body_mb": round(raw_bytes / 1024 / 1024, 3),
                "iproyal_marked": bool(status.get("used_residential_proxy")),
            }
        )

    top_sources.sort(key=lambda item: int(item["body_bytes"]), reverse=True)

    def _mb(value: int) -> float:
        return round(value / 1024 / 1024, 3)

    def _counter_mb(counter: Counter[str]) -> dict[str, float]:
        return {key: _mb(value) for key, value in counter.most_common()}

    return {
        "body_bytes_lower_bound": body_bytes,
        "body_mb_lower_bound": _mb(body_bytes),
        "iproyal_body_bytes_estimate": iproyal_marked_bytes,
        "iproyal_body_mb_estimate": _mb(iproyal_marked_bytes),
        "sources_with_body": len(top_sources),
        "iproyal_marked_sources": sum(1 for item in top_sources if item["iproyal_marked"]),
        "skipped_cached_sources": skipped_cached_sources,
        "by_tier_mb": _counter_mb(by_tier),
        "by_backend_mb": _counter_mb(by_backend),
        "by_site_mb": _counter_mb(by_site),
        "top_sources": top_sources[:15],
        "billing_exact": False,
        "note": (
            "Lower bound from live final response bodies. IPRoyal estimate includes only statuses "
            "marked used_residential_proxy=true. Billing can be higher because retries, redirects, "
            "headers, TLS/HTTP overhead, and browser assets are not counted here."
        ),
    }


async def _browser_inter_source_delay() -> None:
    delay_seconds = request_delay_seconds()
    await asyncio.sleep(delay_seconds * random.uniform(0.75, 1.25))


async def _parallel_stagger_delay() -> None:
    await asyncio.sleep(
        random.uniform(refresh_parallel_stagger_min(), refresh_parallel_stagger_max())
    )


async def _inter_request_cooldown() -> None:
    """Short pause between parallel tier batches to ease proxy load."""
    await asyncio.sleep(random.uniform(1.0, 2.5))


async def _run_tier_after_cooldown(coro):
    await _inter_request_cooldown()
    return await coro


def _fetch_error_status(source: Source, exc: BaseException) -> dict[str, Any]:
    return _status_payload(
        source,
        "fetch_error",
        fetched_at=now_iso(),
        error=type(exc).__name__,
        detail=str(exc)[:2000],
    )


async def _run_tier_parallel(
    sources: list[Source],
    *,
    phase: str,
    concurrency: int,
    client: httpx.AsyncClient | None,
    proxy_info: dict[str, str],
) -> list[dict[str, Any]]:
    if not sources:
        return []

    logger = logging.getLogger(__name__)
    started = time.monotonic()
    semaphore = asyncio.Semaphore(concurrency)

    proxy_407_abort = False

    async def fetch_one(source: Source) -> dict[str, Any]:
        nonlocal proxy_407_abort
        if proxy_407_abort:
            status = _fetch_error_status(
                source,
                ProxyPaymentRequiredError("light_api phase aborted after proxy 407"),
            )
            return _attach_proxy_egress(status, proxy_info)
        async with semaphore:
            await _parallel_stagger_delay()
            set_refresh_context(phase=phase)
            try:
                status = await fetch_source(client, source)
            except ProxyPaymentRequiredError as exc:
                proxy_407_abort = True
                logger.error("Proxy 407 — aborting %s phase: %s", phase, exc)
                log_action(
                    "proxy.health.fail",
                    level="error",
                    detail=str(exc)[:500],
                    extra={"phase_abort": phase},
                )
                status = _fetch_error_status(source, exc)
            except Exception as exc:
                logger.exception("Parallel fetch failed for %s", source.id)
                status = _fetch_error_status(source, exc)
            return _attach_proxy_egress(status, proxy_info)

    raw = await asyncio.gather(*(fetch_one(source) for source in sources), return_exceptions=True)
    results: list[dict[str, Any]] = []
    for source, item in zip(sources, raw, strict=True):
        if isinstance(item, BaseException):
            logger.exception("Parallel gather failed for %s", source.id)
            results.append(_fetch_error_status(source, item))
        else:
            results.append(item)

    ok_count = sum(1 for s in results if s.get("state") == "ok")
    logger.info(
        "refresh phase=%s duration=%.1fs ok=%d fail=%d concurrency=%d",
        phase,
        time.monotonic() - started,
        ok_count,
        len(results) - ok_count,
        concurrency,
    )
    return results


async def _run_tier_serial_browser(
    sources: list[Source],
    *,
    phase: str,
    client: httpx.AsyncClient | None,
    proxy_info: dict[str, str],
    use_flaresolverr: bool,
    apply_delay: bool,
) -> list[dict[str, Any]]:
    if not sources:
        return []

    logger = logging.getLogger(__name__)
    started = time.monotonic()
    results: list[dict[str, Any]] = []
    fs_session: FlareSolverrSession | None = None
    try:
        for source in sources:
            if use_flaresolverr and not fetch_direct_enabled():
                if flaresolverr_session_per_source() or fs_session is None:
                    if fs_session is not None:
                        set_active_flaresolverr_session(None)
                        await fs_session.__aexit__(None, None, None)
                    fs_session = FlareSolverrSession()
                    await fs_session.__aenter__()
                    set_active_flaresolverr_session(fs_session)
            status = await fetch_source(client, source)
            results.append(_attach_proxy_egress(status, proxy_info))
            if apply_delay:
                await _browser_inter_source_delay()
    finally:
        if fs_session is not None:
            set_active_flaresolverr_session(None)
            await fs_session.__aexit__(None, None, None)

    ok_count = sum(1 for s in results if s.get("state") == "ok")
    logger.info(
        "refresh phase=%s duration=%.1fs ok=%d fail=%d concurrency=1",
        phase,
        time.monotonic() - started,
        ok_count,
        len(results) - ok_count,
    )
    return results


async def _refresh_sources_unlocked(
    source_ids: list[str] | None = None,
    *,
    tier_filter: str | None = None,
) -> list[dict[str, Any]]:
    global _firecrawl_fallback_attempts
    _firecrawl_fallback_attempts = 0
    validate_tier_registry()
    from .refresh_context import begin_refresh_run, end_refresh_run
    from .scrapers.rotator import reset_backend_circuits

    begin_refresh_run()
    reset_backend_circuits()
    run_id = new_run_id()
    log_action(
        "refresh.begin",
        extra={
            "source_ids": source_ids,
            "run_id": run_id,
            "tier_filter": tier_filter,
            "runtime": runtime_version_info(),
        },
    )

    selected = list(SOURCES)
    if source_ids:
        selected = [SOURCE_BY_ID[source_id] for source_id in source_ids]

    if tier_filter:
        tier_enum = SourceTier(tier_filter)
        selected = [s for s in selected if tier_for(s.id) == tier_enum]

    full_refresh = source_ids is None and tier_filter is None
    parts_preview = partition_sources(selected)
    backends_lower_preview = [b.lower() for b in fetch_backends()]
    needs_flaresolverr = bool(parts_preview.browser_protected) and not fetch_direct_enabled() and (
        "flaresolverr" in backends_lower_preview
    )

    from .preflight import ensure_refresh_preflight

    proxy_info = await ensure_refresh_preflight(
        full_refresh=full_refresh,
        needs_flaresolverr=needs_flaresolverr,
    )

    if tier_filter is None and parts_preview.light_api:
        from .cards_index import prefetch_hearthstonejson_async

        await prefetch_hearthstonejson_async()

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

    parts = partition_sources(selected)
    backends_lower = [b.lower() for b in fetch_backends()]
    browser_tiers = bool(parts.browser_patchright or parts.browser_protected)
    use_patchright = bool(parts.browser_patchright) and not fetch_direct_enabled() and (
        "patchright" in backends_lower or "playwright" in backends_lower
    )
    use_cloakbrowser = browser_tiers and not fetch_direct_enabled() and (
        "cloakbrowser" in backends_lower
    )
    use_flaresolverr = bool(parts.browser_protected) and not fetch_direct_enabled() and (
        "flaresolverr" in backends_lower
    )
    browser_delay = refresh_delay_browser_only()

    results: list[dict[str, Any]] = []
    try:
        phase_plan = (
            (
                SourceTier.LIGHT_API.value,
                lambda: _run_tier_parallel(
                    parts.light_api,
                    phase=SourceTier.LIGHT_API.value,
                    concurrency=refresh_parallel_light(),
                    client=client,
                    proxy_info=proxy_info,
                ),
            ),
            (
                SourceTier.MEDIUM_API.value,
                lambda: _run_tier_after_cooldown(
                    _run_tier_parallel(
                        parts.medium_api,
                        phase=SourceTier.MEDIUM_API.value,
                        concurrency=refresh_parallel_medium(),
                        client=client,
                        proxy_info=proxy_info,
                    )
                ),
            ),
            (
                SourceTier.BROWSER_PATCHRIGHT.value,
                lambda: _run_tier_after_cooldown(
                    _run_browser_phase(
                        parts.browser_patchright,
                        phase=SourceTier.BROWSER_PATCHRIGHT.value,
                        client=client,
                        proxy_info=proxy_info,
                        use_flaresolverr=False,
                        apply_delay=browser_delay,
                        use_patchright=use_patchright,
                    )
                ),
            ),
            (
                SourceTier.BROWSER_PROTECTED.value,
                lambda: _run_browser_phase(
                    parts.browser_protected,
                    phase=SourceTier.BROWSER_PROTECTED.value,
                    client=client,
                    proxy_info=proxy_info,
                    use_flaresolverr=use_flaresolverr,
                    apply_delay=browser_delay,
                    use_patchright=use_patchright,
                ),
            ),
        )
        for phase_name, phase_factory in phase_plan:
            if tier_filter and phase_name != tier_filter:
                continue
            set_refresh_context(phase=phase_name, run_id=run_id)
            phase_started = time.monotonic()
            log_action("phase.begin", extra={"phase": phase_name})
            phase_results = await phase_factory()
            results.extend(phase_results)
            ok_count = sum(1 for s in phase_results if s.get("state") == "ok")
            log_action(
                "phase.end",
                state="ok" if ok_count == len(phase_results) else "partial",
                duration_ms=(time.monotonic() - phase_started) * 1000,
                level="info" if ok_count == len(phase_results) else "warn",
                extra={
                    "phase": phase_name,
                    "ok": ok_count,
                    "fail": len(phase_results) - ok_count,
                },
            )
    finally:
        if use_patchright or use_flaresolverr:
            await PatchrightPool.shutdown()
        if use_cloakbrowser:
            from .scrapers.cloakbrowser_pool import shutdown_cloakbrowser_pool

            await shutdown_cloakbrowser_pool()
        if client is not None:
            await client.aclose()
        end_refresh_run()
        ok_total = sum(1 for s in results if s.get("state") == "ok")
        traffic = _refresh_traffic_summary(results)
        log_action(
            "refresh.end",
            state="ok" if ok_total == len(results) else "partial",
            level="info" if ok_total == len(results) else "warn",
            extra={
                "ok": ok_total,
                "fail": len(results) - ok_total,
                "run_id": run_id,
                "traffic": traffic,
            },
        )
        if full_refresh:
            from .stale_monitor import alert_stale_sources

            try:
                stale_sent = await alert_stale_sources()
                if stale_sent:
                    log_action(
                        "refresh.stale_alerts",
                        level="warn",
                        extra={"count": stale_sent},
                    )
            except Exception as exc:
                logger.warning("Stale source alerts failed: %s", exc)
    return results


async def refresh_sources(
    source_ids: list[str] | None = None,
    *,
    tier: str | None = None,
) -> list[dict[str, Any]]:
    with RefreshLock():
        return await _refresh_sources_unlocked(source_ids, tier_filter=tier)


async def _run_browser_phase(
    sources: list[Source],
    *,
    phase: str,
    client: httpx.AsyncClient | None,
    proxy_info: dict[str, str],
    use_flaresolverr: bool,
    apply_delay: bool,
    use_patchright: bool,
) -> list[dict[str, Any]]:
    if use_patchright:
        await PatchrightPool.get()
    return await _run_tier_serial_browser(
        sources,
        phase=phase,
        client=client,
        proxy_info=proxy_info,
        use_flaresolverr=use_flaresolverr,
        apply_delay=apply_delay,
    )
