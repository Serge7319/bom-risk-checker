# FR → Compare decision scope + multi-candidate manufacturers

## Summary
Standalone Compare decisions show an explicit **No BOM — workspace-level decision** option (visibly selected; never the first saved BOM) and save with `analysis_id=null`. BOM-scoped compare/decision keeps the exact handed-off `analysis_id`. Multi-compare headings and evidence show each candidate’s MPN + independent manufacturer (TI / ST / onsemi); identities persist through decision snapshots and reload.

Follow-up: Changing Project / BOM in the decision dialog **re-compares every candidate** under the selected scope with that candidate’s manufacturer (no stamped tokens). Snapshot trust requires exact request/claim/payload scope match including workspace-level null. Stale multi tokens return `comparison_refresh_required` (409) instead of silently saving the primary only.

## Acceptance
| Item | Status |
| --- | --- |
| Workspace-level option visible and selected when no analysis_id | PASS |
| Save with analysis_id=null; preserve after reload | PASS |
| Exact BOM preserved when analysis_id present (never first/latest) | PASS |
| Multi headings/evidence show TI LM358AN/NOPB, ST LM358DT, onsemi LM358DR2G | PASS |
| Per-candidate manufacturers in decision snapshots / reload | PASS |
| Scope switch workspace→BOM and BOM→workspace re-compares every candidate | PASS |
| Signed tokens: BOM≠workspace and workspace≠BOM (both directions) | PASS |
| Stale multi tokens → refresh-required 409 (no primary-only save) | PASS |
| AM29 blank-manufacturer stays review-only (cross-family) | PASS (contract) |
| Catalog-only evidence never Compatible | PASS |
| Synthetic fixture browser smoke | PASS |

## Evidence
- `focused_scope_tokens.txt` / prior `focused.txt` — unit/API suites
- `api_af_regressions.txt` — related AF/migration suites
- `database_gate.txt` — cutover disposable DB + migration persistence
- `web_lint.txt` / `web_build.txt` — Next lint/build
- `browser_smoke/` — Playwright fixture smoke (scope switches + save/reload)
