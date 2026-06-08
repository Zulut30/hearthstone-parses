from __future__ import annotations

import unittest
from unittest.mock import patch

from app.hsreplay_client import (
    _is_bg_comps_listing_url,
    _markdown_body_usable,
    _markdown_channel_urls,
)


class MarkdownUsableTest(unittest.TestCase):
    def test_listing_rejects_html_without_headers(self) -> None:
        url = "https://hsreplay.net/battlegrounds/comps/"
        html = "<html><body>" + ("x" * 2000) + "</body></html>"
        self.assertFalse(_markdown_body_usable(html, url))

    def test_listing_accepts_jina_markdown(self) -> None:
        url = "https://hsreplay.net/battlegrounds/comps/"
        md = (
            "Markdown Content:\n\n"
            "[Dragons](https://hsreplay.net/battlegrounds/comps/1/dragons/)\n"
            "[Beasts](https://hsreplay.net/battlegrounds/comps/2/beasts/)\n"
            "[Mechs](https://hsreplay.net/battlegrounds/comps/3/mechs/)\n"
        )
        self.assertTrue(_markdown_body_usable(md, url))

    def test_detail_accepts_hsjson_images(self) -> None:
        url = "https://hsreplay.net/battlegrounds/comps/1/slug/"
        body = (
            "![x](https://art.hearthstonejson.com/v1/256x/BG_1.png) "
            + ("padding " * 40)
        )
        self.assertTrue(_markdown_body_usable(body, url))

    def test_is_listing_url(self) -> None:
        self.assertTrue(_is_bg_comps_listing_url("https://hsreplay.net/battlegrounds/comps/"))
        self.assertFalse(_is_bg_comps_listing_url("https://hsreplay.net/battlegrounds/comps/1/x/"))

    @patch(
        "app.hsreplay_client.hsreplay_markdown_channels",
        return_value=["flaresolverr", "curl_cffi"],
    )
    def test_markdown_channels_no_jina(self, _mock: object) -> None:
        url = "https://hsreplay.net/battlegrounds/comps/"
        labels = [label for label, _ in _markdown_channel_urls(url)]
        self.assertEqual(labels, ["flaresolverr", "curl_cffi"])


if __name__ == "__main__":
    unittest.main()
