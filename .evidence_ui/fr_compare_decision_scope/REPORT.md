# FR → Compare decision scope + multi-candidate manufacturers

## Summary
Standalone Compare decisions show an explicit **No BOM — workspace-level decision** option (visibly selected; never the first saved BOM) and save with `analysis_id=null`. BOM-scoped compare/decision keeps the exact handed-off `analysis_id`. Multi-compare headings and evidence show each candidate’s MPN + independent manufacturer (TI / ST / onsemi); identities persist through decision snapshots and reload.

## Acceptance
| Item | Status |
| --- | --- |
| Workspace-level option visible and selected when no analysis_id | PASS |
| Save with analysis_id=null; preserve after reload | PASS |
| Exact BOM preserved when analysis_id present (never first/latest) | PASS |
| Multi headings/evidence show TI LM358AN/NOPB, ST LM358DT, onsemi LM358DR2G | PASS |
| Per-candidate manufacturers in decision snapshots / reload | PASS |
| AM29 blank-manufacturer stays review-only (cross-family) | PASS (contract) |
| Catalog-only evidence never Compatible | PASS |
| Synthetic fixture browser smoke (standalone multi + BOM-scoped) | PASS |

## Evidence
- `focused.txt` — unit/API suite
- `api_af_regressions.txt` — related AF/migration suites
- `web_lint.txt` / `web_build.txt` — Next lint/build
- `browser_smoke/` — Playwright fixture smoke
