from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


API_URL_RE = re.compile(
    r"""(?P<url>(?:https?:)?//[^"'\s<>]+|/[A-Za-z0-9_./?=&:%-]*(?:api|meta|matchups|decks)[^"'\s<>]*)""",
    re.I,
)


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def discover_hsguru_api_candidates(html: str, *, page_url: str = "https://www.hsguru.com/") -> dict[str, Any]:
    """Inspect HSGuru HTML for embedded data and likely internal API/network endpoints."""
    soup = BeautifulSoup(html, "lxml")
    embedded_json: list[dict[str, Any]] = []
    api_candidates: set[str] = set()

    for script in soup.find_all("script"):
        script_id = script.get("id") or ""
        script_type = script.get("type") or ""
        text = script.string or script.get_text(" ", strip=True)
        if not text:
            continue

        if script_type == "application/json" or script_id in {"__NEXT_DATA__", "__NUXT_DATA__"}:
            payload = _json_object(text)
            if payload is not None:
                embedded_json.append(
                    {
                        "id": script_id or None,
                        "type": script_type or None,
                        "top_level_keys": sorted(payload.keys())[:20],
                        "bytes": len(text.encode("utf-8", errors="replace")),
                    }
                )

        for match in API_URL_RE.finditer(text):
            candidate = match.group("url")
            if candidate.startswith("//"):
                candidate = "https:" + candidate
            api_candidates.add(urljoin(page_url, candidate))

    for tag in soup.find_all(["a", "link", "script"]):
        href = tag.get("href") or tag.get("src")
        if not href:
            continue
        if any(token in href.lower() for token in ("api", "meta", "matchups", "decks")):
            api_candidates.add(urljoin(page_url, str(href)))

    return {
        "ok": bool(embedded_json or api_candidates),
        "embedded_json": embedded_json,
        "api_candidates": sorted(api_candidates)[:50],
        "candidate_count": len(api_candidates),
    }
