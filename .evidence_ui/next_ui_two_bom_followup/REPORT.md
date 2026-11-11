# Next.js UI two-BOM smoke (Nov 10 production fixes)

- Web: `http://127.0.0.1:3011`
- API: `http://127.0.0.1:8081`
- Overall: `PASS`
- Distinct project/BOM labels: `True`

## flat
- ok: `True`
- analysis_id: `3a28f91e-05aa-4325-9744-a0a667a43fdf`
- project: `PR Nov10 Flat Smoke`
- bom_name: `flat-synthetic-25`
- analyze: `ok` — http://127.0.0.1:3011/bom-analyzer
- compare: `ok` — http://127.0.0.1:3011/compare-parts?analysis_id=3a28f91e-05aa-4325-9744-a0a667a43fdf
- decision_save: `ok`
- decision: `ok` — http://127.0.0.1:3011/engineering-decisions?analysis_id=3a28f91e-05aa-4325-9744-a0a667a43fdf
- replacement: `ok` — http://127.0.0.1:3011/find-replacement?analysis_id=3a28f91e-05aa-4325-9744-a0a667a43fdf&mpn=XC3S400-4PQG208C
- reports: `ok` — http://127.0.0.1:3011/reports/3a28f91e-05aa-4325-9744-a0a667a43fdf
- procurement: `ok` — http://127.0.0.1:3011/procurement?analysis_id=3a28f91e-05aa-4325-9744-a0a667a43fdf
- design_impact: `ok` — http://127.0.0.1:3011/design-impact
- monitoring: `ok` — http://127.0.0.1:3011/monitoring?analysis_id=3a28f91e-05aa-4325-9744-a0a667a43fdf
- decision_snapshot_api: `ok`
- exports: `ok`

## nested
- ok: `True`
- analysis_id: `3774bbf3-29df-44a4-bbbc-258038874df5`
- project: `PR Nov10 Nested Smoke`
- bom_name: `nested-product-hierarchy`
- analyze: `ok` — http://127.0.0.1:3011/bom-analyzer
- compare: `ok` — http://127.0.0.1:3011/compare-parts?analysis_id=3774bbf3-29df-44a4-bbbc-258038874df5
- decision_save: `ok`
- decision: `ok` — http://127.0.0.1:3011/engineering-decisions?analysis_id=3774bbf3-29df-44a4-bbbc-258038874df5
- replacement: `ok` — http://127.0.0.1:3011/find-replacement?analysis_id=3774bbf3-29df-44a4-bbbc-258038874df5&mpn=STM32F103
- reports: `ok` — http://127.0.0.1:3011/reports/3774bbf3-29df-44a4-bbbc-258038874df5
- procurement: `ok` — http://127.0.0.1:3011/procurement?analysis_id=3774bbf3-29df-44a4-bbbc-258038874df5
- design_impact: `ok` — http://127.0.0.1:3011/design-impact
- monitoring: `ok` — http://127.0.0.1:3011/monitoring?analysis_id=3774bbf3-29df-44a4-bbbc-258038874df5
- decision_snapshot_api: `ok`
- exports: `ok`

## Checks covered
- Analyze with distinct project/BOM/revision labels
- Compare Parts performed for a real part pair
- Decision saved with comparison_snapshot reuse (snapshot trust)
- Engineering Decisions shows the saved pair + Hold for review
- Reports / Procurement / Design Impact show BOM-linked data
- PDF / XLSX / CSV contents include distinct labels and expected MPNs
