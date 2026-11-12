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

## Aggregator follow-up (supplier identity path)

`integrations/supplier_aggregator.py` now passes `mpn=part_number` into `manufacturers_match()` for:
1. DigiKey brand check in `_safe_supplier_lookup()`
2. Requested-manufacturer filter in `get_best_part_data()`

AM29 lineage (AMD ↔ Infineon/Cypress/Spansion) only applies when the supplier row has a real manufacturer and the exact MPN route permits it. Supplier-reported brand is preserved; typed text alone never verifies identity.

## Tests run

| Suite | Result |
| --- | --- |
| `tests.test_replacement_outcome_identity` | OK |
| `tests.test_threaded_manufacturer_lookup` (incl. AM29 aggregator path) | OK |
| `tests.test_newark_catalog_diagnostics` | OK |
| Alternative Finder regression list (+ post-605 / post-deploy identity) | **436 OK** |
| `apps/web` lint | OK (pre-existing warnings only) |
| `apps/web` build | OK |

Note: `tests.test_compare_parts` has pre-existing failures on main (e.g. capacitor → Needs verification); not introduced by this PR.

## Do not

Merge or deploy from this PR — leave open for Codex review / release. Production remains on `ce20ed59`.
