from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from ..config import fetch_backend_max_seconds, fetch_max_retries
from ..publish_gate import validate_candidate_for_publish
from ..refresh_log import log_action
from ..sources import Source
from .base import FetchResult
from .proxy import assert_proxy_configured
from .quality import looks_like_real_page

logger = logging.getLogger(__name__)

BackendFn = Callable[[Source], Awaitable[FetchResult]]


def _site_backend_order(source: Source) -> list[str]:
    from ..config import fetch_backends

    configured = [b.lower() for b in fetch_backends()]
    if source.site == "hsguru":
        # CloakBrowser + Scrapling use residential proxy; FlareSolverr skips proxy locally.
        # Scrapling proven on HSGuru CF; CloakBrowser second; FlareSolverr fastest when up.
        preferred = [
            "flaresolverr",
            "scrapling",
            "patchright",
            "cloakbrowser",
            "curl_cffi",
            "cloudscraper",
            "camoufox",
        ]
    else:
        from ..config import hsreplay_storage_path

        preferred = [
            "patchright",
            "cloakbrowser",
            "flaresolverr",
            "scrapling",
            "curl_cffi",
            "cloudscraper",
            "camoufox",
        ]
        if not hsreplay_storage_path().exists():
            preferred = [
                "flaresolverr",
                "cloakbrowser",
                "patchright",
                "scrapling",
                "curl_cffi",
                "cloudscraper",
                "camoufox",
            ]
    ordered: list[str] = []
    for name in preferred:
        if name in configured and name not in ordered:
            ordered.append(name)
    for name in configured:
        if name not in ordered:
            ordered.append(name)
    return ordered


def _ordered_backends(source: Source | None = None) -> list[tuple[str, BackendFn, Callable[[], bool]]]:
    from ..config import fetch_backends
    from .camoufox_browser import camoufox_available, fetch_via_camoufox
    from .cloudscraper_client import fetch_via_cloudscraper
    from .curl_impersonate import curl_cffi_available, fetch_via_curl_cffi
    from .flaresolverr import fetch_via_flaresolverr
    from .cloakbrowser_pool import cloakbrowser_available, fetch_via_cloakbrowser
    from .patchright_browser import fetch_via_patchright, patchright_available
    from .scrapling_browser import fetch_via_scrapling, scrapling_available

    registry: dict[str, tuple[BackendFn, Callable[[], bool]]] = {
        "flaresolverr": (fetch_via_flaresolverr, lambda: True),
        "cloakbrowser": (fetch_via_cloakbrowser, cloakbrowser_available),
        "scrapling": (fetch_via_scrapling, scrapling_available),
        "patchright": (fetch_via_patchright, patchright_available),
        "playwright": (fetch_via_patchright, patchright_available),
        "camoufox": (fetch_via_camoufox, camoufox_available),
        "cloudscraper": (fetch_via_cloudscraper, lambda: True),
        "curl_cffi": (fetch_via_curl_cffi, curl_cffi_available),
        "cloudflare_scrape": (fetch_via_cloudscraper, lambda: True),
    }

    names = _site_backend_order(source) if source else [b.lower() for b in fetch_backends()]
    if source and source.site == "hsreplay":
        from ..config import hsreplay_storage_path

        if hsreplay_storage_path().exists():
            names = [n for n in names if n == "patchright"] or names
    ordered: list[tuple[str, BackendFn, Callable[[], bool]]] = []
    for key in names:
        if key not in registry:
            logger.warning("Unknown fetch backend %r, skipping", key)
            continue
        fn, available = registry[key]
        ordered.append((key, fn, available))
    return ordered


async def fetch_html(
    source: Source,
    *,
    preferred_backend: str | None = None,
    parse_preview: Callable[[str], dict] | None = None,
) -> FetchResult:
    assert_proxy_configured()
    backends = _ordered_backends(source)
    if not backends:
        raise RuntimeError("No fetch backends configured (HS_FETCH_BACKENDS).")

    if preferred_backend:
        preferred = preferred_backend.strip().lower()
        backends = sorted(backends, key=lambda item: 0 if item[0] == preferred else 1)

    backend_names = [b[0] for b in backends]
    log_action(
        "browser.fetch.begin",
        source_id=source.id,
        url=source.fetch_url,
        extra={"backends": backend_names, "preferred": preferred_backend},
    )

    errors: list[str] = []
    for attempt in range(1, fetch_max_retries() + 1):
        log_action(
            "browser.round.begin",
            source_id=source.id,
            attempt=attempt,
            extra={"backends": backend_names},
        )
        for name, fetch_fn, is_available in backends:
            if not is_available():
                detail = f"{name}: not installed"
                errors.append(detail)
                log_action(
                    "browser.backend.skip",
                    source_id=source.id,
                    backend=name,
                    attempt=attempt,
                    detail=detail,
                    level="warn",
                )
                continue
            started = time.monotonic()
            log_action(
                "browser.backend.try",
                source_id=source.id,
                backend=name,
                attempt=attempt,
                url=source.fetch_url,
            )
            try:
                max_s = fetch_backend_max_seconds()
                if max_s is not None:
                    result = await asyncio.wait_for(fetch_fn(source), timeout=max_s)
                else:
                    result = await fetch_fn(source)
                html_len = len(result.html)
                if not looks_like_real_page(result.html, source):
                    raise RuntimeError("page looks like Cloudflare or empty shell")
                if parse_preview is not None:
                    parsed = parse_preview(result.html)
                    gate = validate_candidate_for_publish(source, parsed, backend=name)
                    if not gate.ok:
                        log_action(
                            "browser.quality.fail",
                            source_id=source.id,
                            backend=name,
                            attempt=attempt,
                            detail=gate.reason,
                            level="warn",
                            extra={"publish_gate": gate.extra},
                        )
                        raise RuntimeError(f"quality check failed: {gate.reason}")
                logger.info(
                    "Fetched %s via %s attempt=%d (%d bytes)",
                    source.id,
                    name,
                    attempt,
                    html_len,
                )
                log_action(
                    "browser.backend.ok",
                    source_id=source.id,
                    backend=name,
                    state="ok",
                    attempt=attempt,
                    duration_ms=(time.monotonic() - started) * 1000,
                    http_status=result.http_status,
                    url=result.final_url,
                    bytes_out=html_len,
                )
                return result
            except TimeoutError:
                max_s = fetch_backend_max_seconds()
                msg = f"{name}[{attempt}]: TimeoutError: exceeded {max_s}s backend cap"
                errors.append(msg)
                logger.warning("Backend failed for %s — %s", source.id, msg)
                log_action(
                    "browser.backend.fail",
                    source_id=source.id,
                    backend=name,
                    error_type="TimeoutError",
                    detail=msg,
                    attempt=attempt,
                    duration_ms=(time.monotonic() - started) * 1000,
                    level="error",
                )
                continue
            except Exception as exc:
                msg = f"{name}[{attempt}]: {type(exc).__name__}: {exc}"
                errors.append(msg)
                logger.warning("Backend failed for %s — %s", source.id, msg)
                log_action(
                    "browser.backend.fail",
                    source_id=source.id,
                    backend=name,
                    error_type=type(exc).__name__,
                    detail=str(exc)[:1000],
                    attempt=attempt,
                    duration_ms=(time.monotonic() - started) * 1000,
                    level="error",
                )
        if attempt < fetch_max_retries():
            delay = 3 * attempt
            log_action(
                "browser.round.sleep",
                source_id=source.id,
                attempt=attempt,
                extra={"delay_seconds": delay},
            )
            await asyncio.sleep(delay)

    detail = "; ".join(errors[-12:])
    log_action(
        "browser.fetch.end",
        source_id=source.id,
        state="fetch_error",
        detail=detail,
        level="error",
    )
    raise RuntimeError(detail)
