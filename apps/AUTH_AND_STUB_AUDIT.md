# Auth & stub audit — Next.js migration

Branch: `migrate/nextjs-shell-bom-flow` · PR #565  
Environments: Railway **sandbox** (`modest-vibrancy`) and Railway **production** (Next API/web live test)

## Auth paths

| Path | When | Token verify | Workspace | Status |
| --- | --- | --- | --- | --- |
| Cadivor **Supabase Auth** | `RAILWAY_ENVIRONMENT=production` / `CADIVOR_FORCE_PRODUCTION_AUTH=1` / `CADIVOR_USE_SUPABASE_AUTH=1` | Server-side `auth.get_user(access_token)` with **anon** key (`SUPABASE_URL` + `SUPABASE_KEY`) | `migration_workspace_members` in **dedicated** `CADIVOR_MIGRATION_DATABASE_URL` (test workspace per owner) | Implemented in code; live prod deploy gated on env + checks |
| Sandbox **HS256 JWT** | Sandbox / explicit allow only | Server-side HMAC with `CADIVOR_SANDBOX_AUTH_SECRET` | Same membership tables (sandbox DB) | Unchanged; **fail-closed** when production runtime |

Service-role keys are **not** used by the Next web app and must not be set on the browser service.

## Required production Next API env (names only)

| Variable | Purpose |
| --- | --- |
| `SUPABASE_URL` | Existing Cadivor Auth project URL |
| `SUPABASE_KEY` | Anon/publishable key (not service_role) |
| `CADIVOR_MIGRATION_DATABASE_URL` | **New** dedicated production migration Postgres (not Streamlit Supabase DB, not sandbox migration DB) |
| `CADIVOR_WEB_ORIGINS` | Include `https://app.cadivor.com` when cutting over |
| `NEXT_PUBLIC_API_BASE` (web build) | Production Next API public URL |

Do **not** set `CADIVOR_SANDBOX_AUTH_SECRET` as a production Auth substitute.  
Do **not** point `CADIVOR_MIGRATION_DATABASE_URL` at Streamlit’s Supabase connection string or bulk-copy sandbox rows.

## Verified in automated tests (this follow-up)

| Check | Result |
| --- | --- |
| Production runtime → Supabase path; HS256 `sandbox_jwt_permitted=false` | Pass (`tests/test_sandbox_auth.py`, `tests/test_supabase_auth.py`) |
| Missing Supabase/migration vars reported by **name** only (503) | Pass |
| Supabase login → membership test workspace; client `workspace_id` ignored | Pass (mocked Auth client) |
| Reload `/auth/me` + saved report GET after analyze | Pass (mocked) |
| Logout revokes token for this API | Pass (mocked) |
| Cross-workspace report access → 404 | Pass (mocked) |
| Sandbox JWT suite (login/logout/expiry/isolation) | Pass (existing) |

## Hosted / Railway live checks

| Check | Result |
| --- | --- |
| Production Next API/web deploy | Pending — requires Railway production secrets + dedicated migration Postgres |
| Hosted login / reload / logout against Cadivor Auth | Pending live deploy |
| CSV upload + synthetic analysis | Pending live deploy |
| Saved report after reload + nested roll-up | Pending live deploy |
| Cross-workspace isolation (live) | Pending live deploy |
| Persist across API redeploy | Pending live deploy |
| `app.cadivor.com` → Next web | **Not done** until live checks pass; Streamlit remains domain target |

## Still incomplete (product)

1. Live suppliers / Stripe / email disabled on migration API  
2. `/find-replacement` stub/limited; `/settings` limited  
3. Several tool pages are analysis-preview / gap-labeled (`apps/MIGRATION_PARITY.md`)  
4. Production Streamlit data store is **not** the Next migration store (by design)  
5. Domain cutover and production deploy are blocked until secrets + dedicated DB exist and live checks pass  

## Rollback (domain)

If `app.cadivor.com` is ever pointed at Next web:

1. Re-point the custom domain / Railway domain to the **existing Streamlit** service  
2. Leave Streamlit service and its Supabase data untouched  
3. Leave Next API/web running or stop them; migration Postgres stays separate (no Streamlit impact)
