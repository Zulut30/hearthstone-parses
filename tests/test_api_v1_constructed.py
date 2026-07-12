from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_v1_archetypes_returns_typed_envelope() -> None:
    fetched_at = datetime.now(UTC).isoformat()
    payload = {
        "total": 1,
        "limit": 100,
        "offset": 0,
        "archetypes": [
            {
                "archetype_id": 42,
                "name": "Spell Mage",
                "player_class": "MAGE",
                "win_rate": 52.4,
                "total_games": 1234,
                "fetched_at": fetched_at,
            }
        ],
    }
    with patch(
        "app.hsreplay_archetypes_db.list_archetype_snapshots",
        return_value=payload,
    ):
        response = client.get("/v1/constructed/archetypes?limit=25&offset=0")

    assert response.status_code == 200
    body = response.json()
    assert body["data"][0]["name"] == "Spell Mage"
    assert body["meta"] == {
        "source_id": "hsreplay_archetypes",
        "fetched_at": fetched_at,
        "stale": False,
        "count": 1,
        "limit": 25,
        "offset": 0,
    }


def test_openapi_exposes_concrete_v1_models() -> None:
    schema = client.get("/openapi.json").json()
    response_schema = schema["paths"]["/v1/constructed/archetypes"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert "$ref" in response_schema
    assert "ArchetypeRow" in schema["components"]["schemas"]
    assert schema["components"]["schemas"]["ArchetypeRow"]["properties"]["archetype_id"]["type"] == "integer"


def test_legacy_route_remains_registered_separately() -> None:
    paths = set(client.get("/openapi.json").json()["paths"])
    assert "/api/db/archetypes" in paths
    assert "/v1/constructed/archetypes" in paths
