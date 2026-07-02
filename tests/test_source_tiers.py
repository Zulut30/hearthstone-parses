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


class SourceTiersTest(unittest.TestCase):
    def test_registry_covers_all_sources(self) -> None:
        validate_tier_registry()
        configured = {s.id for s in SOURCES}
        all_tier_ids = (
            LIGHT_API_IDS | MEDIUM_API_IDS | BROWSER_PATCHRIGHT_IDS | BROWSER_PROTECTED_IDS
        )
        self.assertEqual(configured, all_tier_ids)
        # Derive from the registry (app/sources.py SOURCES, 44 entries as of
        # Phase 2) instead of hardcoding the count: the invariant under test is
        # tier coverage, not the absolute number of sources.
        self.assertEqual(len(configured), len(SOURCES))
        # Guard against duplicate ids silently shrinking the configured set.
        self.assertEqual(len([s.id for s in SOURCES]), len(configured))

    def test_tier_for_each_source(self) -> None:
        for source in SOURCES:
            tier = tier_for(source.id)
            self.assertIsInstance(tier, SourceTier)

    def test_partition_preserves_count(self) -> None:
        parts = partition_sources(list(SOURCES))
        total = (
            len(parts.light_api)
            + len(parts.medium_api)
            + len(parts.browser_patchright)
            + len(parts.browser_protected)
        )
        self.assertEqual(total, len(SOURCES))
        # Per-tier sizes are defined by the ID sets in app/source_tiers.py
        # (LIGHT_API_IDS etc.); since the registry covers all sources exactly,
        # each partition must match its ID set instead of a hardcoded count.
        self.assertEqual(len(parts.light_api), len(LIGHT_API_IDS))
        self.assertEqual(len(parts.medium_api), len(MEDIUM_API_IDS))
        self.assertEqual(len(parts.browser_patchright), len(BROWSER_PATCHRIGHT_IDS))
        self.assertEqual(len(parts.browser_protected), len(BROWSER_PROTECTED_IDS))
        self.assertEqual({s.id for s in parts.light_api}, LIGHT_API_IDS)
        self.assertEqual({s.id for s in parts.browser_protected}, BROWSER_PROTECTED_IDS)


if __name__ == "__main__":
    unittest.main()
