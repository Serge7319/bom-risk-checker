# Newark production sample — 15 verified offers

**Status: BLOCKED**

The production sample of **15 verified Newark offers** was **not** collected in
this task. There was no live, credentialed production pull. No `NEWARK_API_KEY`
was used, and no request was made to `api.element14.com`. This file does not
claim any production-verified Newark offers, and no production sample data was
fabricated or substituted.

## What this task did verify (synthetic / mocked only)

`tests/test_supplier_provider_matrix.py` uses mocked Element14 responses. It
checks the official-URL behaviour of `integrations/newark_client.py`:

| Behaviour | Result |
| --- | --- |
| `https://www.newark.com/...` `productUrl` → `listing_verified=True`, URL shown | PASS |
| `https://newark.com/...` (official bare host) → verified | PASS |
| `http://www.newark.com/...` (not HTTPS) → rejected, URL empty | PASS |
| Foreign host, look-alike host (`www.newark.com.evil.example`), other distributor, relative path, blank → rejected | PASS |
| Missing `productUrl` + SKU → URL stays empty, `provenance_unavailable=True`, never built from the SKU | PASS |
| `id:<sku>` lookup returns a URL only when SKU, MPN, manufacturer and official HTTPS URL all verify | PASS |
| Exact MPN + manufacturer hit carries `product_detail_url` and `retrieved_at` | PASS |
| Manufacturer mismatch → `PART_NOT_FOUND`, no URL | PASS |
| No hit → `PART_NOT_FOUND`; timeout / HTTP 5xx → `TIMEOUT` / `PROVIDER_ERROR` (not a no-hit) | PASS |
| Missing stock / price stay `None` (explicit stock `0` stays `0`) | PASS |

These are mocked tests. They show that the code accepts only official Newark
HTTPS URLs and does not invent URLs. They are **not** evidence that real
production Newark listings resolve, that the live API returns these fields, or
that the 15-offer sample requirement is met.

## To unblock

1. Run with a production `NEWARK_API_KEY` and network access to `api.element14.com`.
2. Pull 15 distinct exact-MPN BOM lines through `search_newark_by_part_number`
   with the requested manufacturer set.
3. Keep only offers where `listing_verified` is true and `product_detail_url`
   starts with `https://www.newark.com/`. Record MPN, manufacturer, SKU, URL,
   stock, price and `retrieved_at` for each.
4. Attach the raw responses and replace this file with the real sample.

Until then: **15 verified production Newark offers = BLOCKED.**
