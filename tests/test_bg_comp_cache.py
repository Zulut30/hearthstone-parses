from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.battlegrounds_comps_parse import (
    _bg_comp_detail_cache_path,
    _read_bg_comp_detail_cache,
    _write_bg_comp_detail_cache,
)


class BGCompCacheTest(unittest.TestCase):
    def test_cache_roundtrip_and_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch("app.battlegrounds_comps_parse.data_dir", return_value=Path(td)):
                url = "https://hsreplay.net/battlegrounds/comps/42/foo-bar/"
                p = _bg_comp_detail_cache_path(url)
                self.assertIsNotNone(p)
                assert p is not None
                self.assertTrue(str(p).endswith("42.md"))

                _write_bg_comp_detail_cache(url, "markdown here with enough length " + "x" * 300)
                self.assertTrue(p.exists())

                got = _read_bg_comp_detail_cache(url)
                self.assertIsNotNone(got)
                self.assertIn("markdown here", got or "")

                # simulate old file
                import os

                os.utime(p, (time.time() - 86400 * 10, time.time() - 86400 * 10))
                with patch("app.battlegrounds_comps_parse.bg_comp_detail_cache_ttl_hours", return_value=1.0):
                    got_old = _read_bg_comp_detail_cache(url)
                    self.assertIsNone(got_old)


if __name__ == "__main__":
    unittest.main()
