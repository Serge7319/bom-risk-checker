# RES10K RS Group probe

Branch: `fix/datasheet-first-part-compare` (uncommitted). `fix/layout-followup` untouched.

## DigiKey credentials (values never printed)

| Secret | Status |
|--------|--------|
| DIGIKEY_CLIENT_ID | missing |
| DIGIKEY_CLIENT_SECRET | missing |

## RS Group (Ohmite-authorized; stock 70585847)

| Item | Result |
|------|--------|
| Search/stock listing | Discovery lead only: `https://uk.rs-online.com/web/c/?searchTerm=70585847` — snippets not used as evidence |
| UK detail `.../web/p/potentiometers/70585847` | **http_blocked** at 2026-10-28T23:07:46Z — body unused |
| US detail `.../product/ohmite/res10k/70585847/` | **http_blocked** at 2026-10-28T23:07:46Z — body unused |
| RES10K identity verified from RS | **False** |

## Stop

Exact RS Group product-detail pages returned HTTP 403 via the permitted Cadivor product-fetch path. Search listing remains a discovery lead only (snippets not used). No RES10K values were taken. Synthetic RES10K vs RES10KE comparison was not run.

Synthetic RES10K vs RES10KE comparison **not run** (no verifiable RS exact-part fields).

After this RS page-access blocker: configure DigiKey credentials or upload an exact-MPN datasheet naming Ohmite and RES10K. Arrow/Galco blocks were not bypassed.
