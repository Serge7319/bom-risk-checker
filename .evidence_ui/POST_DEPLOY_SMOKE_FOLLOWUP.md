# Post-deploy smoke follow-up

Branch: `fix/post-deploy-smoke-followup`  
Base: `292cd67` (#604)  
Do not merge or deploy from this PR until reviewed.

## Fixes

1. **Find Replacement manufacturer identity** — LM358N (and other dual-source MPNs) require an explicit manufacturer. TI vs onsemi choices surface with official product URLs; Cadivor will not silently present an onsemi identity when TI was selected.
2. **Compare assessment honesty** — Unknown evidence class/conditions with catalog provenance → **Needs verification**. Known catalog agreement → **Catalog values agree — fit unverified**. Compatible is reserved for non-catalog verified evidence.
3. **Supply Risk scope** — Honors `analysis_id` (URL + API). Response includes `scope` (`analysis` | `portfolio`), `source_part_count`, and an explicit gap label. UI shows the active scope.
4. **Compare latency / failures** — 60s per pairwise compare, multi-candidate `Promise.allSettled`, progress copy, and bounded failures that stay Needs verification (never Compatible / “no candidates”).

## Evidence

- Unit regressions: `tests/test_post_deploy_smoke_followup.py` + `CompareHonestyTests` → 21 passed (`next_ui_two_bom_post_deploy_followup/pytest.txt`)
- Flat + nested synthetic UI smoke: `next_ui_two_bom_post_deploy_followup/` (`REPORT.md`, `report.json`, screenshots/exports)
- API checks: `next_ui_two_bom_post_deploy_followup/followup_api_checks.json`
