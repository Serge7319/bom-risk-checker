# Find Replacement E2E (post-#613)

Base: `bff55ff` (main after #613). Branch: `fix/find-replacement-e2e`.

## Defects fixed (coherent change)

See `DEFECTS.md`. Summary:

| ID | Fix |
| --- | --- |
| D1 | Identity banner only when review-only / ambiguous / non-empty choices |
| D2 | DigiKey `_exact_keyword_product` passes `mpn=` into `manufacturers_match` |
| D3 | Review-only offers “Retry search as {other brand}”; same typed brand suppressed |
| D4 | Blank + single supplier brand attaches multi-brand lineage as non-blocking context |
| D5 | `discover_alternative_candidates(..., manufacturer=)` filters conflicting brands; blank-mfr leads kept |
| D7 | Docstring: mismatch hard-block vs unresolved review-only |

Preserved from #609–#613: Newark `any:`, omit-products empty success, honest outcomes, aggregator DigiKey/get_best_part_data `mpn=` pass-through, lineage note provenance, review-only catalog leads.

## AM29F010B-70EC retention (fixtures; no live credentials)

Source: `am29_retention.json`.

| Case | Identity | Candidates | Compatible? |
| --- | --- | --- | --- |
| Blank + DigiKey Infineon verified | supplier Infineon kept | exact path → no substitute fixtures → `no_results` | No |
| AMD + Infineon lineage match | `matched`, verified; manufacturer stays Infineon | same exact path → `no_results` | No |
| AMD unresolved (no supplier brand) | `unresolved` review-only | Mouser AMD/Infineon leads as Needs verification; TI lead filtered; blank-mfr → unclassified | No |
| TI typed vs Infineon supplier | `manufacturer_mismatch` fail-closed | none | No |

**Verdict:** There is **no verified Compatible alternative** for AM29F010B-70EC in these fixtures. Observed Mouser hits are catalog/review-only leads, not drop-in replacements. Live DigiKey/Mouser/Newark were **not** called in this evidence run (no safe credentialed access in this session); provider behavior covered by deterministic fixtures + Newark/outcome regression suites.

## UI identity helpers

`apps/web/scripts/check_find_replacement_identity.mjs` — OK (banner gating + retry suppression).

## Tests / lint / build

| Command | Result |
| --- | --- |
| `unittest` find_replacement_e2e + replacement_outcome_identity + threaded_manufacturer_lookup | OK |
| `unittest` newark_catalog_diagnostics (alone) | OK |
| `unittest` post_605_generic_followup + alternative_finder_search | OK |
| CI Alternative Finder regression list (24 modules) | **369 OK** |
| `npm run lint` / `npm run build` (`apps/web`) | OK (pre-existing img/font warnings only) |

## Live verification label

**Not verified live** in this PR evidence: production Find Replacement POST with real supplier credentials. Codex post-merge/deploy smoke should re-run AM29+AMD on production after release auth merge.

Secrets / credentialed URLs: none in evidence logs.
