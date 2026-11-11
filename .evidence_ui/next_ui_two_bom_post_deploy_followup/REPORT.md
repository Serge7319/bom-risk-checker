# Next.js UI two-BOM smoke (Nov 10 production fixes)

- Web: `http://127.0.0.1:3011`
- API: `http://127.0.0.1:8081`
- Overall: `PASS`
- Distinct project/BOM labels: `True`

## flat
- ok: `True`
- analysis_id: `9cd2d041-7370-4537-8b59-14f2c9f2b7e7`
- project: `PR Nov10 Flat Smoke`
- bom_name: `flat-synthetic-25`
- analyze: `ok` — http://127.0.0.1:3011/bom-analyzer
- compare: `ok` — http://127.0.0.1:3011/compare-parts?analysis_id=9cd2d041-7370-4537-8b59-14f2c9f2b7e7
- decision_save: `ok`
- decision: `ok` — http://127.0.0.1:3011/engineering-decisions?analysis_id=9cd2d041-7370-4537-8b59-14f2c9f2b7e7
- replacement: `ok` — http://127.0.0.1:3011/find-replacement?analysis_id=9cd2d041-7370-4537-8b59-14f2c9f2b7e7&mpn=XC3S400-4PQG208C
- reports: `ok` — http://127.0.0.1:3011/reports/9cd2d041-7370-4537-8b59-14f2c9f2b7e7
- procurement: `ok` — http://127.0.0.1:3011/procurement?analysis_id=9cd2d041-7370-4537-8b59-14f2c9f2b7e7
- design_impact: `ok` — http://127.0.0.1:3011/design-impact
- monitoring: `ok` — http://127.0.0.1:3011/monitoring?analysis_id=9cd2d041-7370-4537-8b59-14f2c9f2b7e7
- decision_snapshot_api: `ok`
- exports: `ok`

## nested
- ok: `True`
- analysis_id: `e1f194d8-e210-4624-a3e7-a82693f9a70e`
- project: `PR Nov10 Nested Smoke`
- bom_name: `nested-product-hierarchy`
- analyze: `ok` — http://127.0.0.1:3011/bom-analyzer
- compare: `ok` — http://127.0.0.1:3011/compare-parts?analysis_id=e1f194d8-e210-4624-a3e7-a82693f9a70e
- decision_save: `ok`
- decision: `ok` — http://127.0.0.1:3011/engineering-decisions?analysis_id=e1f194d8-e210-4624-a3e7-a82693f9a70e
- replacement: `ok` — http://127.0.0.1:3011/find-replacement?analysis_id=e1f194d8-e210-4624-a3e7-a82693f9a70e&mpn=STM32F103
- reports: `ok` — http://127.0.0.1:3011/reports/e1f194d8-e210-4624-a3e7-a82693f9a70e
- procurement: `ok` — http://127.0.0.1:3011/procurement?analysis_id=e1f194d8-e210-4624-a3e7-a82693f9a70e
- design_impact: `ok` — http://127.0.0.1:3011/design-impact
- monitoring: `ok` — http://127.0.0.1:3011/monitoring?analysis_id=e1f194d8-e210-4624-a3e7-a82693f9a70e
- decision_snapshot_api: `ok`
- exports: `ok`

## Checks covered
- Analyze with distinct project/BOM/revision labels
- Compare Parts performed for a real part pair
- Decision saved with comparison_snapshot reuse (snapshot trust)
- Engineering Decisions shows the saved pair + Hold for review
- Reports / Procurement / Design Impact show BOM-linked data
- PDF / XLSX / CSV contents include distinct labels and expected MPNs

## Follow-up API checks (`followup_api_checks.json`)
- LM358N without manufacturer → `identity_ambiguous` with TI + onsemi choices, 0 candidates
- Supply Risk with nested `analysis_id` → `scope=analysis`, `source_part_count=8`
- Supply Risk without `analysis_id` → `scope=portfolio` across both analyses
- Unit regressions: 21 passed (`pytest.txt`)
