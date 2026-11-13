# CI workflow delta (not applied in this push)

GitHub rejected pushing `.github/workflows/alternative_finder_tests.yml` because the
active OAuth token lacks the `workflow` scope.

## Apply with a workflow-scoped token

```bash
gh auth refresh -h github.com -s workflow
# then cherry-pick / re-apply the YAML changes below onto this branch and push
```

## Intended additions to `.github/workflows/alternative_finder_tests.yml`

After the disposable Postgres step, add:

```yaml
      - name: Run file-store two-user isolation matrix
        run: python -m pytest tests/test_workspace_isolation.py -q
```

In the Alternative Finder unittest list, add:

```text
            tests.test_supplier_provider_matrix \
```

Then add these steps (before/around monitoring steps):

```yaml
      - name: Run DigiKey/Mouser/Newark provider matrix (pytest)
        run: python -m pytest tests/test_supplier_provider_matrix.py -q

      - name: Run Supply Risk inventory + scope acceptance
        run: |
          python -m pytest \
            tests/test_live_portfolio_and_supply_scenarios.py::test_supply_scenario_does_not_treat_missing_stock_or_sources_as_zero \
            tests/test_live_portfolio_and_supply_scenarios.py::test_supply_scenario_with_inventory_produces_affected_components \
            tests/test_live_portfolio_and_supply_scenarios.py::test_supply_scenario_uses_recorded_stock_and_lead_time_delta \
            tests/test_live_portfolio_and_supply_scenarios.py::test_supply_scenario_treats_unknown_text_fields_as_unrecorded_not_zero \
            tests/test_post_605_generic_followup.py::SupplyRiskScopeClearTests \
            -q

      - name: Run Datasheet Q&A positive + identity abstention
        run: |
          python -m pytest \
            tests/test_datasheet_qa.py \
            tests/test_datasheet_qa_identity_api.py \
            -q

      - name: Run On-demand Monitoring Supplier Refresh Tests
        run: python -m unittest tests.test_monitoring_refresh tests.test_monitoring_notify_idle_label

      - name: Run Monitoring read-only refresh + explicit Notify
        run: python -m pytest tests/test_monitoring_read_only_refresh.py -q
```

## Already in CI without this delta

- Disposable Postgres two-user isolation via `tests/test_cutover_disposable_db.py`
