# FR → Compare manufacturer identity handoff

## Summary
Carry each side’s manufacturer identity from Find Replacement into Compare (URL, page state, JSON/multipart, API, migration_tools, legacy lookup). Manufacturer text is a lookup constraint, not proof: verify returned source brand; fail closed on mismatch/ambiguity (no borrowed attributes, Needs verification). Part B identity stays independent of Part A. Preserve identities through standalone/BOM/multi compare and decision snapshots.

## Acceptance
| Item | Status |
| --- | --- |
| TI LM358N handoff stays TI; never consumes onsemi LM358N data | PASS |
| onsemi LM358N stays onsemi | PASS |
| Ambiguous standalone LM358N without manufacturer asks for choice / stays unresolved | PASS |
| Supplier brand mismatch → no borrowed values, never Compatible | PASS |
| Candidate manufacturer independent of Part A | PASS |
| JSON + multipart + BOM handoff + decision persistence | PASS |
| Multi-candidate Compare links keep per-side manufacturer_b | PASS |
| Fixture browser smoke: FR search → Compare → decision save/reload | PASS |

## Evidence
- `focused.txt` — identity unit/API suite
- `api_af_regressions.txt` — related AF/compare/migration suites
- `web_lint.txt` / `web_build.txt` — Next lint/build
- `browser_smoke/` — Playwright fixture smoke
