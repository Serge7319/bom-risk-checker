#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${PORT:-}" ]]; then
  echo "Missing required environment variable: PORT" >&2
  exit 1
fi

# The root Railway service now runs the Next.js API. Streamlit is retired.
exec bash apps/api/start.sh
