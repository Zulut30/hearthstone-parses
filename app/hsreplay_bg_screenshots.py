from __future__ import annotations

import base64
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import data_dir
from .firecrawl_backend import scrape_source_with_options
from .hsreplay_auth import hsreplay_cookies_for_fetch
from .sources import Source

COMPOSITIONS_URL = "https://hsreplay.net/battlegrounds/compositions/"
SCREENSHOT_SOURCE_ID = "hsreplay_battlegrounds_compositions_screenshot"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _screenshot_dir() -> Path:
    path = Path(data_dir()) / "firecrawl" / "screenshots" / "hsreplay_battlegrounds_compositions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_screenshot(value: str, image_path: Path) -> dict[str, Any]:
    if value.startswith("data:image/"):
        header, _, encoded = value.partition(",")
        suffix_match = re.search(r"data:image/([a-zA-Z0-9+.-]+)", header)
        suffix = (suffix_match.group(1) if suffix_match else "png").replace("jpeg", "jpg")
        image_path = image_path.with_suffix(f".{suffix}")
        image_path.write_bytes(base64.b64decode(encoded))
        _redact_account_area(image_path)
        _crop_compositions_table(image_path)
        return {"image_path": str(image_path), "image_bytes": image_path.stat().st_size}

    if value.startswith("http://") or value.startswith("https://"):
        request = urllib.request.Request(value, headers={"User-Agent": "HSDataAPI/0.1"})
        with urllib.request.urlopen(request, timeout=90) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read()
        suffix = ".jpg" if "jpeg" in content_type else ".png"
        image_path = image_path.with_suffix(suffix)
        image_path.write_bytes(body)
        _redact_account_area(image_path)
        _crop_compositions_table(image_path)
        return {"image_path": str(image_path), "image_bytes": image_path.stat().st_size, "firecrawl_screenshot_url": value}

    image_path = image_path.with_suffix(".txt")
    image_path.write_text(value, encoding="utf-8")
    return {"image_path": str(image_path), "image_bytes": image_path.stat().st_size}


def _redact_account_area(image_path: Path) -> None:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return
    try:
        with Image.open(image_path) as image:
            image = image.convert("RGBA")
            draw = ImageDraw.Draw(image)
            width, _height = image.size
            draw.rectangle((max(0, width - 420), 0, width, 54), fill=(35, 25, 36, 255))
            image.save(image_path)
    except Exception:
        return


def _crop_compositions_table(image_path: Path) -> None:
    try:
        from PIL import Image
    except Exception:
        return
    try:
        with Image.open(image_path) as image:
            width, height = image.size
            left = int(width * 0.16)
            top = int(height * 0.18)
            right = int(width * 0.84)
            bottom = min(int(height * 0.77), top + int(width * 0.48))
            cropped = image.crop((left, top, right, bottom))
            cropped.save(image_path)
    except Exception:
        return


def _hsreplay_cookie_header() -> str:
    cookies = [
        f"{cookie['name']}={cookie['value']}"
        for cookie in hsreplay_cookies_for_fetch()
        if cookie.get("name") and cookie.get("value")
    ]
    return "; ".join(cookies)


async def capture_compositions_screenshot() -> dict[str, Any]:
    source = Source(
        SCREENSHOT_SOURCE_ID,
        COMPOSITIONS_URL,
        "hsreplay",
        "battlegrounds",
        description="HSReplay Battlegrounds compositions screenshot.",
    )
    scraped = await scrape_source_with_options(
        source,
        formats=["markdown", {"type": "screenshot", "fullPage": True}],
        only_main_content=False,
        headers={
            "Cookie": _hsreplay_cookie_header(),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    if not scraped.screenshot:
        raise RuntimeError("Firecrawl response did not include screenshot")

    out_dir = _screenshot_dir()
    stamp = _safe_stamp()
    image_info = _write_screenshot(scraped.screenshot, out_dir / f"{stamp}")
    payload = {
        "ok": True,
        "source_id": SCREENSHOT_SOURCE_ID,
        "url": COMPOSITIONS_URL,
        "captured_at": _now(),
        "final_url": scraped.final_url,
        "status_code": scraped.status_code,
        "markdown_length": len(scraped.markdown),
        "metadata": scraped.metadata,
        **image_info,
    }
    meta_path = out_dir / f"{stamp}.json"
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_path = out_dir / "latest.json"
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["metadata_path"] = str(meta_path)
    payload["latest_path"] = str(latest_path)
    return payload


def latest_compositions_screenshot() -> dict[str, Any] | None:
    path = _screenshot_dir() / "latest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
