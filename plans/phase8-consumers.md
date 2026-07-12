# Phase 8 consumer compatibility inventory

Read-only scan performed on 2026-07-12 under `/var/www` and `/home/ubuntu`, excluding logs, JSON data, build targets, dependency directories and Git metadata.

| Consumer | Active file | API paths that must remain compatible |
| --- | --- | --- |
| Deckview | `/home/ubuntu/Deckview/hs_data_api.py` | `/datasets/{source_id}`, `/api/db/decks` |
| Deckview arena | `/home/ubuntu/Deckview/arena.py` via `fetch_data_api_dataset` | `/datasets/hsreplay_arena` |

No active references to `api.hs-manacost.ru` were found under `/var/www` or the Hearthstone news bot. Backup files in Deckview contain the same base URL but are not runtime consumers.

Compatibility policy:

- Legacy paths stay registered with their original response bodies and query parameters.
- `/v1/*` is additive and uses the `{data, meta}` envelope.
- Cache headers may be added to legacy GET responses; JSON bodies must not change.
