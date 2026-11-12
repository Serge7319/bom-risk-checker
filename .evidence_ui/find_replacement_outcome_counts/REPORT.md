# Find Replacement outcome wording + catalog vs explicit counts

Base: `c118132` (#614 on main). Branch: `fix/find-replacement-outcome-counts` (PR #615).

## Issues addressed (no live supplier calls)

| Observation | Fix |
| --- | --- |
| LM358N + TI showed “Verified replacements found” while all rows required qualification / none Compatible | Outcome labels claim “verified” only when a candidate carries Compatible (or verified-direct) fit evidence; otherwise “Supplier-listed candidates found — fit unverified”. UI also corrects a stale “Verified…” banner when no Compatible row is present. |
| AM29 + AMD showed Mouser “19 leads” while only one retained Infineon lead | `catalog_raw_count` / `catalog_retained_count` are **catalog-only**. UI: `19 raw catalog matches · 1 retained` + catalog-only `catalog_filter_summary`. |
| Catalog counts mixed with DigiKey explicit substitutions | Rows tagged `discovery_channel`; `explicit_raw_count` / `explicit_retained_count` stay separate. UI never falls back from `explicit_count`/`lead_count` into “raw catalog matches”. |

## Count contract

- `catalog_raw_count` = raw catalog-search hits only
- `catalog_retained_count` = unique catalog leads after manufacturer/lineage/family/dedup
- `explicit_*` = supplier substitution counts only
- Filter summaries compare raw catalog → retained catalog only

## AM29 remaining limitation

Still **no verified same-family Compatible alternative** under configured coverage — **evidence/coverage gap**, not a reporting bug.

## Tests

| Suite | Result |
| --- | --- |
| `tests.test_find_replacement_outcome_counts` (19→1, 0+2 explicit, mixed+dup) | OK |
| `check_find_replacement_outcome_counts.mjs` | OK |

Live DigiKey/Mouser/Newark: **not called** in this PR.
