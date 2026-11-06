# Cadivor Next.js production migration status

Current production source: `main` at merge commit `e7f3d6a`.

## Current production state (verified 2026-11-06)

- `https://app.cadivor.com` is served by the Next.js Railway web service. The active production Railway project contains the Next.js web/API services and the dedicated Postgres service; no Streamlit service is present in the two Railway projects currently visible to this account.
- The web and API deployments are healthy. The web deployment uses merge commit `e7f3d6a` and its BOM Analyzer bundle contains both approved panels: “Before you analyze” and “Recent analyses.” An already-open browser tab can retain the prior bundle; a hard refresh fetches the current deployment.
- Supabase Auth and the dedicated Railway Postgres store back the current application. Existing Streamlit records have not been imported.
- Public signup, live supplier calls, Stripe checkout, monitoring scheduler, and real alert email remain disabled. No charges or verification emails were sent.
- The browser now receives a Supabase publishable key. Login stores the Supabase refresh session; authenticated API requests refresh once and retry after an expired access token. This fix is deployed in `e7f3d6a`; a one-time sign-in may be needed to replace a session created by the previous build.

The sections below retain historical migration evidence and gate details. Where older text says the domain is still on Streamlit, this verified deployment status supersedes it.

## Current capability boundary

- Next.js shell + Supabase Auth path on the production API
- One end-to-end synthetic BOM flow: upload → analyze → report
- Python analysis uses existing `bom_parser`, `risk_engine`, and `health_score`
- Synthetic part evidence only — no live distributor calls, Stripe, or alert email
- Verified-email signup and 14-day trial code is present but gated off; no signup emails are sent
- The customer domain now serves Next.js; the former Streamlit application is not a Railway service in the active production project

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

## Railway production services

`app.cadivor.com` points to the `cadivor-next-web-prod` Railway service. Its API
is `cadivor-next-api-prod`; `Postgres-FGtQ` is the dedicated application store.
These services are in Railway's `production` environment. This means the
Next.js app is the live customer-domain application, not a test service.

## Verified local preview (2026-11-03)

- Web: `http://127.0.0.1:3000`
- API: `http://127.0.0.1:8787/health`
- Evidence: `.evidence/nextjs_migration/` (login → shell → BOM Analyzer → 25-part report)
- API unit test: `tests/test_nextjs_migration_api.py`

## Railway production services (verified 2026-11-06)

The production services are:

- `cadivor-next-api-prod` → https://cadivor-next-api-prod-production.up.railway.app
- `cadivor-next-web-prod` → https://cadivor-next-web-prod-production.up.railway.app
- `Postgres-FGtQ` is the dedicated application record database; existing Streamlit saved-BOM data was not imported.

### API startup dispatch

The root `railway.toml` still contains the legacy Streamlit start path for local
or future use. The active production web/API services run the Next.js app and
`apps/api/start.sh`; no Streamlit service was found in the active production
project.

The API uses Supabase Auth with server-resolved workspace membership and
dedicated Postgres. The disposable-database restore and tenant-isolation checks
passed; a live production-database restore drill remains intentionally unrun.


## Self-serve signup / trial gate

Signup is deliberately **disabled** on the deployed migration services. No verification email is sent unless the feature is explicitly enabled. Before enabling, an operator must configure all of the following on the migration API:

- `CADIVOR_SELF_SERVE_SIGNUP_ENABLED=1`
- `CADIVOR_SIGNUP_EMAIL_CONFIRMATION_CONFIRMED=1` only after Supabase Confirm Email is enabled and tested
- `CADIVOR_SIGNUP_ABUSE_PROTECTION_CONFIRMED=1` only after Supabase Auth abuse/rate controls are reviewed
- `CADIVOR_SIGNUP_REDIRECT_URL` set to an HTTPS login URL whose origin is included in `CADIVOR_WEB_ORIGINS`
- Supabase verification email delivery configured and tested; do not use the Streamlit data database as the migration record store

The migration API exposes only whether signup is enabled, not secrets. Unverified users do not receive a migration workspace. The workspace and 14-day trial start on their first verified sign-in. New BOM analysis is blocked after trial expiry; saved reports remain readable. Alert email, billing, and supplier integrations remain disabled.

## Roadmap gate progress (2026-11-05)

The Next.js app is now live at `app.cadivor.com`. Roadmap work continues on the
current branch against the production API/web services and dedicated Postgres.

| Gate | Status | Notes |
| --- | --- | --- |
| Onboarding / trial | PARTIAL / BLOCKED (live) | Feature gate closed; unit coverage present |
| Trusted evidence | PARTIAL | Mocked authorized lookup + evidence envelopes |
| Monitoring | PARTIAL | Durable store + mock email sink; no real sends |
| Commercial | PARTIAL | Server plan limits; Stripe test prep only |
| Connectors | PARTIAL | Generic CSV ready; vendor choice pending |
| Compliance | PARTIAL | Evidence-linked packs; no unsupported claims |
| Cutover | PARTIAL / POST-CUTOVER | Domain is routed to Next.js; see `apps/CUTOVER_RUNBOOK.md` for remaining recovery and live-DB checks |

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

The shared Supabase project has both `20261105_revoke_anon_security_definer_execute` and `20261106_revoke_authenticated_handle_new_user_execute` applied. Read-only privilege verification confirms `anon` and `authenticated` cannot directly execute `handle_new_user()`, `service_role` retains execute, and the auth.users trigger remains attached.


### Supabase Auth public settings probe (2026-11-05)

`GET /auth/v1/settings` (anon): `disable_signup=false`, `mailer_autoconfirm=false` (email confirmation required), email provider enabled. Public payload does **not** expose leaked-password protection, redirect allowlists, or rate-limit details. Advisor-reported leaked-password protection remains unverified; migration API signup env gates stay **closed**. No verification email sent.

Pytest this pass: **30+ passed** (privilege + cutover + roadmap + migration/auth suites).
