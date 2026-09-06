# Cadivor Railway Deployment

This guide covers deploying the Cadivor Streamlit application to Railway for isolated verification before connecting `app.cadivor.com`.

## Repository connection

1. Create a new Railway service from the `bom-risk-checker` GitHub repository.
2. Confirm Railway uses `railway.toml` as the authoritative deployment configuration.
3. Do **not** add a `Procfile`. The start command is defined in `railway.toml`.
4. The production entry file is **`streamlit_app.py`**, not `app.py`.

## Python version

Railway/Railpack reads `runtime.txt`:

```text
python-3.11.9
```

This prevents Railway from defaulting to Python 3.13, which is not validated for this application.

## Start command

Railway executes:

```bash
bash scripts/railway_start.sh
```

Which resolves to:

```bash
exec streamlit run streamlit_app.py \
  --server.address=0.0.0.0 \
  --server.port=$PORT \
  --server.headless=true \
  --browser.gatherUsageStats=false
```

Expected deploy logs:

- `streamlit run streamlit_app.py`
- not `python app.py`
- not `streamlit run app.py`

## Required Railway variables

Set these in the Railway service variables UI. Do not commit secret values.

### Required for startup

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon/service key used by the app |

### Origins for initial Railway test

| Variable | Initial value |
|----------|---------------|
| `CADIVOR_MARKETING_ORIGIN` | `https://www.cadivor.com` |
| `CADIVOR_APP_ORIGIN` | Railway generated URL, e.g. `https://<service>.up.railway.app` |

Do not set `CADIVOR_APP_ORIGIN` to `https://app.cadivor.com` until the Railway deployment is verified and DNS/TLS are ready.

### Stripe

| Variable | Purpose |
|----------|---------|
| `STRIPE_SECRET_KEY` | Stripe API secret |
| `STRIPE_PRO_PRICE_ID` | Professional plan price ID |
| `STRIPE_BUSINESS_PRICE_ID` | Business plan price ID |

Use Stripe test mode for Railway verification. Update Stripe callback URLs only after the Railway domain is known.

### Email alerts

| Variable | Purpose |
|----------|---------|
| `RESEND_API_KEY` | Resend API key |
| `ALERT_FROM_EMAIL` | Sender address for monitor alerts |

### Supplier APIs

| Variable | Purpose |
|----------|---------|
| `MOUSER_API_KEY` | Mouser API |
| `DIGIKEY_CLIENT_ID` | Digi-Key OAuth client ID |
| `DIGIKEY_CLIENT_SECRET` | Digi-Key OAuth client secret |
| `NEWARK_API_KEY` | Newark/element14 API (optional if unused) |

### AI

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Engineering Assistant provider key |
| `OPENAI_MODEL` | Optional, default `gpt-4.1-mini` |
| `OPENAI_BASE_URL` | Optional, default OpenAI API base URL |

### Feature flags (optional)

| Variable | Default |
|----------|---------|
| `ENABLE_DECISION_ENGINE_V2` | `true` |
| `ENABLE_DECISION_WORKSPACE_V71` | `true` |
| `CADIVOR_STARTUP_TIMING` | off |
| `CADIVOR_LOGOUT_TIMING` | off |

When `CADIVOR_STARTUP_TIMING` is enabled, Cadivor emits structured `CADIVOR_PERF`
JSON lines (in addition to legacy `[cadivor-startup]` milestones). See
`docs/RAILWAY_BUILD_FAILED_TRIAGE.md` for build-email triage.

## Secret loading

Cadivor resolves configuration through `src/secrets.py`:

1. `os.getenv(name)`
2. `st.secrets.get(name)` fallback for Streamlit Community Cloud and local `secrets.toml`
3. documented default for optional values only

Missing required values raise a configuration error naming only the variable, never the secret value.

## Generate the temporary Railway domain

1. Deploy the service.
2. Open Railway service settings → Networking → Generate Domain.
3. Copy the `.up.railway.app` URL.
4. Set `CADIVOR_APP_ORIGIN` to that exact HTTPS origin (no trailing slash).

## Supabase temporary redirect URLs

In the Supabase dashboard, add the Railway domain to allowed redirect URLs for auth testing, for example:

- `https://<service>.up.railway.app/**`

Do not change the production Site URL until cutover.

## Stripe test-mode callback considerations

After Railway assigns a domain, add test-mode success/cancel URLs based on `CADIVOR_APP_ORIGIN`, for example:

- `https://<service>.up.railway.app/?checkout=success&session_id={CHECKOUT_SESSION_ID}`
- `https://<service>.up.railway.app/?checkout=cancel`

### Stripe Customer Portal (self-service billing)

Cadivor’s Settings → Billing **Manage billing** button opens the Stripe-hosted
Customer Portal. Portal configuration is **not** controlled by app code and must
be set separately in each Stripe mode (Dashboard → Settings → Billing → Customer
portal):

| Mode | Configure before use |
|------|----------------------|
| **Sandbox / test** | Allow cancellation at period end, payment-method updates, and invoice history. Confirm the portal return URL origin matches `CADIVOR_APP_ORIGIN`. |
| **Live** | Configure the same options separately in live mode before launch. Do not assume test-mode settings carry over. |

The webhook remains the only source of truth for plan and subscription fields on
the Cadivor `users` row. Opening the portal does not locally mutate plan,
cancellation, or usage.

## Smoke-test checklist

- [ ] Deploy logs show `streamlit run streamlit_app.py`
- [ ] Python 3.11.x appears in build logs
- [ ] Login shell loads
- [ ] Authenticated Dashboard loads
- [ ] CSS/assets render correctly
- [ ] Sign-out returns to marketing origin
- [ ] Alternative Finder navigation works
- [ ] No secret values appear in logs
- [ ] No `KeyError: 'Risk Level'` from `app.py`

## Custom-domain cutover (later)

1. Verify Railway deployment on the temporary domain.
2. Point `app.cadivor.com` DNS to Railway.
3. Attach the custom domain in Railway.
4. Update `CADIVOR_APP_ORIGIN=https://app.cadivor.com`.
5. Update Supabase redirect URLs and Stripe production callbacks.
6. Update marketing Sign In links when ready.

## Rollback to Streamlit Community Cloud

Streamlit Community Cloud remains the existing production deployment until cutover is complete. To roll back:

1. Stop or disable the Railway service.
2. Keep Streamlit Community Cloud connected to `main` with entry file `streamlit_app.py`.
3. Restore `CADIVOR_APP_ORIGIN` wherever it was previously configured.
4. Remove temporary Railway redirect URLs from Supabase and Stripe when no longer needed.

## Local verification

```bash
pip install -r requirements.txt
PORT=8080 bash scripts/railway_start.sh
```

Open `http://localhost:8080`.
