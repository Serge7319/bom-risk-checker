#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${PORT:-}" ]]; then
  echo "Missing required environment variable: PORT" >&2
  exit 1
fi

exec streamlit run streamlit_app.py \
  --server.address=0.0.0.0 \
  --server.port="${PORT}" \
  --server.headless=true \
  --server.enableCORS=true \
  --server.enableXsrfProtection=true \
  --browser.serverAddress=app.cadivor.com \
  --browser.serverPort=443 \
  --browser.gatherUsageStats=false
