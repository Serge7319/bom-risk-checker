#!/usr/bin/env bash
set -euo pipefail
cd /app 2>/dev/null || cd "$(dirname "$0")"
export PYTHONPATH="${PYTHONPATH:-/app}:$(pwd)"
echo "cadivor-migration-api starting PYTHONPATH=$PYTHONPATH PORT=${PORT:-8787}"
python - <<'PY'
import main
print("import_ok", type(main.app))
PY
exec python -m uvicorn main:app --host 0.0.0.0 --port "${PORT:-8787}"
