# Развёртывание и перенос на другой сервер

Репозиторий: **https://github.com/Zulut30/hearthstone-parses**

Перед продакшеном:

- **[docs/API.md](docs/API.md)** — публичные/admin endpoints, source IDs, JSON-схемы.
- **[docs/HSREPLAY_ARCHETYPE_DATABASE.md](docs/HSREPLAY_ARCHETYPE_DATABASE.md)** — SQLite база HSReplay архетипов, API, CLI и расписание.
- **[docs/SECURITY_AND_PARSING.md](docs/SECURITY_AND_PARSING.md)** — секреты, API, прокси, парсинг, чеклист.

## Быстрая установка с нуля

```bash
sudo git clone https://github.com/Zulut30/hearthstone-parses.git /opt/hs-data-api
cd /opt/hs-data-api
sudo ./scripts/install.sh
sudo nano /etc/hs-data-api.env   # прокси, HS_API_KEY, опционально HSReplay/Telegram
sudo systemctl restart hs-data-api hs-flaresolverr
sudo systemctl start hs-data-api-refresh.timer hs-data-api-refresh-api.timer hs-data-api-freshness-check.timer
sudo /opt/hs-data-api/scripts/server-readiness.sh --strict
sudo /opt/hs-data-api/scripts/server-readiness.sh --strict --refresh-all
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
sudo systemctl start hs-data-api-refresh.timer hs-data-api-refresh-api.timer hs-data-api-freshness-check.timer
sudo ./scripts/server-readiness.sh --strict
```

Архив содержит `/etc/hs-data-api.env`, `datasets/`, `statuses/`, сессию HSReplay и индекс карт — **не публикуйте его в открытый доступ**.

## Проверка надёжности парсера

```bash
./scripts/audit.sh
sudo ./scripts/server-readiness.sh --strict
curl -s http://127.0.0.1:8000/health | jq .
source /etc/hs-data-api.env
curl -s -H "X-API-Key: ${HS_API_KEY}" http://127.0.0.1:8000/ops/health | jq .
/opt/hs-data-api/venv/bin/python -m app.cli freshness-check --since-hours 48
/opt/hs-data-api/venv/bin/python -m app.cli quality-check
```

`/health` — лёгкий публичный liveness. Подробная диагностика источников, stale/cache state и filesystem path теперь находится в admin-only `/ops/health`.

Скрипт `audit.sh` повторно прогоняет `validate_parsed_data` по кэшу и показывает источники с расхождением статуса и качества данных. `freshness-check` возвращает non-zero, если есть stale или `cached-after-failure` источники; это отдельный сигнал, потому что refresh job может завершиться systemd-success и при этом оставить старый кэш видимым для API. `quality-check` проверяет все cached datasets через parser validation, source contracts и quality score; scores ниже `--min-quality-score` валят команду, а диапазон до `--warn-quality-score` попадает в warning list.

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
sudo ./scripts/install-docker-systemd.sh
sudo systemctl enable --now hs-flaresolverr.service hs-data-api-refresh.timer hs-data-api-refresh-api.timer hs-data-api-freshness-check.timer
sudo systemctl disable --now hs-data-api-refresh-protected.timer 2>/dev/null || true
sudo systemctl restart hs-data-api hs-flaresolverr
./scripts/audit.sh
```

Production refresh schedule:

- `hs-data-api-refresh.timer`: full parser run at `07:00 Europe/Warsaw`.
- `hs-data-api-refresh-api.timer`: API-tier parser run at `18:00 Europe/Warsaw`; skips browser-protected sources to reduce proxy traffic.
- `hs-data-api-freshness-check.timer`: audit at `07:45` and `18:45 Europe/Warsaw`.
- `hs-data-api-docker-firecrawl-hsreplay-map.timer`: weekly HSReplay crawl-map/index refresh at `02:35 Europe/Warsaw` on Mondays.
- `hs-data-api-docker-refresh-hsreplay-archetypes.timer`: HSReplay Standard archetype SQLite snapshots at `03:20 Europe/Warsaw` on Mondays and Thursdays.
- `scripts/install-docker-systemd.sh`: автоматически устанавливает и включает все
  `hs-data-api-docker-*.timer`, поэтому новый pipeline timer не останется только
  в репозитории после следующего деплоя.
- `hs-data-api-protected-recovery.service`: conditional fallback launched by failed freshness audit; refreshes only stale/cached-after-failure `browser_protected` sources.
- `hs-data-api-refresh-protected.timer`: disabled by default; the morning full run already includes protected sources. Use `systemctl start hs-data-api-refresh-protected.service` only for manual recovery.

После деплоя проверьте новые поля ops:

```bash
source /etc/hs-data-api.env 2>/dev/null || true
curl -s http://127.0.0.1:8000/health | jq .
curl -s -H "X-API-Key: ${HS_API_KEY}" http://127.0.0.1:8000/ops/health | jq '{ok, sources, states, stale_count, cached_count}'
curl -s -H "X-API-Key: ${HS_API_KEY}" http://127.0.0.1:8000/health/premium | jq .
curl -s -H "X-API-Key: ${HS_API_KEY}" http://127.0.0.1:8000/ops/summary | jq '.freshness'
/opt/hs-data-api/venv/bin/python -m app.cli freshness-check --since-hours 48
/opt/hs-data-api/venv/bin/python -m app.cli quality-check
```

HSReplay archetype database smoke-test:

```bash
python -m app.cli refresh-hsreplay-archetypes --limit 1
curl -s http://127.0.0.1:8000/api/db/archetypes?limit=3 | jq .
curl -s http://127.0.0.1:8000/api/db/archetypes/856/mulligan?limit=5 | jq .
```

Preflight strict для cron включают постепенно: сначала `HS_REFRESH_PREFLIGHT_STRICT=false`, после 2 успешных `refresh --all` → `true`.

Green deploy для production: публичный `/health.ok=true`, admin `/ops/health.freshness_ok=true`, `/ops/summary.freshness.cached_after_failure_count=0`, `freshness-check` возвращает `0`, `quality-check.ok=true`.

Для нового сервера или сервера с большим количеством соседних сервисов используйте один readiness gate:

```bash
sudo /opt/hs-data-api/scripts/server-readiness.sh --strict
sudo /opt/hs-data-api/scripts/server-readiness.sh --strict --refresh-all  # перед переключением traffic/DNS
```

Скрипт проверяет env, venv, source tier registry, systemd timers, FlareSolverr, proxy, strict preflight, `/health`, `/ops/summary`, freshness и quality. Это основной smoke-test после переноса.

Точечный refresh:

```bash
./venv/bin/python -m app.cli refresh --source hsreplay_cards_legend_included_popularity
```

## HSGuru stale/cached-after-failure recovery

Диагностика:

```bash
source /etc/hs-data-api.env
curl -s -H "X-API-Key: ${HS_API_KEY}" "http://127.0.0.1:8000/ops/summary?since_hours=48" | jq '{freshness, cached_after_failure_sources, backend_failures}'
curl -s -H "X-API-Key: ${HS_API_KEY}" "http://127.0.0.1:8000/ops/events?action_group=browser&since_hours=48" | jq '.[-20:]'
/opt/hs-data-api/venv/bin/python -m app.cli freshness-check --since-hours 48 --alert
```

Для HSGuru используется отдельный `HS_HSGURU_FETCH_BACKENDS` (default: `flaresolverr,scrapling,curl_cffi,cloudscraper,patchright`). При Cloudflare/403 browser rotator burn-ит sticky proxy session; timeout и quality failures открывают circuit только для конкретного source, чтобы один плохой endpoint не выключал backend для всей HSGuru пачки.

Recovery:

```bash
cd /opt/hs-data-api
sudo systemctl start hs-data-api-freshness-check.service
./venv/bin/python -m app.cli refresh --source hsguru_meta_wild_top_legend
./venv/bin/python -m app.cli refresh --tier browser_protected
```

Если `cached_after_failure_count` остаётся >0, не включайте protected timer: сначала проверьте proxy egress (`proxy-check`, `proxy-rotation-check`) и последние `browser.backend.fail`/`proxy.session.burn` события. Для разового восстановления используйте `systemctl start hs-data-api-refresh-protected.service`.
