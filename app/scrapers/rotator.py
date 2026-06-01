from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from ..config import fetch_max_retries
from ..sources import Source
from .base import FetchResult
from .proxy import assert_proxy_configured
from .quality import looks_like_real_page, validate_parsed_data

logger = logging.getLogger(__name__)

BackendFn = Callable[[Source], Awaitable[FetchResult]]


def _site_backend_order(source: Source) -> list[str]:
    from ..config import fetch_backends

    configured = [b.lower() for b in fetch_backends()]
    if source.site == "hsguru":
        preferred = ["flaresolverr", "patchright", "curl_cffi", "cloudscraper", "camoufox"]
    else:
        preferred = ["patchright", "flaresolverr", "curl_cffi", "cloudscraper", "camoufox"]
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
    from .patchright_browser import fetch_via_patchright, patchright_available

    registry: dict[str, tuple[BackendFn, Callable[[], bool]]] = {
        "flaresolverr": (fetch_via_flaresolverr, lambda: True),
        "patchright": (fetch_via_patchright, patchright_available),
        "playwright": (fetch_via_patchright, patchright_available),
        "camoufox": (fetch_via_camoufox, camoufox_available),
        "cloudscraper": (fetch_via_cloudscraper, lambda: True),
        "curl_cffi": (fetch_via_curl_cffi, curl_cffi_available),
        "cloudflare_scrape": (fetch_via_cloudscraper, lambda: True),
    }

    names = _site_backend_order(source) if source else [b.lower() for b in fetch_backends()]
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

    errors: list[str] = []
    for attempt in range(1, fetch_max_retries() + 1):
        for name, fetch_fn, is_available in backends:
            if not is_available():
                errors.append(f"{name}: not installed")
                continue
            try:
                result = await fetch_fn(source)
                if not looks_like_real_page(result.html, source):
                    raise RuntimeError("page looks like Cloudflare or empty shell")
                if parse_preview is not None:
                    parsed = parse_preview(result.html)
                    ok, reason = validate_parsed_data(source, parsed)
                    if not ok:
                        raise RuntimeError(f"quality check failed: {reason}")
                logger.info(
                    "Fetched %s via %s attempt=%d (%d bytes)",
                    source.id,
                    name,
                    attempt,
                    len(result.html),
                )
                return result
            except Exception as exc:
                msg = f"{name}[{attempt}]: {type(exc).__name__}: {exc}"
                errors.append(msg)
                logger.warning("Backend failed for %s — %s", source.id, msg)
        if attempt < fetch_max_retries():
            await asyncio.sleep(3 * attempt)

    raise RuntimeError("; ".join(errors[-12:]))
