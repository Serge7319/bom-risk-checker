# Cadivor capability map

Business north star: a continuous engineering workflow with persistent project and BOM records, traceable risk decisions, ongoing monitoring, and self-serve adoption.

## Current deployment

- https://app.cadivor.com serves the Next.js web app on Railway.
- The production API uses Supabase Auth and the dedicated Railway Postgres store. The internal database variable is still named CADIVOR_MIGRATION_DATABASE_URL.
- Streamlit Railway services were removed from production, sandbox, and the old project. Historical Streamlit source remains in the repository, but no Railway environment serves it.
- Existing Supabase saved-BOM records were not copied into the Next.js store.
- BOM analysis uses synthetic supplier and price evidence. Live suppliers, scheduled monitoring email, and Stripe checkout remain disabled.

## Capability status

| Goal | Current state | Remaining work |
| --- | --- | --- |
| Persistent project / BOM / revision / analysis workflow | Working on the production Next.js services | Verify persistence across a production API redeploy with a saved record; previous app records were not imported |
| Multi-level BOMs and risk roll-up | Verified with synthetic fixture | CAP100U effective quantity is 8; the top-level assembly inherits the medium-risk contributor; live source data is not used |
| Home from saved data | Working | Home, Reports, Engineering Decisions, and Engineering Intelligence read saved workspace analyses |
| Workspace isolation | Unit and disposable-DB checks pass | Repeat hosted cross-workspace negative checks in production |
| Authentication | Supabase Auth is configured on the production API | Complete hosted login/logout E2E; signup, password reset, and invitations remain gated or incomplete |
| Monitoring and email alerts | Partial | Durable alert history and preferences exist; scheduler and real email transport remain off |
| Self-serve onboarding and trial | Partial / blocked | Confirm email delivery, redirect allowlist, abuse controls, and leaked-password protection; then complete second-account E2E |
| Usage tiers | Partial | Server-side limits and usage display exist; Stripe checkout is disabled |
| PLM / ERP / CAD integrations | Partial | Generic CSV groundwork exists; select and validate one vendor from customer discovery |
| Compliance evidence packs | Partial | Missing-evidence labels exist; sourced live declarations are not connected |
| Decision tools | Partial preview | Evidence envelopes exist; live distributor lookup and several decision screens remain incomplete |
| Cutover | Domain cutover complete; readiness partial | Recovery and hosted isolation checks remain; previous app records are not imported |

## Evidence from this pass

- Production web and API deployments completed successfully on commit 04a6efab6be00b5422e51e02ca4b9f15cd8753fb.
- Regression checks and the Cloudflare Pages build passed for PR #566.
- The live public login page showed the corrected product copy.
- A source scan covered 28 Next.js TypeScript files and found no user-facing migration-test or Streamlit labels.
- Earlier checks passed for nested synthetic BOM roll-up, Next.js lint/build, 31 migration/auth/cutover tests, and disposable-Postgres isolation and backup/restore. The disposable database was not the production database.
- The live Supabase security migration is recorded as applied. anon and PUBLIC execution of public SECURITY DEFINER functions is revoked; the advisor still reports 19 functions callable by authenticated users and leaked-password protection disabled.

## Do not claim complete

Cadivor is not fully production-ready. Signup remains closed; supplier evidence, scheduled monitoring, real alert email, Stripe checkout, vendor-specific connectors, full route parity, production recovery, and hosted tenant-isolation verification remain incomplete.
