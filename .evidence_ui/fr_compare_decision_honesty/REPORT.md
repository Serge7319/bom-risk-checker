# FR → Compare → Decision honesty

## Summary
Focused honesty fixes for Find Replacement outcomes, catalog vs explicit count reconciliation, provenance-aware Compare Parts summaries, and analysis_id handoff (no silent BOM attach).

Follow-up: Verified labels require explicit authoritative fit evidence; Compare customer counts/summary derive from Assessment provenance (raw Status kept in `internal_status_counts`); zero retained substitutions are honored.

## Acceptance
| Item | Status |
| --- | --- |
| Supplier-listed / fit-unverified outcomes; Verified only with engineering fit evidence | PASS |
| No “Qualified alternatives” when fit is not qualified / qualification required | PASS |
| Catalog raw/retained vs explicit counts reconcile; no 39→24 and 0 retained | PASS |
| Compare: parametric Match/Different preserved; catalog agree = fit unverified; missing = Needs verification; Material only with authoritative evidence | PASS |
| analysis_id only when search/handoff had BOM context; clearable BOM on Compare Parts | PASS |
| Fixture/mock regressions (LM358DR→LM358ADR2G, verified datasheet, handoffs, decision persistence); no live suppliers | PASS |
| Authoritative fit evidence required for Verified | PASS |
| Compare counts/summary from provenance assessments; raw Status preserved internally | PASS |
| Zero retained substitutions honored (no raw fallthrough) | PASS |
| Browser smoke on PR production build with fixture API responses | PASS |

## Evidence
- `focused.txt` / `focused_followup.txt` — focused pytest suites
- `af_regression.txt` — AF + honesty unittest suite
- `web_lint*.txt` / `web_build*.txt` — Next lint/build
- `browser_smoke/` — fixture Playwright smoke (standalone FR, handoff, standalone/BOM compare, decision save/reload)
