#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${PORT:-}" ]]; then
  echo "Missing required environment variable: PORT" >&2
  exit 1
fi

# Prefer CADIVOR_APP_ORIGIN when set by Railway. Default matches production.
export CADIVOR_APP_ORIGIN="${CADIVOR_APP_ORIGIN:-https://app.cadivor.com}"

# Boot through the public-origin patch so XSRF upload CORS matches the browser
# Origin on TLS-terminated Railway. CORS and XSRF stay enabled.
exec python scripts/cadivor_streamlit_boot.py
