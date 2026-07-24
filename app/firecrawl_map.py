from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from urllib import request

from .config import (
    data_dir,
    firecrawl_map_hsreplay_limit,
    firecrawl_map_hsreplay_url,
    firecrawl_timeout_ms,
)
from .firecrawl_keys import (
    acquire_firecrawl_key,
    is_firecrawl_credit_error,
    mark_firecrawl_key_exhausted,
    record_firecrawl_credits,
)
from .storage import load_dataset


FIRECRAWL_MAP_URL = "https://api.firecrawl.dev/v2/map"
HSREPLAY_MAP_LIMIT = 5000
MIN_HSREPLAY_MAP_URLS = 500
MIN_INDEX_COUNTS = {
    "standard_minions": 100,
    "battlegrounds_minions": 150,
    "battlegrounds_heroes": 30,
    "standard_unique_archetypes": 20,
}


def firecrawl_dir() -> Path:
    path = data_dir() / "firecrawl"
    path.mkdir(parents=True, exist_ok=True)
    return path


def hsreplay_map_path() -> Path:
    return firecrawl_dir() / "hsreplay-map-latest.json"


def hsreplay_index_path() -> Path:
    return firecrawl_dir() / "hsreplay-index-latest.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    try:
        path.chmod(0o644)
    except OSError:
        pass


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_hsreplay_map() -> dict[str, Any] | None:
    return _read_json(hsreplay_map_path())


def load_hsreplay_index() -> dict[str, Any] | None:
    return _read_json(hsreplay_index_path())


def _extract_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        if value.startswith(("http://", "https://", "/")):
            urls.append(value)
    elif isinstance(value, list):
        for item in value:
            urls.extend(_extract_urls(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"url", "urls", "link", "links"}:
                urls.extend(_extract_urls(item))
            elif isinstance(item, (dict, list)):
                urls.extend(_extract_urls(item))
    return urls


def _normalise_hsreplay_url(url: str) -> str:
    if url.startswith("/"):
        return f"https://hsreplay.net{url}"
    return url


def _unique_urls(payload: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url in _extract_urls(payload):
        normalised = _normalise_hsreplay_url(url).split("#", 1)[0].rstrip("/")
        if not normalised.startswith("https://hsreplay.net"):
            continue
        if normalised in seen:
            continue
        seen.add(normalised)
        out.append(normalised)
    return sorted(out)


def _validate_map_size(url_count: int, *, previous_count: int) -> None:
    minimum_count = max(MIN_HSREPLAY_MAP_URLS, int(previous_count * 0.50))
    if url_count < minimum_count:
        raise RuntimeError(
            "HSReplay Firecrawl map truncation guard rejected refresh: "
            f"discovered {url_count}, required at least {minimum_count} "
            f"(previous {previous_count})"
        )


def fetch_hsreplay_firecrawl_map() -> dict[str, Any]:
    payload = {
        "url": firecrawl_map_hsreplay_url(),
        "limit": firecrawl_map_hsreplay_limit(HSREPLAY_MAP_LIMIT),
        "includeSubdomains": False,
        "sitemap": "include",
    }
    body = json.dumps(payload).encode("utf-8")
    timeout = (firecrawl_timeout_ms() / 1000) + 60
    errors: list[str] = []
    parsed: dict[str, Any] | None = None
    lease_label: str | None = None
    lease_fingerprint: str | None = None
    rotation: dict[str, Any] | None = None

    for _ in range(8):
        lease = acquire_firecrawl_key()
        lease_label = lease.key.label
        lease_fingerprint = lease.key.fingerprint
        req = request.Request(
            FIRECRAWL_MAP_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {lease.key.key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                parsed = json.loads(raw)
        except Exception as exc:
            if is_firecrawl_credit_error(exc):
                mark_firecrawl_key_exhausted(lease.key.label, reason=str(exc))
                errors.append(f"{lease.key.label}: {exc}")
                continue
            raise

        credits = 1
        if isinstance(parsed, dict):
            if parsed.get("creditsUsed") is not None:
                try:
                    credits = int(parsed.get("creditsUsed") or 1)
                except (TypeError, ValueError):
                    credits = 1
            elif not parsed.get("success", True):
                raise RuntimeError(f"Firecrawl map failed: {parsed}")
        rotation = record_firecrawl_credits(lease.key.label, max(1, credits))
        break
    else:
        detail = "; ".join(errors) if errors else "no available keys"
        raise RuntimeError(f"Firecrawl map failed after key rotation attempts: {detail}")

    assert parsed is not None
    now = datetime.now(UTC).isoformat()
    urls = _unique_urls(parsed)
    previous = load_hsreplay_map() or {}
    previous_count = int(previous.get("url_count") or 0)
    _validate_map_size(len(urls), previous_count=previous_count)
    result = {
        "ok": True,
        "fetched_at": now,
        "request": {**payload, "authorization": "redacted"},
        "url_count": len(urls),
        "urls": urls,
        "firecrawl_response": parsed,
        "firecrawl_key_label": lease_label,
        "firecrawl_key_fingerprint": lease_fingerprint,
        "firecrawl_key_rotation": rotation,
    }
    _write_json(hsreplay_map_path(), result)
    return result


def _structured(source_id: str) -> dict[str, Any]:
    dataset = load_dataset(source_id) or {}
    return ((dataset.get("data") or {}).get("structured") or {})


def _unique_by(items: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = tuple(item.get(field) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def build_hsreplay_index() -> dict[str, Any]:
    cards = _structured("hsreplay_cards_legend_1d").get("cards") or []
    standard_minions = [
        {
            "id": card.get("id"),
            "dbfId": card.get("dbfId"),
            "name": card.get("name"),
            "class": card.get("cardClass"),
            "cost": card.get("cost"),
            "rarity": card.get("rarity"),
            "deck_popularity": card.get("deck_popularity"),
            "deck_winrate": card.get("deck_winrate"),
        }
        for card in cards
        if card.get("type") == "MINION" and card.get("name")
    ]

    bg_minions_raw = _structured("hsreplay_battlegrounds_minions").get("minions") or []
    battlegrounds_minions = [
        {
            "id": row.get("id"),
            "dbfId": row.get("dbfId") or row.get("minion_dbf_id"),
            "name": row.get("name") or row.get("minion"),
            "tavern_tier": row.get("tavern_tier") or row.get("techLevel"),
            "impact": row.get("impact"),
            "win_share": row.get("win_share"),
            "popularity": row.get("popularity"),
        }
        for row in bg_minions_raw
        if row.get("name") or row.get("minion")
    ]

    heroes_raw = _structured("hsreplay_battlegrounds_heroes").get("heroes") or []
    battlegrounds_heroes = [
        {
            "hero": row.get("hero"),
            "dbfId": row.get("dbfId"),
            "tier": row.get("tier"),
            "pick_rate": row.get("pick_rate"),
            "avg_placement": row.get("avg_placement"),
            "best_comp": row.get("best_comp"),
        }
        for row in heroes_raw
        if row.get("hero")
    ]

    meta = _structured("hsreplay_meta_archetypes_legend_eu_1d")
    standard_archetypes: list[dict[str, Any]] = []
    for class_row in meta.get("classes") or []:
        for archetype in class_row.get("archetypes") or []:
            name = archetype.get("archetype")
            archetype_id = archetype.get("archetype_id")
            if not name or not archetype.get("url") or (isinstance(archetype_id, int) and archetype_id < 0):
                continue
            standard_archetypes.append(
                {
                    "archetype_id": archetype_id,
                    "archetype": name,
                    "class": class_row.get("class"),
                    "class_name": class_row.get("class_name"),
                    "url": _normalise_hsreplay_url(archetype.get("url")),
                    "winrate": archetype.get("winrate"),
                    "popularity": archetype.get("popularity"),
                    "games": archetype.get("games"),
                }
            )

    map_payload = load_hsreplay_map() or {}
    standard_minions = _unique_by(standard_minions, ("dbfId", "name"))
    battlegrounds_minions = _unique_by(battlegrounds_minions, ("dbfId", "name"))
    battlegrounds_heroes = _unique_by(battlegrounds_heroes, ("dbfId", "hero"))
    standard_archetypes = _unique_by(standard_archetypes, ("archetype_id", "archetype"))
    result = {
        "ok": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "map_fetched_at": map_payload.get("fetched_at"),
        "map_url_count": map_payload.get("url_count"),
        "sources": {
            "standard_minions": "hsreplay_cards_legend_1d",
            "battlegrounds_minions": "hsreplay_battlegrounds_minions",
            "battlegrounds_heroes": "hsreplay_battlegrounds_heroes",
            "standard_archetypes": "hsreplay_meta_archetypes_legend_eu_1d",
        },
        "counts": {
            "standard_minions": len(standard_minions),
            "battlegrounds_minions": len(battlegrounds_minions),
            "battlegrounds_heroes": len(battlegrounds_heroes),
            "standard_unique_archetypes": len(standard_archetypes),
        },
        "standard_minions": standard_minions,
        "battlegrounds_minions": battlegrounds_minions,
        "battlegrounds_heroes": battlegrounds_heroes,
        "standard_unique_archetypes": standard_archetypes,
    }
    quality_errors = [
        f"{name} too small ({int(result['counts'].get(name) or 0)} < {minimum})"
        for name, minimum in MIN_INDEX_COUNTS.items()
        if int(result["counts"].get(name) or 0) < minimum
    ]
    if quality_errors:
        raise RuntimeError(
            "HSReplay derived index quality gate rejected refresh: " + "; ".join(quality_errors)
        )
    _write_json(hsreplay_index_path(), result)
    return result


def refresh_hsreplay_map_and_index() -> dict[str, Any]:
    map_payload = fetch_hsreplay_firecrawl_map()
    index = build_hsreplay_index()
    return {
        "ok": True,
        "map_path": str(hsreplay_map_path()),
        "index_path": str(hsreplay_index_path()),
        "map_url_count": map_payload.get("url_count"),
        "counts": index.get("counts"),
    }
