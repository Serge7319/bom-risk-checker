"""Local evidence-only API launcher: seed sandbox users then serve uvicorn."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    os.environ.setdefault("CADIVOR_SANDBOX_AUTH_SECRET", "evidence-sandbox-auth-secret-key")
    os.environ.setdefault("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    os.environ.setdefault("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    os.environ.setdefault(
        "CADIVOR_WEB_ORIGINS",
        "http://127.0.0.1:3005,http://localhost:3005,http://127.0.0.1:3000,http://localhost:3000",
    )
    os.environ.setdefault("CADIVOR_SEED_SANDBOX_DEMO_USERS", "1")
    os.environ.pop("RAILWAY_ENVIRONMENT", None)
    os.environ.pop("CADIVOR_FORCE_PRODUCTION_AUTH", None)

    import sys

    sys.path.insert(0, str(ROOT))
    from apps.api.sandbox_auth import reset_auth_store_for_tests, seed_demo_users
    from apps.api.workspace_store import reset_store_for_tests
    from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS

    reset_store_for_tests(Path("/tmp/cadivor_evidence_store.json"))
    reset_auth_store_for_tests(
        Path("/tmp/cadivor_evidence_auth.json"), accounts=SANDBOX_SEED_USERS
    )
    print("evidence-api seeded", [u["email"] for u in SANDBOX_SEED_USERS], flush=True)

    import uvicorn
    from apps.api.main import app

    port = int(os.environ.get("PORT", "8787"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
