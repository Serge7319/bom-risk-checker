# Auth & stub audit — Next.js migration

Branch: `migrate/nextjs-shell-bom-flow` · PR #565 · head includes Supabase Auth path
Commit: `0ed21b9` (source + test hardening; signup/trial follow-up is this change)

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
| `cadivor-next-api-prod` | Online | `9ea080a8-d48c-4099-a8db-7cf262d3d0a1` | https://cadivor-next-api-prod-production.up.railway.app |
| `cadivor-next-web-prod` | Online | `a302c19d-aeea-4e62-9b85-238d997cf2b6` | https://cadivor-next-web-prod-production.up.railway.app |
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
| Live Next bundle points to production migration API, no sandbox API fallback | **Pass** |
| Signup config remains disabled; no signup/verification email sent | **Pass** (gate is unset) |
| `app.cadivor.com` still Streamlit boot/auth gate | **Pass** (domain **not** cut over) |

## Blocked / not completed

| Check | Blocker |
| --- | --- |
| Hosted signup / confirmation email / first verified login / trial expiry | Not run: signup gate is intentionally closed and no designated test account/email configuration is enabled. |
| Hosted login / CSV upload / synthetic analysis / nested roll-up | No designated live test account credentials are available in the environment. |
| Saved report after reload + persist across redeploy | No authenticated hosted E2E performed in this pass. |
| Cross-workspace isolation (live) | No authenticated hosted E2E performed in this pass. |
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


## Onboarding release gate (2026-11-05)

- Verified-email signup and 14-day trial are implemented in PR code, but the migration API feature flag is **off**.
- No verification email was sent and no public account was created.
- Server requires explicit acknowledgments for email confirmation and abuse controls, plus an HTTPS allowlisted redirect, before signup can turn on.
- Hosted signup, verification, trial expiry, and saved-report read-only behavior remain unverified against a designated test identity.
- Do not enable signup until delivery, CAPTCHA/rate limits, redirect allowlist, and an end-to-end test are confirmed.
