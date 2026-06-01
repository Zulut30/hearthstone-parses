# Hearthstone Parses & Data API

Кэширующий парсер и REST API для публичных страниц ведущих Hearthstone-порталов:
* **NEW! Vicious Syndicate** (Data Reaper's Radars — интерактивные графы синергий карт)
* **NEW! MetaStats** (Архетипы и колоды по 11 классам, матрица матчапов)
* **NEW! Hearthstone-Decks.net** (Топ легенды Standard/Wild с дедупликацией и слиянием)
* **Firestone** (Поля Боя: герои, композиции, существа и заклинания по тавернам)
* **HSGuru** (Мета, матчапы и колоды стримеров Standard/Wild/Legend/Diamond)
* **HSReplay** (Трендовые колоды, тир-листы карт, Арена — классы, карты, легендарки)

Обходит защиту Cloudflare через резидентский прокси-сервер и ротацию бэкендов (FlareSolverr, patchright, cloudscraper, curl-impersonate).

Репозиторий: [github.com/Zulut30/hearthstone-parses](https://github.com/Zulut30/hearthstone-parses)

---

## Быстрый старт

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
patchright install chromium

cp .env.example /etc/hs-data-api.env   # или export переменные окружения
# Заполните HS_FETCH_PROXY_URL и HS_API_KEY

docker compose up -d   # Запуск FlareSolverr (опционально, для HSGuru)

python -m app.cli proxy-check
python -m app.cli refresh --all
uvicorn app.server:app --host 0.0.0.0 --port 8000
```

Автоматический сбор данных раз в сутки по таймеру: `systemd/hs-data-api-refresh.timer`.

**Установка на новый сервер и перенос кэша:** см. [DEPLOY.md](DEPLOY.md) и `scripts/install.sh`, `scripts/export-bundle.sh`, `scripts/import-bundle.sh`, `scripts/audit.sh`.

**Безопасность и устройство парсинга (подробно):** [docs/SECURITY_AND_PARSING.md](docs/SECURITY_AND_PARSING.md)  
**Ротация IP и надёжность:** [docs/PROXY_AND_RELIABILITY.md](docs/PROXY_AND_RELIABILITY.md)

---

## Базовый URL REST API

Все эндпоинты API и демонстрационный веб-интерфейс теперь доступны публично на выделенном поддомене:
```
https://api.hs-manacost.ru
```

---

## 1. Справочник системных Endpoint'ов

Все системные эндпоинты возвращают ответы в формате `application/json`.

### 1.1 Получить состояние здоровья кэша всех источников
* **Эндпоинт:** `GET /health`
* **Доступ:** Публичный
* **Описание:** Возвращает информацию о том, какие источники успешно кэшированы, какие пустые, и общее здоровье API.
* **Пример ответа:**
```json
{
  "status": "ok",
  "ok_count": 18,
  "total_count": 21,
  "empty_sources": [
    "firestone_arena_cards_normal",
    "firestone_arena_cards_underground"
  ]
}
```

### 1.2 Получить список источников данных
* **Эндпоинт:** `GET /sources`
* **Доступ:** Публичный
* **Параметры запроса (Query parameters):**
  * `site` (string, опционально) — фильтр по сайту (например, `hsreplay`, `hsguru`, `metastats`, `vicious-syndicate`, `hearthstone-decks`, `firestone`)
  * `category` (string, опционально) — фильтр по категории (например, `meta`, `arena`, `ranked`, `matchups`, `battlegrounds`)
* **Описание:** Возвращает массив поддерживаемых источников, их URL на целевых сайтах и текущий статус кэширования на сервере.
* **Пример запроса:** `/sources?site=metastats`
* **Пример ответа:**
```json
[
  {
    "id": "metastats_decks",
    "site": "metastats",
    "category": "ranked",
    "url": "https://metastats.net/hearthstone/class/decks/DeathKnight/",
    "fetch_url": "https://metastats.net/hearthstone/class/decks/DeathKnight/",
    "fragment": "",
    "description": "MetaStats archetypes and decks for all classes.",
    "status": {
      "state": "ok",
      "fetched_at": "2026-06-01T20:41:15.123+00:00",
      "http_status": 200,
      "backend": "metastats_api"
    },
    "has_dataset": true,
    "dataset_fetched_at": "2026-06-01T20:41:15.123+00:00"
  }
]
```

### 1.3 Получить информацию об одном источнике
* **Эндпоинт:** `GET /sources/{source_id}`
* **Доступ:** Публичный
* **Пример ответа:** `/sources/vicious_syndicate_radars`

### 1.4 Получить список сохраненных на сервере датасетов
* **Эндпоинт:** `GET /datasets`
* **Доступ:** Публичный
* **Описание:** Возвращает список ID источников, для которых на диске физически присутствует кэшированный файл JSON.

### 1.5 Получить структурированные данные датасета (Основной метод получения данных)
* **Эндпоинт:** `GET /datasets/{source_id}`
* **Доступ:** Публичный
* **Описание:** Возвращает метаданные сбора и сам спарсенный контент, упакованный в объект `data`.
* **Схема ответа верхнего уровня:**
```json
{
  "state": "ok",
  "fetched_at": "ISO-8601 Timestamp",
  "http_status": 200,
  "final_url": "https://...",
  "content_length": 123456,
  "backend": "patchright | metastats_api | vicious_syndicate_api | ...",
  "proxy_egress_ip": "IP-адрес прокси, через который выполнялся запрос",
  "data": {
    "source_id": "vicious_syndicate_radars",
    "title": "Заголовок страницы",
    "structured": {
      "type": "Тип структуры (vicious_syndicate_radars, metastats_decks и др.)",
      "..." : "Поля, специфичные для каждого источника (см. Раздел 2)"
    },
    "counts": {
      "api_bytes": 0,
      "text_lines": 0
    }
  }
}
```

### 1.6 Принудительно запустить парсинг источника в фоне
* **Эндпоинт:** `POST /admin/refresh`
* **Доступ:** Требует заголовок `X-API-Key: {YOUR_API_KEY}`
* **Параметры запроса (Query parameters):**
  * `source_id` (string, обязательно) — ID источника для обновления.
* **Описание:** Запускает асинхронный процесс сбора данных с целевого сайта. Сразу возвращает статус инициализации.
* **Пример ответа:**
```json
{
  "source_id": "vicious_syndicate_radars",
  "status": "started"
}
```

### 1.7 Загрузить свой JSON в кэш датасета
* **Эндпоинт:** `PUT /admin/datasets/{source_id}`
* **Доступ:** Требует заголовок `X-API-Key: {YOUR_API_KEY}`
* **Тело запроса:** JSON-документ
* **Описание:** Позволяет вручную перезаписать кэшированный датасет на сервере (полезно для интеграции сторонних выгрузок или исправления битых данных).

---

## 2. Подробное описание источников данных и JSON-схем

Для каждого источника, запрашиваемого через `/datasets/{source_id}`, блок `data.structured` содержит строго типизированные, очищенные и готовые к рендерингу данные.

---

### 2.1 Vicious Syndicate: Радары связей карт (`vicious_syndicate_radars`)
* **ID источника:** `vicious_syndicate_radars`
* **Целевой URL:** `https://www.vicioussyndicate.com/deck-library/death-knight-decks/` (и все остальные классовые разделы)
* **Бэкэнд сбора:** `vicious_syndicate_api` (асинхронный сбор в параллельном режиме с автоматическим обнаружением и парсингом как общих радаров классов, так и специфичных радаров для отдельных архетипов)
* **Описание:** Парсит интерактивные физические радары синергий карт Vicious Syndicate для всех классов и архетипов Hearthstone, а также **извлекает прямые коды колод** для этих архетипов с их страниц деталей. Извлекает координаты, радиусы популярности и веса связей (совместную встречаемость) для построения динамических графов на Canvas.

#### Спецификация JSON-ответа `data.structured`:
```json
{
  "type": "vicious_syndicate_radars",
  "issue": "349",
  "classes_summary": [
    {
      "class": "Hunter",
      "has_archetypes": true,
      "archetypes": ["Companion Hunter", "Face Hunter"]
    },
    {
      "class": "Paladin",
      "has_archetypes": false,
      "archetypes": []
    }
  ],
  "total_radars": 15,
  "radars": [
    {
      "class": "Paladin",
      "archetype": null,
      "title": "Data Reaper's Radar - Issue #349 - Dude Paladin",
      "issue": "349",
      "url": "https://www.vicioussyndicate.com/deck-library/paladin-decks/dude-paladin/",
      "radar_url": "https://www.vicioussyndicate.com/wp-content/datareaper/radars/Paladin/index.html",
      "deck_code": "AAECAZ8FBMODB8avB+XBB+jFBw3JoASU9QW6lgfXlwfOmweNnQf1rwf2wQeDwgfkxQfmxQfnxQfD4wcAAA==",
      "nodes": [
        {
          "name": "Arisen Onyxia",
          "radius": 14.6,
          "strokewidth": 2.0,
          "fill": "rgba(0,102,0,0.75)",
          "stroke": "rgba(255,127,0,1.00)",
          "text": "rgba(255,255,255,1.00)"
        }
      ],
      "edges": [
        {
          "source": "Arisen Onyxia",
          "target": "Command Claw",
          "weight": 0.15,
          "length": 250.0,
          "stroke": "rgba(0,0,0,0.01)"
        }
      ]
    }
  ]
}
```

#### Ключевые поля объектов:
* `classes_summary` (array) — верхнеуровневый свод классов, упрощающий отрисовку вкладок в UI. Содержит поле `has_archetypes` (есть ли у класса субарехтипы) и список `archetypes`.
* **Элемент массива `radars`:**
  * `class` (string) — класс Hearthstone.
  * `archetype` (string | null) — название конкретного архетипа (или `null` для общего радара класса).
  * `deck_code` (string | null) — **импортируемый код колоды** Hearthstone, автоматически извлеченный со страницы подробностей данного архетипа.
  * **Узлы (Nodes):**
    * `name` (string) — локализованное (английское) название карты.
    * `radius` (float) — популярность карты (определяет диаметр круга в симуляции).
    * `fill` (string) — цвет заливки в формате `rgba`. Используется для классификации (классовые, нейтральные, заклинания).
    * `stroke` (string) — цвет границы узла.
  * **Ребра (Edges):**
    * `source` (string) — название первой карты.
    * `target` (string) — название второй карты.
    * `weight` (float) — сила связи совместной встречаемости (от $0.0$ до $1.0$). Чем выше вес, тем сильнее синергия между картами в реальных колодах.
    * `length` (float) — базовая длина физической связи-пружины (обычно `250.0`).

---

### 2.2 MetaStats: Архетипы и колоды классов (`metastats_decks`)
* **ID источника:** `metastats_decks`
* **Целевой URL:** Классовые разделы MetaStats (парсятся 11 классов параллельно в асинхронном режиме)
* **Бэкэнд сбора:** `metastats_api`
* **Описание:** Извлекает все актуальные архетипы для каждого класса, а также конкретные сборки (версии колод), их статистику игр, процент побед, код колоды и полный список входящих карт.

#### Спецификация JSON-ответа `data.structured`:
```json
{
  "type": "metastats_decks",
  "decks": [
    {
      "class": "DeathKnight",
      "archetype_id": "dk_unholy_dk",
      "archetype_name": "Unholy Death Knight",
      "deck_id": "12345",
      "title": "Unholy Death Knight #12345",
      "games": 1400,
      "win_rate": 58.4,
      "deck_code": "AAECAfHGBATp0ASY1AS42QT8+gUNkeQEkuQE0eSEkvQElfQEj6UF88gF8vgFu/kF6/8F9fcFgvgF6oAGAAA=",
      "cards": [
        {
          "name": "Body Bagger",
          "id": "RLK_037",
          "dbfId": 86105,
          "cost": 1,
          "rarity": "COMMON",
          "count": 2
        }
      ]
    }
  ]
}
```

#### Ключевые поля объектов:
* `class` (string) — класс Hearthstone (например, `Mage`, `DemonHunter`).
* `archetype_name` (string) — название архетипа (например, `Plague Death Knight`).
* `deck_id` (string) — внутренний ID колоды на MetaStats.
* `games` (int) — количество зафиксированных матчей с этой сборкой.
* `win_rate` (float) — процент побед (винрейт) колоды.
* `deck_code` (string) — стандартный импортируемый код колоды в Hearthstone.
* `cards` (array) — список карт в колоде. Каждая карта содержит `name`, `id` (строковый ID карты в HearthstoneJSON), `dbfId` (числовой ID в Hearthstone), ману (`cost`), редкость (`rarity`) и количество копий (`count`).

---

### 2.3 MetaStats: Матрица матчапов архетипов (`metastats_matchups`)
* **ID источника:** `metastats_matchups`
* **Целевой URL:** `https://metastats.net/hearthstone/archetype/matchup/`
* **Бэкэнд сбора:** `metastats_api`
* **Описание:** Парсит сводную таблицу матчапов между лидирующими архетипами на основе извлечения данных из интерактивных всплывающих окон (tooltips) ячеек таблицы.

#### Спецификация JSON-ответа `data.structured`:
```json
{
  "type": "metastats_matchups",
  "matchups": [
    {
      "archetype": "Plague Death Knight",
      "vs": "Treant Druid",
      "games": 12450,
      "winrate": 48.2,
      "vs_winrate": 51.8
    }
  ],
  "archetypes": [
    "Plague Death Knight",
    "Treant Druid",
    "Sif Mage"
  ]
}
```

---

### 2.4 Hearthstone-Decks: Топ-колоды Легенды (`hearthstone_decks`)
* **ID источника:** `hearthstone_decks`
* **Целевые URL:** Стандартный (`standard-decks/`) и Вольный (`wild-decks/`) разделы Hearthstone-Decks.net
* **Бэкэнд сбора:** `hearthstone_decks_api`
* **Описание:** Парсит посты о взятии высоких рангов Легенды. Извлекает архетип, занятый ранг, имя игрока, рекорд побед (score), дату, оригинальную ссылку и код колоды (для получения кодов парсер переходит по ссылкам внутрь постов асинхронно).
* **Слияние и дедупликация:** При каждом запуске новые посты скачиваются и объединяются со старыми. Дубликаты отсеиваются по `url`. В кэше поддерживается до 100 самых свежих колод для каждого из форматов (Standard и Wild).

#### Спецификация JSON-ответа `data.structured`:
```json
{
  "type": "hearthstone_decks",
  "total_decks": 145,
  "standard_count": 82,
  "wild_count": 63,
  "decks": [
    {
      "format": "Standard",
      "title": "Rainbow Death Knight #12 Legend – PlayerName (15-4)",
      "archetype": "Rainbow Death Knight",
      "rank": "#12 Legend",
      "player": "PlayerName",
      "score": "15-4",
      "deck_code": "AAECAfHGBBKXoATOyQS0yQT8+gX/lwbHpAa7sQa9sQb7uAb9uAbHpAavwQa7wQbHyQa6wQbXyQYB8vgFAAA=",
      "date": "2026-06-01",
      "url": "https://hearthstone-decks.net/rainbow-death-knight-12-legend-playername-15-4/"
    }
  ]
}
```

---

### 2.5 Firestone: Существа Полей Боя по тавернам (`firestone_battlegrounds_cards`)
* **ID источника:** `firestone_battlegrounds_cards`
* **Целевой URL:** Firestone API / static assets
* **Описание:** Извлекает статистику по всем существам Полей Боя (Battlegrounds), разделенным по тирам таверны. Применяет строгую валидацию по флагам `isBattlegroundsPoolMinion` из базы HearthstoneJSON, исключая неактивные или коллекционные карты стандартного режима.

#### Спецификация JSON-ответа `data.structured`:
```json
{
  "type": "bg_card_stats",
  "tiers": {
    "1": [
      {
        "id": "BG21_001",
        "name": "Puppy",
        "dbfId": 74321,
        "is_spell": false,
        "games": 125000,
        "avg_placement": 4.12,
        "placement_without": 4.54,
        "impact": -0.42
      }
    ],
    "2": []
  }
}
```

#### Ключевые поля:
* `avg_placement` (float) — среднее итоговое место игрока при наличии этой карты в финальной армии.
* `placement_without` (float) — среднее место игрока без этой карты в армии.
* `impact` (float) — влияние карты на результат (`avg_placement - placement_without`). Отрицательное значение означает улучшение среднего места (карта полезна).

---

### 2.6 Firestone: Заклинания Полей Боя по тавернам (`firestone_battlegrounds_spells`)
* **ID источника:** `firestone_battlegrounds_spells`
* **Целевой URL:** Firestone API / static assets
* **Описание:** Аналогично существам, но собирает исключительно заклинания таверны, используя валидацию через флаг `isBattlegroundsPoolSpell`.
* **Спецификация ответа:** Идентична структуре существ (`bg_card_stats` с разбиением по тавернам от 1 до 6).

---

### 2.7 Firestone: Композиции Полей Боя (`firestone_battlegrounds_comps`)
* **ID источника:** `firestone_battlegrounds_comps`
* **Описание:** Готовые шаблоны финальных сборок армий (Мурлоки, Демоны, Звери и др.) со средней позицией, процентом топ-4 и популярностью.

---

### 2.8 HSGuru: Мета-отчет Standard/Wild (`hsguru_meta_standard_legend` и др.)
* **ID источников:**
  * `hsguru_meta_standard_legend` — Standard, Легенда
  * `hsguru_meta_standard_diamond_4to1` — Standard, Алмаз 4-1
  * `hsguru_meta_wild_legend` — Wild, Легенда
  * `hsguru_meta_wild_diamond_4to1` — Wild, Алмаз 4-1
* **Описание:** Возвращает силу архетипов, их процент побед, популярность, среднее количество ходов и скорость подъема.

#### Формат ответа в таблицах:
```json
{
  "data": {
    "tables": [
      {
        "headers": ["Archetype", "Winrate", "Popularity", "Turns", "Duration"],
        "objects": [
          {
            "Archetype": "Sludge Warlock",
            "Winrate": "54.8%",
            "Popularity": "8.4%",
            "Turns": "7.2",
            "Duration": "6.1 min"
          }
        ]
      }
    ]
  }
}
```

---

### 2.9 HSReplay: Тир-лист карт Арены (`hsreplay_arena_cards_advanced`)
* **ID источника:** `hsreplay_arena_cards_advanced`
* **Описание:** Автоматически забирает JSON с тир-листом карт Арены.

#### Спецификация JSON-ответа `data.structured`:
```json
{
  "type": "arena_card_stats",
  "total_cards": 482,
  "cards": [
    {
      "name": "Goliath, Sneed's Masterpiece",
      "id": "DED_002",
      "dbfId": 69702,
      "cost": 8,
      "rarity": "LEGENDARY",
      "deck_winrate": 62.4,
      "played_winrate": 64.1,
      "deck_popularity": 4.5,
      "avg_copies": 1.05,
      "times_played": 12400,
      "tier": "S"
    }
  ]
}
```

#### Поле `tier` (Категория силы):
Высчитывается скриптом нормализации на основе `deck_winrate`:
* **S** — $\ge 59\%$
* **A** — $56\%$ – $58.9\%$
* **B** — $53\%$ – $55.9\%$
* **C** — $50\%$ – $52.9\%$
* **D** — $47\%$ – $49.9\%$
* **F** — $< 47\%$

---

## 3. Практическое руководство по получению данных (Примеры запросов)

Ниже приведены готовые примеры запросов через `curl` и `HTTP` для получения ключевых наборов данных, таких как матч-апы, колоды и радары.

### 3.1 Как получить матрицу матч-апов (MetaStats)
* **Запрос:** `GET https://api.hs-manacost.ru/datasets/metastats_matchups`
* **Команда curl:**
  ```bash
  curl -s "https://api.hs-manacost.ru/datasets/metastats_matchups" | jq '.data.structured'
  ```
* **Пример структуры ответа:**
  ```json
  {
    "type": "metastats_matchups",
    "matchups": [
      {
        "archetype": "Plague Death Knight",
        "vs": "Treant Druid",
        "games": 12450,
        "winrate": 48.2,
        "vs_winrate": 51.8
      }
    ],
    "archetypes": [
      "Plague Death Knight",
      "Treant Druid",
      "Sif Mage"
    ]
  }
  ```

### 3.2 Как получить архетипы и версии колод (MetaStats)
* **Запрос:** `GET https://api.hs-manacost.ru/datasets/metastats_decks`
* **Команда curl:**
  ```bash
  curl -s "https://api.hs-manacost.ru/datasets/metastats_decks" | jq '.data.structured.decks[0:2]'
  ```
* **Пример структуры ответа:**
  ```json
  [
    {
      "class": "DeathKnight",
      "archetype_id": "dk_unholy_dk",
      "archetype_name": "Unholy Death Knight",
      "deck_id": "12345",
      "title": "Unholy Death Knight #12345",
      "games": 1400,
      "win_rate": 58.4,
      "deck_code": "AAECAfHGBATp0ASY1AS42QT8+gUNkeQEkuQE0eSEkvQElfQEj6UF88gF8vgFu/kF6/8F9fcFgvgF6oAGAAA=",
      "cards": [
        {
          "name": "Body Bagger",
          "id": "RLK_037",
          "dbfId": 86105,
          "cost": 1,
          "rarity": "COMMON",
          "count": 2
        }
      ]
    }
  ]
  ```

### 3.3 Как получить интерактивный радар популярности и связей карт (Vicious Syndicate)
* **Запрос:** `GET https://api.hs-manacost.ru/datasets/vicious_syndicate_radars`
* **Команда curl:**
  ```bash
  # Получить радар для DeathKnight (первый в массиве)
  curl -s "https://api.hs-manacost.ru/datasets/vicious_syndicate_radars" | jq '.data.structured.radars[0]'
  ```
* **Пример структуры ответа:**
  ```json
  {
    "class": "DeathKnight",
    "title": "Data Reaper's Radar - Issue #349 - DeathKnight",
    "issue": "349",
    "url": "https://www.vicioussyndicate.com/wp-content/datareaper/radars/DeathKnight/index.html",
    "nodes": [
      {
        "name": "Arisen Onyxia",
        "radius": 14.6,
        "strokewidth": 2,
        "fill": "rgba(0,102,0,0.75)",
        "stroke": "rgba(255,127,0,1.00)",
        "text": "rgba(255,255,255,1.00)"
      }
    ],
    "edges": [
      {
        "source": "Arisen Onyxia",
        "target": "Command Claw",
        "weight": 0.15,
        "length": 250,
        "stroke": "rgba(0,0,0,0.01)"
      }
    ]
  }
  ```

### 3.4 Как получить топ-колоды Легенды с Hearthstone-Decks.net
* **Запрос:** `GET https://api.hs-manacost.ru/datasets/hearthstone_decks`
* **Команда curl:**
  ```bash
  # Показать последние 5 колод Standard формата
  curl -s "https://api.hs-manacost.ru/datasets/hearthstone_decks" | jq '[.data.structured.decks[] | select(.format == "Standard")][0:5]'
  ```

### 3.5 Как получить существ Полей Боя по тавернам (Firestone)
* **Запрос:** `GET https://api.hs-manacost.ru/datasets/firestone_battlegrounds_cards`
* **Команда curl:**
  ```bash
  # Получить список существ 1-го тира
  curl -s "https://api.hs-manacost.ru/datasets/firestone_battlegrounds_cards" | jq '.data.structured.tiers["1"] | .[0:3]'
  ```

---

## 4. Политика дедупликации, слияния и надежности сбора

Для обеспечения отказоустойчивости парсеров применены следующие архитектурные паттерны:

1. **Неразрушающий кэш (Graceful Fallback):**
   Если при очередном автоматическом или ручном обновлении целевой сайт выдал ошибку (Cloudflare block, HTTP 500), старый рабочий кэш на диске **не удаляется**. Сервер продолжает отдавать предыдущую успешную сборку, отправляя уведомление в Telegram.
2. **Асинхронные пулы соединений (`httpx.AsyncClient`):**
   Все тяжелые парсеры (Vicious Syndicate, MetaStats, Hearthstone-Decks) выполняют подзапросы к вложенным страницам параллельно через `asyncio.gather` с ограничением лимитов конкурентности (семафоры), чтобы не перегружать прокси-сервер.
3. **Обнаружение битых данных (Quality Assurance):**
   Перед записью датасета на диск он проходит валидацию качества (`app/scrapers/quality.py`). Например, для `hearthstone_decks` или `metastats_decks` валидатор проверяет, что количество извлеченных колод не меньше 5, а структура содержит валидные deck_codes. Если валидация провалена — обновление отклоняется.
4. **Защита от бесконечного разрастания кэша:**
   Сценарии слияния данных (такие как `hearthstone_decks`) используют строгие скользящие лимиты (хранение строго последних 100 колод на формат), чтобы размер кэша оставался в пределах нескольких сотен килобайт и отдавался клиенту за миллисекунды.

---

## 4. Использование интерфейса командной строки (CLI)

Для ручного администрирования используйте утилиту `cli.py` внутри виртуального окружения:

```bash
# Проверить внешний IP-адрес прокси-сервера
python -m app.cli proxy-check

# Обновить абсолютно все источники данных по очереди
python -m app.cli refresh --all

# Обновить только Vicious Syndicate радары
python -m app.cli refresh --source vicious_syndicate_radars

# Обновить несколько конкретных источников за раз
python -m app.cli refresh --source metastats_decks --source hearthstone_decks
```

---

## 5. Настройка Telegram-оповещений

Если сбор данных завершается сбоем или прокси-сервер перестает отвечать, система автоматически шлет уведомления.

Добавьте в `/etc/hs-data-api.env`:
```ini
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=-100123456789
```

---

## 6. Деплой в production-окружение (systemd)

Копирование файлов и управление демонами на сервере Ubuntu/Debian:

```bash
# Синхронизация кода в рабочую папку службы
cp -rv * /opt/hs-data-api/

# Перезапуск API сервера
sudo systemctl restart hs-data-api.service

# Посмотреть логи сервера в реальном времени
sudo journalctl -u hs-data-api.service -f -n 100
```
