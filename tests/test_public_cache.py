from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.public_cache import PUBLIC_CACHE_CONTROL, cache_revision
from app.storage import save_dataset


client = TestClient(app)


def test_v1_get_returns_etag_and_conditional_304() -> None:
    fetched_at = datetime.now(UTC).isoformat()
    payload = {
        "count": 1,
        "fetched_at": fetched_at,
        "heroes": [{"hero": "A.F. Kay", "dbfId": 1}],
    }
    with patch("app.hsreplay_bg_hero_details.list_bg_heroes", return_value=payload):
        first = client.get(
            "/v1/bg/heroes",
            headers={"Origin": "https://api.hs-manacost.ru"},
        )
        second = client.get(
            "/v1/bg/heroes",
            headers={
                "If-None-Match": first.headers["etag"],
                "Origin": "https://api.hs-manacost.ru",
            },
        )

    assert first.status_code == 200
    assert first.headers["cache-control"] == PUBLIC_CACHE_CONTROL
    assert first.headers["etag"].startswith('"')
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["etag"] == first.headers["etag"]
    assert second.headers["access-control-allow-origin"] == "https://api.hs-manacost.ru"


def test_dataset_etag_changes_with_fetched_at() -> None:
    source_id = "hsreplay_arena"
    first_time = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    save_dataset(source_id, {"source_id": source_id, "fetched_at": first_time, "data": {}})
    first = client.get(f"/datasets/{source_id}")

    second_time = datetime.now(UTC).isoformat()
    save_dataset(source_id, {"source_id": source_id, "fetched_at": second_time, "data": {}})
    second = client.get(f"/datasets/{source_id}")

    assert first.status_code == second.status_code == 200
    assert first.headers["etag"] != second.headers["etag"]


def test_health_and_ui_are_not_publicly_cached() -> None:
    health = client.get("/health")
    assert "etag" not in health.headers
    assert "cache-control" not in health.headers


def test_legacy_api_shape_is_unchanged_and_gets_cache_headers() -> None:
    expected = {
        "type": "bg_heroes",
        "mode": "solo",
        "count": 1,
        "fetched_at": None,
        "filters": {},
        "source": {},
        "heroes": [{"hero": "A.F. Kay"}],
    }
    with patch("app.hsreplay_bg_hero_details.list_bg_heroes", return_value=expected):
        response = client.get("/api/bg/heroes")

    assert response.status_code == 200
    assert response.json() == expected
    assert response.headers["cache-control"] == PUBLIC_CACHE_CONTROL
    assert "etag" in response.headers


def test_cache_revision_is_best_effort_when_storage_is_unavailable() -> None:
    with patch("app.public_cache.load_dataset", side_effect=PermissionError("denied")):
        assert cache_revision("/datasets", b"") == "not-cached"
