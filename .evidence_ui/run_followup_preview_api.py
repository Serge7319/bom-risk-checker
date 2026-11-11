from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["CADIVOR_SANDBOX_AUTH_SECRET"] = "evidence-sandbox-auth-secret-key"
os.environ["CADIVOR_ALLOW_EPHEMERAL_FILE_STORE"] = "1"
os.environ["CADIVOR_ALLOW_SANDBOX_JWT"] = "1"
os.environ["CADIVOR_ANALYSIS_MODE"] = "synthetic-preview"
os.environ["CADIVOR_WEB_ORIGINS"] = ",".join(
    [
        "http://127.0.0.1:3011",
        "http://localhost:3011",
        "http://127.0.0.1:3001",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]
)
os.environ["CADIVOR_SEED_SANDBOX_DEMO_USERS"] = "1"
os.environ.pop("RAILWAY_ENVIRONMENT", None)
os.environ.pop("CADIVOR_FORCE_PRODUCTION_AUTH", None)
sys.path.insert(0, str(ROOT))

from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS

reset_store_for_tests(Path("/tmp/cadivor_followup_store.json"))
reset_auth_store_for_tests(Path("/tmp/cadivor_followup_auth.json"), accounts=SANDBOX_SEED_USERS)
print("seeded", [u["email"] for u in SANDBOX_SEED_USERS], flush=True)

import uvicorn
from apps.api.main import app

uvicorn.run(app, host="127.0.0.1", port=8081, log_level="info")
