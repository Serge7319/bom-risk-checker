# Cadivor Streamlit → Next.js parity matrix

Worktree: `bom-risk-checker-ui-approval/.worktrees/next-parity-584`  
Branch: `ui/next-parity-integrations-584` (from `main` @ `b77cec3` / PR #584)

Statuses: **WIRED** · **UI_ONLY** · **CONFIG_BLOCKED** · **MISSING**

| # | Capability | Status | Next evidence | Streamlit SoT |
| --- | --- | --- | --- | --- |
| **1** | **Account creation / email verification / invitations / sign-in** | | | |
| 1a | Sign-in | **WIRED** | `POST /auth/login` → `apps/api/supabase_auth.py`; UI `apps/web/src/app/login/page.tsx` | `src/authenticated_runtime.py` |
| 1b | Account creation (signup) | **CONFIG_BLOCKED** | `POST /auth/signup` gated by `signup_enabled()` | Streamlit signup/confirmation |
| 1c | Email verification | **CONFIG_BLOCKED** | Supabase confirm-email in `supabase_auth.signup()` | `src/email_delivery.py` |
| 1d | Workspace invitations | **WIRED** (this PR; email CONFIG_BLOCKED without Resend vars) | `/workspace/invitations*`, `/invitations/lookup|register`; login invite path | `src/workspace_service.py`, `20260919_workspace_invitation_acceptance.sql` |
| **2** | **Workspace switching/creation, members, roles, activity** | **WIRED** | `/workspaces`, `/workspace/members|activity|settings`; Settings → Workspace | `src/workspace_service.py` |
| **3** | **BOM upload, analysis, risk results, saved reports, reruns** | **WIRED** | `/boms/analyze`, reports CRUD/export | Streamlit BOM upload / saved analyses |
| **4** | **Find a Replacement (standalone + from BOM row)** | **WIRED** (stale-`analysis_id` bug fixed in this PR) | `/tools/find-replacement` → `legacy_supplier_workflow` when production analysis enabled; standalone sends MPN only; soft-context on optional ID | `src/alternative_finder_search.py` |
| **5** | **Compare Parts + engineering decision records** | **WIRED** | `/tools/compare-parts`, `/decision-records` | Streamlit compare + decisions |
| **6a** | Monitoring signal view | **WIRED** | `/tools/monitoring` + page | Monitoring Center |
| **6b** | Monitoring prefs / ack / notify / refresh UI | **UI_ONLY** | APIs exist; page not fully connected | Streamlit monitoring prefs |
| **6c** | Monitoring real email / cron | **CONFIG_BLOCKED** | Needs email + scheduler config | `src/email_delivery.py` |
| **6d** | Procurement | **WIRED** | `/tools/procurement` (live suppliers CONFIG_BLOCKED) | Procurement advisor |
| **6e** | Reports + exports | **WIRED** | PDF/XLSX/CSV via `report_exports.py` | Report export |
| **7a** | Free BOM test (public stress test) | **MISSING** | No Next route | `src/public_bom_stress_test.py` |
| **7b** | One-time report purchase | **CONFIG_BLOCKED** | Bridge to Supabase edge function | One-time BOM |
| **7c** | Plan usage | **WIRED** | `GET /plan/usage` | Plan limits |
| **7d** | Subscription upgrades / billing portal | **CONFIG_BLOCKED** | Stripe checkout flags + price IDs | Streamlit Stripe |
| **8a** | Settings · Profile | **WIRED** | `/settings` Profile tab → `/settings/profile` | `customer_profile_service.py` / `team_service` |
| **8b** | Settings · Preferences | **WIRED** | Preferences tab → `/settings/preferences` | Streamlit Preferences |
| **8c** | Settings · Workspace | **WIRED** | Workspace tab: switch/create, members, invites, activity | Settings → Workspace |
| **8d** | Settings · Security | **WIRED** (2FA/sessions status honest; password via Supabase) | `/settings/security` + change/reset | Settings → Security |
| **8e** | Settings · Billing | **WIRED** (live checkout CONFIG_BLOCKED without Stripe) | Billing tab → existing Stripe endpoints | Billing tab |

## Root causes addressed in this PR

1. **Find Replacement “Report not found”:** Standalone submit used unscoped `readLastAnalysis()` and the API’s `_require_analysis(None)` loaded the latest workspace report. Soft-context path now: no ID → no BOM context; stale/inaccessible ID → standalone + `context_unavailable` notice (no cross-tenant leak).
2. **Split membership plane:** Next uses `CADIVOR_MIGRATION_DATABASE_URL` (`migration_workspace_members`); Streamlit uses Supabase `workspace_*`. This PR chooses migration DB as Next authority and adds invite/member adapters there (documented in PR body).
3. **Supplier/email credentials on `cadivor-next-api-prod`:** Production service currently has only `SUPABASE_*` among app secrets — missing `MOUSER_API_KEY`, `DIGIKEY_CLIENT_ID`, `DIGIKEY_CLIENT_SECRET`, `NEWARK_API_KEY`, `NEXAR_*`/`OCTOPART_*`, `RESEND_API_KEY`, `TRANSACTIONAL_FROM_EMAIL`. Legacy Streamlit Railway service `bom-risk-checker` is no longer present; GH Actions secrets hold a subset of names. Transfer must use Railway secure variable management without logging values.

## Membership authority (decision)

**Authoritative for Next:** `CADIVOR_MIGRATION_DATABASE_URL` membership + invite tables (file-store equivalent in sandbox).  
**Not authoritative for Next tenancy:** Streamlit Supabase `workspace_members` / `workspace_invites` (remain for legacy Streamlit until fully retired).  
Invite accept resolves workspace + role server-side from the pending invite row; browser-submitted workspace/role are ignored.
