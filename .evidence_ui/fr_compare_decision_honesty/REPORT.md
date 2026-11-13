# FR → Compare → Decision honesty

## Summary
Focused honesty fixes for Find Replacement outcomes, catalog vs explicit count reconciliation, provenance-aware Compare Parts summaries, and analysis_id handoff (no silent BOM attach).

## Acceptance
| Item | Status |
| --- | --- |
| Supplier-listed / fit-unverified outcomes; Verified only with engineering fit evidence | PASS |
| No “Qualified alternatives” when fit is not qualified / qualification required | PASS |
| Catalog raw/retained vs explicit counts reconcile; no 39→24 and 0 retained | PASS |
| Compare: parametric Match/Different preserved; catalog agree = fit unverified; missing = Needs verification; Material only with authoritative evidence | PASS |
| analysis_id only when search/handoff had BOM context; clearable BOM on Compare Parts | PASS |
| Fixture/mock regressions (LM358DR→LM358ADR2G, verified datasheet, handoffs, decision persistence); no live suppliers | PASS |

## Evidence
- `focused.txt` — focused pytest suites
- `af_regression.txt` — AF + honesty unittest suite
- `web_lint.txt` / `web_build.txt` — Next lint/build
