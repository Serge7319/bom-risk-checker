# Next.js UI two-BOM smoke (PR #597 follow-up)

- Web: `http://127.0.0.1:3001`
- API: `http://127.0.0.1:8081`
- Overall: `PASS`
- Distinct project/BOM labels: `True`

## flat
- ok: `True`
- analysis_id: `cd637503-81e3-43f3-8e0b-0454548b485d`
- project: `PR597 Flat Smoke`
- bom_name: `flat-synthetic-25`
- analyze: `ok` — http://127.0.0.1:3001/bom-analyzer
- compare: `ok` — http://127.0.0.1:3001/compare-parts?analysis_id=cd637503-81e3-43f3-8e0b-0454548b485d
- decision_save: `ok`
- decision: `ok` — http://127.0.0.1:3001/engineering-decisions?analysis_id=cd637503-81e3-43f3-8e0b-0454548b485d
- replacement: `ok` — http://127.0.0.1:3001/find-replacement?analysis_id=cd637503-81e3-43f3-8e0b-0454548b485d&mpn=XC3S400-4PQG208C
- reports: `ok` — http://127.0.0.1:3001/reports/cd637503-81e3-43f3-8e0b-0454548b485d
- procurement: `ok` — http://127.0.0.1:3001/procurement
- design_impact: `ok` — http://127.0.0.1:3001/design-impact
- decision_snapshot_api: `ok`
- exports: `ok`

## nested
- ok: `True`
- analysis_id: `96478adf-bed1-43cc-9155-98f797385fed`
- project: `PR597 Nested Smoke`
- bom_name: `nested-product-hierarchy`
- analyze: `ok` — http://127.0.0.1:3001/bom-analyzer
- compare: `ok` — http://127.0.0.1:3001/compare-parts?analysis_id=96478adf-bed1-43cc-9155-98f797385fed
- decision_save: `ok`
- decision: `ok` — http://127.0.0.1:3001/engineering-decisions?analysis_id=96478adf-bed1-43cc-9155-98f797385fed
- replacement: `ok` — http://127.0.0.1:3001/find-replacement?analysis_id=96478adf-bed1-43cc-9155-98f797385fed&mpn=STM32F103
- reports: `ok` — http://127.0.0.1:3001/reports/96478adf-bed1-43cc-9155-98f797385fed
- procurement: `ok` — http://127.0.0.1:3001/procurement
- design_impact: `ok` — http://127.0.0.1:3001/design-impact
- decision_snapshot_api: `ok`
- exports: `ok`

## Checks covered
- Analyze with distinct project/BOM/revision labels
- Compare Parts performed for a real part pair
- Decision saved with comparison_snapshot reuse (snapshot trust)
- Engineering Decisions shows the saved pair + Hold for review
- Reports / Procurement / Design Impact show BOM-linked data
- PDF / XLSX / CSV contents include distinct labels and expected MPNs
