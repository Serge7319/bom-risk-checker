# Next.js migration route parity checklist

`app.cadivor.com` now serves the Next.js app from Railway. This checklist tracks feature parity and remaining product-readiness gaps after the domain cutover.

Updated: 2026-11-06

| Route | Migration status | Current data source | Remaining gaps |
| --- | --- | --- | --- |
| `/login` | Supabase auth path available on migration API | Supabase Auth; membership derives workspace | Hosted login lifecycle not re-run; signup remains feature-gated; reset/invite not implemented |
| `/signup` | Page present; API gated off | `/auth/config`, `/auth/signup` | Live enablement blocked on email/abuse/redirect confirms |
| `/` Home | Working | Saved migration workspace records | Existing Streamlit data is not imported |
| `/bom-analyzer` | Working in production Next.js | Uploaded CSV → saved Railway Postgres record; server plan limits enforced; approved side panels are in the current web bundle | Live supplier evidence is disabled |
| `/reports` | Working | Workspace-scoped saved report list | Disposable-DB backup/restore PASS; live migration DB recovery check still outstanding (not run against live) |
| `/reports/[id]` | Working | Workspace-scoped saved report + evidence envelopes | Supplier evidence remains synthetic unless live path authorized |
| `/engineering-decisions` | Partial | Latest saved report risk counts | Decisions/approvals are not independently persisted |
| `/engineering-intelligence` | Partial | Latest saved report | Multi-BOM engineering record/history is not fully mirrored |
| `/monitoring` | Partial preview | Durable alerts/preferences from migration monitoring store; derived from saved analyses | Durable Postgres-backed alerts when migration DB URL set; no scheduled refresh; email uses mock sink only |
| `/compare-parts` | Preview | Saved analysis fields or synthetic records | Live supplier lookup is disabled |
| `/datasheet-qa` | Preview | Uploaded datasheet extraction and grounded answer | No full production document-management workflow |
| `/procurement` | Preview | Analysis parts; no live offer feed | Live distributor pricing is disabled |
| `/design-impact` | Preview | Saved migration analyses | Existing Streamlit catalog/history is not imported |
| `/cost-optimization` | Preview | Synthetic unit prices | Not live quotes or contract pricing |
| `/supply-risk` | Preview | Scenario assumptions and saved fields | No live disruption feed |
| `/portfolio-intelligence` | Partial preview | Saved migration workspace analyses | Existing Streamlit portfolio history is not imported |
| `/detailed-risk-report` | Preview | Saved synthetic analysis rows | Live distributor refresh and complete export workflow are outstanding |
| `/find-replacement` | Limited/stub | — | Live alternate search and fit scoring are not implemented here |
| `/settings` | Read-only/limited | Signed-in workspace + `/plan/usage` + `/billing/status` available on API | Workspace admin UI and live checkout not implemented |

## API surfaces added for roadmap gates (2026-11-05)

| Endpoint | Purpose | Live side effects |
| --- | --- | --- |
| `POST /tools/supplier-lookup` | Exact-MPN authorized lookup (mock default) | None (live gated) |
| `GET/PUT /tools/monitoring/preferences` | Notification preferences | None |
| `GET /tools/monitoring/alerts` | Durable alert history | None |
| `POST /tools/monitoring/acknowledge` | Ack alert | None |
| `POST /tools/monitoring/notify` | Mock email sink | No real email unless enabled |
| `GET /plan/usage` | Plan limits + metering | None |
| `GET /billing/status` | Stripe test-mode readiness | None |
| `POST /billing/checkout-prep` | Validate intent; no Checkout session | No charges |
| `GET /integrations/connectors` | Connector registry | None |
| `POST /integrations/connectors/sync` | Generic CSV sync | None |
| `GET /compliance/{pack_type}` | RoHS/REACH/CMRT/audit packs | None |

## Production-readiness gaps

1. Signup/trial live enablement still requires operator-confirmed email confirmation, delivery, redirect allowlisting, abuse controls, and a designated hosted E2E.
2. Live distributor evidence requires migration-owned provider credentials and an authorized transport — not Streamlit secret reuse.
3. Scheduled monitoring refresh and real alert email transport.
4. Stripe Checkout session creation in test mode after trial lifecycle verification; live keys remain blocked.
5. Production-service persistence recovery and cross-workspace isolation rechecks.
6. Customer discovery for vendor-specific PLM/ERP connectors.
7. Post-cutover hosted auth/API verification, production recovery review and Next.js rollback rehearsal — see `apps/CUTOVER_RUNBOOK.md`.

## Builder truthfulness rules

| Surface | Allowed data | Never imply |
| --- | --- | --- |
| Monitoring | Saved-analysis-derived signals + durable history | Live stock/price changes, scheduled refresh, or sent alerts when sink is mock |
| Compare Parts | Saved fields, uploaded datasheets, clearly marked synthetic fields | Live supplier lookup when disabled |
| Datasheet Q&A | Extracted text from the uploaded datasheet | Specs absent from the document |
| Procurement / Cost | Saved prices or clearly marked synthetic estimates | Distributor quotes or contract prices when offers are unavailable |
| Design / Portfolio | Migration workspace analyses | Imported Streamlit history when none exists |
| Supply Risk | Explicit scenario assumptions and saved fields | Live disruption monitoring |
| Detailed Risk | Saved analysis rows | Live distributor refresh |
| Compliance | Evidence-linked records only | RoHS/REACH/CMRT compliance without sourced evidence |
| Billing | Plan catalog + test-mode readiness | Completed charges or live checkout |

## Verification notes (2026-11-05)

- `apps/web` lint + production build: **PASS** (Node v22.14.0 outside default PATH).
- Disposable embedded-Postgres cutover suite: **PASS** (`tests/test_cutover_disposable_db.py`).
- Second-account signup/login email: **BLOCKED** — `serge.subscription+cadivor-sandbox@gmail.com` known; credentials/inbox not available to the agent; safeguards unverified; public signup not enabled.

## Production deployment verification (2026-11-06)

- `app.cadivor.com/bom-analyzer`: **HTTP 200**, Next.js response headers.
- Production Railway web and API deployments: **SUCCESS**; API health reports Supabase Auth and durable Postgres.
- The current live Analyzer JavaScript bundle includes “Before you analyze” and “Recent analyses.” If an already-open browser tab still shows the prior one-column layout, hard-refresh it to fetch the current bundle.
- `npm run lint`: **PASS** (one pre-existing custom-font warning); `npm run build`: **PASS** (Next.js 15.5.9; 22 routes).
- Browser token refresh: **in progress on the production-readiness branch**; until it deploys, an expired access token can still lead to a 401 on authenticated API requests.

## Security and auth notes (2026-11-05)

- Privilege hardening migration `20261105_revoke_anon_security_definer_execute.sql` is applied to the shared Supabase project. A follow-up migration removes authenticated direct execute on the trigger-only `handle_new_user()` function; live application is pending.
- Signup remains closed on the migration API. Public Auth settings: email confirmation required (`mailer_autoconfirm=false`). Leaked-password protection not confirmed via public API; keep signup closed.
- Monitoring refresh hook: `POST /tools/monitoring/refresh` (user JWT or cron token); real email still disabled.
