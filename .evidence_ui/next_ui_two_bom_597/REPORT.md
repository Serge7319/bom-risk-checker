# Next.js UI two-BOM smoke (PR #597 follow-up)

- Web: `http://127.0.0.1:3001`
- API: `http://127.0.0.1:8081`
- Overall: `PASS`
- Distinct project/BOM labels: `True`

## flat
- ok: `True`
- analysis_id: `d3ad7ae5-2a8f-45da-bc19-d337a945a71c`
- project: `PR597 Flat Smoke`
- bom_name: `flat-synthetic-25`
- analyze: `ok` — http://127.0.0.1:3001/bom-analyzer
- compare: `ok` — http://127.0.0.1:3001/compare-parts?analysis_id=d3ad7ae5-2a8f-45da-bc19-d337a945a71c
- decision_save: `ok`
- decision: `ok` — http://127.0.0.1:3001/engineering-decisions?analysis_id=d3ad7ae5-2a8f-45da-bc19-d337a945a71c
- replacement: `ok` — http://127.0.0.1:3001/find-replacement?analysis_id=d3ad7ae5-2a8f-45da-bc19-d337a945a71c&mpn=XC3S400-4PQG208C
- reports: `ok` — http://127.0.0.1:3001/reports/d3ad7ae5-2a8f-45da-bc19-d337a945a71c
- procurement: `ok` — http://127.0.0.1:3001/procurement
- design_impact: `ok` — http://127.0.0.1:3001/design-impact
- monitoring: `ok` — http://127.0.0.1:3001/monitoring?analysis_id=d3ad7ae5-2a8f-45da-bc19-d337a945a71c
- decision_snapshot_api: `ok`
- exports: `ok`

## nested
- ok: `True`
- analysis_id: `44ad1d4a-ba09-4472-a2d0-222de6cb82f9`
- project: `PR597 Nested Smoke`
- bom_name: `nested-product-hierarchy`
- analyze: `ok` — http://127.0.0.1:3001/bom-analyzer
- compare: `ok` — http://127.0.0.1:3001/compare-parts?analysis_id=44ad1d4a-ba09-4472-a2d0-222de6cb82f9
- decision_save: `ok`
- decision: `ok` — http://127.0.0.1:3001/engineering-decisions?analysis_id=44ad1d4a-ba09-4472-a2d0-222de6cb82f9
- replacement: `ok` — http://127.0.0.1:3001/find-replacement?analysis_id=44ad1d4a-ba09-4472-a2d0-222de6cb82f9&mpn=STM32F103
- reports: `ok` — http://127.0.0.1:3001/reports/44ad1d4a-ba09-4472-a2d0-222de6cb82f9
- procurement: `ok` — http://127.0.0.1:3001/procurement
- design_impact: `ok` — http://127.0.0.1:3001/design-impact
- monitoring: `ok` — http://127.0.0.1:3001/monitoring?analysis_id=44ad1d4a-ba09-4472-a2d0-222de6cb82f9
- decision_snapshot_api: `ok`
- exports: `ok`

## Checks covered
- Analyze with distinct project/BOM/revision labels
- Compare Parts performed for a real part pair
- Decision saved with comparison_snapshot reuse (snapshot trust)
- Engineering Decisions shows the saved pair + Hold for review
- Reports / Procurement / Design Impact show BOM-linked data
- PDF / XLSX / CSV contents include distinct labels and expected MPNs
