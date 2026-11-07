# Supplier / email configuration gap (`cadivor-next-api-prod`)

Compared **variable names/presence only** (no values logged).

## Required by mature engine

From `integrations/supplier_aggregator.py`, `integrations/*_client.py`, `src/email_delivery.py`:

| Variable | On `cadivor-next-api-prod` (production) | In GitHub Actions secrets | Notes |
| --- | --- | --- | --- |
| `MOUSER_API_KEY` | missing | present | Required for Mouser |
| `DIGIKEY_CLIENT_ID` | missing | present | Required for Digi-Key |
| `DIGIKEY_CLIENT_SECRET` | missing | present | Required for Digi-Key |
| `NEWARK_API_KEY` | missing | absent | Optional if Newark unused |
| `NEXAR_CLIENT_ID` / `OCTOPART_CLIENT_ID` | missing | absent | Nexar/Octopart catalog |
| `NEXAR_CLIENT_SECRET` / `OCTOPART_CLIENT_SECRET` | missing | absent | |
| `RESEND_API_KEY` | missing | present | Workspace invitation email |
| `TRANSACTIONAL_FROM_EMAIL` | missing | absent | Preferred sender; `TRANSACTIONAL_FROM` also accepted by code |

Present on prod API today (app-relevant): `SUPABASE_URL`, `SUPABASE_KEY`, `CADIVOR_MIGRATION_DATABASE_URL`, `CADIVOR_WEB_ORIGINS`.

## Legacy Streamlit service

Railway project `incredible-radiance` / service `bom-risk-checker` (documented in `docs/RAILWAY_DEPLOYMENT.md`) **no longer has services**. Secure same-project variable transfer is therefore unavailable.

## Production health (live probe, 2026-11-07)

`GET https://cadivor-next-api-prod-production.up.railway.app/health`:

- `mode`: `legacy-supplier-engine` (code path ready)
- `suppliers`: `credentials-not-present`
- `supplier_provider_count`: `0`
- `email` / `alert_email`: `disabled`

## Transfer plan (no secret values in git)

1. When credentials are available via Railway secure UI or operator paste, set on `cadivor-next-api-prod` / `production` using `railway variables --set` **without echoing values**.
2. Prefer copying from GitHub Actions secrets through a one-shot operator-run sync (values never committed).
3. After set: redeploy API, re-probe `/health` for `suppliers: configured` and synthetic `AM29F010B-70EC` / `LM358DR` find-replacement with honest provider coverage.
