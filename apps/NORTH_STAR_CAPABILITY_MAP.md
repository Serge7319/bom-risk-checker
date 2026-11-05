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
| Workspace isolation | **Implemented; verification is mixed by environment** | Membership is server-derived and isolation tests pass; prior live sandbox cross-workspace checks passed. A live cross-tenant test against the current production migration database was not repeated in this pass. |
| Authentication | **Supabase path configured on migration API** | Health reports Supabase JWT membership auth and sandbox JWT disabled in production runtime. Full signup, reset, invitation, expiry, and multi-tenant production test sequence remain open. Existing `app.cadivor.com` auth was not changed. |
| Proactive monitoring and email alerts | **Not yet live** | Monitoring is derived from saved analysis data. No scheduled supplier refresh or alert email delivery. |
| Self-serve onboarding and 14-day trial | **Not yet live** | No public account creation, email verification, workspace provisioning flow, or enforceable trial lifecycle. This is the next product milestone. |
| Usage-based subscription tiers | **Not yet live** | Plan display is not usage metering. Stripe checkout and limits are not enabled in the migration build. |
| PLM / ERP / CAD integrations | **Not yet live** | No connectors or add-ins. |
| Compliance evidence packs | **Not yet live** | Synthetic report fields do not constitute RoHS, REACH, conflict-minerals, or audit evidence. |
| Decision tools | **Partial preview** | Several pages render analysis-derived or synthetic fields. Live distributor lookup is disabled; Find Replacement and Settings remain limited/stubbed. |

## Checks completed on 2026-11-05

| Check | Result |
| --- | --- |
| Migration API health | **PASS** — Supabase auth path reported; dedicated Postgres configured; no production service-role key reported as used. |
| Flat synthetic BOM | **PASS** — saved report and Home reload observed on the migration web app. |
| Nested synthetic BOM upload | **PASS** — 7 rows; CAP100U effective quantity 8; medium-risk leaf rolled to top level. |
| Nested report browser refresh | **PASS** — same quantities and roll-up retrieved by report ID after refresh. |
| Migration routes | **PASS for navigation/render smoke** — all 16 sidebar routes opened; preview/stub status still applies. |
| Production migration DB redeploy survival | **Not checked in this pass** |
| Production migration DB cross-workspace isolation | **Not checked in this pass** |
| `app.cadivor.com` Next.js cutover | **Not done** — app remains on Streamlit. |

Previous sandbox isolation and redeploy results are recorded in `MIGRATION_TEST_RESULTS.txt` and `MIGRATION_SANDBOX_VERIFY.json`; they are not production migration-service test evidence.

## Ordered roadmap to production readiness

1. **Self-serve onboarding:** email-verified signup, workspace creation, first-login provisioning, and a real 14-day trial lifecycle with tenant-isolation checks.
2. **Trusted product evidence:** authorized distributor integrations, source citations, refresh timestamps, and live/synthetic separation throughout BOM, compare, and monitoring workflows.
3. **Continuous monitoring:** scheduled lifecycle/availability refresh, durable alert history, notification preferences, and email delivery.
4. **Commercial readiness:** enforce usage limits and active-BOM/component pricing; connect billing only after trial/account lifecycle is verified.
5. **Workflow integration:** PLM/ERP connectors and CAD integrations, prioritized from customer discovery.
6. **Compliance:** sourced RoHS/REACH/conflict-minerals evidence and audit-ready exports.
7. **Cutover:** parity, auth, tenant isolation, persistence/recovery, performance, and rollback checks before moving `app.cadivor.com`.

## Do not claim complete

Production readiness is not achieved until onboarding/auth lifecycle, live supplier evidence, monitoring delivery, tenant isolation, persistence recovery, commercial controls, and cutover/rollback are verified on the intended production deployment. The migration subdomains are test services, not the customer-domain release.
