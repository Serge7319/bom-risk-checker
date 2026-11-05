# Cadivor Next.js production runbook

**Status:** Domain cutover completed November 5, 2026. The public app URL now serves Next.js. The previous Streamlit Railway services were deleted from production, sandbox, and the old project. No volumes were detached or deleted.

## Current boundaries

- app.cadivor.com routes to cadivor-next-web-prod on port 3000.
- The production API is cadivor-next-api-prod on port 8787. Supabase provides sign-in; the app's project and analysis records use the dedicated Railway Postgres store.
- The existing Supabase project and its saved-BOM tables were not deleted or copied. Previous app records are not available in the Next.js workspace.
- Analysis currently uses synthetic supplier and price evidence. Signup, live suppliers, real monitoring email, and Stripe checkout remain disabled.
- The root Railway startup script now starts only the Next.js API. Historical Streamlit code remains in the repository but is not deployed.
- Do not restore backups into the existing Supabase database or the production Railway Postgres. Recovery checks must use a separate disposable or isolated database.

## Post-cutover checks

| Check | Result | Follow-up |
| --- | --- | --- |
| app.cadivor.com serves Next.js | PASS | Login page and updated copy rendered in the public app |
| Production web deployment | PASS | Railway deployment on commit 04a6efab succeeded |
| Production API deployment | PASS | Railway deployment on commit 04a6efab succeeded |
| Domain and service routing | PASS | Custom domain points to the Next web service on port 3000 |
| Flat and nested synthetic BOM behavior | PASS in prior checks | Re-run a hosted synthetic flow and confirm its saved report after API restart |
| Workspace isolation | PASS on disposable database | Repeat hosted cross-workspace negative tests |
| Disposable database backup/restore | PASS | Evidence is in apps/.evidence_cutover; it did not use production data |
| Production database recovery | OPEN | Create and validate a recovery procedure using an isolated target |
| Signup/trial lifecycle | BLOCKED | Confirm email, delivery, redirect allowlist, abuse controls, and leaked-password protection before opening signup |
| Supplier, monitoring email, checkout | PARTIAL | Keep disabled until each live data and notification path is tested |

## Routine release verification

1. Confirm Railway web and API deployments reach SUCCESS on the same main commit.
2. Check service health and recent logs.
3. Sign in with the designated test account.
4. Upload the synthetic flat and nested BOM fixtures; verify saved report pages and reload behavior.
5. Confirm visible data labels still distinguish synthetic evidence from live sources.
6. Check the plan usage, monitoring, compliance, and connector pages for accurate unavailable-state copy.
7. Record the commit, deployment IDs, checks, and any remaining blockers here.

## Recovery

- First rollback option: redeploy the last known-good Next.js web and API deployments through Railway and verify app.cadivor.com again.
- Streamlit is not an immediate rollback target because its Railway services were deleted. Restoring it would require creating and configuring a new service from the retained source, then deliberately reassigning the domain.
- Do not copy records between the Next.js Railway Postgres and existing Supabase tables during recovery.
- Keep both data stores intact until the product owner decides whether historical test records are needed.

## Supabase security

Migration 20261105_revoke_anon_security_definer_execute is recorded in the live Supabase project. A read-only privilege audit confirmed anon and PUBLIC cannot execute public SECURITY DEFINER functions. The advisor still reports 19 functions callable by authenticated users; review their intended callers before enabling signup. The leaked-password-protection warning is still open.

Disposable-DB verification of the migration is recorded in tests/test_supabase_security_definer_grants.py. This is separate from the live migration record and does not replace hosted auth verification.
