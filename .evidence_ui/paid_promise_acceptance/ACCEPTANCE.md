# Paid-promise acceptance report

**Baseline commit:** `6cd47f73e71acba7a3bec95e6437c693809d86be`  
**Branch:** `release/paid-promise-acceptance-2026-11-16`  
**PR:** https://github.com/Serge7319/bom-risk-checker/pull/625  
**Release target:** Monday, November 16, 2026  
**Note:** CI green is not a production acceptance pass. Missing evidence is never marked PASS.

Status legend: PASS | FAIL | BLOCKED | NOT TESTED

## Production findings

| # | Finding | Status | Notes |
|---|---|---|---|
| 1 | Ask Cadivor ignored LM358DR operating-voltage; returned generic BOM summary | PASS | Part-specific supply Q routed before `_s473_report` |
| 2 | Datasheet Q&A stitched excerpts without substantiating LM358DR answer | PASS | Recommended vs abs-max; Needs verification; Next sends MPN/mfr |
| 3 | Compare unreliable Match/Different | PASS | Operating vs abs-max; fixtures; Hold-once |
| 4 | Fifteen Newark offers missing product listing URL | BLOCKED | Code resolves official HTTPS `www.newark.com` URLs via provider `productUrl` or documented `id:<sku>` lookup; arbitrary hosts rejected; unresolved rows stay provenance-unavailable. Production 15-row verification not completed against live Newark |
| 5 | Second independently authenticated user vs first user’s work | BLOCKED | Manual production check; disposable two-user suite PASS |
| 6 | Monitoring GET upserts; lacks freshness/actions | PASS | GET read-only; refresh ≠ email; reconcile inactive; Notify explicit |

## A. Ask Cadivor and Datasheet Q&A

| Item | Status |
|---|---|
| Bind answer+citation to exact MPN, manufacturer, source document | PASS | Next page + `askDatasheet` send `mpn`/`manufacturer` |
| LM358DR operating-supply from TI excerpt with page/section citation | PASS |
| Recommended operating range distinct from absolute maximum | PASS |
| Direct answer with citations or Needs verification | PASS |
| Ask Cadivor does not replace part-specific Q with generic risk summary | PASS |
| Regressions + UI/API identity smoke (wrong PDF abstains; supported cites part) | PASS |

## B. Compare Parts and decisions

| Item | Status |
|---|---|
| Semantically different ratings never compared as same property | PASS |
| Units and operating/abs-max distinctions preserved | PASS |
| Fixtures: Match, Different (50V vs 100V), units, catalog-only, missing, mfr mismatch | PASS |
| Catalog stays Needs verification; Match ≠ drop-in Compatible | PASS |
| BOM/workspace scope + stale snapshots | PASS |
| Exactly one Hold for review; no approval/duplicate | PASS |
| Disposable migration-ledger reconcile | PASS |

## C. Supplier evidence and replacements

| Item | Status |
|---|---|
| Per-supplier exact MPN+mfr / mismatch / no hit / failures | PASS |
| One provider failure preserves others; failure ≠ no hit | PASS |
| Store listing URL, identity, retrieval time | PASS | Verified official HTTPS only |
| Newark missing URLs without fabricating | BLOCKED | Lookup path implemented; live 15-offer production check incomplete |
| Missing stock/price stay null | PASS |
| Catalog leads fit-unverified | PASS |

## D. Fresh-user BOM journey, reports, isolation

| Item | Status |
|---|---|
| Synthetic repeat-upload journey | PASS |
| PDF/Excel/CSV parity | PASS | PDF CJK glyphs strict xfail |
| Two-user disposable deny/allow | PASS |
| Production second-user check | BLOCKED |

## E. Monitoring and analysis pages

| Item | Status |
|---|---|
| Page GET read-only | PASS |
| Explicit scoped refresh (never sends email) | PASS |
| Visible stale / failure / last-refresh + per-part actions | PASS |
| Explicit Notify action for email; dry-run no delivery | PASS |
| Reconcile stale alerts off active view; part-scoped dry-run counts | PASS |
| Procurement / Design Impact / Cost / Supply Risk / Portfolio limits | PASS |

## Gates

| Gate | Status | Notes |
|---|---|---|
| Focused A–E suites | PASS | See `gates_focused_rereview.txt` |
| Disposable DB / roadmap | PASS | |
| Next lint/build | PASS | |
| Synthetic browser / repeat-upload harness | PASS | `D_journey/` |
| Production second-user live check | BLOCKED | User manual |
| CI on final PR head | PASS | Head `b949b63909fcb2eb5a24cdadbac121c8b4c07353`: regression-tests, billing-contract, Cloudflare Pages SUCCESS |
