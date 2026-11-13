# Paid-promise follow-up — coverage vs gaps

**Worktree:** `.worktrees/paid-promise-followup`  
**Branch:** `release/paid-promise-followup-gaps` @ `2c44ce3`  
**Baseline note:** `.evidence_ui/paid_promise_followup/HEAD.txt`  
**Thoroughness:** medium

Legend: **COVERED** | **PARTIAL** | **GAP**

---

## 1. DigiKey / Mouser / Newark supplier matrix

| Scenario | Newark | DigiKey | Mouser | Aggregator |
|---|---|---|---|---|
| Exact MPN (+ mfr when constrained) | COVERED | PARTIAL (exact MPN in client + substitutions; mfr filter in `_exact_keyword_product` / aggregator) | PARTIAL (exact MPN keyword/part APIs) | COVERED via `_safe_supplier_lookup` + mfr match |
| Mismatch (wrong MPN / wrong mfr) | COVERED | GAP (no dedicated DigiKey wrong-mfr test) | GAP (no dedicated Mouser wrong-mfr test) | PARTIAL (`test_newark_manufacturer_constraint_…` only names Newark) |
| No hit | COVERED | PARTIAL (non-exact → empty MPN) | PARTIAL (family neighbor no datasheet) | COVERED (`PROVIDER_PART_NOT_FOUND`) |
| Failure ≠ no hit | COVERED | PARTIAL (via aggregator mocks) | COVERED (`test_failed_provider_responses_are_not_reported_as_no_match`) | COVERED |
| Missing stock/price → null | COVERED (`None`) | GAP (price → `0.0` via `extract_digikey_price` / `_as_number`; stock uses `parse_stock_total` → null OK) | GAP (price → `0.0` via `extract_mouser_price`; empty default `unit_price: 0.0`) | PARTIAL (`unit_price_known` flag; coerces missing to `0.0`) |
| Product URL + `retrieved_at` stored | COVERED (official `www.newark.com` only) | COVERED (fields set) | COVERED (fields set) | COVERED |
| Product URL + `retrieved_at` display | N/A client | PARTIAL UI (procurement / find-replacement / compare show `retrieved_at`; listing URL uneven) | same | — |
| Newark official HTTPS only | COVERED (`_official_newark_https_url`, `NEWARK_STORE_ID`) | — | — | — |

### Change / extend

| Action | File / function |
|---|---|
| Fix DigiKey missing price → null | `integrations/digikey_client.py` — `extract_digikey_price`, `_as_number` (default `0.0`), substitution normalize path |
| Fix Mouser missing price → null | `integrations/mouser_client.py` — `extract_mouser_price`, empty-result default `unit_price` |
| Align aggregator null price | `integrations/supplier_aggregator.py` — `_safe_supplier_lookup` price coercion (~431–436) |
| DigiKey exact+mfr / mismatch / no-hit / failure / null stock+price / URL+stamp | Extend `tests/test_digikey_substitutions.py` **or** add DigiKey integration cases parallel to Newark; also `search_digikey_by_part_number`, `_exact_keyword_product` |
| Mouser same matrix | Extend `tests/test_mouser_keyword_fallback.py`; `search_mouser_by_part_number`, `normalize_mouser_part` |
| DigiKey/Mouser mfr constraint | Extend `tests/test_supplier_health.py` (mirror `test_newark_manufacturer_constraint_rejects_exact_mpn_wrong_vendor`) |
| Newark (mostly done) | Keep/extend `tests/test_newark_integration.py`; `integrations/newark_client.py` — `search_newark_by_part_number`, `lookup_newark_official_listing_url`, `_official_newark_https_url` |
| Display URL + retrieved_at consistently | `apps/web/src/app/procurement/page.tsx`, `apps/web/src/app/find-replacement/page.tsx`, `apps/web/src/app/compare-parts/page.tsx` (and any supplier offer row renderer) |

**Existing tests to extend:** `tests/test_newark_integration.py`, `tests/test_supplier_health.py`, `tests/test_mouser_keyword_fallback.py`, `tests/test_digikey_substitutions.py`  
**CI note:** only `tests.test_digikey_substitutions` is in `.github/workflows/alternative_finder_tests.yml`; Newark/Mouser/supplier_health not in CI.

---

## 2. Supply Risk page / API (+ monitoring refresh clause)

| Requirement | Status | Where |
|---|---|---|
| Inventory input contract (build qty, stock reduction %, analysis_id) | COVERED | `apps/web/src/app/supply-risk/page.tsx` → `runSupplyRisk`; `apps/api/main.py` `supply_risk_post`; `apps/api/migration_tools.py` `supply_risk_payload` |
| Affected components section | COVERED | supply-risk page “Affected components” table |
| Analysis vs portfolio vs clear scope | COVERED | payload `scope`/`gap`; Clear analysis scope control; tests below |
| `"inventory evidence unavailable"` when no inventory | **GAP** | Phrase absent. Scenario sets `Stock Recorded=False` / `Original Stock=None` (`src/supply_risk_scenario.py` `build_supply_scenario`); UI shows `—` or empty “No affected components found”, not the required copy. Gap text says “synthetic stock… not live supplier inventory” for all runs. |
| Refresh must not email / write alerts | COVERED (monitoring, not supply-risk) | Supply-risk has no refresh/alert write. Monitoring: GET read-only; refresh persists alerts but never emails — `tests/test_monitoring_read_only_refresh.py`, `apps/api/migration_tools.py` `monitoring_refresh_payload`, `apps/api/monitoring_scheduler.py`, `apps/web/src/app/monitoring/page.tsx` |

### Change / extend

| Action | File / function |
|---|---|
| Emit / surface `"inventory evidence unavailable"` when no recorded stock | `src/supply_risk_scenario.py` `build_supply_scenario`; `apps/api/migration_tools.py` `supply_risk_payload` (gap / scenario flags); `apps/web/src/app/supply-risk/page.tsx` empty/missing-inventory UX |
| Keep scope/clear behavior | Already good — don’t regress |

**Existing tests to extend:**  
- `tests/test_live_portfolio_and_supply_scenarios.py` (`test_supply_scenario_does_not_treat_missing_stock_or_sources_as_zero`)  
- `tests/test_post_605_generic_followup.py` `SupplyRiskScopeClearTests`  
- `tests/test_post_deploy_smoke_followup.py` `SupplyRiskScopeTests`  
- Monitoring refresh: `tests/test_monitoring_read_only_refresh.py` (already strong; not in CI workflow)

---

## 3. Datasheet Q&A

| Requirement | Status | Where |
|---|---|---|
| Positive answer, part-specific fixture | COVERED | `tests/fixtures/datasheets/lm358dr_ti_excerpts.json` + `tests/test_datasheet_qa.py` / `tests/test_datasheet_qa_identity_api.py` |
| Family / wrong / uncertain → Needs verification | COVERED | `src/datasheet_qa.py` `NEEDS_VERIFICATION_ANSWER`, `_needs_verification_result`, `answer_datasheet_question`; wrong MPN API test; family/variant tests |
| “Official” datasheet fixture | PARTIAL | Fixture is **sanitized paraphrased** TI excerpts (`source_url` `https://fixture.invalid/...`), not a live manufacturer URL — intentional for copyright; identity binding still part-specific |

### Change / extend

| Action | File / function |
|---|---|
| Only if tightening “official” provenance labeling | `tests/fixtures/datasheets/lm358dr_ti_excerpts.json`; `src/datasheet_qa.py`; UI copy in `apps/web/src/app/datasheet-qa/page.tsx` |
| Keep regression matrix | Extend `tests/test_datasheet_qa.py`, `tests/test_datasheet_qa_identity_api.py` |

**Verdict:** largely done for follow-up; no blocking functional gap beyond optional provenance wording. Not in CI workflow.

---

## 4. Two-user isolation in CI

| Path | Status |
|---|---|
| Shared matrix | COVERED — `tests/two_user_isolation_suite.py` |
| Disposable Postgres | COVERED in CI — `tests/test_cutover_disposable_db.py` → `test_two_user_postgres_matrix_workspaces_boms_reports_decisions_monitoring` via `.github/workflows/alternative_finder_tests.yml` “Run disposable Postgres migration gates” |
| File-store suite | PARTIAL — `tests/test_workspace_isolation.py` exists, **not** listed in CI |

### Change / extend

| Action | File |
|---|---|
| Optionally add file-store suite to CI | `.github/workflows/alternative_finder_tests.yml` — add `tests/test_workspace_isolation.py` (or pytest select) |
| Extend matrix cases if needed | `tests/two_user_isolation_suite.py`; callers in cutover + workspace isolation |

**Verdict:** Postgres two-user isolation **is** in CI. Gap is only dual-backend CI parity (file store).

---

## 5. Monitoring “Notifying…” idle label bug

| Status | **GAP (bug confirmed)** |
|---|---|
| File | `apps/web/src/app/monitoring/page.tsx` |
| Cause | Idle `notifying === ""` and `String(a.id \|\| "") === ""` for unpersisted alerts → label shows **“Notifying…”** instead of **“Notify”** |
| Fix | Compare only when a real id is present, e.g. `Boolean(a.id) && notifying === String(a.id)` (and/or init notifying as `null`) |
| Tests | **None** — add a small component/source assertion or Playwright/unit check that idle unpersisted rows show `Notify` |

Related (already correct elsewhere): refresh vs notify separation, email gating — covered by `tests/test_monitoring_read_only_refresh.py`.

---

## Priority suggested for follow-up PR

1. Fix monitoring Notifying idle label (`apps/web/src/app/monitoring/page.tsx`) + tiny regression test  
2. Supply Risk `"inventory evidence unavailable"` when `Stock Recorded` is false / no inventory  
3. DigiKey/Mouser null price + dedicated exact/mismatch/no-hit/failure/URL+retrieved_at parity with Newark; extend `test_supplier_health` mfr constraint to DigiKey/Mouser  
4. Wire missing focused suites into CI if release gate requires them (`test_supplier_health`, `test_newark_integration`, `test_datasheet_qa*`, `test_monitoring_read_only_refresh`, optional `test_workspace_isolation`)  
5. Datasheet Q&A — leave unless provenance wording required

---

## Follow-up closeout (this PR)

See `ACCEPTANCE_MATRIX.md`. Supplier null-price + matrix, Supply Risk inventory-unavailable, Monitoring Notifying idle, CI wiring, Datasheet official TI URL binding are addressed in code. **Still BLOCKED:** 15 live Newark offers; production second-account isolation. Paid workflow **not accepted** while those remain BLOCKED.
