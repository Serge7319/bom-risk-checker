# Newark catalog-search production evidence (redacted)

Source: production Alternative Finder verification for `AM29F010B-70EC`  
Correlator: `request_id=cf31d9b17119`  
Captured during provider-credential verification (2026-11-07).  
No API keys, tokens, credentialed request URLs, or absolute developer paths.

## Observed behavior

Exact-lookup diagnostics logged `zero_results` for all three suppliers. Separately, Newark **catalog search** failed with a generic message while DigiKey/Mouser catalog paths remained usable and Mouser candidates were retained:

```text
ALT_FINDER_SUPPLIER_DIAG request_id=cf31d9b17119 supplier=Newark category=provider_response subreason=zero_results status_code=none retryable=false
ALT_FINDER_SUPPLIER_DIAG request_id=cf31d9b17119 supplier=DigiKey category=provider_response subreason=zero_results status_code=none retryable=false
ALT_FINDER_SUPPLIER_DIAG request_id=cf31d9b17119 supplier=Mouser category=provider_response subreason=zero_results status_code=none retryable=false
configured_supplier_count 3
candidate_count 18
search_outcome partial_success
providers:
  Newark {'lookup': 'error', 'catalog': 'error', 'substitutions': 'not_supported', 'family_search': 'error', 'message': 'Newark catalog candidate search did not return a usable response.'}
  DigiKey {'lookup': 'available', 'catalog': 'ok', 'substitutions': 'ok', 'family_search': 'ok', 'catalog_count': 0}
  Mouser {'lookup': 'available', 'catalog': 'ok', 'substitutions': 'not_supported', 'family_search': 'ok', 'catalog_count': 19}
providers_returning_results ['Mouser']
```

## Gap addressed by this PR

1. Opaque RuntimeError hid timeout / HTTP / auth / malformed distinctions.
2. Empty success on one term could hide a failed sibling term.
3. Catalog diagnostics did not defer `retained_candidates` until the merged candidate set was known.
4. Lookup `zero_results` lines were easy to confuse with catalog failure (now `stage=catalog_search`).
