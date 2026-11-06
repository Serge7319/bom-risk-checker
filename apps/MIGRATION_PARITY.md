# Next.js migration route parity checklist

`app.cadivor.com` now serves the Next.js app from Railway. This checklist tracks feature parity and remaining product-readiness gaps after the domain cutover.

Updated: 2026-11-06 · audit basis: production `f6b61f6`; expanded report exports are on this branch until merged and deployed.

| Route | Migration status | Current data source | Remaining gaps |
| --- | --- | --- | --- |
| `/login` | **Available for existing accounts** | Supabase Auth; workspace membership is server-derived | Password reset and invitation flows are not implemented; signup remains closed |
| `/signup` | **Disabled in production** | `/auth/config`, `/auth/signup` | Email confirmation/delivery, redirect allowlist, abuse protection, and hosted second-account E2E remain unverified |
| `/` Home | **Working** | Saved migration-workspace records | Existing Streamlit records were not imported |
| `/bom-analyzer` | **Working in production Next.js** | CSV/XLSX upload → saved Railway Postgres report; server plan limits | Analysis uses synthetic evidence; it is not a live distributor scan |
| `/reports` | **Working** | Workspace-scoped saved report list | Production has the basic CSV download; this branch adds PDF, Excel, and an evidence-labeled component-audit CSV; pending deployment |
| `/reports/[id]` | **Working; CSV available in production** | Workspace-scoped saved report, evidence envelopes, hierarchy, decision history | Supplier evidence is synthetic; PDF, Excel, and the expanded audit CSV are added by this branch |
| `/engineering-decisions` | **Working for review signals and recorded comparison decisions** | Latest saved report counts + persisted workspace decision records | The queue is a risk summary; there is no multi-stage sign-off, digital approval, or automatic alternate qualification |
| `/engineering-intelligence` | **Partial** | Latest saved report | Not a full cross-BOM decision command center with verified evidence and approval lifecycle |
| `/monitoring` | **Partial** | Signals derived from saved analyses; durable alert/preferences/refresh APIs exist | Current page has no refresh, acknowledge, or notification-preference controls; scheduler and real email are disabled |
| `/compare-parts` | **Working comparison + decision capture** | Saved BOM values and clearly labeled synthetic/offline catalog values | A saved human decision does not prove fit or change the BOM; live supplier/datasheet evidence is disabled |
| `/datasheet-qa` | **Limited** | Uploaded PDF text extraction and evidence-grounded answers | No managed document library or persisted datasheet history |
| `/procurement` | **Preview** | Saved analysis fields and synthetic/sample estimates | No live distributor inventory, price, lead-time, or authorization feed |
| `/design-impact` | **Partial** | Saved migration-workspace analyses | No imported Streamlit history or live product-catalog coverage |
| `/cost-optimization` | **Preview** | Saved fields and synthetic unit prices | Not live quotes, contract pricing, or purchasing optimization |
| `/supply-risk` | **Scenario preview** | User-entered scenario assumptions and saved analysis fields | No live disruption or supplier-event feed |
| `/portfolio-intelligence` | **Partial** | Saved analyses in the current workspace | No imported Streamlit portfolio history or multi-workspace roll-up |
| `/detailed-risk-report` | **Partial** | Saved analysis rows | No live refresh; report downloads are exposed from `/reports/[id]` after this branch ships |
| `/find-replacement` | **Limited** | Offline/sample catalog and saved BOM fields | No live alternate search or verified fit score |
| `/settings` | **Read-only / partial** | Current workspace, usage, billing readiness, connector registry, compliance-pack status | No create/switch-workspace UI, team administration, checkout, or configured vendor integration |

## Account, workspace, and purchase availability

| Customer action | Production status | What the current app does |
| --- | --- | --- |
| Create a new account / trial | **Unavailable** | Signup route is visible, but the production API reports signup disabled and returns 503 from the signup endpoint. |
| Create another workspace | **Unavailable** | A verified account is resolved to one owner workspace; there is no workspace create/switch endpoint or UI. Projects and BOMs are records inside that workspace. |
| Buy one report | **Unavailable** | No one-time-report checkout flow exists. Stripe checkout is disabled; `/billing/checkout-prep` only validates intent and creates no Checkout Session or charge. |
| Download a saved analysis | **Partial** | A basic component CSV is live. This branch adds PDF, Excel, and expanded CSV audit exports; they are not live until this branch passes CI and deploys. |

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
| `GET /reports/{analysis_id}/export.csv` | Existing component CSV | Workspace-scoped; deployed |
| `GET /reports/{analysis_id}/export/{format}` (`pdf`, `xlsx`, `csv`) | Download one workspace-scoped saved report | No mutation; added on this branch, pending deployment |
| `GET /integrations/connectors` | Connector registry | None |
| `POST /integrations/connectors/sync` | Generic CSV sync | None |
| `GET /compliance/{pack_type}` | RoHS/REACH/CMRT/audit packs | None |

## Production-readiness gaps

1. Signup/trial live enablement still requires operator-confirmed email confirmation, delivery, redirect allowlisting, abuse controls, and a designated hosted E2E.
2. Live distributor evidence requires migration-owned provider credentials and an authorized transport — not Streamlit secret reuse.
3. Wire monitoring UI controls to existing refresh, acknowledge, and preference endpoints; then configure and verify a scheduled refresh and real email transport.
4. Implement Stripe Checkout Session creation and the one-time-report payment lifecycle; test mode first, live charges remain off.
5. Add multi-workspace creation, switching, membership, and workspace administration.
6. Production-service persistence recovery and cross-workspace isolation rechecks.
7. Customer discovery for vendor-specific PLM/ERP connectors and credentials.
8. Post-cutover hosted auth/API workflow verification and Next.js rollback rehearsal — see `apps/CUTOVER_RUNBOOK.md`.

## Builder truthfulness rules

| Surface | Allowed data | Never imply |
| --- | --- | --- |
| Monitoring | Saved-analysis-derived signals + durable history | Live stock/price changes, scheduled refresh, or sent alerts when scheduler/sink is disabled |
| Engineering decisions | Human-submitted comparison snapshot, reviewer, decision, and rationale | A qualified alternate, signed approval, or BOM change |
| Compare Parts | Saved fields, uploaded datasheets, clearly marked synthetic fields | Live supplier lookup or drop-in compatibility when disabled |
| Datasheet Q&A | Extracted text from the uploaded datasheet | Specs absent from the document |
| Procurement / Cost | Saved prices or clearly marked synthetic estimates | Distributor quotes or contract prices when offers are unavailable |
| Design / Portfolio | Migration workspace analyses | Imported Streamlit history when none exists |
| Supply Risk | Explicit scenario assumptions and saved fields | Live disruption monitoring |
| Detailed Risk | Saved analysis rows | Live distributor refresh |
| Compliance | Evidence-linked records only | RoHS/REACH/CMRT compliance without sourced evidence |
| Billing | Plan limits + checkout readiness status | Completed charges, one-time report purchases, or live checkout |

## Verification notes (2026-11-05)

- `apps/web` lint + production build: **PASS** (Node v22.14.0 outside default PATH).
- Disposable embedded-Postgres cutover suite: **PASS** (`tests/test_cutover_disposable_db.py`).
- Second-account signup/login email: **BLOCKED** — `serge.subscription+cadivor-sandbox@gmail.com` known; credentials/inbox not available to the agent; safeguards unverified; public signup not enabled.

## Production deployment verification (2026-11-06)

- `app.cadivor.com/bom-analyzer`: **HTTP 200**, Next.js response headers.
- Production Railway web and API deployments at `e7f3d6a`: **SUCCESS**; API health reports Supabase Auth and durable Postgres.
- The current live Analyzer JavaScript bundle includes “Before you analyze” and “Recent analyses.” If an already-open browser tab still shows the prior one-column layout, hard-refresh it to fetch the current bundle.
- `npm run lint`: **PASS** (one pre-existing custom-font warning); `npm run build`: **PASS** (Next.js 15.5.9; 22 routes).
- Browser token refresh: **deployed**; the login response seeds the Supabase client session and authenticated API requests retry once after refresh. First sign-in after the deployment may be required for sessions created by the prior build. Hosted account POST/report E2E still needs an authenticated browser.

## Security and auth notes (2026-11-06)

- Both privilege migrations are applied to the shared Supabase project: `20261105_revoke_anon_security_definer_execute.sql` and `20261106_revoke_authenticated_handle_new_user_execute.sql`. Read-only verification confirms `anon` and `authenticated` cannot directly execute `handle_new_user()`, `service_role` retains execute, and its auth.users trigger remains attached.
- Signup remains closed on the migration API. Public Auth settings: email confirmation required (`mailer_autoconfirm=false`). Leaked-password protection not confirmed via public API; keep signup closed.
- Monitoring refresh hook: `POST /tools/monitoring/refresh` (user JWT or cron token); real email still disabled.

## Latest production deployment check (2026-11-06)

- Railway production web and API services are healthy at `f6b61f6` with no staged changes; `app.cadivor.com` is attached to the Next.js web service.
- The deployed report detail currently exposes CSV only. PR #579 adds PDF, Excel, and the expanded audit CSV after CI and deployment.
