# Cadivor Next.js migration (preview)

Same repository, branch `migrate/nextjs-shell-bom-flow`.

## Scope of this preview

- Shared Next.js shell + smoke login
- One end-to-end synthetic BOM flow: upload → analyze → report
- Python analysis uses existing `bom_parser`, `risk_engine`, and `health_score`
- Synthetic part evidence only — no live distributor calls, Stripe, or email
- **Production Streamlit on `app.cadivor.com` is unchanged**

## Local run

```bash
# Optional local API (port 8787)
.venv312/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8787

# Web (port 3000) — prefers apps/web/.env.local
# Default sandbox target:
# NEXT_PUBLIC_API_BASE=https://cadivor-next-api-sandbox.up.railway.app
cd apps/web
cp -n .env.example .env.local   # if needed
npm run dev
```

Smoke login: `auth-smoke@cadivor.test` / `cadivor-auth-smoke`  
Fixture: `tests/fixtures/synthetic_bom_25parts.csv`

## Railway

Use the **sandbox** environment only. Do not point the production domain at these services until cutover is approved.

## Verified local preview (2026-11-03)

- Web: `http://127.0.0.1:3000`
- API: `http://127.0.0.1:8787/health`
- Smoke login: `auth-smoke@cadivor.test` / `cadivor-auth-smoke`
- Evidence: `.evidence/nextjs_migration/` (login → shell → BOM Analyzer → 25-part report)
- API unit test: `tests/test_nextjs_migration_api.py`

## Railway sandbox

Services created in **sandbox** only (production domain untouched):

- `cadivor-next-api` → https://cadivor-next-api-sandbox.up.railway.app
- `cadivor-next-web` (created, not yet deployed)

### API startup fix (2026-11-04)

Root cause: Railpack deployed with start command `python main.py`. The previous
`main.py` only imported `app` and exited 0 immediately (container status
Completed → public 502). Fix: `main.py` now starts uvicorn when executed as
`__main__`. `scripts/railway_start.sh` also dispatches to
`start_migration_api.sh` when `RAILWAY_SERVICE_NAME=cadivor-next-api` so a
shared Streamlit `railway.toml` cannot boot Streamlit on the API service.

Verified after redeploy: `/health` 200, smoke login, and 25-part synthetic
analyze. Do not cut over `app.cadivor.com`.
