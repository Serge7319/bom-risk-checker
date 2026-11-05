# Cadivor Next.js migration test build

Same repository, branch `migrate/nextjs-shell-bom-flow`.

## Scope of this preview

- Shared Next.js shell + Supabase Auth path on the migration API
- One end-to-end synthetic BOM flow: upload → analyze → report
- Python analysis uses existing `bom_parser`, `risk_engine`, and `health_score`
- Synthetic part evidence only — no live distributor calls, Stripe, or email
- **Production Streamlit on `app.cadivor.com` is unchanged**

## Local run

```bash
# Optional local API (port 8787)
.venv312/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8787

# Web (port 3000): configure the API target explicitly in apps/web/.env.local.
# Example for sandbox testing:
# NEXT_PUBLIC_API_BASE=https://cadivor-next-api-sandbox.up.railway.app
cd apps/web
npm run dev
```

Fixture: `tests/fixtures/synthetic_bom_25parts.csv`
Fixture: `tests/fixtures/synthetic_bom_25parts.csv`

## Railway deployment boundary

`app.cadivor.com` remains on the Streamlit service. The Next.js web/API test
services use separate Railway subdomains and a dedicated migration Postgres
database. A Railway environment named `production` does not mean the migration
app has replaced the customer-domain application.

## Verified local preview (2026-11-03)

- Web: `http://127.0.0.1:3000`
- API: `http://127.0.0.1:8787/health`
- Evidence: `.evidence/nextjs_migration/` (login → shell → BOM Analyzer → 25-part report)
- API unit test: `tests/test_nextjs_migration_api.py`

## Railway migration test services (2026-11-05)

The API and web services are separate from the customer app:

- `cadivor-next-api-prod` → https://cadivor-next-api-prod-production.up.railway.app
- `cadivor-next-web-prod` → https://cadivor-next-web-prod-production.up.railway.app
- `Postgres-FGtQ` is the dedicated migration record database; existing Streamlit saved-BOM data was not imported.

### API startup dispatch

The root `railway.toml` is shared with Streamlit. `scripts/railway_start.sh`
must dispatch `cadivor-next-api` and `cadivor-next-api-prod` to
`apps/api/start.sh`; `bom-risk-checker` stays on the Streamlit boot path.

The migration API uses Supabase Auth with workspace membership and dedicated
migration Postgres. The current production migration service's database
redeploy-survival and cross-workspace checks have not been re-run in this pass.
Do not cut over `app.cadivor.com` based on the migration smoke checks alone.
