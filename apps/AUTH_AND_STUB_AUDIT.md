# Auth & stub audit — Next.js migration (**sandbox-only**)

Branch: `migrate/nextjs-shell-bom-flow` · PR #565 (open; auth work **not committed yet**)
Environment: Railway **sandbox** (`modest-vibrancy`)
**Custom HS256 JWT is sandbox migration auth only — not production authentication.**
Production Supabase Auth remains a separate future task. No commit / push / merge / production deploy in this slice.

| Service | Deploy | URL |
| --- | --- | --- |
| API | `fc39d25d-a95f-4fd0-9f54-80916275256e` | https://cadivor-next-api-sandbox.up.railway.app |
| Web | `1fbc54f0-971b-4f16-b830-a3f255cd958a` | https://cadivor-next-web-sandbox.up.railway.app |
| Evidence | | `apps/MIGRATION_SANDBOX_AUTH_VERIFY.json` |

## Fixed (hardening requested)

| Item | Status |
| --- | --- |
| Demo passwords in application source | **Fixed.** Removed from `apps/api` and `apps/web`. Login fields start empty; copy states credentials are not shipped. |
| Test credentials location | **Fixed.** Only in `tests/fixtures/sandbox_auth_accounts.py`. |
| Demo-user seeding | **Fixed.** Explicit sandbox-only step: `seed_demo_users(...)` / `python -m apps.api.seed_sandbox_demo` with `CADIVOR_SEED_SANDBOX_DEMO_USERS=1` + JSON/file. Login/resolve do **not** auto-seed (`test_login_does_not_auto_seed_users`). |
| Production + `CADIVOR_ALLOW_SANDBOX_JWT=1` + secret | **Fixed / proven.** `is_production_runtime()` wins first. `test_production_blocks_even_when_allow_sandbox_jwt_and_secret_set` → login **503**, seed blocked, `sandbox_jwt_permitted: false`. |
| Authenticated API **401** leaves stale session | **Fixed.** `apiJson` clears localStorage and redirects to `/login` when a bearer request returns **401**. Hosted browser: revoked token → `/login` with `session: null`. |

## Auth model (sandbox JWT — still not production Auth)

| Topic | Behavior |
| --- | --- |
| Passwords | PBKDF2-HMAC-SHA256, 120k, `compare_digest` |
| Tokens | HS256 + 12h `exp` + `jti` revocation |
| Workspace | Membership table after verify; client `workspace_id` ignored |
| Cross-tenant | Foreign report → **404** (does not clear session) |
| Missing secret | Login **503** fail closed |
| Smoke login | **410** |

## Checks

- Pytest (sandbox auth + isolation + migration API/tools/foundation): **20 passed**
- Hosted sandbox browser E2E: empty login → login A → reload → protected report → revoke → **401 → /login, session cleared** → login B → A’s report **not found**

## Remaining limitations (not fixed here)

1. **Production Auth** — Supabase (or equivalent) still a separate cutover task.
2. Revocation table has no TTL sweeper.
3. Stub pages + suppliers / Stripe / email not production-ready.
4. Auth remains **uncommitted**; sandbox redeploys only.
5. Demo passwords still exist in **test fixtures** (intentional). New empty sandbox DBs need the explicit seed CLI/env (existing sandbox Postgres users already present).
