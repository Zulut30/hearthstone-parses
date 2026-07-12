from __future__ import annotations

import json
from pathlib import Path

from app.cli import parse_args
from app.vicious_syndicate_auth import (
    cookie_editor_to_playwright,
    import_vicious_syndicate_storage,
    vicious_syndicate_cookies_for_fetch,
)


def test_cookie_editor_conversion_and_cli_registration() -> None:
    converted = cookie_editor_to_playwright(
        [
            {
                "name": "wordpress_logged_in_test",
                "value": "secret",
                "domain": ".vicioussyndicate.com",
                "sameSite": "no_restriction",
                "session": True,
            }
        ]
    )

    assert converted["cookies"][0]["sameSite"] == "None"
    assert converted["cookies"][0]["expires"] == -1
    assert parse_args(["vicious-import-storage", "/tmp/cookies.json"]).command == (
        "vicious-import-storage"
    )


def test_import_is_atomic_private_and_domain_scoped(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "export.json"
    destination = tmp_path / "stored.json"
    source.write_text(
        json.dumps(
            [
                {
                    "name": "wordpress_logged_in_test",
                    "value": "secret",
                    "domain": ".vicioussyndicate.com",
                },
                {
                    "name": "unrelated",
                    "value": "must-not-leak",
                    "domain": ".example.com",
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VICIOUS_SYNDICATE_STORAGE_PATH", str(destination))

    assert import_vicious_syndicate_storage(source) == destination
    assert destination.stat().st_mode & 0o777 == 0o600
    assert not destination.with_suffix(".json.tmp").exists()
    assert vicious_syndicate_cookies_for_fetch() == {
        "wordpress_logged_in_test": "secret"
    }


def test_invalid_saved_session_fails_open_without_exposing_secrets(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    destination = tmp_path / "stored.json"
    destination.write_text("not-json", encoding="utf-8")
    monkeypatch.setenv("VICIOUS_SYNDICATE_STORAGE_PATH", str(destination))

    assert vicious_syndicate_cookies_for_fetch() == {}
    assert "Ignoring invalid Vicious Syndicate storage file" in caplog.text
