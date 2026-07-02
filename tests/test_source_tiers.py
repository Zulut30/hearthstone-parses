from __future__ import annotations

import unittest

from app.source_tiers import (
    BROWSER_PATCHRIGHT_IDS,
    BROWSER_PROTECTED_IDS,
    LIGHT_API_IDS,
    MEDIUM_API_IDS,
    SourceTier,
    partition_sources,
    tier_for,
    validate_tier_registry,
)
from app.sources import SOURCES


def _scrape_sources():
    return [s for s in SOURCES if s.kind == "scrape"]


class SourceTiersTest(unittest.TestCase):
    def test_registry_covers_all_scrape_sources(self) -> None:
        validate_tier_registry()
        configured = {s.id for s in _scrape_sources()}
        all_tier_ids = (
            LIGHT_API_IDS | MEDIUM_API_IDS | BROWSER_PATCHRIGHT_IDS | BROWSER_PROTECTED_IDS
        )
        self.assertEqual(configured, all_tier_ids)
        # Derive from the registry (app/sources.py SOURCES) instead of
        # hardcoding the count: the invariant under test is tier coverage of
        # kind="scrape" sources, not the absolute number of sources.
        self.assertEqual(len(configured), len(_scrape_sources()))
        # Guard against duplicate ids silently shrinking the configured set.
        self.assertEqual(len([s.id for s in SOURCES]), len({s.id for s in SOURCES}))

    def test_pipeline_sources_have_no_tier(self) -> None:
        pipeline = [s for s in SOURCES if s.kind == "pipeline"]
        self.assertTrue(pipeline, "phase-5 registered pipeline sources expected")
        all_tier_ids = (
            LIGHT_API_IDS | MEDIUM_API_IDS | BROWSER_PATCHRIGHT_IDS | BROWSER_PROTECTED_IDS
        )
        for source in pipeline:
            self.assertNotIn(source.id, all_tier_ids)
            with self.assertRaises(KeyError):
                tier_for(source.id)

    def test_tier_for_each_scrape_source(self) -> None:
        for source in _scrape_sources():
            tier = tier_for(source.id)
            self.assertIsInstance(tier, SourceTier)

    def test_partition_preserves_scrape_count_and_skips_pipeline(self) -> None:
        parts = partition_sources(list(SOURCES))
        total = (
            len(parts.light_api)
            + len(parts.medium_api)
            + len(parts.browser_patchright)
            + len(parts.browser_protected)
        )
        self.assertEqual(total, len(_scrape_sources()))
        partitioned_ids = {
            s.id
            for bucket in parts
            for s in bucket
        }
        for source in SOURCES:
            if source.kind == "pipeline":
                self.assertNotIn(source.id, partitioned_ids)
        # Per-tier sizes are defined by the ID sets in app/source_tiers.py
        # (LIGHT_API_IDS etc.); since the registry covers all scrape sources
        # exactly, each partition must match its ID set.
        self.assertEqual(len(parts.light_api), len(LIGHT_API_IDS))
        self.assertEqual(len(parts.medium_api), len(MEDIUM_API_IDS))
        self.assertEqual(len(parts.browser_patchright), len(BROWSER_PATCHRIGHT_IDS))
        self.assertEqual(len(parts.browser_protected), len(BROWSER_PROTECTED_IDS))
        self.assertEqual({s.id for s in parts.light_api}, LIGHT_API_IDS)
        self.assertEqual({s.id for s in parts.browser_protected}, BROWSER_PROTECTED_IDS)


if __name__ == "__main__":
    unittest.main()
