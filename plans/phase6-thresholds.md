# Phase 6 validation threshold inventory

Authoritative inventory for moving per-source/per-type rules out of
`app/scrapers/quality.py`. A row is complete only when the old branch is removed
and the replacement has a focused regression test.

| Existing rule | Scope | New home | Status |
| --- | --- | --- | --- |
| HTML ≥ 2,000 bytes | default fetched page | `SourceContract.min_html_bytes` | transferred + tested |
| HSGuru meta/matchups HTML ≥ 25,000 bytes | HSGuru meta/matchups | `SourceContract.min_html_bytes` | transferred + tested |
| HSGuru streamer HTML ≥ 8,000 bytes | HSGuru streamer decks | `SourceContract.min_html_bytes` | transferred + tested |
| meta table rows ≥ configured 5 | HSGuru meta | contract/type validator | pending |
| streamer deck codes ≥2 or table rows ≥3 | HSGuru streamer decks | type validator | pending |
| matchup rows ≥3 or text lines ≥30 plus content marker | HSGuru matchups | type validator | pending |
| decks ≥5 | MetaStats decks | `SourceContract` (current minimum 40) | duplicated; remove old branch after parity test |
| matchups ≥ configured 10 | MetaStats matchups | `SourceContract` (current minimum 50) | duplicated; remove old branch after parity test |
| decks ≥5 | Hearthstone Decks | `SourceContract` (current minimum 40) | duplicated; remove old branch after parity test |
| classes ≥8, tier brackets ≥3, tier rows ≥20 | Vicious Live | `source_validators` + contract | pending |
| radars ≥5 | Vicious radars | `SourceContract` | duplicated; remove old branch |
| groups ≥10 and at least one `key_card` | Arena legendary groups | contract + type validator | pending |
| comps ≥3 and ≥max(3, half) with cards | BG comps | type validator | pending |
| cards ≥50 and ≥40 with placement stats | BG card stats | type validator | pending |
| trinkets ≥8 and ≥max(6, half) valid | BG trinkets | type validator | pending |
| decks ≥1 and at least one `final_deck` | Arena winning decks | contract + type validator | pending |
| classes ≥8 | Arena class matrix | `SourceContract` | duplicated; remove old branch |
| classes ≥10 and ≥10 with stats | Arena class pages | contract + type validator | pending |
| heroes ≥30, names ≥20, stats ≥20 | BG heroes | `source_validators` + contract | transferred + tested; remove old branch |
| minions ≥50 and ≥40 with stats | BG minions | contract + type validator | pending |
| compositions ≥5 and ≥5 with stats | BG compositions | contract + type validator | pending |
| cards ≥ dynamic source threshold and tier labels present | Arena card tiers | contract + type validator | pending |
| classes ≥5, cards ≥300, tier ids ≥200 | HearthArena tier list | contract + type validator | pending |
| cards ≥30, metrics ≥20, blocked payload rejected | card stats | contract + type validator | pending |
| classes ≥8, archetypes ≥20, metrics ≥20 | HSReplay meta archetypes | contract + type validator | pending |
| premium-login/userdata/content markers | HSReplay raw-page fallback | page/auth structural checks | remains in `quality.py` by design |
| default text lines ≥10 | unstructured fallback | page structural check | remains in `quality.py` by design |
