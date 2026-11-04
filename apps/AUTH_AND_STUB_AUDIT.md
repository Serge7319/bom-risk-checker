# Auth & stub audit — Next.js migration

Branch: `migrate/nextjs-shell-bom-flow` · PR #565 · head includes Supabase Auth path  
Commit: `ee458d4` (+ this audit refresh)

## Auth paths

| Path | When | Token verify | Workspace | Status |
| --- | --- | --- | --- | --- |
| Cadivor **Supabase Auth** | Production runtime (`RAILWAY_ENVIRONMENT=production`) | Server-side `auth.get_user(access_token)` with **anon** key (`SUPABASE_URL` + `SUPABASE_KEY` from Streamlit service) | `migration_workspace_members` in dedicated **Postgres-FGtQ** via `CADIVOR_MIGRATION_DATABASE_URL` | **Live API health OK** |
| Sandbox **HS256 JWT** | Sandbox only | `CADIVOR_SANDBOX_AUTH_SECRET` | Sandbox migration Postgres | Unchanged; **fail-closed** on production (`sandbox_jwt_permitted=false`) |

Service-role is **not** used by Next web. `SUPABASE_SERVICE_ROLE_KEY` was **not** copied to Next services.

## Production Railway (modest-vibrancy / production)

| Service | Status | Deployment ID | URL |
| --- | --- | --- | --- |
| `bom-risk-checker` (Streamlit) | Online | `a970694c-316a-4afd-975c-a301908cc4bc` | **https://app.cadivor.com** (unchanged) |
| `cadivor-next-api-prod` | Online | `6be46919-db75-4a81-9e90-5fcd2dbba7b9` | https://cadivor-next-api-prod-production.up.railway.app |
| `cadivor-next-web-prod` | Online | `5e376c2a-4076-4b45-835c-9c1f6dfadff7` | https://cadivor-next-web-prod-production.up.railway.app |
| `Postgres-FGtQ` (dedicated migration DB) | Online | `82313949-eb5b-4e1e-9b3e-469c04814b5f` | internal only |

## Verified

| Check | Result |
| --- | --- |
| Unit: Supabase login / membership / logout / cross-workspace (mocked) | **Pass** (`tests/test_supabase_auth.py`) |
| Unit: production HS256 fail-closed + missing var **names** | **Pass** |
| Live `/health`: `auth_path=supabase`, `auth_configured=true`, `production_runtime=true`, `sandbox_jwt_permitted=false` | **Pass** |
| Live persistence: postgres, durable, Streamlit data store unused | **Pass** |
| Live unauthenticated analyze → **401** | **Pass** |
| Live Next `/login` serves Cadivor Auth UI pointing at prod API | **Pass** |
| `app.cadivor.com` still Streamlit boot/auth gate | **Pass** (domain **not** cut over) |

## Blocked / not completed

| Check | Blocker |
| --- | --- |
| Hosted login / reload / logout / expiry against Cadivor Auth | No live Cadivor test credentials in this environment (`CADIVOR_LIVE_TEST_EMAIL` etc. unset). Provide a non-production-impacting owner account to finish. |
| CSV upload + synthetic analysis + nested roll-up | Depends on login |
| Saved report after reload + persist across redeploy | Depends on login |
| Cross-workspace isolation (live) | Depends on login (+ second user or planted foreign workspace row) |
| Route `app.cadivor.com` → Next web | **Not done** — leave Streamlit until the checks above pass |

## Incomplete product pages (unchanged)

- `/find-replacement` stub/limited; `/settings` limited  
- Suppliers / Stripe / email disabled on migration API  
- Several tool pages remain analysis-preview / gap-labeled (`apps/MIGRATION_PARITY.md`)

## Rollback

`app.cadivor.com` was **not** moved. If it is later pointed at `cadivor-next-web-prod`:

1. Re-attach the custom domain to **`bom-risk-checker`** (Streamlit) in Railway production  
2. Leave Streamlit deployment + Supabase data intact  
3. Next API/web + `Postgres-FGtQ` are separate; stopping them does not affect Streamlit
