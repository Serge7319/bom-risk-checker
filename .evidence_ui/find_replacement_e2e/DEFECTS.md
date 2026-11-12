# Find Replacement E2E defect list (main `bff55ff` / #613)

| ID | Reproduction | Root cause | Fix | Test |
| --- | --- | --- | --- | --- |
| D1 | Matched search still shows identity banner | UI gates on `Array.isArray(identity_choices)` which is always `[]` | Show banner only when choices.length > 0, review-only, or ambiguous | `check_find_replacement_identity.mjs` |
| D2 | AMD + DigiKey Infineon product for lineage MPN never selected | `digikey_client._exact_keyword_product` calls `manufacturers_match` without `mpn=` | Pass `mpn=part_number` | `DigiKeyLineageMatchTests` |
| D3 | Review-only hides all brand buttons → cannot escalate to Infineon | `!identityReviewOnly` wraps Use-brand buttons | Keep review-only leads; offer “Retry search as {other brand}” for non-typed choices | identity helpers + review-only matrix case |
| D4 | Blank manufacturer with multi-brand lineage silently accepts sole supplier brand | Blank path ignores `lineage_identity_choices` when `len(labels)==1` | Attach lineage choices as informational context when route has multi-brand lineage (non-blocking) | blank path + lineage_context in search |
| D5 | Catalog discovery ignores requested manufacturer | `discover_alternative_candidates` has no manufacturer filter | Prefer/filter catalog leads by manufacturer+lineage when requested | `DiscoveryManufacturerFilterTests` |
| D7 | Docstring still says unresolved fails closed with no candidates | Stale docstring | Align with review-only vs mismatch hard-block | review-only AltFinder tests |

Already fixed on main (#609–#613): `any:` Newark, empty products, honest outcomes, aggregator mpn pass-through, lineage provenance notes, review-only catalog leads for unresolved identity.