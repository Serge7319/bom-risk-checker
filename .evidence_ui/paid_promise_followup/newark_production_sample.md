# Newark production sample — 15 verified offers

**Status: BLOCKED**

No live, credentialed production pull was possible in this update.

- `NEWARK_API_KEY` was **not** present in the agent environment.
- No request was made to `api.element14.com`.
- No production sample rows were fabricated or substituted from mocks.

## URL contract enforced in code (mocked)

Verified listings require:

1. HTTPS
2. Host exactly `www.newark.com` (bare `newark.com` **rejected**)
3. Exact MPN + manufacturer match when constrained
4. `retrieved_at` stamped on hits
5. Never fabricate a URL from SKU alone

Evidence: `tests/test_supplier_provider_matrix.py` · `integrations/newark_client.py`

## To unblock

1. Provide a production `NEWARK_API_KEY` with network access to Element14.
2. Pull ≥15 distinct exact-MPN BOM lines via `search_newark_by_part_number`.
3. Keep only offers where `listing_verified` is true and `product_detail_url` starts with `https://www.newark.com/`.
4. Record MPN, manufacturer, SKU, URL, stock, price, `retrieved_at` for each.
5. Attach raw responses and replace this file.

Until then: **15 verified production Newark offers = BLOCKED.**
