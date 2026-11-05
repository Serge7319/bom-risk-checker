"""Test-only sandbox demo credentials — never imported by application runtime."""
from __future__ import annotations

# Passwords live here (tests / explicit seed tooling), not in apps/api or apps/web.
SANDBOX_ACCOUNTS: dict[str, dict[str, str]] = {
    "sandbox-a@cadivor.test": {
        "email": "sandbox-a@cadivor.test",
        "password": "CadivorSandbox!a",
        "workspace_id": "ws-sandbox-a",
        "workspace": "Sandbox Workspace A",
        "plan": "Trial",
    },
    "sandbox-b@cadivor.test": {
        "email": "sandbox-b@cadivor.test",
        "password": "CadivorSandbox!b",
        "workspace_id": "ws-sandbox-b",
        "workspace": "Sandbox Workspace B",
        "plan": "Trial",
    },
}

SANDBOX_SEED_USERS = tuple(SANDBOX_ACCOUNTS.values())

SMOKE_EMAIL = SANDBOX_SEED_USERS[0]["email"]
SMOKE_PASSWORD = SANDBOX_SEED_USERS[0]["password"]
SMOKE_WORKSPACE_ID = SANDBOX_SEED_USERS[0]["workspace_id"]
