# PR #605 — threaded manufacturer lookup fix

## Problem
`digikey_requested_manufacturer` ContextVar was set around `get_best_part_data`, but DigiKey lookups run inside `ThreadPoolExecutor` workers in `get_supplier_results`. ContextVars do not propagate to those workers, so DigiKey could search without the selected brand.

## Fix
- Pass `manufacturer` explicitly: `get_best_part_data` → `get_supplier_results` → `_safe_supplier_lookup` → DigiKey `search_digikey_by_part_number(..., manufacturer=)`.
- Filter aggregated supplier hits to the requested brand.
- Reject DigiKey hits that do not match the requested manufacturer.
- AF calls `get_best_part_data(mpn, manufacturer=...)` instead of relying on ContextVar.
- Fail-closed identity behavior unchanged.

## Tests
- `tests/test_threaded_manufacturer_lookup.py` — TI/onsemi selection via threaded path, absent brand, fail-closed replacements, concurrent isolation
- Focused + follow-up: 19 passed
- AF regression suite including new tests: **372 OK**

## Remaining
Keep PR open; do not merge or deploy until CI is green.
