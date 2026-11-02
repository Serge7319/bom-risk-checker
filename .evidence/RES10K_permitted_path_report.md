# RES10K exact-MPN evidence — permitted path report

Branch: `fix/datasheet-first-part-compare` (isolated worktree). Uncommitted. No push/PR/merge/deploy.

## Verdict

**RES10K remains unverified** on live manufacturer/distributor retrieval in this environment. DigiKey public HTML for the indexed listing is HTTP 403 and is **not** used. Values are shown only after Ohmite + exact MPN identity is verified (API retrieval or Compare Parts upload).

## Permitted source paths

| Path | Integration | Configuration needed |
|------|-------------|----------------------|
| **DigiKey API** (preferred authorized distributor) | `integrations/digikey_client.py` | Product secrets: `DIGIKEY_CLIENT_ID`, `DIGIKEY_CLIENT_SECRET` |
| Mouser API | `integrations/mouser_client.py` | `MOUSER_API_KEY` |
| Newark / element14 API | `integrations/newark_client.py` | `NEWARK_API_KEY` |
| **Exact-MPN datasheet upload** | Compare Parts → *Optional: upload exact-MPN datasheet* | None (PDF must name manufacturer + exact MPN) |

Do not paste secrets into chat. Configure via the product secrets store / environment.

Discovery lead (not evidence): `https://www.digikey.com/en/products/detail/ohmite/RES10K/258353`

## Implementation (uncommitted)

- `document_from_uploaded_datasheet` + `datasheet_uploads=` on `run_compare_parts`
- Compare Parts UI uploaders for Part A / Part B
- `access_blockers` on comparison results (provider, required config names, detail)
- DigiKey `not_configured` detail names both secret keys
- Cite uploaded values only after `verify_datasheet_identity` (Ohmite + RES10K)

## Test report

- `tests.test_rheostat_evidence_comparison` — **13 passed** (includes upload cite / reject + DigiKey config wording)
- `tests.test_compare_parts.ComparePartsUiWiringTests.test_compare_parts_page_wires_exact_mpn_datasheet_upload` — **passed**
- Baseline `test_nav_and_runtime_wire_compare_parts` still fails independently (runtime lazy-import), unrelated to this change

Evidence artifacts: `.evidence/res10k_permitted_path_report.json`, `.evidence/compare_result.json`

## Upload verification (fixture)

With an uploaded PDF naming Ohmite and RES10K: Part A Resistance cites `10 kOhm`. Without upload / without API credentials: Part A Resistance stays `Not stated in retrieved evidence`.
