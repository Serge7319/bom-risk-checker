# Cadivor Next.js production status

**Updated:** November 5, 2026

## Active deployment

- The Next.js application now serves https://app.cadivor.com through Railway service cadivor-next-web-prod on port 3000.
- The production API runs as cadivor-next-api-prod on port 8787 and uses Supabase Auth for sign-in.
- Project, BOM, revision, analysis, and report records use the dedicated Railway Postgres service Postgres-FGtQ. Its existing environment variable name is CADIVOR_MIGRATION_DATABASE_URL.
- The previous Streamlit Railway services were removed from production, sandbox, and the old project. No volumes were detached or deleted. Legacy Streamlit source files remain in the repository, but the root Railway startup now targets only the Next.js API.
- Existing Supabase saved-BOM records were not imported into the Next.js workspace store. The app labels that data boundary.
- Flat and nested BOM analysis currently uses clearly labeled synthetic supplier evidence. Live supplier calls, automated alert email, and Stripe checkout are disabled.

## Current user-facing limits

- Public signup remains disabled. Before opening it, Supabase email confirmation and delivery, redirect allowlisting, abuse protections, and leaked-password protection must be verified. The Supabase security advisor currently reports leaked-password protection disabled.
- The hosted second-account signup and login lifecycle has not been completed in this environment.
- Monitoring supports saved-analysis-derived alerts and a mock notification sink; there is no scheduled refresh or real email delivery.
- Billing has server-side plan limits and checkout preparation, but no checkout session or charge.
- Generic CSV connector groundwork and evidence-linked compliance packs exist. No vendor-specific PLM/ERP integration or sourced compliance claim is enabled.
- Production database recovery and a post-cutover cross-workspace end-to-end check remain open.

## Verification recorded for this release

- Commit 04a6efab6be00b5422e51e02ca4b9f15cd8753fb merged PR #566 and deployed to the production Next.js web and API services.
- Railway reports both production deployments SUCCESS.
- The PR regression-tests and Cloudflare Pages checks passed.
- The Next.js source scan covered 28 TypeScript files and found no remaining user-facing “Migration test”, “test build”, or Streamlit labels.
- The public login page on app.cadivor.com displayed the corrected workspace and integration wording.
- Earlier migration and cutover checks reported 31 passing tests, a successful Next.js lint/build, nested quantity and risk roll-up, and disposable-Postgres isolation / backup-restore / performance checks. Those disposable database checks did not use the production database.

## Roadmap status

| Gate | Status | Remaining work |
| --- | --- | --- |
| Onboarding and trial | Partial / blocked | Verify Supabase safeguards and email delivery; complete second-account hosted E2E |
| Trusted evidence | Partial | Add migration-owned supplier credentials and authorized live transport |
| Monitoring | Partial | Add scheduled refresh and real email transport |
| Commercial readiness | Partial | Verify trial lifecycle, then test-mode checkout; no live charges |
| Connectors | Partial | Validate one vendor with customer discovery and sandbox credentials |
| Compliance | Partial | Add attributable live declarations; never infer compliance from missing evidence |
| Cutover | Domain cutover complete; readiness partial | Recovery drill, hosted isolation check, and decision on historical data |

## Supabase security status

The migration 20261105_revoke_anon_security_definer_execute is recorded in the live Supabase project. A read-only privilege audit confirmed that anon and PUBLIC cannot execute public SECURITY DEFINER functions. The Supabase advisor still reports 19 SECURITY DEFINER functions executable by authenticated users; these include legacy workspace and admin RPCs that need function-by-function review before public signup. The leaked-password-protection advisor warning remains open.

Keep signup disabled until the remaining auth protections are verified. No verification email or Stripe charge was sent for this release.
