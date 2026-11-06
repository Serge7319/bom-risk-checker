# Cadivor north-star capability map

Business north star: **continuous engineering workflow**—persistent project/BOM records, risk roll-up, ongoing monitoring, and self-serve adoption. This map distinguishes verified production behavior from capabilities that remain gated or incomplete.

## Current production boundary (verified 2026-11-06)

- `https://app.cadivor.com` is served by the Next.js Railway web service and its Supabase-authenticated API.
- Railway production services are `cadivor-next-web-prod`, `cadivor-next-api-prod`, and the dedicated `Postgres-FGtQ` database. No Streamlit service is present in either Railway project visible to this account; legacy Streamlit source remains in the repository.
- The Next.js database is separate from the old Streamlit/Supabase saved-BOM store. Existing Streamlit records have not been imported.
- Supplier and component evidence remains synthetic unless clearly labeled and sourced from an enabled live provider.

## Goals vs current state

| Goal | Current state | Verified boundary / remaining work |
| --- | --- | --- |
| Persistent project / BOM / revision / analysis workflow | **Working in production Next.js** | Flat and nested synthetic analyses save to dedicated Railway Postgres and reload by report ID after a browser refresh. Live production database restore testing remains outstanding. |
| Multi-level BOMs and risk roll-up | **Verified with synthetic fixture** | `nested_bom_product.csv`: CAP100U effective quantity is 8; the top-level roll-up surfaces the medium-risk NRND leaf. No customer BOM or live distributor evidence was used. |
| Home from saved data | **Working in production Next.js** | Home, Reports, Engineering Decisions, and Engineering Intelligence read saved workspace analyses. Existing Streamlit records have not been imported. |
| Workspace isolation | **Implemented; verification is mixed by environment** | Membership is server-derived and isolation tests pass; prior live sandbox cross-workspace checks passed. Disposable embedded-Postgres cross-tenant read/mutation isolation PASS this pass; live production migration database recheck not repeated (and restore drills intentionally avoid that DB). |
| Authentication | **Supabase Auth and refresh handling deployed** | The API validates Supabase JWTs and resolves membership server-side. The browser persists and refreshes Supabase sessions; one hosted second-account POST/report E2E remains outstanding. Signup remains gated; password reset and invitations are not implemented. |
| Proactive monitoring and email alerts | **PARTIAL (2026-11-05)** | Durable tenant-scoped alert history, preferences, on-demand refresh history, and mock email sink are implemented and unit-tested. Scheduled cron and real email transport remain disabled (`CADIVOR_MONITORING_EMAIL_ENABLED` unset). |
| Self-serve onboarding and 14-day trial | **PARTIAL / BLOCKED for live enablement (2026-11-05)** | Verified-email signup, workspace provisioning on verified sign-in, trial dates, and analysis restriction after 14 days are in code and covered by unit tests. Live signup remains off until Supabase email confirmation, delivery, redirect allowlist, and abuse controls are operator-confirmed; no verification emails sent this pass. |
| Usage-based subscription tiers | **PARTIAL (2026-11-05)** | Server-enforced plan limits + `/plan/usage` metering against migration reports. Stripe status/checkout-prep endpoints use existing `src.plans` price secret names; checkout stays disabled; live keys blocked; no charges created. |
| PLM / ERP / CAD integrations | **PARTIAL (2026-11-05)** | Connector registry + generic CSV sync groundwork and tests. Vendor-specific Arena/Propel/NetSuite/SAP choices remain **BLOCKED** pending customer discovery and sandbox credentials. |
| Compliance evidence packs | **PARTIAL (2026-11-05)** | RoHS/REACH/conflict-minerals/audit export paths label missing evidence and never claim compliance without sourced live evidence. Synthetic examples only. |
| Decision tools | **Partial preview** | Evidence envelopes on reports; mocked authorized supplier lookup with exact-MPN matching. Live distributor HTTP remains disabled without migration-owned credentials + transport flag. |

## Ordered roadmap status (2026-11-06)

| Gate | Status | Evidence |
| --- | --- | --- |
| 1. Onboarding / trial | **PARTIAL / BLOCKED (live)** | Code+unit tests PASS. Live enablement blocked on: Supabase Confirm Email verified, delivery tested, `CADIVOR_SIGNUP_REDIRECT_URL` allowlisted in `CADIVOR_WEB_ORIGINS`, abuse/rate controls confirmed, designated second-account E2E. Env gates remain closed. |
| 2. Trusted product evidence | **PARTIAL** | `evidence_contract`, mocked `supplier_lookup`, report `evidence_summary`; tests in `tests/test_nextjs_roadmap_gates.py`. Live authorized calls **BLOCKED** without migration-service credentials + `CADIVOR_MIGRATION_SUPPLIER_LIVE` + transport ready. |
| 3. Continuous monitoring | **PARTIAL** | Durable alerts/preferences/refresh + mock notify sink; schema tables added. Scheduler and real email **BLOCKED** (no cron attach; `CADIVOR_MONITORING_EMAIL_ENABLED` off). |
| 4. Commercial readiness | **PARTIAL** | Plan limit enforcement on `/boms/analyze`; billing status + checkout-prep (no sessions). Live checkout **BLOCKED** by design. |
| 5. Workflow integration | **PARTIAL** | Connector groundwork ready for generic CSV; vendor pick **BLOCKED** on discovery. |
| 6. Compliance | **PARTIAL** | Packs+audit export with missing-evidence labels; no false claims. |
| 7. Cutover readiness | **PARTIAL / POST-CUTOVER** | `app.cadivor.com` is live on Next.js; web/API deployments are healthy; no Streamlit service is present in the active Railway project. Disposable Postgres isolation/backup/restore/performance drills pass. Live database restore drill and hosted recovery rehearsal remain outstanding. |

## Checks completed on 2026-11-05

| Check | Result |
| --- | --- |
| Migration API health | **PASS** — production API reports Supabase Auth and dedicated Postgres; no production service-role key is used by the browser. |
| Flat / nested synthetic BOM (prior) | **PASS** — synthetic flow saves to production Railway Postgres and reloads by report ID. |
| Roadmap gate unit/API tests | **PASS** — local pytest → `30+ passed` including disposable-DB cutover suite (2026-11-05). |
| Live signup enablement | **Not done** — public settings show email confirmation on (`mailer_autoconfirm=false`); leaked-password protection still advisor-flagged/unverified; signup env gates closed; no email sent. |
| SECURITY DEFINER privilege hardening | **PASS live + disposable DB** — migrations `20261105_revoke_anon_security_definer_execute` and `20261106_revoke_authenticated_handle_new_user_execute` are applied. Anon/authenticated direct execution is revoked; the auth.users trigger stays attached and service_role retains execute. |
| Live supplier / Stripe charges / alert email | **Not done** — intentionally disabled. |
| Disposable Postgres cutover drill | **PASS** — isolation + backup/restore + performance on embedded Postgres only (`apps/.evidence_cutover/`). |
| `apps/web` lint | **PASS** — `npm run lint` exit 0 (1 `@next/next/no-page-custom-font` warning in `layout.tsx`). |
| `apps/web` production build | **PASS** — `npm run build` exit 0 (Next.js 15.5.9); 22 routes generated including `/signup`. |
| Second-account hosted auth/signup | **BLOCKED** — account `serge.subscription+cadivor-sandbox@gmail.com` known from prior session; password/inbox unavailable here; Supabase email/abuse/redirect confirms unverified; signup remains closed. |
| `app.cadivor.com` Next.js deployment | **PASS** — domain serves the Railway Next.js web app; the live bundle contains the approved BOM Analyzer side panels. |

## Do not claim complete

Production readiness remains partial while signup safeguards and the hosted second-account E2E, live supplier evidence, scheduled monitoring delivery, production recovery, commercial controls and post-cutover checks remain open. `app.cadivor.com` is already the live Next.js customer-domain application.
