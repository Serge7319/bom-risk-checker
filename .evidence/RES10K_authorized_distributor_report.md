# RES10K authorized distributor recheck

Branch: `fix/datasheet-first-part-compare` (uncommitted). `fix/layout-followup` untouched.

## Live retrieval (Cadivor product fetcher)

| Source | URL | Status | Used for values? |
|--------|-----|--------|------------------|
| Arrow authorized product page | https://www.arrow.com/en/products/res10k/ohmite | **timeout** | No — fail closed |
| Galco authorized product page | https://www.galco.com/buy/Ohmite/RES10K (and res10k-ohm.html probe) | **http_blocked (Cloudflare)** | No — body unused |
| Ohmite RES10KE manufacturer page | https://www.ohmite.com/catalog/rheostats/RES10KE/ | available / identity verified when retrieved | Yes for Part B |

### Specific blockers (before API credentials or PDF upload)

1. **Arrow:** product fetcher with `CadivorEngineeringReview/1.0` times out / connection aborts. No browser-UA bypass was used. Page is wired into Compare Parts evidence path and will cite values only when retrieval succeeds and text names Ohmite + RES10K.
2. **Galco:** Cloudflare interstitial / HTTP 403. Challenge body is never used as evidence.
3. Only after these page-access blockers: configure DigiKey `DIGIKEY_CLIENT_ID` + `DIGIKEY_CLIENT_SECRET`, or upload an exact-MPN datasheet via Compare Parts.

## Implementation

- Authorized distributor candidates for Ohmite RES10K: Arrow + Galco
- HTML parse supports JSON-LD PropertyValue, attribute tables, and heading pairs
- Values require Ohmite + exact MPN; URL slug alone rejected
- Source field labels preserved (e.g. `Resistance Value (Ohm)`, `Maximum Voltage Rating (V)`); no RMS invention
- Series/`Family/Series` kept separate from exact-part compare aliases
- `retrieved_at` recorded on source status rows
- Access blockers surface Arrow/Galco statuses before API/upload recommendations

## Fixture compare (Arrow accessible → vs Ohmite RES10KE)

Finding: **Needs data / engineering validation**  
Counts: compatible=4, material=0, needs=13  
KPI sum matches visible rows: **True**

## Tests

`tests.test_rheostat_evidence_comparison` — **14 passed** (identity, wrong-part rejection, label/unit preservation, conflicts, fail-closed timeout/403).
