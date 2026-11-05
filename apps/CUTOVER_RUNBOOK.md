# Cadivor Next.js cutover and rollback runbook

**Status:** Disposable-DB cutover drills executed locally (2026-11-05). `https://app.cadivor.com` remains on Streamlit. Do not change DNS, custom domains, or Streamlit traffic until every gate below is PASS with dated evidence on the intended production migration deployment.

## Boundaries that stay in force

- Customer domain (`app.cadivor.com`) stays on the Streamlit service until explicit cutover approval.
- Migration records stay in `CADIVOR_MIGRATION_DATABASE_URL` only. Do not import, merge, or alter existing Streamlit/Supabase customer BOM tables during cutover rehearsal.
- Cutover drills in this repository use a **disposable embedded Postgres** only. Never restore into the customer database or the live Railway migration database.
- Use synthetic fixtures and provider mocks for checks. No customer BOMs, live Stripe charges, marketing email, or unauthorized supplier calls.

## Pre-cutover checklist

| # | Check | Evidence required | Status (2026-11-05) |
| --- | --- | --- | --- |
| 1 | Signup/trial lifecycle on migration API (email confirm, redirect allowlist, abuse controls, designated account) | Hosted logs + test account notes | **BLOCKED** — Supabase Confirm Email / delivery / abuse / redirect operator confirms not verified; second account `serge.subscription+cadivor-sandbox@gmail.com` identified from prior session evidence but password and inbox are **not available** in this agent environment; no verification email sent; signup gate remains closed |
| 2 | Auth login/logout/`/auth/me` on disposable/migration path | HTTP/API tests | **PARTIAL** — sandbox JWT lifecycle PASS on disposable Postgres (`tests/test_cutover_disposable_db.py`); hosted Supabase second-account login not re-run (credentials unavailable) |
| 3 | Tenant isolation across reports, monitoring alerts, preferences, mutations | Cross-workspace negative tests on disposable DB | **PASS (disposable DB)** — workspace B gets 404 on A's report get/delete; monitoring prefs/alerts isolated; B cannot ack A's alerts |
| 4 | Trusted supplier evidence path (exact MPN, source URL, retrieved_at, units, live vs synthetic labels) | Mock PASS; live PASS only with migration-owned credentials | **PARTIAL** — mocked PASS including procurement evidence envelopes; live calls still disabled |
| 5 | Monitoring durable history + mock notification sink | API tests | **PARTIAL** — Postgres-backed monitoring store used when `CADIVOR_MIGRATION_DATABASE_URL` set; mock email only; scheduler not attached |
| 6 | Plan limits enforced server-side; Stripe test-mode prep only | API tests; no charges | **PARTIAL** — limits enforced; checkout disabled |
| 7 | Connector groundwork + documented vendor decision gaps | Unit/API tests | **PARTIAL** — generic CSV ready; vendor pick blocked on discovery |
| 8 | Compliance packs label missing evidence; no false claims | API tests | **PARTIAL** — packs PASS on disposable DB; no unsupported claims |
| 9 | Persistence backup/restore of disposable migration Postgres | Dump/restore drill | **PASS (disposable DB)** — see evidence below; **not** run against live migration or customer DB |
| 10 | Performance smoke (analyze + report load) on disposable DB | Timed synthetic run | **PASS (disposable DB)** — analyze ~30ms, report GET ~13ms locally on synthetic 25-part fixture (not a production SLA) |
| 11 | Rollback procedure reviewed | This document | Prepared (domain cutover not performed) |
| 12 | `apps/web` lint + production build | lockfile install + commands | **PASS** — Node v22.14.0 at `~/.local/node-v22.14.0-darwin-arm64`; `npm ci`, `npm run lint` exit 0 (1 font warning), `npm run build` exit 0 |

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

## Cutover sequence (only after checklist PASS on intended production migration services)

1. Freeze Streamlit feature flags that would conflict; leave Streamlit serving `app.cadivor.com`.
2. Confirm migration API health: Supabase auth, dedicated Postgres, signup gate state, suppliers/stripe/email flags.
3. Run synthetic end-to-end: login → analyze fixture → report → monitoring → compliance export.
4. Attach custom domain to Next web **only** after approval; keep Streamlit service runnable.
5. Monitor error rates for 30–60 minutes; keep Streamlit ready.

## Rollback sequence

1. Point `app.cadivor.com` back to the Streamlit Railway service (reverse the domain attachment only; do not delete Streamlit).
2. Leave migration API/web and migration Postgres intact for forensics.
3. Do not write migration DB rows into Streamlit tables during rollback.
4. Confirm Streamlit login + one saved BOM load on the customer domain.
5. Record incident notes: time, trigger, health diffs, whether any customer saw Next.js.

## Shared Supabase privilege hardening (2026-11-05)

Migration file: `supabase/migrations/20261105_revoke_anon_security_definer_execute.sql`

Disposable verification: `tests/test_supabase_security_definer_grants.py` **PASS** — preserves authenticated grants for Streamlit RPCs (`cadivor_record_user_activity`, admin RPCs, workspace invitation/role helpers); revokes anon globally on SECURITY DEFINER; strips anon+authenticated from trigger helpers `cadivor_write_audit_event` / `cadivor_audit_engineering_record`; keeps service_role-only helpers off anon/authenticated.

Live apply to the shared Cadivor Supabase project **pending** operator DB credentials or Supabase Management API token (not present in agent env). Apply before customer-domain cutover.

## Explicit non-goals for this document

- No DNS change instructions that execute automatically.
- No destructive migration of customer data.
- No restore drills against live migration Postgres or customer databases.
- No enablement of live Stripe charges or marketing/monitoring email.
