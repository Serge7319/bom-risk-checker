# Paid-promise acceptance report

**Baseline commit:** `6cd47f73e71acba7a3bec95e6437c693809d86be`  
**Branch:** `release/paid-promise-acceptance-2026-11-16`  
**Release target:** Monday, November 16, 2026  
**Note:** CI green is not a production acceptance pass.

Status legend: PASS | FAIL | BLOCKED | NOT TESTED

## Production findings

| # | Finding | Status | Notes |
|---|---|---|---|
| 1 | Ask Cadivor ignored LM358DR operating-voltage; returned generic BOM summary | PASS | Part-specific supply Q routed before `_s473_report`; redirects to Datasheet Q&A when BOM lacks electrical facts |
| 2 | Datasheet Q&A stitched excerpts/citations without substantiating LM358DR answer | PASS | Recommended vs abs-max separation; Needs verification on ambiguity; TI LM358DR excerpt fixture |
| 3 | Compare unreliable Match/Different; verification/semantics issues | PASS | Operating vs abs-max not cross-matched; fixtures for Match/Different/units/catalog/mfr |
| 4 | Fifteen Newark offers missing product listing URL | PASS | Provider `productUrl` verified; missing URL → provenance unavailable (no fabricated `/dp/` URLs) |
| 5 | Second independently authenticated user vs first user’s work | BLOCKED | Manual production verification by user; disposable two-user suite PASS; no new prod account |
| 6 | Monitoring lacks freshness/failure/actions; GET refreshes/upserts | PASS | GET read-only; explicit POST refresh; stale/failure/last-refresh UI; dry-run no email |

## A. Ask Cadivor and Datasheet Q&A

| Item | Status |
|---|---|
| Bind answer+citation to exact MPN, manufacturer, source document | PASS |
| LM358DR operating-supply from official TI source with page/section citation | PASS | Sanitized TI excerpt fixture (page/section); no live TI download |
| Recommended operating range distinct from absolute maximum | PASS |
| Datasheet Q&A direct answer with substantiating citations or Needs verification | PASS |
| Ask Cadivor does not replace part-specific Q with generic risk summary | PASS |
| Regressions: exact MPN, wrong citation, variant ambiguity, missing evidence, abstention | PASS |

## B. Compare Parts and decisions

| Item | Status |
|---|---|
| Semantically different ratings never compared as same property | PASS |
| Units and operating/abs-max distinctions preserved | PASS |
| Fixtures: Match, Different (50V vs 100V), equivalent units, catalog-only, missing, mfr mismatch | PASS |
| Match/Different require authoritative same-property evidence; catalog stays Needs verification | PASS | Via `assess_compare_row` provenance path |
| Match alone does not establish drop-in compatibility | PASS | Catalog Match → fit unverified |
| BOM/workspace scope switches and stale snapshots | PASS |
| Exactly one Hold for review under correct BOM; no approval/duplicate | PASS |
| Disposable Postgres migration-ledger reconcile (no blind production SQL) | PASS |

## C. Supplier evidence and replacements

| Item | Status |
|---|---|
| Per-supplier exact MPN+mfr / mismatch / no hit / timeout/HTTP/auth/malformed | PASS |
| One provider failure preserves others; failure ≠ no hit | PASS |
| Store/display listing URL, exact identity, retrieval time | PASS |
| Newark missing URLs fixed without fabricating; unavailable provenance labeled | PASS | Empty URL + `provenance_unavailable` when provider omits `productUrl` |
| Missing stock/price stay null | PASS |
| Catalog leads fit-unverified; never Compatible without engineering evidence | PASS |

## D. Fresh-user BOM journey, reports, isolation

| Item | Status |
|---|---|
| Synthetic repeat-upload journey save/reload/reopen | PASS | Evidence under `D_journey/` |
| PDF/Excel/CSV parity (UTF-8 BOM, rows, part/source fields) | PASS | PDF CJK glyph rendering remains strict xfail (row present; glyphs boxes) |
| Two-user disposable deny/allow (workspaces/BOMs/reports/decisions/monitoring) | PASS |
| Production second-user check | BLOCKED | Manual by user |

## E. Monitoring and analysis pages

| Item | Status |
|---|---|
| Page GET read-only | PASS |
| Explicit scoped refresh | PASS | `POST /tools/monitoring/refresh` |
| Visible stale / provider-failure / last-refresh + per-part actions | PASS |
| Dry-run/no-delivery path; no email sent | PASS |
| Procurement / Design Impact / Cost / Supply Risk / Portfolio scope & limits | PASS | Route copy clarifies non-live limits |

## Gates

| Gate | Status | Evidence |
|---|---|---|
| Focused A–E suites | PASS | `gates_focused.txt` (239 passed, 1 xfailed) |
| Disposable DB / roadmap | PASS | `gates_disposable_db.txt` (40 passed) |
| Next lint/build | PASS | `gates_next_lint.txt`, `gates_next_build.txt` |
| AF pytest (migration/auth/exports) | PASS | `gates_af_pytest.txt` |
| AF unittest regression block | PASS | `gates_af_unittest.txt` (369 OK) |
| Billing/report unittests | PASS | `gates_billing_report.txt` (68 OK) |
| Synthetic browser / repeat-upload harness | PASS | `D_journey/` |
| Production second-user live check | BLOCKED | User manual |
| CI regression + Cloudflare on PR head | PASS | Head `278e58db42a17a24c5aaa0bb73b7b48c9d37841f`: regression-tests, billing-contract, Cloudflare Pages SUCCESS |
