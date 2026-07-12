from __future__ import annotations

import os
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.patches_db import count_patches, get_patch, list_patches, upsert_patch


class PatchesDbTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.old_data_dir = os.environ.get("HS_API_DATA_DIR")
        os.environ["HS_API_DATA_DIR"] = self.tmp.name

    def tearDown(self) -> None:
        if self.old_data_dir is None:
            os.environ.pop("HS_API_DATA_DIR", None)
        else:
            os.environ["HS_API_DATA_DIR"] = self.old_data_dir
        self.tmp.cleanup()

    def test_upsert_and_lookup_patch(self) -> None:
        upsert_patch(
            {
                "version": "35.6.0",
                "display_version": "35.6.0",
                "wiki_title": "Patch 35.6.0",
                "wiki_url": "https://hearthstone.wiki.gg/wiki/Patch_35.6.0",
                "official_title": "35.6 Patch Notes",
                "official_url": "https://hearthstone.blizzard.com/en-us/news/24276665/35-6-patch-notes",
                "official_published_at": "2026-06-02T17:00:00+00:00",
                "hs_manacost_version": "35.6",
                "title": "Обновление 35.6",
                "slug": "obnovlenie-35-6-test",
                "source_url": "https://hs-manacost.ru/obnovlenie-35-6-test/",
                "summary": "summary",
                "sections": [{"level": "h3", "title": "Навигация"}],
                "content_text": "full text",
                "published_at": "2026-06-03T14:24:11",
            }
        )

        by_wiki_version = get_patch("35.6.0")
        by_manacost_version = get_patch("35.6")
        self.assertEqual(by_wiki_version["title"], "Обновление 35.6")
        self.assertEqual(by_manacost_version["version"], "35.6.0")
        self.assertEqual(by_wiki_version["wiki_title"], "Patch 35.6.0")
        self.assertEqual(by_wiki_version["official_title"], "35.6 Patch Notes")
        self.assertIn("hearthstone.blizzard.com", by_wiki_version["official_url"])
        self.assertEqual(by_wiki_version["match_state"], "matched")
        self.assertEqual(by_wiki_version["sections"][0]["title"], "Навигация")

        listed = list_patches()
        self.assertEqual(listed["total"], 1)
        self.assertEqual(count_patches(), 1)
        self.assertNotIn("content_text", listed["patches"][0])

    def test_api_routes(self) -> None:
        upsert_patch(
            {
                "version": "35.6.2.245096",
                "display_version": "35.6.2.245096",
                "wiki_title": "Patch 35.6.2.245096",
                "wiki_url": "https://hearthstone.wiki.gg/wiki/Patch_35.6.2.245096",
                "hs_manacost_version": "35.6.2",
                "title": "Обновление 35.6.2",
                "slug": "obnovlenie-35-6-2-test",
                "source_url": "https://hs-manacost.ru/obnovlenie-35-6-2-test/",
                "summary": "summary",
                "published_at": "2026-06-11T20:12:12",
            }
        )

        client = TestClient(app)
        list_response = client.get("/api/patches")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["patches"][0]["version"], "35.6.2.245096")

        detail_response = client.get("/api/patches/35.6.2")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["title"], "Обновление 35.6.2")

    def test_wiki_only_patch_can_be_stored(self) -> None:
        upsert_patch(
            {
                "version": "99.0.0.1",
                "display_version": "99.0.0.1",
                "wiki_title": "Patch 99.0.0.1",
                "wiki_url": "https://hearthstone.wiki.gg/wiki/Patch_99.0.0.1",
            }
        )

        patch = get_patch("99.0.0.1")
        self.assertEqual(patch["match_state"], "missing_manacost")
        self.assertIsNone(patch["source_url"])


if __name__ == "__main__":
    unittest.main()
