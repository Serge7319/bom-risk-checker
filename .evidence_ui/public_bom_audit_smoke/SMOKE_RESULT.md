# Public BOM audit — Next.js app preview smoke

**Not Cloudflare Pages.** Marketing `*.cadivor.pages.dev` is out of scope for this check.

## Stub upload / lead smoke (signed-out)

| Field | Value |
| --- | --- |
| Kind | **stub-api upload + lead** |
| App preview | `http://127.0.0.1:13017` (local Next.js `next dev`) |
| Stub API | `http://127.0.0.1:18080` (`scripts/public_bom_preview_api.py`) |
| Runner | `apps/web/scripts/public_bom_browser_smoke.mjs` (Playwright) |
| Result | **PASS** |
| Proves | status → upload → preliminary audit → lead; anonymous + signed-in non-QA need Turnstile; server `qa_verified` QA can skip; client QA flags do not bypass |
| Does **not** prove | email confirmation, verified-report ownership, remaining-row completion |

## Report-delivery smoke (authenticated handoff)

| Field | Value |
| --- | --- |
| Kind | **report-delivery** (stub bearer gate; not live Supabase OTP) |
| App preview | `http://127.0.0.1:13017` |
| Stub API | bearer-gated verified-report + complete + export |
| Runner | `apps/web/scripts/public_bom_report_delivery_smoke.mjs` |
| Result | **PASS** |
| Proves | owner token loads audit; remaining rows complete; CSV download control present; cross-user denied; reopen after reload |
| Does **not** prove | live OTP email delivery / Supabase confirm click |

Live OTP confirmation remains an environment check outside this stub smoke.

## Abuse-protection notes (local)

- Anonymous preview enriches only the first five rows; remaining rows stay pending until complete.
- Full enrichment uses an atomic email lease (`full_enrichment_lease_expires_at`) so concurrent claims and retries cannot double-spend the 1/30-day quota.
- Daily enrichment budget default: **500** rows/UTC day (`CADIVOR_PUBLIC_BOM_DAILY_ENRICHED_ROWS`).
- Turnstile is fail-closed when `CADIVOR_TURNSTILE_SECRET_KEY` is set (requires `success`, allowed hostname, and action exactly `public_bom_audit`).
- Do **not** deploy until the Supabase abuse-protections migration is applied.
