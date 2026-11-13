# Paid-promise follow-up acceptance matrix

**PR:** https://github.com/Serge7319/bom-risk-checker/pull/626  
**Branch:** `release/paid-promise-followup-gaps`  
**Head:** `0f6014e2926f368f0be5ede6b25043b1d7409783`  
**Base:** `main` @ `2c44ce3` (merged PR #625)  
**Evidence dir:** `.evidence_ui/paid_promise_followup/`  
**Verdict:** **Paid workflow is NOT accepted** while required production checks remain BLOCKED.



| # | Check | Result | Commands / evidence |
|---|---|---|---|
| 1 | DigiKey / Mouser / Newark deterministic matrix (exact match, mismatch, no hit, provider failure, missing stock/price → unknown/`None`, offer URL + `retrieved_at`) | **PASS** | `python -m unittest tests.test_supplier_provider_matrix -q` → 31+ cases OK. Evidence: `tests/test_supplier_provider_matrix.py`. Clients: `integrations/{digikey,mouser,newark}_client.py`, aggregator null-price path. Display: `apps/web/src/app/procurement/page.tsx` shows each offer’s listing URL + Retrieved timestamp. |
| 2 | Newark official `https://www.newark.com/...` only; never fabricate from SKU | **PASS** (mocked) | Covered in provider matrix (`test_only_official_https_newark_url_is_verified`, `test_missing_product_url_is_never_fabricated_from_sku`). |
| 3 | Production sample of 15 distinct verified Newark offers | **BLOCKED** | `.evidence_ui/paid_promise_followup/newark_production_sample.md` — no live credentialed pull; sample not fabricated. |
| 4 | Supply Risk inventory contract — synthetic BOM with inventory → affected components; analysis / portfolio / clear scopes | **PASS** | `python -m unittest tests.test_post_605_generic_followup.SupplyRiskScopeClearTests -v`; `python -c` / pytest `tests/test_live_portfolio_and_supply_scenarios.py` (`test_supply_scenario_with_inventory_produces_affected_components`). |
| 5 | Absent inventory → “inventory evidence unavailable” (not zero-impact) | **PASS** | Scenario + payload + UI EmptyState. Tests: `test_supply_scenario_does_not_treat_missing_stock_or_sources_as_zero`, `test_missing_inventory_is_unavailable_not_zero_impact`, supply-risk page source asserts. |
| 6 | Monitoring refresh must not email / write alerts as Notify; Notify is explicit | **PASS** | `python -m pytest tests/test_monitoring_read_only_refresh.py -q`; `python -m unittest tests.test_monitoring_notify_idle_label -q`. Refresh note: “Email was not sent — use Notify”. |
| 7 | Idle Monitoring “Notifying…” label fixed | **PASS** | Gate is `a.id && notifying === String(a.id)` in `apps/web/src/app/monitoring/page.tsx`. Test: `tests/test_monitoring_notify_idle_label.py`. |
| 8 | Datasheet Q&A positive answer on part-specific official datasheet URL; citations bound to MPN + manufacturer | **PASS** | Fixture `tests/fixtures/datasheets/lm358dr_ti_excerpts.json` → `https://www.ti.com/lit/ds/symlink/lm358.pdf`. `DatasheetQaPaidPromiseSupplyTests` + `tests/test_datasheet_qa_identity_api.py`. |
| 9 | Family-only / wrong-part / identity-uncertain → Needs verification | **PASS** | Same suites (`test_wrong_component_citation_is_rejected`, `test_prefix_of_longer_mpn_does_not_bind`, `test_variant_ambiguity_needs_verification`, API wrong-part abstention). |
| 10 | Two-user isolation in CI (workspaces, BOMs, reports, exports, decisions) | **PASS** (CI suite) | Disposable Postgres already in AF workflow; this PR also wires `tests/test_workspace_isolation.py` (file-store). Commands: `python -m pytest tests/test_cutover_disposable_db.py -q`; `python -m pytest tests/test_workspace_isolation.py -q`. |
| 11 | Production isolation with a second verified account | **BLOCKED** | No second production account exercised in this follow-up. Do not claim production isolation. |
| 12 | CI status for this PR head | **PENDING** (regression-tests in progress; Cloudflare Pages PASS) | Run: https://github.com/Serge7319/bom-risk-checker/actions/runs/43527520259 — Postgres two-user isolation already in AF workflow. Extra suite wiring: `CI_WORKFLOW_DELTA.md` (YAML push blocked without `workflow` scope). |

## Explicit non-claims

- **15 live Newark offers:** BLOCKED — not accepted.
- **Production two-user isolation:** BLOCKED — CI-only.
- **Paid workflow overall:** **not accepted** while #3 and #11 remain BLOCKED.

## Local command bundle (evidence)

```bash
cd .worktrees/paid-promise-followup
python -m unittest tests.test_supplier_provider_matrix -q
python -m unittest tests.test_post_605_generic_followup.SupplyRiskScopeClearTests -v
python -m unittest tests.test_datasheet_qa.DatasheetQaPaidPromiseSupplyTests -v
python -m unittest tests.test_monitoring_notify_idle_label -q
python -m pytest tests/test_live_portfolio_and_supply_scenarios.py tests/test_monitoring_read_only_refresh.py tests/test_datasheet_qa_identity_api.py -q
```
