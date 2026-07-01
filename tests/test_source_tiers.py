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
        self.assertEqual(len(configured), 40)

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
        self.assertEqual(len(parts.light_api), 15)
        self.assertEqual(len(parts.medium_api), 9)
        self.assertEqual(len(parts.browser_patchright), 2)
        self.assertEqual(len(parts.browser_protected), 14)


if __name__ == "__main__":
    unittest.main()
