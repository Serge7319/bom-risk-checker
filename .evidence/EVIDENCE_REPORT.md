# Evidence-backed Compare Parts report — Ohmite RES10K vs RES10KE

## 1. Final bounded RES10K search — outcome
**No permitted source retrieved an exact Ohmite + RES10K verification.** RES10K remains **unverified**. The comparison is **incomplete** (one-sided: RES10KE verified; RES10K not).

Rules honored: no family-PDF inference, no part-number-pattern identity, DigiKey indexed listing is a discovery lead only, HTTP 403 bodies unused.

## 2. Sources checked for RES10K
- **linked_datasheet** (`manufacturer_or_supplier_datasheet`): status=`available`; identity_verified=`False`; url=`https://www.ohmite.com/assets/files/Datasheets/rheostats.pdf?r=false`; detail=The extracted text does not name the exact MPN RES10K.
- **Ohmite** (`manufacturer_product_page`): status=`redirect_loop`; identity_verified=`False`; url=`https://www.ohmite.com/catalog/rheostats/RES10K`; detail=The manufacturer page redirected too many times.
- **Ohmite** (`manufacturer_site_search`): status=`not_found`; identity_verified=`False`; url=`https://www.ohmite.com/catalog/?search=RES10K`; detail=Search page retrieved, but extractable text did not verify the exact MPN. No values were taken.
- **Ohmite** (`manufacturer_site_search`): status=`not_found`; identity_verified=`False`; url=`https://www.ohmite.com/?s=RES10K`; detail=Search page retrieved, but extractable text did not verify the exact MPN. No values were taken.
- **Ohmite** (`manufacturer_series_pdf`): status=`available`; identity_verified=`False`; url=`https://www.ohmite.com/assets/images/res-10.pdf?r=false`; detail=The extracted text does not name the exact MPN RES10K. Exact MPN RES10K was not verified in this Ohmite catalog/order-code material; no values were taken.
- **Ohmite** (`manufacturer_series_page`): status=`available`; identity_verified=`False`; url=`https://www.ohmite.com/res-10/`; detail=The extracted text does not name the exact MPN RES10K. Exact MPN RES10K was not verified in this Ohmite catalog/order-code material; no values were taken.
- **Ohmite** (`manufacturer_rheostat_guide`): status=`available`; identity_verified=`False`; url=`https://www.ohmite.com/guide-to-rheostats/`; detail=The extracted text does not name the exact MPN RES10K. Exact MPN RES10K was not verified in this Ohmite catalog/order-code material; no values were taken.
- **Mouser** (`authorized_distributor_api`): status=`not_configured`; identity_verified=`False`; url=`—`; detail=Mouser API credentials are not configured in this environment.
- **DigiKey** (`authorized_distributor_api`): status=`not_configured`; identity_verified=`False`; url=`—`; detail=DigiKey API credentials are not configured in this environment.
- **Newark** (`authorized_distributor_api`): status=`not_configured`; identity_verified=`False`; url=`—`; detail=Newark API credentials are not configured in this environment.
- **DigiKey** (`digikey_indexed_listing_lead`): status=`discovery_lead`; identity_verified=`False`; url=`https://www.digikey.com/en/products/detail/ohmite/RES10K/258353`; detail=Indexed DigiKey product listing recorded as a discovery lead only. Public HTML access is HTTP 403-blocked and is not used. Values are taken only if the permitted DigiKey API integration retrieves and cites this exact MPN.
- **DigiKey** (`authorized_distributor_api_lookup`): status=`not_configured`; identity_verified=`False`; url=`—`; detail=DigiKey API credentials are not configured. The indexed listing remains a discovery lead; RES10K values stay unverified.
- **digikey** (`digikey_product_search`): status=`http_blocked`; identity_verified=`False`; url=`https://www.digikey.com/en/products/result?keywords=RES10K`; detail=HTTP 403. The body was not used as evidence.
- **digikey** (`digikey_indexed_listing_probe`): status=`http_blocked`; identity_verified=`False`; url=`https://www.digikey.com/en/products/detail/ohmite/RES10K/258353`; detail=HTTP 403. The body was not used as evidence.
- **digikey** (`digikey_product_page`): status=`http_blocked`; identity_verified=`False`; url=`https://www.digikey.com/en/products/detail/ohmite/RES10K`; detail=HTTP 403. The body was not used as evidence.
- **mouser** (`mouser_product_search`): status=`timeout`; identity_verified=`False`; url=`https://www.mouser.com/c/?q=RES10K`; detail=The source timed out.
- **mouser** (`mouser_product_page`): status=`timeout`; identity_verified=`False`; url=`https://www.mouser.com/ProductDetail/Ohmite/RES10K`; detail=The source timed out.
- **newark** (`newark_product_search`): status=`timeout`; identity_verified=`False`; url=`https://www.newark.com/search?st=RES10K`; detail=The source timed out.
- **octopart** (`parts_aggregator_search`): status=`available`; identity_verified=`False`; url=`https://octopart.com/search?q=RES10K+Ohmite`; detail=Aggregator listing names the manufacturer and exact MPN, but aggregator pages are not used as authorized evidence for attribute values.

### DigiKey discovery lead
- URL: `https://www.digikey.com/en/products/detail/ohmite/RES10K/258353`
- Role: discovery lead only
- Public HTML: HTTP 403 (not used)
- DigiKey API: not configured — lead not retrievable through the permitted integration

## 3. RES10KE (unchanged verified side)
Source: `https://www.ohmite.com/catalog/rheostats/RES10KE` — identity verified.

| UI attribute | Value | Source field label |
|---|---|---|
| Resistance | 10000 | Ohms Value |
| Power rating | 12.50 | Watts |
| Volts | 305.000 | Volts |
| Diameter | 0.875 | Diameter (no unit) |
| Element type | Wirewound | Construction |
| Body | not attributed | Diameter not mapped |

## 4. Identity
- Part A: verified=`False` — The extracted text does not name the exact MPN RES10K.
- Part B: verified=`True` — Extracted text names Ohmite RES10KE.

## 5. Finding / KPI / fixtures
- Finding: **Material difference**
- Compatible 1 / Material 1 / Needs 15 / Rows 17 (KPI sum equals rows: **True**)
- One-sided evidence: Part B has manufacturer-verified values; Part A does not. Rows with Part B values and empty Part A remain Needs validation.
- 2 matrix row(s) use [Test fixture] stubs (Mounting, Lifecycle). Those rows are included in the Compatible / Material difference / Needs validation KPI totals and are not live manufacturer evidence.
- Production isolation: Mounting and Lifecycle [Test fixture] stubs contribute to visible KPI totals only when explicitly flagged on in-process test parts. lookup_part_for_compare strips fixture flags and clears fixture Mounting/Lifecycle values so synthetic stubs cannot enter the normal production evidence path as unlabeled catalog data.
- Fixture-isolation regression retained: `test_fixture_mounting_lifecycle_cannot_enter_production_compare_path`

## 6. Matrix

| Attribute | Part A | Part B | Assessment | Evidence |
|---|---|---|---|---|
| Mounting | [Test fixture] Panel Mount | [Test fixture] Panel Mount | Compatible on available evidence | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B manufacturer product page does not state this field. Part B value is from the supplier catalog. No manufacturer product page citation. Part A value is a [Test fixture] catalog/lifecycle stub, not live manufacturer evidence. Part B value is a [Test fixture] catalog/lifecycle stub, not live manufacturer evidence. |
| Temperature range | Not stated in retrieved evidence | Not stated in this manufacturer product page | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B manufacturer product page does not state this field. |
| Lifecycle | [Test fixture] Supplier A: Active (2024-01-02T00:00:00Z); Supplier B: Obsolete (2024-03-04T00:00:00Z) | [Test fixture] Active | Material difference | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B manufacturer product page does not state this field. Part B value is from the supplier catalog. No manufacturer product page citation. Part A value is a [Test fixture] catalog/lifecycle stub, not live manufacturer evidence. Part B value is a [Test fixture] catalog/lifecycle stub, not live manufacturer evidence. |
| Resistance | Not stated in retrieved evidence | 10000 | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B Manufacturer product page p. attributes. Source URL: https://www.ohmite.com/catalog/rheostats/RES10KE. Source field label: Ohms Value. Excerpt: Ohms Value: 10000. Extraction method: manufacturer product HTML. |
| Tolerance | Not stated in retrieved evidence | Not stated in this manufacturer product page | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B manufacturer product page does not state this field. |
| Power rating | Not stated in retrieved evidence | 12.50 | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B Manufacturer product page p. attributes. Source URL: https://www.ohmite.com/catalog/rheostats/RES10KE. Source field label: Watts. Excerpt: Watts: 12.50. Extraction method: manufacturer product HTML. |
| Volts | Not stated in retrieved evidence | 305.000 | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B Manufacturer product page p. attributes. Source URL: https://www.ohmite.com/catalog/rheostats/RES10KE. Source field label: Volts. Excerpt: Volts: 305.000. Extraction method: manufacturer product HTML. |
| Taper | Not stated in retrieved evidence | Not stated in this manufacturer product page | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B manufacturer product page does not state this field. |
| Element type | Not stated in retrieved evidence | Wirewound | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B Manufacturer product page p. attributes. Source URL: https://www.ohmite.com/catalog/rheostats/RES10KE. Source field label: Construction. Excerpt: Construction: Wirewound. Extraction method: manufacturer product HTML. |
| Turns | Not stated in retrieved evidence | Not stated in this manufacturer product page | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B manufacturer product page does not state this field. |
| Rotation | Not stated in retrieved evidence | Not stated in this manufacturer product page | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B manufacturer product page does not state this field. |
| Terminal style | Not stated in retrieved evidence | Not stated in this manufacturer product page | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B manufacturer product page does not state this field. |
| Terminal count | Not stated in retrieved evidence | Not stated in this manufacturer product page | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B manufacturer product page does not state this field. |
| Shaft | Not stated in retrieved evidence | Not stated in this manufacturer product page | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B manufacturer product page does not state this field. |
| Bushing | Not stated in retrieved evidence | Not stated in this manufacturer product page | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B manufacturer product page does not state this field. |
| Diameter | Not stated in retrieved evidence | 0.875 | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B Manufacturer product page p. attributes. Source URL: https://www.ohmite.com/catalog/rheostats/RES10KE. Source field label: Diameter. Excerpt: Diameter: 0.875. Extraction method: manufacturer product HTML. |
| Body | Not stated in retrieved evidence | Not stated in this manufacturer product page | Needs data / engineering validation | Part A datasheet was not used. The extracted text does not name the exact MPN RES10K. Part B manufacturer product page does not state this field. |

## 7. Warnings
- Part A: The extracted text does not name the exact MPN RES10K.
- Drop-in fit is unverified: Temperature range, Resistance, Tolerance, Power rating, Volts, Taper, Element type, Turns, Rotation, Terminal style, Terminal count, Shaft, Bushing, Diameter, and Body are not stated in the verified datasheet. Those values were not inferred.

Needs-validation (15): Temperature range, Resistance, Tolerance, Power rating, Volts, Taper, Element type, Turns, Rotation, Terminal style, Terminal count, Shaft, Bushing, Diameter, Body

## 8. Focused tests
```text
/tmp/cadivor-st160/bin/python -m unittest tests.test_rheostat_evidence_comparison -q
# Ran 12 — OK

/tmp/cadivor-st160/bin/python -m unittest tests.test_compare_parts -q
# Ran 21 — 2 FAIL (baseline only)
```

| Failing test | Baseline? |
|---|---|
| `test_approved_compare_page_wires_the_add_part_slot` | Yes |
| `test_nav_and_runtime_wire_compare_parts` | Yes |

New failures: none.

## 9. Completeness
Comparison remains **incomplete**: RES10KE has manufacturer-verified product-page values; RES10K has no permitted exact-MPN source that could be retrieved and cited.
