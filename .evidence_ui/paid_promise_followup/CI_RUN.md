# CI run for PR #626 (suites included)

**PR:** https://github.com/Serge7319/bom-risk-checker/pull/626  
**Exact head SHA:** `6c7c7f2267b720c9c05e0cc8a8d9f2f11b0d222e`  
**Exact run URL:** https://github.com/Serge7319/bom-risk-checker/actions/runs/43530288479  
**Result:** **success** (`regression-tests` job completed successfully)

## How the new suites ran on this head

OAuth lacked the `workflow` scope, so `.github/workflows/alternative_finder_tests.yml` could not be pushed. The intended YAML is stored at:

`alternative_finder_tests.intended.yml`

On this head the suites still execute inside the existing disposable-Postgres CI step via:

`tests/test_nextjs_roadmap_gates.py::test_paid_promise_followup_pytest_suites_in_existing_ci_gate`

That gate subprocesses:

- `tests/test_supplier_provider_matrix.py`
- Supply Risk complete/partial/absent stock scenario tests
- `tests/test_post_605_generic_followup.py::SupplyRiskScopeClearTests`
- `tests/test_datasheet_qa.py::DatasheetQaPaidPromiseSupplyTests`
- `tests/test_datasheet_qa_identity_api.py`
- `tests/test_monitoring_read_only_refresh.py`
- `tests/test_monitoring_notify_idle_label.py`
- `tests/test_procurement_offer_display.py`
- `tests/test_workspace_isolation.py`

CI collected **23** tests for `test_cutover_disposable_db.py` + `test_nextjs_roadmap_gates.py` (including the paid-promise gate) and reported **23 passed**.

## Production gates

Still **BLOCKED** (not accepted):

1. 15 live Newark offers — no `NEWARK_API_KEY` / Element14 access  
2. Second verified production account isolation — not exercised  

**Paid workflow remains not accepted.**
