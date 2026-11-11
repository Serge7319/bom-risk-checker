# Next.js UI two-BOM smoke (Nov 10 production fixes)

- Web: `http://127.0.0.1:3011`
- API: `http://127.0.0.1:8081`
- Overall: `PASS`
- Distinct project/BOM labels: `True`

## flat
- ok: `True`
- analysis_id: `44129d59-0109-40be-aad3-ae2cb4ba233d`
- project: `PR Nov10 Flat Smoke`
- bom_name: `flat-synthetic-25`
- analyze: `ok` — http://127.0.0.1:3011/bom-analyzer
- compare: `ok` — http://127.0.0.1:3011/compare-parts?analysis_id=44129d59-0109-40be-aad3-ae2cb4ba233d
- decision_save: `ok`
- decision: `ok` — http://127.0.0.1:3011/engineering-decisions?analysis_id=44129d59-0109-40be-aad3-ae2cb4ba233d
- replacement: `ok` — http://127.0.0.1:3011/find-replacement?analysis_id=44129d59-0109-40be-aad3-ae2cb4ba233d&mpn=XC3S400-4PQG208C
- reports: `ok` — http://127.0.0.1:3011/reports/44129d59-0109-40be-aad3-ae2cb4ba233d
- procurement: `ok` — http://127.0.0.1:3011/procurement?analysis_id=44129d59-0109-40be-aad3-ae2cb4ba233d
- design_impact: `ok` — http://127.0.0.1:3011/design-impact
- monitoring: `ok` — http://127.0.0.1:3011/monitoring?analysis_id=44129d59-0109-40be-aad3-ae2cb4ba233d
- decision_snapshot_api: `ok`
- exports: `ok`

## nested
- ok: `True`
- analysis_id: `fa42459c-35c8-43de-a14b-1cb0aaf3c29a`
- project: `PR Nov10 Nested Smoke`
- bom_name: `nested-product-hierarchy`
- analyze: `ok` — http://127.0.0.1:3011/bom-analyzer
- compare: `ok` — http://127.0.0.1:3011/compare-parts?analysis_id=fa42459c-35c8-43de-a14b-1cb0aaf3c29a
- decision_save: `ok`
- decision: `ok` — http://127.0.0.1:3011/engineering-decisions?analysis_id=fa42459c-35c8-43de-a14b-1cb0aaf3c29a
- replacement: `ok` — http://127.0.0.1:3011/find-replacement?analysis_id=fa42459c-35c8-43de-a14b-1cb0aaf3c29a&mpn=STM32F103
- reports: `ok` — http://127.0.0.1:3011/reports/fa42459c-35c8-43de-a14b-1cb0aaf3c29a
- procurement: `ok` — http://127.0.0.1:3011/procurement?analysis_id=fa42459c-35c8-43de-a14b-1cb0aaf3c29a
- design_impact: `ok` — http://127.0.0.1:3011/design-impact
- monitoring: `ok` — http://127.0.0.1:3011/monitoring?analysis_id=fa42459c-35c8-43de-a14b-1cb0aaf3c29a
- decision_snapshot_api: `ok`
- exports: `ok`

## Checks covered
- Analyze with distinct project/BOM/revision labels
- Compare Parts performed for a real part pair
- Decision saved with comparison_snapshot reuse (snapshot trust)
- Engineering Decisions shows the saved pair + Hold for review
- Reports / Procurement / Design Impact show BOM-linked data
- PDF / XLSX / CSV contents include distinct labels and expected MPNs
