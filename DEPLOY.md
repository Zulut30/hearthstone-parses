# Развёртывание и перенос на другой сервер

Репозиторий: **https://github.com/Zulut30/hearthstone-parses**

Перед продакшеном:

- **[docs/API.md](docs/API.md)** — публичные/admin endpoints, source IDs, JSON-схемы.
- **[docs/SECURITY_AND_PARSING.md](docs/SECURITY_AND_PARSING.md)** — секреты, API, прокси, парсинг, чеклист.

## Быстрая установка с нуля

```bash
sudo git clone https://github.com/Zulut30/hearthstone-parses.git /opt/hs-data-api
cd /opt/hs-data-api
sudo ./scripts/install.sh
sudo nano /etc/hs-data-api.env   # прокси, HS_API_KEY, опционально HSReplay/Telegram
sudo /opt/hs-data-api/venv/bin/python -m app.cli proxy-check
sudo /opt/hs-data-api/venv/bin/python -m app.cli refresh --all
sudo systemctl start hs-data-api
```

Или одной командой (клонирует в `/opt/hs-data-api`):

```bash
curl -fsSL https://raw.githubusercontent.com/Zulut30/hearthstone-parses/main/scripts/install.sh | sudo bash
```

> Для `curl | bash` сначала убедитесь, что в `main` на GitHub актуальная версия скриптов.

## Перенос с текущего сервера (с сохранением кэша)

**На старом сервере:**

```bash
cd /opt/hs-data-api   # или /root/hearthstone-parses
./scripts/export-bundle.sh /tmp/hs-migrate.tar.gz
scp /tmp/hs-migrate.tar.gz user@NEW_SERVER:/tmp/
```

**На новом сервере:**

```bash
sudo ./scripts/install.sh
sudo ./scripts/import-bundle.sh /tmp/hs-migrate.tar.gz
sudo systemctl restart hs-data-api
./scripts/audit.sh
```

Архив содержит `/etc/hs-data-api.env`, `datasets/`, `statuses/`, сессию HSReplay и индекс карт — **не публикуйте его в открытый доступ**.

## Проверка надёжности парсера

```bash
./scripts/audit.sh
curl -s http://127.0.0.1:8000/health | jq .
source /etc/hs-data-api.env
curl -s -H "X-API-Key: ${HS_API_KEY}" http://127.0.0.1:8000/ops/health | jq .
```

`/health` — лёгкий публичный liveness. Подробная диагностика источников, stale/cache state и filesystem path теперь находится в admin-only `/ops/health`.

Скрипт `audit.sh` повторно прогоняет `validate_parsed_data` по кэшу и показывает источники с расхождением статуса и качества данных.

## Структура на сервере

| Путь | Назначение |
|------|------------|
| `/opt/hs-data-api` | Код приложения (git clone) |
| `/var/lib/hs-data-api` | Кэш JSON, статусы, `hsreplay-auth.json` |
| `/etc/hs-data-api.env` | Секреты и настройки (не в git) |
| `systemd/hs-data-api*.service` | API и ежедневный refresh |

## Зависимости

- Python 3.12+, venv, `requirements.txt`
- `patchright install chromium` — HSReplay cards, BG heroes, trending
- Docker + `docker compose` — FlareSolverr (HSGuru, часть HSReplay)
- Резидентный прокси (`HS_FETCH_PROXY_URL`) — обязателен при `HS_FETCH_REQUIRE_PROXY=true`

## Обновление кода без потери кэша

**С этого workspace (rsync):**

```bash
sudo ./scripts/deploy-local.sh
```

**Или через git:**

```bash
cd /opt/hs-data-api
git pull
./venv/bin/pip install -r requirements.txt
sudo ./scripts/merge-env-example.sh /etc/hs-data-api.env
sudo cp systemd/*.timer systemd/*.service /etc/systemd/system/  # или sed как в install.sh
sudo systemctl daemon-reload
sudo systemctl enable hs-flaresolverr.service hs-data-api-refresh.timer hs-data-api-refresh-protected.timer
sudo systemctl restart hs-data-api hs-flaresolverr
./scripts/audit.sh
```

После деплоя проверьте новые поля ops:

```bash
source /etc/hs-data-api.env 2>/dev/null || true
curl -s http://127.0.0.1:8000/health | jq .
curl -s -H "X-API-Key: ${HS_API_KEY}" http://127.0.0.1:8000/ops/health | jq '{ok, sources, states, stale_count, cached_count}'
curl -s -H "X-API-Key: ${HS_API_KEY}" http://127.0.0.1:8000/health/premium | jq .
curl -s -H "X-API-Key: ${HS_API_KEY}" http://127.0.0.1:8000/ops/summary | jq '.freshness'
```

Preflight strict для cron включают постепенно: сначала `HS_REFRESH_PREFLIGHT_STRICT=false`, после 2 успешных `refresh --all` → `true`.

Точечный refresh:

```bash
./venv/bin/python -m app.cli refresh --source hsreplay_cards_legend_included_popularity
```
