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
# API (port 8787)
.venv312/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8787

# Web (port 3000)
cd apps/web
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8787 npm run dev
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

API image builds, but the sandbox container currently exits before serving (502). Local preview remains the verified path until the Railpack start command for this service is fixed. Do not cut over `app.cadivor.com`.
