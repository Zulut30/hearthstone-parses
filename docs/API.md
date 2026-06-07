# Hearthstone Parses API

Актуальная документация REST API для `hearthstone-parses`.

Production base URL:

```text
https://api.hs-manacost.ru
```

Локально:

```text
http://127.0.0.1:8000
```

## Auth

Публичные read-only endpoints доступны без ключа. Операционные и admin endpoints требуют:

```http
X-API-Key: <HS_API_KEY>
```

`HS_API_KEY` хранится только в `/etc/hs-data-api.env`.

## Public Endpoints

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/health` | Лёгкий liveness API. Не раскрывает список источников, пути и premium auth детали. |
| `GET` | `/sources` | Список источников с URL, категорией, статусом и наличием dataset. |
| `GET` | `/sources/{source_id}` | Метаданные одного источника. |
| `GET` | `/datasets` | Список источников и наличие сохранённого dataset. |
| `GET` | `/datasets/{source_id}` | Основной endpoint данных: статус refresh и `data.structured`. |
| `GET` | `/demo/overview` | Сводка для UI. |
| `GET` | `/demo/view/{source_id}` | Подготовленное представление одного источника для UI. |
| `GET` | `/system/technologies` | Публичная техническая карточка источников и parser stack без секретов. |
| `GET` | `/ui` | Web UI. |
| `GET` | `/ui/logs` | UI логов. |
| `GET` | `/ui/technologies` | UI страницы технологий. |
| `GET` | `/api/db/decks` | SQL-backed поиск колод. |
| `GET` | `/api/db/cards/trends` | SQL-backed история популярности карт. |

### `GET /health`

Публичный liveness endpoint. Он специально минимальный: подробные diagnostics перенесены в `/ops/health`.

```json
{
  "ok": true,
  "serving_ok": true,
  "degraded": false,
  "checked_at": "2026-06-07T21:34:41.682806+00:00"
}
```

### `GET /sources`

Query parameters:

| Parameter | Type | Описание |
| --- | --- | --- |
| `site` | string | Фильтр по сайту: `hsreplay`, `hsguru`, `firestone`, `metastats`, `vicious-syndicate`, `hearthstone-decks`, `heartharena`. |
| `category` | string | Фильтр по категории: `ranked`, `meta`, `matchups`, `arena`, `battlegrounds`, `streamer_decks`. |

Пример:

```bash
curl -s "https://api.hs-manacost.ru/sources?site=hsreplay" | jq .
```

Ответ:

```json
{
  "sources": [
    {
      "id": "hsreplay_meta_archetypes_legend_eu_1d",
      "site": "hsreplay",
      "category": "ranked",
      "url": "https://hsreplay.net/meta/#rankRange=LEGEND&tab=archetypes&region=REGION_EU&timeFrame=LAST_1_DAY&popularitySortBy=rank51",
      "fetch_url": "https://hsreplay.net/meta/",
      "fragment": "rankRange=LEGEND&tab=archetypes&region=REGION_EU&timeFrame=LAST_1_DAY&popularitySortBy=rank51",
      "description": "HSReplay meta archetypes grouped by class, Legend EU, last 1 day.",
      "status": {
        "state": "ok",
        "fetched_at": "2026-06-07T21:31:29.446191+00:00",
        "backend": "hsreplay_meta_api"
      },
      "has_dataset": true,
      "dataset_fetched_at": "2026-06-07T21:31:29.446191+00:00"
    }
  ]
}
```

### `GET /datasets/{source_id}`

Основной endpoint потребления данных. Верхний уровень содержит состояние последнего успешного refresh; данные лежат в `data.structured`.

```json
{
  "state": "ok",
  "fetched_at": "2026-06-07T21:33:28.080730+00:00",
  "http_status": 200,
  "final_url": "https://hsreplay.net/cards/#rankRange=GOLD&sortBy=includedPopularity&timeRange=LAST_14_DAYS",
  "content_length": 514780,
  "backend": "hsreplay_cards_api",
  "data": {
    "source_id": "hsreplay_cards_legend_included_popularity",
    "site": "hsreplay",
    "category": "ranked",
    "title": "HSReplay cards, Gold rank, 14 days, sorted by included popularity.",
    "structured": {
      "type": "card_stats",
      "cards": []
    },
    "schema_validation": {
      "ok": true,
      "type": "card_stats",
      "validated": true
    },
    "counts": {
      "tables": 0,
      "json_scripts": 0,
      "deck_codes": 0,
      "links": 0,
      "text_lines": 0,
      "api_bytes": 514780
    }
  }
}
```

Если live refresh упал, но старый cache рабочий, endpoint может продолжать отдавать старый dataset. В status тогда появляются `serving_cached_dataset`, `last_refresh_state`, `last_refresh_error`.

## Admin And Ops Endpoints

Все endpoints из этого раздела требуют `X-API-Key`.

| Method | Path | Назначение |
| --- | --- | --- |
| `POST` | `/admin/refresh` | Запустить refresh одного или нескольких источников. |
| `PUT` | `/admin/datasets/{source_id}` | Ручная загрузка JSON dataset в cache. |
| `GET` | `/ops/health` | Подробное состояние источников: states, stale, cached, data dir. |
| `GET` | `/health/premium` | Проверка локального premium auth состояния. |
| `GET` | `/health/premium?live=true` | Live-probe HSReplay/VS premium endpoints. |
| `GET` | `/ops/summary` | Сводка событий refresh за период. |
| `GET` | `/ops/events` | Журнал событий refresh с фильтрами. |
| `GET` | `/ops/trace/{trace_id}` | Timeline одного source trace. |
| `GET` | `/ops/run/{run_id}` | Timeline одного refresh run. |

### `POST /admin/refresh`

Запустить refresh всех источников:

```bash
curl -s -X POST \
  -H "X-API-Key: ${HS_API_KEY}" \
  "https://api.hs-manacost.ru/admin/refresh" | jq .
```

Запустить один или несколько источников:

```bash
curl -s -X POST \
  -H "X-API-Key: ${HS_API_KEY}" \
  "https://api.hs-manacost.ru/admin/refresh?source_id=hsreplay_meta_archetypes_legend_eu_1d&source_id=vicious_syndicate_live_beta" | jq .
```

### `GET /ops/health`

Подробная диагностика cache/refresh. В отличие от `/health`, endpoint закрыт admin key.

```json
{
  "ok": true,
  "serving_ok": true,
  "freshness_ok": true,
  "degraded": false,
  "data_dir": "/var/lib/hs-data-api",
  "sources": 40,
  "states": {
    "ok": 40
  },
  "hard_failed_sources": [],
  "cached_sources": [],
  "stale_sources": [],
  "stale_count": 0,
  "cached_count": 0
}
```

### `GET /health/premium`

Локальная проверка premium auth без сетевого live-probe.

```bash
curl -s -H "X-API-Key: ${HS_API_KEY}" \
  "https://api.hs-manacost.ru/health/premium" | jq .
```

Live probe:

```bash
curl -s -H "X-API-Key: ${HS_API_KEY}" \
  "https://api.hs-manacost.ru/health/premium?live=true" | jq .
```

Проверяет:

- HSReplay saved session и premium-readable endpoint.
- Vicious Syndicate premium Firebase data availability.

Ответ не возвращает cookie values, токены, session id и Firebase auth token.

### `GET /ops/summary`

Query parameters:

| Parameter | Type | Default | Описание |
| --- | --- | --- | --- |
| `since_hours` | float | `24.0` | Окно анализа от `1` до `168` часов. |

Пример:

```bash
curl -s -H "X-API-Key: ${HS_API_KEY}" \
  "https://api.hs-manacost.ru/ops/summary?since_hours=48" | jq .
```

### `GET /ops/events`

Query parameters:

| Parameter | Type | Описание |
| --- | --- | --- |
| `limit` | int | 1-2000 events. |
| `source_id` | string | Фильтр по source id. |
| `event` | string | Фильтр по типу event. |
| `action` | string | Фильтр по action. |
| `action_group` | string | Фильтр по группе action. |
| `level` | string | `info`, `warn`, `error`. |
| `trace_id` | string | Фильтр по trace. |
| `run_id` | string | Фильтр по refresh run. |
| `since_hours` | float | Окно анализа. |

Пример:

```bash
curl -s -H "X-API-Key: ${HS_API_KEY}" \
  "https://api.hs-manacost.ru/ops/events?since_hours=48&level=error&limit=20" | jq .
```

## SQL-backed Endpoints

### `GET /api/db/decks`

Query parameters:

| Parameter | Type | Описание |
| --- | --- | --- |
| `class_name` | string | Фильтр по классу. |
| `format_name` | string | `Standard`, `Wild`, etc. |
| `source_id` | string | Фильтр по источнику. |
| `min_win_rate` | float | Минимальный win rate. |
| `q` | string | Поиск по title/archetype/deck_code. |
| `limit` | int | По умолчанию 50. |
| `offset` | int | Offset pagination. |

### `GET /api/db/cards/trends`

Query parameters:

| Parameter | Type | Required | Описание |
| --- | --- | --- | --- |
| `card_name` | string | yes | Название карты. |
| `source_id` | string | no | Фильтр по source id. |
| `class_name` | string | no | Фильтр по классу. |
| `limit` | int | no | По умолчанию 100. |

## Source IDs

### HSGuru

- `hsguru_streamer_decks_legend_1000`
- `hsguru_meta_standard_legend`
- `hsguru_meta_standard_diamond_4to1`
- `hsguru_meta_standard_top_5k`
- `hsguru_meta_standard_top_legend`
- `hsguru_meta_wild_legend`
- `hsguru_meta_wild_diamond_4to1`
- `hsguru_meta_wild_top_legend`
- `hsguru_meta_wild_top_5k`
- `hsguru_matchups_legend`
- `hsguru_matchups_diamond_4to1`

### HSReplay

- `hsreplay_battlegrounds_comps`
- `hsreplay_battlegrounds_heroes`
- `hsreplay_battlegrounds_minions`
- `hsreplay_battlegrounds_compositions`
- `hsreplay_battlegrounds_trinkets_lesser`
- `hsreplay_battlegrounds_trinkets_greater`
- `hsreplay_arena`
- `hsreplay_arena_legendaries`
- `hsreplay_arena_winning_decks`
- `hsreplay_arena_cards_advanced`
- `hsreplay_decks_trending`
- `hsreplay_cards_legend_included_winrate`
- `hsreplay_cards_legend_included_popularity`
- `hsreplay_cards_legend_1d`
- `hsreplay_cards_wild_legend_1d`
- `hsreplay_meta_archetypes_legend_eu_1d`

### Firestone

- `firestone_battlegrounds_comps`
- `firestone_battlegrounds_cards`
- `firestone_battlegrounds_spells`
- `firestone_arena_cards_normal`
- `firestone_arena_cards_underground`
- `firestone_arena_legendaries_underground`
- `firestone_arena_legendaries_normal`

### Other Sources

- `heartharena_tierlist`
- `metastats_decks`
- `metastats_matchups`
- `hearthstone_decks`
- `vicious_syndicate_radars`
- `vicious_syndicate_live_beta`

## Structured Data Types

`data.structured.type` определяет схему payload.

| Type | Основные поля | Источники |
| --- | --- | --- |
| `card_stats` | `cards[]` with `id`, `dbfId`, `deck_popularity`, `copies`, `deck_winrate`, `games_played`, `wins_when_played`, `kept`, `winrate_when_drawn`, `avg_turns_in_hand`, `avg_turn_played_on` | HSReplay cards |
| `arena_card_tiers` | `cards[]`, `by_class`, `total_cards`, `primary_class` | HSReplay Arena advanced |
| `bg_heroes` | `heroes[]` with `hero`, `dbfId`, `pick_rate`, `best_comp`, `avg_placement`, `tier`, `placement_distribution` | HSReplay BG heroes |
| `bg_minions` | `minions[]` with `minion`, `minion_dbf_id`, `impact`, `win_share`, `popularity` | HSReplay BG minions |
| `bg_compositions` | `compositions[]` with `type`, `first_place`, `avg_placement`, `popularity`, `placement_distribution` | HSReplay BG compositions |
| `hsreplay_meta_archetypes` | `classes[]` grouped by class, each with `archetypes[]` | HSReplay meta archetypes |
| `vicious_live` | `class_distribution`, `deck_distribution`, `tier_list` | VS Data Reaper Live |
| `vicious_syndicate_radars` | `classes_summary`, `radars[]`, `nodes[]`, `edges[]` | VS radars |
| `metastats_decks` | `decks[]` with archetype/deck/card details | MetaStats decks |
| `metastats_matchups` | `matchups[]`, `archetypes[]` | MetaStats matchups |
| `hearthstone_decks` | `decks[]`, `standard_count`, `wild_count` | Hearthstone-Decks |
| `bg_card_stats` | `tiers` keyed by tavern tier | Firestone BG cards/spells |

Structured datasets created by API-first parsers include:

```json
{
  "schema_validation": {
    "ok": true,
    "type": "card_stats",
    "validated": true
  }
}
```

If a legacy/generic dataset has no registered schema, `validated` can be `false` with `reason: "no schema registered"`.

## Examples

HSReplay cards, Legend, last 1 day:

```bash
curl -s "https://api.hs-manacost.ru/datasets/hsreplay_cards_legend_1d" \
  | jq '.data.structured.cards[0:5]'
```

HSReplay Wild cards, Legend, last 1 day:

```bash
curl -s "https://api.hs-manacost.ru/datasets/hsreplay_cards_wild_legend_1d" \
  | jq '.data.structured.cards[0:5]'
```

HSReplay meta archetypes grouped by class:

```bash
curl -s "https://api.hs-manacost.ru/datasets/hsreplay_meta_archetypes_legend_eu_1d" \
  | jq '.data.structured.classes[] | {class, winrate, popularity, games, archetypes: .archetypes[0:3]}'
```

HSReplay Battlegrounds heroes:

```bash
curl -s "https://api.hs-manacost.ru/datasets/hsreplay_battlegrounds_heroes" \
  | jq '.data.structured.heroes[0:5]'
```

Vicious Syndicate Live tier list:

```bash
curl -s "https://api.hs-manacost.ru/datasets/vicious_syndicate_live_beta" \
  | jq '.data.structured.tier_list'
```

Detailed source diagnostics:

```bash
curl -s -H "X-API-Key: ${HS_API_KEY}" \
  "https://api.hs-manacost.ru/ops/health" | jq .
```

Premium auth live probe:

```bash
curl -s -H "X-API-Key: ${HS_API_KEY}" \
  "https://api.hs-manacost.ru/health/premium?live=true" | jq .
```
