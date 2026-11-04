"""Explicit sandbox-only demo user seed.

Run against sandbox (never production):

  CADIVOR_SANDBOX_AUTH_SECRET=... \\
  CADIVOR_MIGRATION_DATABASE_URL=... \\
  RAILWAY_ENVIRONMENT=sandbox \\
  CADIVOR_SANDBOX_DEMO_USERS_JSON='[{"email":"...","password":"...","workspace_id":"...","workspace":"...","plan":"Trial"}]' \\
  python -m apps.api.seed_sandbox_demo

Or point at a local JSON file (not committed with secrets):

  CADIVOR_SANDBOX_DEMO_USERS_FILE=/path/to/demo_users.json \\
  python -m apps.api.seed_sandbox_demo

Requires CADIVOR_SEED_SANDBOX_DEMO_USERS=1 as an explicit opt-in.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if (os.environ.get("CADIVOR_SEED_SANDBOX_DEMO_USERS") or "").strip() != "1":
        print(
            "Refusing to seed: set CADIVOR_SEED_SANDBOX_DEMO_USERS=1 "
            "for an explicit sandbox-only setup step.",
            file=sys.stderr,
        )
        return 2

    from apps.api.sandbox_auth import (
        AuthNotConfiguredError,
        is_production_runtime,
        seed_demo_users,
    )

    if is_production_runtime():
        print("Refusing to seed: production runtime (fail closed).", file=sys.stderr)
        return 2

    raw = (os.environ.get("CADIVOR_SANDBOX_DEMO_USERS_JSON") or "").strip()
    file_path = (os.environ.get("CADIVOR_SANDBOX_DEMO_USERS_FILE") or "").strip()
    if file_path:
        raw = Path(file_path).read_text(encoding="utf-8")
    if not raw:
        print(
            "Provide CADIVOR_SANDBOX_DEMO_USERS_JSON or CADIVOR_SANDBOX_DEMO_USERS_FILE.",
            file=sys.stderr,
        )
        return 2

    try:
        accounts = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid demo users JSON: {exc}", file=sys.stderr)
        return 2

    if not isinstance(accounts, list) or not accounts:
        print("Demo users JSON must be a non-empty list.", file=sys.stderr)
        return 2

    try:
        seeded = seed_demo_users(accounts)
    except AuthNotConfiguredError as exc:
        print(f"Seed blocked: {exc}", file=sys.stderr)
        return 2
    except (TypeError, ValueError) as exc:
        print(f"Seed failed: {exc}", file=sys.stderr)
        return 2

    print(json.dumps({"ok": True, "seeded": seeded, "sandbox_only": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
