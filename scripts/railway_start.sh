#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${PORT:-}" ]]; then
  echo "Missing required environment variable: PORT" >&2
  exit 1
fi

# The Streamlit service and the separate Next migration API share this script.
# Keep both API service names on the API path; the customer app stays Streamlit.
service_name="${RAILWAY_SERVICE_NAME:-}"
if [[ "${CADIVOR_RUNTIME:-}" == "next-api" \
  || "${service_name}" == "cadivor-next-api" \
  || "${service_name}" == "cadivor-next-api-prod" ]]; then
  echo "railway_start: dispatching migration API for service=${service_name}" >&2
  exec bash apps/api/start.sh
fi

# Prefer CADIVOR_APP_ORIGIN when set by Railway. Default matches production.
export CADIVOR_APP_ORIGIN="${CADIVOR_APP_ORIGIN:-https://app.cadivor.com}"

# Boot through the public-origin patch so XSRF upload CORS matches the browser
# Origin on TLS-terminated Railway. CORS and XSRF stay enabled.
exec python scripts/cadivor_streamlit_boot.py
