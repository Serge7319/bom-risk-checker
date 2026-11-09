# Next.js UI two-BOM smoke (PR #597 follow-up)

- Web: `http://127.0.0.1:3001`
- API: `http://127.0.0.1:8081`
- Overall: `PASS`

## flat
- ok: `True`
- analysis_id: `7f56a339-7a2e-4fce-a090-f81ccf01d388`
- analyze: `ok` — http://127.0.0.1:3001/bom-analyzer
- compare: `ok` — http://127.0.0.1:3001/compare-parts?analysis_id=7f56a339-7a2e-4fce-a090-f81ccf01d388
- replacement: `ok` — http://127.0.0.1:3001/find-replacement?analysis_id=7f56a339-7a2e-4fce-a090-f81ccf01d388
- decision: `ok` — http://127.0.0.1:3001/engineering-decisions
- reports: `ok` — http://127.0.0.1:3001/reports/7f56a339-7a2e-4fce-a090-f81ccf01d388
- procurement: `ok` — http://127.0.0.1:3001/procurement
- design_impact: `ok` — http://127.0.0.1:3001/design-impact
- exports: `ok` — 

## nested
- ok: `True`
- analysis_id: `f169c7ed-bc96-4629-9d20-a536f4e355ff`
- analyze: `ok` — http://127.0.0.1:3001/bom-analyzer
- compare: `ok` — http://127.0.0.1:3001/compare-parts?analysis_id=f169c7ed-bc96-4629-9d20-a536f4e355ff
- replacement: `ok` — http://127.0.0.1:3001/find-replacement?analysis_id=f169c7ed-bc96-4629-9d20-a536f4e355ff
- decision: `ok` — http://127.0.0.1:3001/engineering-decisions
- reports: `ok` — http://127.0.0.1:3001/reports/f169c7ed-bc96-4629-9d20-a536f4e355ff
- procurement: `ok` — http://127.0.0.1:3001/procurement
- design_impact: `ok` — http://127.0.0.1:3001/design-impact
- exports: `ok` —

## Export inspection notes
- Flat CSV: 26 rows (header + 25 parts), MPN column present; XLSX has Summary + Components; PDF parses as valid %PDF with extractable text.
- Nested CSV: hierarchy rows present (`PRODTOP` assembly, `PSUASM` child). BOM/project label in exports reused the flat draft name from the same browser session; part rows are from the nested fixture.
- Cloudflare Pages preview remains marketing-only and was not used for this check.
