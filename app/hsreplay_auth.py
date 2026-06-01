from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import hsreplay_email, hsreplay_password, hsreplay_storage_path

logger = logging.getLogger(__name__)


async def _dismiss_consent(page) -> None:
    for sel in (
        "#onetrust-accept-btn-handler",
        'button:has-text("Consent")',
        'button:has-text("Accept all")',
        'button:has-text("Accept")',
    ):
        try:
            await page.click(sel, timeout=4000)
            await page.wait_for_timeout(1500)
            return
        except Exception:
            continue


async def _wait_for_login_form(page, timeout_ms: int = 120000) -> bool:
    from .scrapers.navigation import _wait_cloudflare

    await _wait_cloudflare(page, timeout_ms)
    loops = max(timeout_ms // 2000, 10)
    for _ in range(loops):
        has_email = await page.locator('input[type="email"], input[name="email"]').count()
        if has_email:
            return True
        await page.wait_for_timeout(2000)
    return False


async def ensure_hsreplay_login(page, context) -> bool:
    email = hsreplay_email()
    password = hsreplay_password()
    storage = hsreplay_storage_path()

    if storage.exists():
        return True

    if not email or not password:
        logger.warning("HSReplay credentials not configured; premium pages may be empty")
        return False

    try:
        await page.goto("https://hsreplay.net/cards/", wait_until="domcontentloaded", timeout=120000)
        await _wait_for_login_form(page, 90000)
        await _dismiss_consent(page)

        try:
            await page.click('a[href*="login"], text=SIGN IN', timeout=15000)
            await page.wait_for_timeout(3000)
        except Exception:
            await page.goto("https://hsreplay.net/account/login/", wait_until="domcontentloaded", timeout=120000)

        if not await _wait_for_login_form(page, 90000):
            logger.error("HSReplay login form not found (Cloudflare or layout change)")
            return False

        await page.fill('input[type="email"], input[name="email"]', email, timeout=15000)
        await page.fill('input[type="password"], input[name="password"]', password, timeout=15000)
        await page.click('button[type="submit"], input[type="submit"]', timeout=15000)
        await page.wait_for_timeout(10000)

        if "login" in page.url.lower() and await page.locator('input[type="password"]').count():
            logger.error("HSReplay login may have failed; still on login page")
            return False

        await context.storage_state(path=str(storage))
        logger.info("HSReplay session saved to %s", storage)
        return True
    except Exception as exc:
        logger.error("HSReplay login failed: %s", exc)
        return False


def _cookie_editor_to_playwright(items: list) -> dict:
    cookies: list[dict] = []
    for item in items:
        if not isinstance(item, dict) or "name" not in item or "value" not in item:
            continue
        same = str(item.get("sameSite", "Lax")).capitalize()
        if same not in ("Lax", "Strict", "None"):
            same = "Lax"
        exp = item.get("expirationDate")
        if item.get("session") or exp is None:
            expires = -1
        else:
            expires = float(exp)
        cookies.append(
            {
                "name": item["name"],
                "value": item["value"],
                "domain": item.get("domain", "hsreplay.net"),
                "path": item.get("path", "/"),
                "expires": expires,
                "httpOnly": bool(item.get("httpOnly")),
                "secure": bool(item.get("secure", True)),
                "sameSite": same,
            }
        )
    if not cookies:
        raise ValueError("No valid cookies found")
    return {"cookies": cookies, "origins": []}


def hsreplay_cookies_for_fetch() -> list[dict[str, str]]:
    """Cookies for FlareSolverr / httpx from saved storage_state."""
    storage = hsreplay_storage_path()
    if not storage.exists():
        return []
    raw = json.loads(storage.read_text(encoding="utf-8"))
    out: list[dict[str, str]] = []
    for c in raw.get("cookies") or []:
        if c.get("name") and c.get("value"):
            out.append(
                {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", "hsreplay.net"),
                }
            )
    return out


def import_storage_state(path: Path) -> Path:
    """Import Playwright storage_state or Cookie-Editor JSON array."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        raw = _cookie_editor_to_playwright(raw)
    if not isinstance(raw, dict) or "cookies" not in raw:
        raise ValueError("Expected Playwright storage_state or Cookie-Editor cookie array")
    dest = hsreplay_storage_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    dest.chmod(0o600)
    return dest


async def force_relogin_hsreplay() -> bool:
    """Delete current storage state, force automatic browser login, and save new session."""
    from .scrapers.browser_pool import PatchrightPool
    from .scrapers.proxy import playwright_proxy

    storage = hsreplay_storage_path()
    if storage.exists():
        try:
            storage.unlink()
        except Exception as e:
            logger.warning("Failed to delete expired hsreplay storage state: %s", e)

    pool = await PatchrightPool.get()
    ctx_kw: dict = {"viewport": {"width": 1440, "height": 900}}
    px = playwright_proxy("hsreplay_login")
    if px:
        ctx_kw["proxy"] = px
    context = await pool._browser.new_context(**ctx_kw)
    page = await context.new_page()
    try:
        return await ensure_hsreplay_login(page, context)
    except Exception as exc:
        logger.error("Auto relogin failed: %s", exc)
        return False
    finally:
        await context.close()
