from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import cli
from app.sources import Source


class CliTest(unittest.TestCase):
    def test_refresh_source_uses_global_source_map_after_freshness_imports(self) -> None:
        with patch("app.cli.refresh_sources", return_value=[]) as refresh:
            exit_code = cli.main(["refresh", "--source", "hsguru_meta_wild_top_legend"])

        self.assertEqual(exit_code, 0)
        refresh.assert_called_once_with(["hsguru_meta_wild_top_legend"], tier=None)

    def test_load_env_file_overrides_stale_hsguru_backend_export(self) -> None:
        with TemporaryDirectory() as td:
            env_path = Path(td) / "hs.env"
            env_path.write_text(
                "HS_HSGURU_FETCH_BACKENDS=flaresolverr,scrapling,curl_cffi\n",
                encoding="utf-8",
            )
            old = os.environ.get("HS_HSGURU_FETCH_BACKENDS")
            os.environ["HS_HSGURU_FETCH_BACKENDS"] = "patchright"
            try:
                cli.load_env_file(env_path)
                self.assertEqual(
                    os.environ["HS_HSGURU_FETCH_BACKENDS"],
                    "flaresolverr,scrapling,curl_cffi",
                )
            finally:
                if old is None:
                    os.environ.pop("HS_HSGURU_FETCH_BACKENDS", None)
                else:
                    os.environ["HS_HSGURU_FETCH_BACKENDS"] = old

    def test_quality_check_returns_nonzero_for_invalid_cached_dataset(self) -> None:
        source = Source("bad_source", "https://example.test", "hsreplay", "arena")
        with patch("app.cli.SOURCE_BY_ID", {"bad_source": source}), patch(
            "app.storage.load_status",
            return_value={"state": "ok", "backend": "test"},
        ), patch("app.storage.load_dataset", return_value={"data": {}}):
            exit_code = cli.main(["quality-check"])

        self.assertEqual(exit_code, 1)

    def test_quality_check_passes_valid_cached_dataset(self) -> None:
        source = Source("ok_source", "https://example.test", "hsreplay", "arena")
        with patch("app.cli.SOURCE_BY_ID", {"ok_source": source}), patch(
            "app.storage.load_status",
            return_value={"state": "ok", "backend": "test"},
        ), patch(
            "app.storage.load_dataset",
            return_value={"data": {"title": "ok", "structured": {"type": "legacy_dataset", "rows": []}}},
        ):
            with patch("app.scrapers.quality.validate_parsed_data", return_value=(True, "ok")):
                exit_code = cli.main(["quality-check"])

        self.assertEqual(exit_code, 0)

    def test_quality_check_warn_band_does_not_fail(self) -> None:
        source = Source("warn_source", "https://example.test", "hsreplay", "arena")
        with patch("app.cli.SOURCE_BY_ID", {"warn_source": source}), patch(
            "app.storage.load_status",
            return_value={"state": "ok", "backend": "test"},
        ), patch(
            "app.storage.load_dataset",
            return_value={"data": {"title": "ok", "structured": {"type": "legacy_dataset", "rows": []}}},
        ), patch("app.scrapers.quality.validate_parsed_data", return_value=(True, "ok")), patch(
            "app.scrapers.quality.quality_metrics",
            return_value={"quality_score": 0.90},
        ):
            exit_code = cli.main(["quality-check", "--min-quality-score", "0.85", "--warn-quality-score", "0.95"])

        self.assertEqual(exit_code, 0)

    def test_quality_check_reports_validation_exception_as_bad_source(self) -> None:
        source = Source("raises_source", "https://example.test", "hsreplay", "arena")
        with patch("app.cli.SOURCE_BY_ID", {"raises_source": source}), patch(
            "app.storage.load_status",
            return_value={"state": "ok", "backend": "test"},
        ), patch(
            "app.storage.load_dataset",
            return_value={"data": {"title": "ok", "structured": {"type": "arena_class_matrix"}}},
        ), patch(
            "app.scrapers.quality.validate_parsed_data",
            side_effect=ValueError("bad deck_class"),
        ):
            exit_code = cli.main(["quality-check"])

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
