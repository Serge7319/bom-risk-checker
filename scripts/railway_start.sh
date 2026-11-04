#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${PORT:-}" ]]; then
  echo "Missing required environment variable: PORT" >&2
  exit 1
fi

# Same-repo sandbox services share this start script via railway.toml.
# Production bom-risk-checker keeps the Streamlit path below.
service_name="${RAILWAY_SERVICE_NAME:-}"
if [[ "${CADIVOR_RUNTIME:-}" == "next-api" || "${service_name}" == "cadivor-next-api" ]]; then
  echo "railway_start: dispatching migration API for service=${service_name}" >&2
  exec bash start_migration_api.sh
fi

# Prefer CADIVOR_APP_ORIGIN when set by Railway. Default matches production.
export CADIVOR_APP_ORIGIN="${CADIVOR_APP_ORIGIN:-https://app.cadivor.com}"

# Boot through the public-origin patch so XSRF upload CORS matches the browser
# Origin on TLS-terminated Railway. CORS and XSRF stay enabled.
exec python scripts/cadivor_streamlit_boot.py
