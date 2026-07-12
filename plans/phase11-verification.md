# Phase 11 verification — 2026-07-12

## Completed on the stabilization branch

- `python -m pytest -q`: **276 passed**, 4 subtests passed, 0 failed.
- `python -m compileall -q app`: passed.
- `python scripts/generate-source-catalog.py --check`: passed; 46 sources (44 scrape + 2 pipeline).
- `docker compose config --quiet` with a temporary non-secret env file: passed.
- Anti-pattern checks: no `os.environ.get` outside `app/config.py`; no duplicate `_parse_percent_value` / `_is_percent` helpers.
- Real Uvicorn smoke on isolated storage: `/health` 200, `/openapi.json` 200 with all eight v1 routes, `/v1/system/sources` returned 46 rows, conditional request returned 304 with an empty body.
- GitHub review threads: all resolved; PR is mergeable. GitHub pytest must be green on the final SHA before merge.

## Current production baseline (before merge/deploy)

Read-only audit of `https://api.hs-manacost.ru`:

- `/health`: healthy.
- `/datasets`: 46/46 have a dataset and status `ok`.
- Local contract + semantic replay over every public dataset: 44 pass both layers.
- `vicious_syndicate_radars`: contract passes, semantic validation rejects missing latest-report issue/date metadata.
- `vicious_syndicate_live_beta`: contract passes, semantic validation rejects 11/11 placeholder `Other <Class>` decks and zero named archetypes.
- `hsreplay_battlegrounds_hero_details`: approximately 251 hours old versus its 192-hour source limit.
- `/v1/system/sources`: 404, expected because this branch has not been deployed.

The three production data findings are exactly the kind of silent-success/staleness that the new health and publish gates surface; they require refresh after deployment, not weakening validators.

## Post-baseline remediation added to the branch

- Live Firebase recon confirmed every Vicious interval (`last6Hours` through `last2Weeks`) currently contains only 11 `Other <Class>` buckets. Extraction now reports `upstream_unclassified`, removes those buckets from deck/tier output, and fails the publish gate instead of presenting them as archetypes.
- Live radar recon found 24 parsed radars at issue 349 while the latest report is issue 352. Radar output now reports `upstream_stale` and retains latest-report issue/date provenance.
- BG hero detail refresh now runs Mon/Thu rather than only Monday; its stale limit is 120 hours (96-hour maximum schedule gap + 24-hour slack), preventing one missed weekly run from silently aging for 8–11 days.
- Quality diagnostics are retained in failure statuses so `/sources/{id}` and operations tooling can distinguish upstream warm-up/staleness from transport or parser failures.
- Final local suite after these changes: **281 passed**, 4 subtests passed, 0 failed; GitHub pytest is green on commit `a30686a`.

## New-expansion card coverage

- Current HearthstoneJSON lists 135 collectible cards in `ESCAPEFROM_VIOLET_HOLD`; the full local card index contains 254 records for the set including non-collectible/token forms.
- Production `hsreplay_cards_legend_included_winrate` and `...included_popularity` each resolve all 135/135 collectible IDs. The union of all four ranked card datasets also covers 135/135; the one-day Legend sample contains 132/135, which is expected usage sampling rather than an index miss.
- The in-process HearthstoneJSON index previously remained frozen until process restart even after its file TTL elapsed. It now refreshes and rebuilds derived ID/name/dbf indexes after 24 hours, writes atomically, rejects payload truncation, serves stale data with a retry backoff during upstream failure, and falls back from unavailable locale data to enUS.
- Final local suite after card-index hardening: **286 passed**, 4 subtests passed, 0 failed.

## External steps still required

1. Human review and merge PR #2.
2. Clean Docker build. This workspace cannot access `/var/run/docker.sock` because user `debian` is not in group `docker`; Podman/Buildah are unavailable.
3. Deploy the merged commit from `/srv/hs-data-api` using the documented fast-forward-only procedure.
4. Refresh `vicious_syndicate_radars`, `vicious_syndicate_live_beta`, and `hsreplay_battlegrounds_hero_details`; do not publish candidates that fail the new gates.
5. Run production smoke for health, all legacy Deckview paths, all v1 routes, ETag/304, UI/docs, and `freshness-check --since-hours 48`.
6. Observe every Docker timer for 24 hours and confirm no new contract, semantic, freshness, or systemd failures.
