# Scrapy + scrapy-playwright (lab)

Экспериментальный паук для обхода и сравнения с production-ротатором (`app/scrapers/rotator.py`).
**Не используется в systemd refresh.**

## Установка

```bash
cd /opt/hs-data-api
python3 -m venv .venv-lab
. .venv-lab/bin/activate
pip install scrapy scrapy-playwright patchright
playwright install chromium
```

## Запуск

```bash
cd lab/scrapy_hsreplay
scrapy crawl hsreplay_probe -a url=https://hsreplay.net/
```

См. [scrapy-playwright](https://github.com/scrapy-plugins/scrapy-playwright) и [Scrapy](https://github.com/scrapy/scrapy).
