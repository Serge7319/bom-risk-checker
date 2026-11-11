# Evidence provenance reconciliation

## Changes
- Field-level provenance: identity / lifecycle / stock / price each keep source, retrieval time, and (for price) price type.
- Live identity no longer promotes synthetic/unlabeled prices to live.
- Detailed risk + cost optimization banners derive from row-level evidence counts for the selected analysis.
- Portfolio project health preserves `Not scored` (never coerces to `0`).
- Procurement and Cost Optimization share `analysis_id` context; absent prices show as blank/absent.
- Replacement search separates qualified alternatives from catalog leads; empty state does not claim “no candidates exist.”
- Unmatched sourcing copy: `Check an authorized source`.
- PDF/XLSX exports include assembly roll-ups and per-field provenance columns.

## Local verify
```
CADIVOR_ALLOW_EPHEMERAL_FILE_STORE=1 CADIVOR_ANALYSIS_MODE=synthetic-preview \
python3.12 -m unittest tests.test_evidence_provenance_reconciliation \
  tests.test_two_bom_smoke_parity.ExportAndSignalsTests \
  tests.test_procurement_advisor -v
```
Result: PASS.

Deploy/merge: not requested.
