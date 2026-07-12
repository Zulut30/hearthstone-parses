# План улучшения парсера Hearthstone Parses

Обновлено: 2026-07-12 (статус реализации). Детальный stabilization/refactor plan и Definition of Done: [`plans/2026-07-01-parser-api-refactor-plan.md`](../plans/2026-07-01-parser-api-refactor-plan.md).

## Статус фаз

| Фаза | Статус |
|------|--------|
| A1–A5 Надёжность | **Сделано** (proxy 407 abort, API retry, Firestone direct, auth summary, Telegram dedup) |
| B2 Prefetch HearthstoneJSON | **Сделано** |
| B3 In-run HSReplay cache | **Сделано** |
| B1 `PARALLEL_LIGHT=3` | **В .env.example**; на проде включать после стабильного cron |
| B4 Ночной `browser_protected` | **Сделано** (`hs-data-api-refresh-protected.timer`) |
| C1 Season scale quality | **Сделано** (`quality_thresholds` + `season_scale_factor`) |
| C2–C3 Регрессия dataset | **Сделано** (`dataset_regression.py`, state `partial`) |
| D1 Ротация JSONL | **Сделано** |
| D2 Auth `/ops/*` | **Сделано** |
| D3 Loki/Vector | **Открыто** (опционально) |
| D4 Runbook | **Сделано** (`docs/PROXY_AND_RELIABILITY.md`) |
| Phase 6 Contracts/publish gate | **Сделано** (единая валидация и regression guard) |
| Phase 7 Parser resilience | **Сделано** (fallback diagnostics, normalizer, 6 snapshot fixtures + mutations) |
| Phase 8 API v1 | **Сделано в коде** (`/v1/*`, typed envelope, ETag/304; production deploy ожидает merge) |
| Phase 9 pydantic-settings | **Отложено** (опционально; 69 env accessor’ов, отдельный migration PR) |

## Деплой

```bash
sudo ./scripts/deploy-local.sh
sudo ./scripts/merge-env-example.sh
./scripts/audit.sh
```

См. [DEPLOY.md](../DEPLOY.md).

## Цели

| Цель | Метрика |
|------|---------|
| Стабильный refresh | 46 зарегистрированных источников, нет новых quality/freshness failures после cron |
| Прозрачность | `/ui/logs` + `/ops/summary` (с API key) |
| HSReplay JSON | каналы `direct,flaresolverr,curl_cffi,jina` |

## Команды

```bash
/srv/hs-data-api/venv/bin/python -m app.cli preflight --strict
curl -s -H "X-API-Key: $HS_API_KEY" http://127.0.0.1:8000/ops/summary | jq '.hsreplay_auth,.stale_datasets'
systemctl list-timers 'hs-data-api-*'
```
