# PR #605 review-blocker fix

Branch: `fix/post-deploy-smoke-followup`  
Failed run addressed: https://github.com/Serge7319/bom-risk-checker/actions/runs/43016114393

## Fixes

1. **`src/parametric_compare.py`** — Restored role-aware unknown-class handling so LIMIT_GE/LE and catalog-equal paths can still emit Match / Different / Listing agreement. Typical/guaranteed unknown class stays Needs data. Customer-facing “Catalog values agree — fit unverified” remains an assessment label only; internal Status is unchanged for ranking.
2. **Manufacturer lookup** — DigiKey exact selection honors requested manufacturer (kwarg + ContextVar). AF search sets the context, verifies identity after lookup, and fail-closes with `manufacturer_mismatch` / `unresolved` and **no candidates** without stamping the caller’s selection as supplier-verified.
3. **`src/parts_compare.py`** — Empty/unknown sources are unverified; Compatible requires authoritative non-catalog evidence. Matching rows with known class/conditions but missing sources → Needs verification.
4. **Compare progress** — Multi-candidate UI updates `completed` as each pairwise request settles (still 60s timeout; failures stay Needs verification).

## Verification

| Check | Result |
|---|---|
| Previously failing 10 AF tests | 10 passed |
| Full AF regression suite (368) | OK |
| `tests/test_post_deploy_smoke_followup.py` + migration API suite | 48 passed (includes nested CI suites) |
| Next lint | passed (existing img/font warnings only) |
| Next build | passed |
| Disposable Postgres migration gates | see `migration_gates.txt` |

## Remaining

- Keep PR open; do not merge or deploy until CI on the new head is green and reviewed.
