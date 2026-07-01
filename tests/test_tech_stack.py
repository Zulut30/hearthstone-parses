import unittest

from app.tech_stack import build_technologies_payload


class TechStackTest(unittest.TestCase):
    def test_technologies_payload_includes_site_kitchen(self) -> None:
        data = build_technologies_payload()

        self.assertGreaterEqual(data["count"], 10)
        names = {t["name"] for t in data["technologies"]}
        self.assertIn("FastAPI + Uvicorn", names)
        self.assertIn("playwright-stealth", names)
        self.assertGreaterEqual(data["site_count"], 7)

        sites = {site["key"]: site for site in data["sites"]}
        self.assertIn("hsreplay", sites)
        self.assertIn("hsguru", sites)
        self.assertIn("vicious-syndicate", sites)
        hsreplay_api_names = {api["name"] for api in sites["hsreplay"]["apis"]}
        self.assertIn("Meta archetypes", hsreplay_api_names)
        self.assertIn(
            "Firebase ladderData",
            {api["name"] for api in sites["vicious-syndicate"]["apis"]},
        )


if __name__ == "__main__":
    unittest.main()
