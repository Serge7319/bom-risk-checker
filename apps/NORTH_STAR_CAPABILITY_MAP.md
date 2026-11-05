# Cadivor north-star capability map

Business north star: **continuous engineering workflow**—persistent project/BOM records, risk roll-up, ongoing monitoring, and self-serve adoption. This map separates verified migration-test behavior from a customer-facing production release.

## Deployment boundary

- `https://app.cadivor.com` remains the existing Streamlit application.
- The Next.js migration build and API run on separate Railway service subdomains in the Railway `production` environment. They have no `app.cadivor.com` custom domain and have not replaced the customer application.
- Migration records are stored in the dedicated `CADIVOR_MIGRATION_DATABASE_URL` Postgres database; do not point it at or merge it with the existing Streamlit/Supabase saved-BOM store.
- Use synthetic BOMs for migration checks. Do not describe the migration build as generally released or its generated supplier fields as live evidence.

## Goals vs current state

| Goal | Current state | Verified boundary / remaining work |
| --- | --- | --- |
| Persistent project / BOM / revision / analysis workflow | **Working on the separate migration test services** | Flat and nested synthetic analyses save to migration Postgres and reload by report ID after a browser refresh. A fresh API redeploy-survival check on the current production test service has not been run. |
| Multi-level BOMs and risk roll-up | **Verified with synthetic fixture** | `nested_bom_product.csv`: CAP100U effective quantity is 8; the top-level roll-up surfaces the medium-risk NRND leaf. No customer BOM or live distributor evidence was used. |
| Home from saved data | **Working on migration test services** | Home, Reports, Engineering Decisions, and Engineering Intelligence read saved workspace analyses. Existing Streamlit records have not been imported. |
| Workspace isolation | **Implemented; verification is mixed by environment** | Membership is server-derived and isolation tests pass; prior live sandbox cross-workspace checks passed. Disposable embedded-Postgres cross-tenant read/mutation isolation PASS this pass; live production migration database recheck not repeated (and restore drills intentionally avoid that DB). |
| Authentication | **Supabase path configured on migration API** | Health reports Supabase JWT membership auth and sandbox JWT disabled in production runtime. Hosted login lifecycle is not fully re-run in this pass. Signup, password reset, invitation, and production-domain cutover remain separate. Existing `app.cadivor.com` auth was not changed. |
| Proactive monitoring and email alerts | **PARTIAL (2026-11-05)** | Durable tenant-scoped alert history, preferences, on-demand refresh history, and mock email sink are implemented and unit-tested. Scheduled cron and real email transport remain disabled (`CADIVOR_MONITORING_EMAIL_ENABLED` unset). |
| Self-serve onboarding and 14-day trial | **PARTIAL / BLOCKED for live enablement (2026-11-05)** | Verified-email signup, workspace provisioning on verified sign-in, trial dates, and analysis restriction after 14 days are in code and covered by unit tests. Live signup remains off until Supabase email confirmation, delivery, redirect allowlist, and abuse controls are operator-confirmed; no verification emails sent this pass. |
| Usage-based subscription tiers | **PARTIAL (2026-11-05)** | Server-enforced plan limits + `/plan/usage` metering against migration reports. Stripe status/checkout-prep endpoints use existing `src.plans` price secret names; checkout stays disabled; live keys blocked; no charges created. |
| PLM / ERP / CAD integrations | **PARTIAL (2026-11-05)** | Connector registry + generic CSV sync groundwork and tests. Vendor-specific Arena/Propel/NetSuite/SAP choices remain **BLOCKED** pending customer discovery and sandbox credentials. |
| Compliance evidence packs | **PARTIAL (2026-11-05)** | RoHS/REACH/conflict-minerals/audit export paths label missing evidence and never claim compliance without sourced live evidence. Synthetic examples only. |
| Decision tools | **Partial preview** | Evidence envelopes on reports; mocked authorized supplier lookup with exact-MPN matching. Live distributor HTTP remains disabled without migration-owned credentials + transport flag. |

## Ordered roadmap status (2026-11-05)

| Gate | Status | Evidence |
| --- | --- | --- |
| 1. Onboarding / trial | **PARTIAL / BLOCKED (live)** | Code+unit tests PASS. Live enablement blocked on: Supabase Confirm Email verified, delivery tested, `CADIVOR_SIGNUP_REDIRECT_URL` allowlisted in `CADIVOR_WEB_ORIGINS`, abuse/rate controls confirmed, designated second-account E2E. Env gates remain closed. |
| 2. Trusted product evidence | **PARTIAL** | `evidence_contract`, mocked `supplier_lookup`, report `evidence_summary`; tests in `tests/test_nextjs_roadmap_gates.py`. Live authorized calls **BLOCKED** without migration-service credentials + `CADIVOR_MIGRATION_SUPPLIER_LIVE` + transport ready. |
| 3. Continuous monitoring | **PARTIAL** | Durable alerts/preferences/refresh + mock notify sink; schema tables added. Scheduler and real email **BLOCKED** (no cron attach; `CADIVOR_MONITORING_EMAIL_ENABLED` off). |
| 4. Commercial readiness | **PARTIAL** | Plan limit enforcement on `/boms/analyze`; billing status + checkout-prep (no sessions). Live checkout **BLOCKED** by design. |
| 5. Workflow integration | **PARTIAL** | Connector groundwork ready for generic CSV; vendor pick **BLOCKED** on discovery. |
| 6. Compliance | **PARTIAL** | Packs+audit export with missing-evidence labels; no false claims. |
| 7. Cutover readiness | **PARTIAL** | Disposable embedded-Postgres drills PASS (isolation, backup/restore, performance) in `tests/test_cutover_disposable_db.py`; evidence in `apps/.evidence_cutover/`. Domain cutover **not done**. Hosted prod-migration-DB restore still outstanding (by design not run here). `apps/web` lint+build PASS (Node v22.14.0). |

## Checks completed on 2026-11-05

| Check | Result |
| --- | --- |
| Migration API health (prior) | **PASS** — Supabase auth path reported; dedicated Postgres configured; no production service-role key reported as used. |
| Flat / nested synthetic BOM (prior) | **PASS** on migration test services. |
| Roadmap gate unit/API tests | **PASS** — local pytest → `30+ passed` including disposable-DB cutover suite (2026-11-05). |
| Live signup enablement | **Not done** — public settings show email confirmation on (`mailer_autoconfirm=false`); leaked-password protection still advisor-flagged/unverified; signup env gates closed; no email sent. |
| SECURITY DEFINER anon revoke migration | **PASS on disposable DB** — `20261105_revoke_anon_security_definer_execute.sql` + `tests/test_supabase_security_definer_grants.py`. Live apply pending DB credentials/Management token. |
| Live supplier / Stripe charges / alert email | **Not done** — intentionally disabled. |
| Disposable Postgres cutover drill | **PASS** — isolation + backup/restore + performance on embedded Postgres only (`apps/.evidence_cutover/`). |
| `apps/web` lint | **PASS** — `npm run lint` exit 0 (1 `@next/next/no-page-custom-font` warning in `layout.tsx`). |
| `apps/web` production build | **PASS** — `npm run build` exit 0 (Next.js 15.5.9); 22 routes generated including `/signup`. |
| Second-account hosted auth/signup | **BLOCKED** — account `serge.subscription+cadivor-sandbox@gmail.com` known from prior session; password/inbox unavailable here; Supabase email/abuse/redirect confirms unverified; signup remains closed. |
| `app.cadivor.com` Next.js cutover | **Not done** — app remains on Streamlit. |

## Do not claim complete

Production readiness is not achieved until onboarding/auth lifecycle, live supplier evidence, monitoring delivery, tenant isolation, persistence recovery, commercial controls, and cutover/rollback are verified on the intended production deployment. The migration subdomains are test services, not the customer-domain release.
