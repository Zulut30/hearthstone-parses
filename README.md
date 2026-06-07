# Hearthstone Parses & Data API

Кэширующий парсер и REST API для Hearthstone-источников: HSReplay, HSGuru, Firestone, MetaStats, Hearthstone-Decks, HearthArena и Vicious Syndicate.

Production API:

```text
https://api.hs-manacost.ru
```

Репозиторий:

```text
https://github.com/Zulut30/hearthstone-parses
```

## Что собирает

- **HSReplay**: ranked card stats, Wild/Standard Legend 1 day, Arena cards, Battlegrounds heroes/minions/compositions/trinkets, meta archetypes grouped by class.
- **Vicious Syndicate**: Data Reaper Live class/deck distribution and power tier list, radar graphs.
- **HSGuru**: meta, matchups, streamer decks.
- **Firestone**: Battlegrounds cards/spells/compositions and Arena card stats.
- **MetaStats**: archetypes, decks, matchups.
- **Hearthstone-Decks**: Standard/Wild Legend deck posts with deck codes.
- **HearthArena**: Arena tier list.

## Документация

- [REST API](docs/API.md) — endpoints, auth, source IDs, response schemas and examples.
- [Deploy](DEPLOY.md) — установка, перенос, systemd и runtime checks.
- [Security and Parsing](docs/SECURITY_AND_PARSING.md) — секреты, proxy, premium auth, reliability.
- [Parser Improvement Plan](docs/PARSER_IMPROVEMENT_PLAN.md) — roadmap улучшения стабильности.

## Быстрый старт

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
patchright install chromium

cp .env.example /etc/hs-data-api.env
# Заполните HS_API_KEY, HS_FETCH_PROXY_URL и другие нужные параметры.

python -m app.cli proxy-check
python -m app.cli refresh --all
uvicorn app.server:app --host 0.0.0.0 --port 8000
```

На production-сервере используйте `scripts/install.sh` и systemd units из `systemd/`.

## Основные API endpoints

Public:

- `GET /health` — лёгкий liveness.
- `GET /sources` and `GET /sources/{source_id}` — source registry and statuses.
- `GET /datasets` and `GET /datasets/{source_id}` — cached parser output.
- `GET /demo/overview`, `GET /demo/view/{source_id}` — prepared UI payloads.
- `GET /system/technologies` — public parser/source technology overview.
- `GET /ui`, `/ui/logs`, `/ui/technologies` — web UI pages.

Admin/ops, requires `X-API-Key`:

- `POST /admin/refresh`
- `PUT /admin/datasets/{source_id}`
- `GET /ops/health`
- `GET /ops/summary`
- `GET /ops/events`
- `GET /ops/trace/{trace_id}`
- `GET /ops/run/{run_id}`
- `GET /health/premium`

Подробнее: [docs/API.md](docs/API.md).

## Примеры

```bash
curl -s "https://api.hs-manacost.ru/health" | jq .

curl -s "https://api.hs-manacost.ru/sources?site=hsreplay" | jq .

curl -s "https://api.hs-manacost.ru/datasets/hsreplay_meta_archetypes_legend_eu_1d" \
  | jq '.data.structured.classes[0]'

curl -s -H "X-API-Key: ${HS_API_KEY}" \
  "https://api.hs-manacost.ru/ops/health" | jq .
```

## Надёжность

Парсер использует:

- tiered refresh orchestration: `light_api`, `medium_api`, `browser_patchright`, `browser_protected`;
- API-first parsers там, где возможно;
- residential proxy and backend rotation;
- quality gates and dataset regression checks;
- structured schema validation for typed API-first datasets;
- contract fixtures for real upstream payload shapes;
- stale cache preservation when live refresh fails;
- admin-only ops logs, premium auth health and refresh timelines.

## CLI

```bash
python -m app.cli proxy-check
python -m app.cli preflight
python -m app.cli refresh --all
python -m app.cli refresh --source hsreplay_cards_legend_1d
python -m app.cli hsreplay-login
```

## Production Checks

```bash
curl -s "http://127.0.0.1:8000/health" | jq .

curl -s -H "X-API-Key: ${HS_API_KEY}" \
  "http://127.0.0.1:8000/ops/health" | jq .

curl -s -H "X-API-Key: ${HS_API_KEY}" \
  "http://127.0.0.1:8000/health/premium?live=true" | jq .
```

## License

MIT
