# План улучшения парсера Hearthstone Parses

Обновлено: 2026-06-02 (статус реализации).

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
| Стабильный refresh | `states.ok >= 31` после 3 cron |
| Прозрачность | `/ui/logs` + `/ops/summary` (с API key) |
| HSReplay JSON | каналы `direct,flaresolverr,curl_cffi,jina` |

## Команды

```bash
/opt/hs-data-api/venv/bin/python -m app.cli preflight --strict
curl -s -H "X-API-Key: $HS_API_KEY" http://127.0.0.1:8000/ops/summary | jq '.hsreplay_auth,.stale_datasets'
systemctl list-timers 'hs-data-api-*'
```
