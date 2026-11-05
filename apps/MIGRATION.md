# Cadivor Next.js migration test build

Same repository, branch `migrate/nextjs-shell-bom-flow`.

## Scope of this preview

- Shared Next.js shell + Supabase Auth path on the migration API
- One end-to-end synthetic BOM flow: upload → analyze → report
- Python analysis uses existing `bom_parser`, `risk_engine`, and `health_score`
- Synthetic part evidence only — no live distributor calls, Stripe, or alert email
- Verified-email signup and 14-day trial code is present but gated off; no signup emails are sent
- **Production Streamlit on `app.cadivor.com` is unchanged**

## Local run

```bash
# Optional local API (port 8787)
.venv312/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8787

# Web (port 3000): configure the API target explicitly in apps/web/.env.local.
# Example for sandbox testing:
# NEXT_PUBLIC_API_BASE=https://cadivor-next-api-sandbox.up.railway.app
cd apps/web
npm run dev
```

Fixture: `tests/fixtures/synthetic_bom_25parts.csv`

## Railway deployment boundary

`app.cadivor.com` remains on the Streamlit service. The Next.js web/API test
services use separate Railway subdomains and a dedicated migration Postgres
database. A Railway environment named `production` does not mean the migration
app has replaced the customer-domain application.

## Verified local preview (2026-11-03)

- Web: `http://127.0.0.1:3000`
- API: `http://127.0.0.1:8787/health`
- Evidence: `.evidence/nextjs_migration/` (login → shell → BOM Analyzer → 25-part report)
- API unit test: `tests/test_nextjs_migration_api.py`

## Railway migration test services (2026-11-05)

The API and web services are separate from the customer app:

- `cadivor-next-api-prod` → https://cadivor-next-api-prod-production.up.railway.app
- `cadivor-next-web-prod` → https://cadivor-next-web-prod-production.up.railway.app
- `Postgres-FGtQ` is the dedicated migration record database; existing Streamlit saved-BOM data was not imported.

### API startup dispatch

The root `railway.toml` is shared with Streamlit. `scripts/railway_start.sh`
must dispatch `cadivor-next-api` and `cadivor-next-api-prod` to
`apps/api/start.sh`; `bom-risk-checker` stays on the Streamlit boot path.

The migration API uses Supabase Auth with workspace membership and dedicated
migration Postgres. The current production migration service's database
redeploy-survival and cross-workspace checks have not been re-run in this pass.
Do not cut over `app.cadivor.com` based on the migration smoke checks alone.


## Self-serve signup / trial gate

Signup is deliberately **disabled** on the deployed migration services. No verification email is sent unless the feature is explicitly enabled. Before enabling, an operator must configure all of the following on the migration API:

- `CADIVOR_SELF_SERVE_SIGNUP_ENABLED=1`
- `CADIVOR_SIGNUP_EMAIL_CONFIRMATION_CONFIRMED=1` only after Supabase Confirm Email is enabled and tested
- `CADIVOR_SIGNUP_ABUSE_PROTECTION_CONFIRMED=1` only after Supabase Auth abuse/rate controls are reviewed
- `CADIVOR_SIGNUP_REDIRECT_URL` set to an HTTPS login URL whose origin is included in `CADIVOR_WEB_ORIGINS`
- Supabase verification email delivery configured and tested; do not use the Streamlit data database as the migration record store

The migration API exposes only whether signup is enabled, not secrets. Unverified users do not receive a migration workspace. The workspace and 14-day trial start on their first verified sign-in. New BOM analysis is blocked after trial expiry; saved reports remain readable. Alert email, billing, and supplier integrations remain disabled.

## Roadmap gate progress (2026-11-05)

Work continues on branch `migrate/nextjs-shell-bom-flow` against the dedicated migration API/web services only. `app.cadivor.com` Streamlit traffic was not changed.

| Gate | Status | Notes |
| --- | --- | --- |
| Onboarding / trial | PARTIAL / BLOCKED (live) | Feature gate closed; unit coverage present |
| Trusted evidence | PARTIAL | Mocked authorized lookup + evidence envelopes |
| Monitoring | PARTIAL | Durable store + mock email sink; no real sends |
| Commercial | PARTIAL | Server plan limits; Stripe test prep only |
| Connectors | PARTIAL | Generic CSV ready; vendor choice pending |
| Compliance | PARTIAL | Evidence-linked packs; no unsupported claims |
| Cutover | PARTIAL | See `apps/CUTOVER_RUNBOOK.md`; domain unchanged |

### New migration API modules

- `apps/api/evidence_contract.py`
- `apps/api/supplier_lookup.py`
- `apps/api/monitoring_store.py`
- `apps/api/plan_limits.py`
- `apps/api/billing_prep.py`
- `apps/api/connectors.py`
- `apps/api/compliance_packs.py`

### Verification commands

```bash
.venv312/bin/python -m pytest tests/test_nextjs_roadmap_gates.py tests/test_nextjs_migration_api.py tests/test_nextjs_migration_tools.py tests/test_supabase_auth.py tests/test_nextjs_api_origin_contract.py -q
```

Results from this pass are recorded after the pytest run below (update if re-run).

### Pytest evidence (2026-11-05, local)

Command:

```bash
.venv312/bin/python -m pytest tests/test_nextjs_roadmap_gates.py tests/test_nextjs_migration_api.py tests/test_nextjs_migration_tools.py tests/test_supabase_auth.py tests/test_nextjs_api_origin_contract.py -q
```

Result: **PASS** — `25 passed` (13 in `tests/test_nextjs_roadmap_gates.py` + 12 existing migration/auth/origin tests). No live signup, supplier, Stripe charge, or alert email was exercised. Later same day: Node located at `~/.local/node-v22.14.0-darwin-arm64` (v22.14.0); `npm ci` + `npm run lint` (exit 0, 1 font warning) + `npm run build` (exit 0).


### Cutover disposable-DB + web evidence (2026-11-05 evening)

Node binary: `/Users/sergekashambala/.local/node-v22.14.0-darwin-arm64/bin/node` (v22.14.0) / npm 10.9.2

```bash
export PATH="$HOME/.local/node-v22.14.0-darwin-arm64/bin:$PATH"
cd apps/web && npm ci && npm run lint && npm run build
.venv312/bin/pip install 'embedded-postgres==18.6.3' 'psycopg[binary]'
.venv312/bin/python -m pytest tests/test_cutover_disposable_db.py tests/test_nextjs_roadmap_gates.py tests/test_nextjs_migration_api.py tests/test_nextjs_migration_tools.py tests/test_supabase_auth.py tests/test_nextjs_api_origin_contract.py -q
```

Results:

- `npm run lint`: **PASS** (exit 0; warning `@next/next/no-page-custom-font` in `src/app/layout.tsx`)
- `npm run build`: **PASS** (exit 0; Next 15.5.9; 22 routes)
- pytest: **29 passed**
- Disposable DB backup/restore + tenant isolation + performance: **PASS** (artifacts under `apps/.evidence_cutover/`; not customer/live migration DB)
- Signup: remains **disabled**; second-account hosted check **BLOCKED** (password/inbox unavailable; Supabase safeguards unverified)

### Security DEFINER privilege migration (2026-11-05)

Source: `supabase/migrations/20261105_revoke_anon_security_definer_execute.sql`

Disposable-DB test: `tests/test_supabase_security_definer_grants.py` — **PASS** (anon revoked; trigger helpers `cadivor_write_audit_event` / `cadivor_audit_engineering_record` revoked from anon+authenticated; Streamlit authenticated RPCs retained; service-only RPCs stay service_role).

**Live shared Supabase apply:** not executed in this pass — no database password / Management API token available in the agent environment. Apply via Supabase SQL editor or `psql` with the project DB credentials after review.

### Supabase Auth public settings probe (2026-11-05)

`GET /auth/v1/settings` (anon): `disable_signup=false`, `mailer_autoconfirm=false` (email confirmation required), email provider enabled. Public payload does **not** expose leaked-password protection, redirect allowlists, or rate-limit details. Advisor-reported leaked-password protection remains unverified; migration API signup env gates stay **closed**. No verification email sent.

Pytest this pass: **30+ passed** (privilege + cutover + roadmap + migration/auth suites).
