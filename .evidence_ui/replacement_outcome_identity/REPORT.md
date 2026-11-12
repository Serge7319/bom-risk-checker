# Replacement outcome + identity follow-up (PR draft)

Base: `ce20ed594c2763cf670fb716cc081319d2c8d891` (#609/#610 on main)

## Before / after — AM29F010B-70EC page

| | Before (prod baseline) | After (this PR) |
| --- | --- | --- |
| Blank manufacturer, Mouser catalog leads, Newark zero | Overall label: **Search outcome: failure** | **No verified replacement; catalog leads available** (`catalog_leads_only`) |
| Newark catalog | Searched — no results (`zero_results`, retained) | Unchanged Newark `any:` + empty-products handling |
| Explicit `AMD` / `Advanced Micro Devices` with no supplier brand hit | “Could not verify…”, empty candidates | Still **fail-closed** (typed text ≠ proof); clearer copy; lineage choices from trusted `legacy_mpn_routes` when present |
| AMD vs Infineon on this MPN only | No alias / lineage match | Match only when supplier resolves a lineage brand **and** MPN route supports it |
| Catalog / cross-family leads | Visible unclassified/cross-family | Still never Compatible / never qualified substitutes |

Sanitized correlator from prior prod check: `4bc26b9498f5` (no keys/URLs).

## Tests run

| Suite | Result |
| --- | --- |
| `tests.test_replacement_outcome_identity` | OK |
| `tests.test_newark_catalog_diagnostics` | OK (18) |
| Alternative Finder regression list (+ post-605 / post-deploy identity) | **427 OK** |
| `apps/web` lint | OK (pre-existing warnings only) |
| `apps/web` build | OK |

Note: `tests.test_compare_parts` has pre-existing failures on main (e.g. capacitor → Needs verification); not introduced by this PR.

## Do not

Merge or deploy from this PR — leave open for Codex review / release.
