# Hearthstone Parses

Кэширующий парсер и REST API для публичных страниц [HSGuru](https://www.hsguru.com) и [HSReplay](https://hsreplay.net).  
Обходит Cloudflare через резидентский прокси + ротацию backends (FlareSolverr, patchright, cloudscraper).

Репозиторий: [github.com/Zulut30/hearthstone-parses](https://github.com/Zulut30/hearthstone-parses)

---

## Быстрый старт

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
patchright install chromium

cp .env.example /etc/hs-data-api.env   # или export переменные
# Заполните HS_FETCH_PROXY_URL и HS_API_KEY

docker compose up -d   # FlareSolverr (опционально, для HSGuru)

python -m app.cli proxy-check
python -m app.cli refresh --all
uvicorn app.server:app --host 0.0.0.0 --port 8000
```

Автосбор раз в сутки: `systemd/hs-data-api-refresh.timer`.

---

## Демо-сайт

После запуска API откройте в браузере:

```
http://YOUR_HOST:8000/ui
```

Показывает распарсенные данные по каждому источнику. Колоды стримеров декодируются в карты с **id** и **dbfId** через [HearthstoneJSON](https://api.hearthstonejson.com).

---

## Базовый URL API

```
http://YOUR_HOST:8000
```

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/health` | Статус кэша по всем источникам |
| `GET` | `/sources` | Список источников + статус |
| `GET` | `/sources/{source_id}` | Один источник |
| `GET` | `/datasets` | Какие датасеты есть на диске |
| `GET` | `/datasets/{source_id}` | **Данные** (JSON) |
| `POST` | `/admin/refresh?source_id=...` | Принудительный парсинг (`X-API-Key`) |
| `PUT` | `/admin/datasets/{source_id}` | Загрузить свой JSON (`X-API-Key`) |

### Формат ответа датасета

```json
{
  "state": "ok",
  "fetched_at": "2026-06-01T16:00:00+00:00",
  "http_status": 200,
  "final_url": "https://...",
  "content_length": 303232,
  "backend": "patchright",
  "data": {
    "source_id": "hsreplay_decks_trending",
    "title": "...",
    "tables": [{ "headers": [], "rows": [], "objects": [] }],
    "json_scripts": [{ "id": "userdata", "value": {} }],
    "hsreplay_bootstrap": {},
    "deck_codes": ["AAE..."],
    "links": [{ "text": "...", "href": "..." }],
    "text_preview": ["..."],
    "counts": { "tables": 1, "deck_codes": 20, "text_lines": 300 }
  }
}
```

**Как читать данные:**

| Поле | Когда использовать |
|------|-------------------|
| `data.tables[].objects` | Таблицы HSGuru (meta, streamer decks) |
| `data.deck_codes` | Коды колод (`AAE...`, `AAEC...`) |
| `data.json_scripts` | Встроенный JSON со страницы HSReplay |
| `data.hsreplay_bootstrap` | Блок `userdata` с HSReplay (если есть) |
| `data.text_preview` | Текст страницы (тир-листы, подписи) |
| `data.links` | Ссылки на колоды/карты |

---

## Справочник: `source_id` → сценарий

### HSGuru — конструкт (Standard / Wild)

| Сценарий | `source_id` | Страница |
|----------|-------------|----------|
| Мета Standard, Legend | `hsguru_meta_standard_legend` | [meta format=2 legend](https://www.hsguru.com/meta?format=2&rank=legend) |
| Мета Standard, Diamond 4–1 | `hsguru_meta_standard_diamond_4to1` | [meta format=2 diamond](https://www.hsguru.com/meta?format=2&rank=diamond_4to1) |
| Мета Wild, Legend | `hsguru_meta_wild_legend` | [meta format=1 legend](https://www.hsguru.com/meta?format=1&rank=legend) |
| Мета Wild, Diamond 4–1 | `hsguru_meta_wild_diamond_4to1` | [meta format=1 diamond](https://www.hsguru.com/meta?format=1&rank=diamond_4to1) |

```bash
curl -s "http://localhost:8000/datasets/hsguru_meta_standard_legend" | jq '.data.tables[0].objects[:5]'
```

Пример строки meta: `Archetype`, `Winrate↓`, `Popularity`, `Turns`, `Duration`, `Climbing Speed`.

---

### HSGuru — матчапы

| Сценарий | `source_id` |
|----------|-------------|
| Матрица матчапов, Legend | `hsguru_matchups_legend` |
| Матрица матчапов, Diamond 4–1 | `hsguru_matchups_diamond_4to1` |

```bash
curl -s "http://localhost:8000/datasets/hsguru_matchups_legend" | jq '.data.tables[0].objects[0:3]'
```

---

### HSGuru — колоды стримеров

| Сценарий | `source_id` |
|----------|-------------|
| Streamer decks, top legend | `hsguru_streamer_decks_legend_1000` |

```bash
curl -s "http://localhost:8000/datasets/hsguru_streamer_decks_legend_1000" \
  | jq '{codes: .data.deck_codes[0:3], decks: .data.tables[0].objects[0:2]}'
```

Поля таблицы: `Deck`, `Streamer`, `Format`, `Peak`, `Win - Loss`, `Links`.

---

### HSReplay — Арена

| Сценарий | `source_id` | Что на странице |
|----------|-------------|-----------------|
| **Обзор арены, тир-лист классов (2-class / dual class)** | `hsreplay_arena` | [Arena Guide](https://hsreplay.net/arena/) — таблица матчапов классов |
| **Тир-лист карт арены (advanced)** | `hsreplay_arena_cards_advanced` | [Arena cards #advanced](https://hsreplay.net/arena/cards/#view=advanced) |
| **Винрейт легендарок в арене** | `hsreplay_arena_legendaries` | [Arena legendaries](https://hsreplay.net/arena/legendaries/) |
| **Виновые колоды арены (12-win и др.)** | `hsreplay_arena_winning_decks` | [Winning decks](https://hsreplay.net/arena/winning_decks/#playerClass=ALL) |

#### Двухклассовый тир / матрица классов на арене

```bash
# Таблица классов (строки = класс, ячейки = винрейт vs другой класс)
curl -s "http://localhost:8000/datasets/hsreplay_arena" \
  | jq '.data.tables[0].objects[0:5]'
```

#### Тир-лист карт арены

```bash
curl -s "http://localhost:8000/datasets/hsreplay_arena_cards_advanced" \
  | jq '.data | {title, lines: [.text_preview[] | select(test("Tier|Winrate|Pick";"i"))][0:20]}'
```

#### Колоды для арены (победные листы)

```bash
curl -s "http://localhost:8000/datasets/hsreplay_arena_winning_decks" \
  | jq '{title: .data.title, deck_links: [.data.links[] | select(.href | test("deck";"i"))][0:10]}'
```

#### Легендарки арены

```bash
curl -s "http://localhost:8000/datasets/hsreplay_arena_legendaries" \
  | jq '.data.counts'
```

---

### HSReplay — Ранкед / конструкт

| Сценарий | `source_id` |
|----------|-------------|
| Трендовые колоды | `hsreplay_decks_trending` |
| Карты Legend по **included winrate** | `hsreplay_cards_legend_included_winrate` |
| Карты Legend по **included popularity** | `hsreplay_cards_legend_included_popularity` |

```bash
# Трендовые колоды
curl -s "http://localhost:8000/datasets/hsreplay_decks_trending" \
  | jq '[.data.links[] | select(.text != "")][0:15]'

# Топ карт по винрейту (фильтр на странице: rankRange=LEGEND, sortBy=includedWinrate)
curl -s "http://localhost:8000/datasets/hsreplay_cards_legend_included_winrate" \
  | jq '.data.text_preview[0:30]'
```

---

### HSReplay — Поля боя (Battlegrounds)

| Сценарий | `source_id` |
|----------|-------------|
| Композиции / билды | `hsreplay_battlegrounds_comps` |
| Герои (тир-лист) | `hsreplay_battlegrounds_heroes` |
| Малые тринкеты | `hsreplay_battlegrounds_trinkets_lesser` |
| Большие тринкеты | `hsreplay_battlegrounds_trinkets_greater` |

```bash
# Герои BG
curl -s "http://localhost:8000/datasets/hsreplay_battlegrounds_heroes" \
  | jq '[.data.text_preview[] | select(test("Top|%|Hero";"i"))][0:25]'

# Компы
curl -s "http://localhost:8000/datasets/hsreplay_battlegrounds_comps" \
  | jq '.data.text_preview[0:40]'
```

---

## Фильтрация списка источников

```bash
# Только арена
curl -s "http://localhost:8000/sources?site=hsreplay&category=arena"

# Только HSGuru meta
curl -s "http://localhost:8000/sources?site=hsguru&category=meta"
```

---

## Обновление данных

```bash
# Всё (долго, ~30–60 мин)
python -m app.cli refresh --all

# Один источник
python -m app.cli refresh --source hsreplay_arena

# Через API
curl -X POST "http://localhost:8000/admin/refresh?source_id=hsreplay_arena" \
  -H "X-API-Key: YOUR_KEY"
```

Проверка прокси:

```bash
python -m app.cli proxy-check
```

---

## Переменные окружения

См. [.env.example](.env.example).

| Переменная | Назначение |
|------------|------------|
| `HS_FETCH_PROXY_URL` | HTTP/SOCKS5 прокси (обязателен для парсинга) |
| `HS_API_KEY` | Ключ для `/admin/*` |
| `HS_FETCH_BACKENDS` | Порядок: `flaresolverr,patchright,...` |
| `HS_API_REQUEST_DELAY_SECONDS` | Пауза между URL (рекомендуется 8+) |

---

## Деплой (systemd)

```bash
sudo cp systemd/hs-data-api.service /etc/systemd/system/
sudo cp systemd/hs-data-api-refresh.* /etc/systemd/system/
sudo cp systemd/hs-flaresolverr.service /etc/systemd/system/
sudo cp .env.example /etc/hs-data-api.env   # и отредактировать

sudo systemctl enable --now hs-data-api hs-flaresolverr hs-data-api-refresh.timer
```

---

## Ограничения

- HSReplay — SPA: часть данных в `text_preview` / `userdata`, не всегда в HTML-таблицах.
- HSGuru — надёжнее через **FlareSolverr**; HSReplay — через **patchright**.
- Нужен **резидентский прокси**; без него Cloudflare блокирует запросы.
- Не коммитьте `/etc/hs-data-api.env` с паролями — только `.env.example`.

---

## Лицензия

MIT — данные принадлежат HSGuru / HSReplay; используйте в соответствии с их ToS.
