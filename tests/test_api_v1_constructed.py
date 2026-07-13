from __future__ import annotations

from datetime import UTC, datetime
import sqlite3
from unittest.mock import patch

from starlette.testclient import TestClient

from app.main import app


client = TestClient(app)


def _deck_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE decks (
            id INTEGER, source_id TEXT, class TEXT, archetype TEXT,
            deck_code TEXT, win_rate REAL, title TEXT, format TEXT, updated_at TEXT
        )"""
    )
    connection.execute(
        "INSERT INTO decks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, "fixture", "Warlock", "Evenlock", "AAECAf0GTestDeckCode1234567890==", 55.1, "Evenlock", "Wild", datetime.now(UTC).isoformat()),
    )
    return connection


def test_v1_decks_filters_class_and_format_case_insensitively() -> None:
    with patch("app.db.get_db_connection", side_effect=_deck_connection):
        response = client.get("/v1/constructed/decks?class_name=warlock&format_name=wild")

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["count"] == 1
    assert body["data"][0]["archetype"] == "Evenlock"


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
