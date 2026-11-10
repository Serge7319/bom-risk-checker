# Next.js UI two-BOM smoke (Nov 10 production fixes)

- Web: `http://127.0.0.1:3011`
- API: `http://127.0.0.1:8081`
- Overall: `PASS`
- Distinct project/BOM labels: `True`

## flat
- ok: `True`
- analysis_id: `c72da60f-a50f-4f0c-9175-7240bd8f3a5f`
- project: `PR Nov10 Flat Smoke`
- bom_name: `flat-synthetic-25`
- analyze: `ok` — http://127.0.0.1:3011/bom-analyzer
- compare: `ok` — http://127.0.0.1:3011/compare-parts?analysis_id=c72da60f-a50f-4f0c-9175-7240bd8f3a5f
- decision_save: `ok`
- decision: `ok` — http://127.0.0.1:3011/engineering-decisions?analysis_id=c72da60f-a50f-4f0c-9175-7240bd8f3a5f
- replacement: `ok` — http://127.0.0.1:3011/find-replacement?analysis_id=c72da60f-a50f-4f0c-9175-7240bd8f3a5f&mpn=XC3S400-4PQG208C
- reports: `ok` — http://127.0.0.1:3011/reports/c72da60f-a50f-4f0c-9175-7240bd8f3a5f
- procurement: `ok` — http://127.0.0.1:3011/procurement
- design_impact: `ok` — http://127.0.0.1:3011/design-impact
- monitoring: `ok` — http://127.0.0.1:3011/monitoring?analysis_id=c72da60f-a50f-4f0c-9175-7240bd8f3a5f
- decision_snapshot_api: `ok`
- exports: `ok`

## nested
- ok: `True`
- analysis_id: `fbcfed8a-849f-4c38-98da-de553288cd99`
- project: `PR Nov10 Nested Smoke`
- bom_name: `nested-product-hierarchy`
- analyze: `ok` — http://127.0.0.1:3011/bom-analyzer
- compare: `ok` — http://127.0.0.1:3011/compare-parts?analysis_id=fbcfed8a-849f-4c38-98da-de553288cd99
- decision_save: `ok`
- decision: `ok` — http://127.0.0.1:3011/engineering-decisions?analysis_id=fbcfed8a-849f-4c38-98da-de553288cd99
- replacement: `ok` — http://127.0.0.1:3011/find-replacement?analysis_id=fbcfed8a-849f-4c38-98da-de553288cd99&mpn=STM32F103
- reports: `ok` — http://127.0.0.1:3011/reports/fbcfed8a-849f-4c38-98da-de553288cd99
- procurement: `ok` — http://127.0.0.1:3011/procurement
- design_impact: `ok` — http://127.0.0.1:3011/design-impact
- monitoring: `ok` — http://127.0.0.1:3011/monitoring?analysis_id=fbcfed8a-849f-4c38-98da-de553288cd99
- decision_snapshot_api: `ok`
- exports: `ok`

## Checks covered
- Analyze with distinct project/BOM/revision labels
- Compare Parts performed for a real part pair
- Decision saved with comparison_snapshot reuse (snapshot trust)
- Engineering Decisions shows the saved pair + Hold for review
- Reports / Procurement / Design Impact show BOM-linked data
- PDF / XLSX / CSV contents include distinct labels and expected MPNs

## Viewport checks
- 1440px: `PASS` (bad rows=0)
- 696px: `PASS` (bad rows=0)
- 390px: `PASS` (bad rows=0)

## Screenshots
- Real-route screenshots in this folder (`flat_*.png`, `nested_*.png`, `viewport_*.png`)
- Nested quantity roll-ups verified in CSV/XLSX/PDF exports
