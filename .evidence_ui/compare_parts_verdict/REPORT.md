# Compare Parts verdict + decision path

Branch: `fix/compare-parts-verdict-decision` (from main `#615` / `1df5f44`)

## Root causes fixed

1. **Limit/max fields blocked Different/Match** when value class was unknown (`role=max/min` → Needs data for `50V` vs `25V`, `3 mV` vs `2 mV`). Known magnitudes with units (or a field-declared preferred/storage unit) now Compare as Match/Different; Compatible still requires authoritative provenance.
2. **`build_datasheet_comparison` always demoted Match → Listing agreement**, even when `datasheet_url` was present. Datasheet URLs now resolve as manufacturer provenance; Match is kept only when both sides are authoritative.
3. **Counts double-keyed** Status labels and snake_case aliases, so `sum(counts.values())` was `2 × rows`. Payload now exposes snake_case buckets only, with Status labels under `count_aliases`.

## Acceptance checks

| Criterion | Evidence |
| --- | --- |
| Unequal known params → Different; equal → Match (family unknown OK) | `tests/test_compare_verdict_decision_path.py`, `test_lm358dr_vs_lm358adr2g_offset_is_material_not_compatible` |
| Catalog/unknown → Needs verification / fit unverified; Compatible needs authoritative evidence | Cap fixtures with DigiKey-only sources; `assess_compare_row` guards |
| Missing/errors never Compatible or misleading empty-candidate claim | Fail-closed compare matrix tests; AM29 discovery failure narration unchanged |
| Arbitrary MPNs; no hardcoding | USER-MPN / fixture MPNs only |
| Replacement → compare → decision persists after reload | `test_replacement_candidate_compare_decision_persists_after_reload` |

## AM29F010B-70EC

Official Am29F010B datasheet (AMD/Spansion, pub 22336): 1 Mb (128K×8), 5 V, 70 ns, package suffix **E** = 32-pin TSOP standard pinout, **C** = commercial temp.

Microchip/SST application note S72014 lists SST39SF010A as the corresponding 1 Mb MPF device and states PLCC/PDIP pin compatibility, but **TSOP footprints differ** (AMD 8×20 mm vs SST 8×14 mm) and sector/software command behavior differs.

**Decision:** Do not promote SST39SF010A (or cross-family catalog leads) to Compatible for `AM29F010B-70EC`. Keep review-only / Needs verification until manufacturer-verified package, pinout, and program/erase fit evidence is attached. Regression: `test_am29_cross_family_lead_never_promotes_to_compatible`.

## Live suppliers

No live supplier smoke in this PR. All regressions use fixtures/mocks.

## Commands

See `focused.txt`, `af_regression.txt`, `web_lint.txt`, `web_build.txt` in this folder.
