# Newark catalog-search diagnostics (PR #608 amend)

Branch: `fix/newark-catalog-diagnostics` (rebased onto current `main`)  
Scope: Newark diagnostics only — no repeated #606 implementation/evidence.

## Fixes in this amend

1. Partial-term handling: exact + family terms keep candidate rows and surface per-term failures (`NewarkCatalogPartialResultsError`).
2. Empty success on one term cannot hide timeout/HTTP/auth/malformed on another (AM29 empty exact + family timeout → Timeout).
3. All catalog diagnostics deferred until suppliers settle; `retained_candidates` comes from the final merged candidate set (including zero-result lines).
4. Unconfigured Newark is configuration-only — no catalog request, no catalog-failure diagnostic.
5. Missing/malformed `keywordSearchReturn` / `products` treated as malformed (only `products: []` is empty success).

## Verification

| Suite | Result |
|---|---|
| `tests.test_newark_catalog_diagnostics` | 16 OK |
| `tests.test_alternative_finder_search` (+ Newark catalog keyword tests) | 26 OK |
| `tests.test_threaded_manufacturer_lookup` | 4 OK |

Evidence kept here is redacted (no API keys, credentialed URLs, or absolute developer paths).

## Remaining

Leave PR open for review — do not merge or deploy.
