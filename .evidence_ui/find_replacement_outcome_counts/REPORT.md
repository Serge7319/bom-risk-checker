# Find Replacement outcome wording + raw/retained counts

Base: `c118132` (#614 on main). Branch: `fix/find-replacement-outcome-counts`.

## Issues addressed (no live supplier calls)

| Observation | Fix |
| --- | --- |
| LM358N + TI showed “Verified replacements found” while all rows required qualification / none Compatible | Outcome labels claim “verified” only when a candidate carries Compatible (or verified-direct) fit evidence; otherwise “Supplier-listed candidates found — fit unverified”. UI also corrects a stale “Verified…” banner when no Compatible row is present. |
| AM29 + AMD showed Mouser “19 leads” while only one unclassified Infineon lead was retained | Provider `catalog_raw_count` stays at the raw hit count; `catalog_retained_count` reflects post manufacturer/lineage/family/dedup retention. UI: `19 raw catalog matches · 1 retained` plus `catalog_filter_summary` when available. Filtered rows are not re-exposed as replacements. |

## AM29 remaining limitation

Still **no verified same-family Compatible alternative** under configured fixture/provider coverage. That is an **evidence/coverage gap**, not a label/count bug: Newark/DigiKey zero and Mouser catalog noise correctly fail to become Compatible.

## Tests

| Suite | Result |
| --- | --- |
| `tests.test_find_replacement_outcome_counts` (+ identity/discovery guards) | OK |
| CI Alternative Finder regression list + new focused module | **374 OK** |
| `check_find_replacement_outcome_counts.mjs` | OK |
| `apps/web` lint / build | OK (pre-existing warnings only) |

Live DigiKey/Mouser/Newark: **not called** in this PR.
