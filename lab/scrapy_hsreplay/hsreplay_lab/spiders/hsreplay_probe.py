import scrapy


class HsreplayProbeSpider(scrapy.Spider):
    name = "hsreplay_probe"
    custom_settings = {
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 120_000,
    }

    def start_requests(self):
        url = getattr(self, "url", None) or "https://hsreplay.net/"
        yield scrapy.Request(
            url,
            meta={
                "playwright": True,
                "playwright_include_page": True,
            },
            callback=self.parse,
        )

    async def parse(self, response):
        page = response.meta.get("playwright_page")
        title = response.css("title::text").get() or ""
        userdata = response.css("script#userdata::text").get()
        yield {
            "url": response.url,
            "title": title.strip(),
            "has_userdata": bool(userdata and userdata.strip()),
            "html_bytes": len(response.text or ""),
        }
        if page:
            await page.close()
