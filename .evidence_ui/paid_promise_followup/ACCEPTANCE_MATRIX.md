# Paid-promise follow-up acceptance matrix

**PR:** https://github.com/Serge7319/bom-risk-checker/pull/626  
**Branch:** `release/paid-promise-followup-gaps`  
**Head:** `885956248bd8334d5b89493d767ac8ff3d164e6a` (update to tip after final evidence commit)  
**Base:** `main` (merged PR #625)  
**Evidence dir:** `.evidence_ui/paid_promise_followup/`  
**Verdict:** **Paid workflow is NOT accepted** while required production checks remain BLOCKED.

| # | Check | Result | Commands / evidence |
|---|---|---|---|
| 1 | DigiKey / Mouser / Newark deterministic matrix (exact, mismatch, no-hit, failure; missing stock/price → unknown; URL + retrieved_at) | **PASS** | `python -m pytest tests/test_supplier_provider_matrix.py -q` · executed via roadmap-gates CI hook |
| 2 | Newark URL contract: verified HTTPS www.newark.com only; reject bare newark.com and all other hosts | **PASS** (mocked) | `integrations/newark_client.py` `_OFFICIAL_NEWARK_HOSTS={"www.newark.com"}` · matrix `test_only_official_https_newark_url_is_verified` |
| 3 | Production sample of 15 distinct verified Newark offers (exact match, official URL, retrieval time) | **BLOCKED** | No NEWARK_API_KEY / live Element14 access. See `newark_production_sample.md`. |
| 4 | Supply Risk — complete / partial / absent stock coverage; missing stock never zero; stock-coverage gap explicit | **PASS** | complete/partial/absent tests · UI coverage gap copy |
| 5 | Absent stock preserves independently evidenced lifecycle / supplier risks; stock-based impact unavailable | **PASS** | `test_supply_scenario_absent_stock_preserves_lifecycle_and_supplier_risks` |
| 6 | Monitoring refresh read-only; Notify explicit (no email from refresh) | **PASS** | `tests/test_monitoring_read_only_refresh.py` |
| 7 | Idle Monitoring Notifying… fixed | **PASS** | `tests/test_monitoring_notify_idle_label.py` |
| 8 | Datasheet Q&A — citations bind to selected MPN, manufacturer, and synthetic source metadata | **PASS** | Fixture `synthetic` / `production_source_verification: not_claimed` — not live TI PDF proof |
| 9 | Family / wrong-part / identity-uncertain → Needs verification | **PASS** | Same suites + `tests/test_datasheet_qa_identity_api.py` |
| 10 | Two-user isolation in CI (workspaces, BOMs, reports, exports, decisions) | **PASS** (CI suite) | Postgres cutover + file-store suite via roadmap-gates hook |
| 11 | Production isolation with a second verified account | **BLOCKED** | Not exercised. No monitoring emails / no duplicate decisions. |
| 12 | Supplier offer rows show listing URL + retrieval time | **PASS** | `tests/test_procurement_offer_display.py` |
| 13 | CI status on this PR head (must include new suites) | **PENDING** | Suites run via `test_paid_promise_followup_pytest_suites_in_existing_ci_gate`. Intended workflow YAML: `alternative_finder_tests.intended.yml` (OAuth lacks workflow scope to push `.github/workflows`). Exact run URL in `CI_RUN.md`. |

## Explicit non-claims

- **15 live Newark offers:** BLOCKED — not accepted.
- **Production two-user isolation:** BLOCKED — CI-only.
- **Datasheet fixture ≠ live TI PDF:** synthetic paraphrased excerpts only.
- **Paid workflow overall:** **not accepted** while #3 and #11 remain BLOCKED.

## Local command bundle

```bash
cd .worktrees/paid-promise-followup
python -m pytest tests/test_supplier_provider_matrix.py -q
python -m pytest \
  tests/test_live_portfolio_and_supply_scenarios.py::test_supply_scenario_complete_stock_coverage_produces_affected_components \
  tests/test_live_portfolio_and_supply_scenarios.py::test_supply_scenario_partial_stock_coverage_exposes_gap \
  tests/test_live_portfolio_and_supply_scenarios.py::test_supply_scenario_absent_stock_preserves_lifecycle_and_supplier_risks \
  tests/test_post_605_generic_followup.py::SupplyRiskScopeClearTests -q
python -m unittest tests.test_datasheet_qa.DatasheetQaPaidPromiseSupplyTests -q
python -m pytest tests/test_datasheet_qa_identity_api.py tests/test_monitoring_read_only_refresh.py -q
python -m unittest tests.test_monitoring_notify_idle_label tests.test_procurement_offer_display -q
python -m pytest tests/test_nextjs_roadmap_gates.py::test_paid_promise_followup_pytest_suites_in_existing_ci_gate -q
```
