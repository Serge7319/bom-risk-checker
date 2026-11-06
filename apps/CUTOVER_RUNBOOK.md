# Cadivor Next.js cutover and rollback runbook

**Status (2026-11-06):** `https://app.cadivor.com` is live on the Next.js Railway web service. Web and API deployments are healthy. The approved BOM Analyzer side-panel code is in the live web bundle. The earlier pre-cutover status below is superseded; the remaining list is post-cutover readiness work.

## Boundaries that stay in force

- Customer domain (`app.cadivor.com`) now routes to `cadivor-next-web-prod`; the active Railway production project has no Streamlit service.
- Next.js records stay in the dedicated Railway Postgres store. Existing Streamlit/Supabase BOM tables were not merged or imported.
- Cutover drills in this repository use a **disposable embedded Postgres** only. Never restore into the customer database or the live Railway migration database.
- Use synthetic fixtures and provider mocks for checks. No customer BOMs, live Stripe charges, marketing email, or unauthorized supplier calls.

## Post-cutover readiness checklist

| # | Check | Evidence required | Status (2026-11-06) |
| --- | --- | --- | --- |
| 1 | Signup/trial lifecycle on migration API (email confirm, redirect allowlist, abuse controls, designated account) | Hosted logs + test account notes | **BLOCKED** — Supabase Confirm Email / delivery / abuse / redirect operator confirms not verified; second account `serge.subscription+cadivor-sandbox@gmail.com` identified from prior session evidence but password and inbox are **not available** in this agent environment; no verification email sent; signup gate remains closed |
| 2 | Auth login/logout/`/auth/me` on hosted production path | Hosted account exercise + API logs | **PARTIAL** — Supabase Auth and browser token refresh are deployed. Hosted second-account POST/report lifecycle still needs an authenticated browser session. |
| 3 | Tenant isolation across reports, monitoring alerts, preferences, mutations | Cross-workspace negative tests on disposable DB | **PASS (disposable DB)** — workspace B gets 404 on A's report get/delete; monitoring prefs/alerts isolated; B cannot ack A's alerts |
| 4 | Trusted supplier evidence path (exact MPN, source URL, retrieved_at, units, live vs synthetic labels) | Mock PASS; live PASS only with migration-owned credentials | **PARTIAL** — mocked PASS including procurement evidence envelopes; live calls still disabled |
| 5 | Monitoring durable history + mock notification sink | API tests | **PARTIAL** — Postgres-backed monitoring store used when `CADIVOR_MIGRATION_DATABASE_URL` set; mock email only; scheduler not attached |
| 6 | Plan limits enforced server-side; Stripe test-mode prep only | API tests; no charges | **PARTIAL** — limits enforced; checkout disabled |
| 7 | Connector groundwork + documented vendor decision gaps | Unit/API tests | **PARTIAL** — generic CSV ready; vendor pick blocked on discovery |
| 8 | Compliance packs label missing evidence; no false claims | API tests | **PARTIAL** — packs PASS on disposable DB; no unsupported claims |
| 9 | Persistence backup/restore of disposable migration Postgres | Dump/restore drill | **PASS (disposable DB)** — see evidence below; **not** run against live migration or customer DB |
| 10 | Performance smoke (analyze + report load) on disposable DB | Timed synthetic run | **PASS (disposable DB)** — analyze ~30ms, report GET ~13ms locally on synthetic 25-part fixture (not a production SLA) |
| 11 | Rollback procedure reviewed | This document + Railway deployment history | **PARTIAL** — rollback target is a known-good Next.js deployment; no Streamlit service is currently available in the active Railway projects. |
| 12 | `apps/web` lint + production build | lockfile install + commands | **PASS (2026-11-06)** — `npm run lint` exit 0 (one existing custom-font warning); `npm run build` exit 0; Next.js 15.5.9, 22 routes |

## Disposable-DB drill commands (2026-11-05)

```bash
# From repo root (migrate/nextjs-shell-bom-flow checkout)
export PATH="$HOME/.local/node-v22.14.0-darwin-arm64/bin:$PATH"

# Web
cd apps/web && npm ci && npm run lint && npm run build && cd ../..

# Optional local dep for disposable Postgres binaries (test-only)
.venv312/bin/pip install 'embedded-postgres==18.6.3' 'psycopg[binary]'

# Cutover readiness against disposable embedded Postgres ONLY
.venv312/bin/python -m pytest tests/test_cutover_disposable_db.py -q

# Broader migration/API regression
.venv312/bin/python -m pytest \
  tests/test_cutover_disposable_db.py \
  tests/test_nextjs_roadmap_gates.py \
  tests/test_nextjs_migration_api.py \
  tests/test_nextjs_migration_tools.py \
  tests/test_supabase_auth.py \
  tests/test_nextjs_api_origin_contract.py -q
```

### Evidence artifacts

- `apps/.evidence_cutover/backup_restore.json`
- `apps/.evidence_cutover/performance.json`

Backup/restore evidence (2026-11-05):

```json
{
  "pass": true,
  "dump_bytes": 27299,
  "analysis_id": "751ddffb-0dbc-4eb8-9882-f2f9659ac54c",
  "parts_before": 25,
  "parts_after": 25,
  "database": "disposable-embedded-postgres",
  "not_customer_db": true,
  "not_live_migration_db": true
}
```

Performance evidence (2026-11-05):

```json
{
  "pass": true,
  "analyze_ms": 29.64,
  "report_get_ms": 12.74,
  "fixture": "synthetic_bom_25parts.csv",
  "database": "disposable-embedded-postgres"
}
```

Pytest result this pass: **29 passed** (4 cutover disposable-DB + 25 prior migration/auth/roadmap).

## Domain cutover record (completed 2026-11-06)

1. `app.cadivor.com` was attached to `cadivor-next-web-prod`; Cloudflare DNS now targets the Railway web endpoint.
2. `app.cadivor.com/bom-analyzer` responds with HTTP 200 and Next.js headers.
3. The active Railway production project has healthy Next.js web/API deployments and dedicated Postgres; the live API reports Supabase Auth and Postgres persistence.
4. The production web bundle contains “Before you analyze” and “Recent analyses.” A user with an older tab may need a hard refresh to load its new asset.
5. Signup, live supplier access, Stripe checkout, scheduled monitoring and real alert email remain disabled.

## Remaining post-cutover work

1. Verify a fresh sign-in followed by authenticated POST requests and saved-report reload on the customer domain.
2. Complete hosted second-account login/report persistence once a browser session for that account is available.
3. Keep signup closed until email confirmation, delivery, redirects, abuse safeguards and leaked-password protection are verified.
4. Complete the production backup/restore and tenant-isolation review without restoring over production data.

## Rollback sequence

1. Use Railway's rollback to the last known-good Next.js web deployment and verify the matching API version.
2. Keep the domain attached to Next.js and leave Postgres intact; the previous Streamlit service is not currently provisioned in the active Railway projects.
3. Do not restore or merge saved-BOM data across the old and new database stores during incident response.
4. Confirm login, report listing and a saved report load on the customer domain.
5. Record incident notes: time, trigger, health diffs and user-visible impact.

## Shared Supabase privilege hardening (2026-11-06)

Migration file: `supabase/migrations/20261105_revoke_anon_security_definer_execute.sql`

Disposable verification: `tests/test_supabase_security_definer_grants.py` **PASS** — preserves authenticated grants for existing RPCs; revokes anon globally on SECURITY DEFINER; strips anon+authenticated from trigger helpers and from direct execution of `handle_new_user()`; keeps service_role-only helpers off anon/authenticated. The `auth.users` insert trigger remains attached.

Both privilege migrations are **applied to the shared Supabase project**. Read-only verification confirms `anon` and `authenticated` cannot execute `handle_new_user()`, `service_role` can execute it, and the trigger remains attached.

## Explicit non-goals for this document

- No DNS change instructions that execute automatically.
- No destructive migration of customer data.
- No restore drills against live migration Postgres or customer databases.
- No enablement of live Stripe charges or marketing/monitoring email.
