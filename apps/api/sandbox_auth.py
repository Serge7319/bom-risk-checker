"""Sandbox migration auth — signed JWTs + membership-derived workspace.

Verifies tokens server-side. Workspace is resolved from membership tables for
the authenticated user_id; client-supplied workspace_id is never trusted.

Requires CADIVOR_SANDBOX_AUTH_SECRET. Uses the same CADIVOR_MIGRATION_DATABASE_URL
Postgres for durable users/memberships/revocations when configured; otherwise a
local file store for tests (CADIVOR_ALLOW_EPHEMERAL_FILE_STORE).

Does NOT read production SUPABASE_* credentials.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_PBKDF2_ROUNDS = 120_000
_TOKEN_TTL_SECONDS = 60 * 60 * 12  # 12h
_DEFAULT_FILE = Path(
    os.environ.get(
        "CADIVOR_SANDBOX_AUTH_STORE",
        str(
            Path(__file__).resolve().parents[2]
            / ".evidence"
            / "nextjs_migration"
            / "sandbox_auth_store.json"
        ),
    )
)

# Demo passwords are NOT stored in application source. Seed via
# `seed_demo_users(...)` / `python -m apps.api.seed_sandbox_demo` (explicit
# sandbox-only setup). Test credentials live in tests/fixtures/sandbox_auth_accounts.py.


class AuthError(Exception):
    def __init__(self, detail: str, status_code: int = 401) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class AuthNotConfiguredError(RuntimeError):
    """Raised when sandbox JWT auth is unavailable or blocked."""


def railway_environment() -> str:
    return (os.environ.get("RAILWAY_ENVIRONMENT") or "").strip().lower()


def is_production_runtime() -> bool:
    """True when this process must not accept sandbox JWT / seed accounts."""
    env = railway_environment()
    if env in {"production", "prod"}:
        return True
    if (os.environ.get("CADIVOR_FORCE_PRODUCTION_AUTH") or "").strip() == "1":
        return True
    origin = (os.environ.get("CADIVOR_APP_ORIGIN") or "").strip().lower()
    if "app.cadivor.com" in origin and env not in {"sandbox", "staging"}:
        # Production Streamlit origin on a non-sandbox env → fail closed.
        return True
    return False


def sandbox_jwt_permitted() -> bool:
    """Sandbox HS256 JWT is never a production auth path."""
    if is_production_runtime():
        return False
    env = railway_environment()
    if env == "sandbox":
        return True
    if (os.environ.get("CADIVOR_ALLOW_SANDBOX_JWT") or "").strip() == "1":
        return True
    # Local / CI tests without Railway: require ephemeral allow flag.
    if not env and (os.environ.get("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE") or "").strip() == "1":
        return True
    return False


def auth_secret() -> str:
    return (os.environ.get("CADIVOR_SANDBOX_AUTH_SECRET") or "").strip()


def auth_configured() -> bool:
    """Ready to issue/verify sandbox JWTs (never true in production runtime)."""
    return sandbox_jwt_permitted() and bool(auth_secret())


def describe_auth() -> dict[str, Any]:
    permitted = sandbox_jwt_permitted()
    secret_set = bool(auth_secret())
    ready = auth_configured()
    db = bool((os.environ.get("CADIVOR_MIGRATION_DATABASE_URL") or "").strip())
    setup: list[str] = []
    if is_production_runtime():
        setup = [
            "Sandbox JWT auth is disabled on production runtimes (fail closed).",
            "Wire production Supabase Auth / verified membership separately — "
            "do not set CADIVOR_SANDBOX_AUTH_SECRET or seed sandbox users in production.",
        ]
    elif not secret_set:
        setup = [
            "Set CADIVOR_SANDBOX_AUTH_SECRET on sandbox cadivor-next-api only "
            "(random 32+ byte secret; do not reuse production secrets).",
            "Keep CADIVOR_MIGRATION_DATABASE_URL pointed at sandbox Postgres "
            "(already separate from production Supabase).",
            "Do not copy SUPABASE_* from bom-risk-checker / production onto "
            "cadivor-next-api for this auth path.",
            "Seed demo users only via explicit sandbox setup "
            "(python -m apps.api.seed_sandbox_demo with "
            "CADIVOR_SEED_SANDBOX_DEMO_USERS=1); passwords are not in app source.",
        ]
    elif not permitted:
        setup = [
            "Sandbox JWT is not permitted in this environment. "
            "Use RAILWAY_ENVIRONMENT=sandbox or CADIVOR_ALLOW_SANDBOX_JWT=1 for local tests only.",
        ]
    return {
        "mode": "sandbox-jwt-membership" if ready else (
            "blocked-production" if is_production_runtime() else "unconfigured"
        ),
        "sandbox_only": True,
        "production_auth": False,
        "production_runtime": is_production_runtime(),
        "sandbox_jwt_permitted": permitted,
        "token_verification": "server-side-hs256" if ready else None,
        "workspace_source": "membership_table" if ready else None,
        "client_workspace_id_trusted": False,
        "production_supabase_unused": True,
        "smoke_login_default": False,
        "auth_secret_configured": secret_set,
        "membership_backend": (
            "postgres" if (ready and db) else ("file" if ready else None)
        ),
        "setup_required": setup,
    }


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS
    )
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${_b64url(salt)}${_b64url(digest)}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds_s, salt_b64, digest_b64 = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        rounds = int(rounds_s)
        salt = _b64url_decode(salt_b64)
        expected = _b64url_decode(digest_b64)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, rounds
    )
    return hmac.compare_digest(actual, expected)


def _require_sandbox_jwt_runtime() -> str:
    if is_production_runtime():
        raise AuthNotConfiguredError(
            "Sandbox JWT auth is disabled outside sandbox (fail closed). "
            "Configure production Auth separately; do not use CADIVOR_SANDBOX_AUTH_SECRET "
            "or sandbox seed accounts in production."
        )
    if not sandbox_jwt_permitted():
        raise AuthNotConfiguredError(
            "Sandbox JWT auth is not permitted in this environment."
        )
    secret = auth_secret()
    if not secret:
        raise AuthNotConfiguredError(
            "CADIVOR_SANDBOX_AUTH_SECRET is required for sandbox JWT auth"
        )
    return secret


def _sign_jwt(claims: dict[str, Any]) -> str:
    secret = _require_sandbox_jwt_runtime()
    header = {"alg": "HS256", "typ": "JWT"}
    segments = [
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    segments.append(_b64url(sig))
    return ".".join(segments)


def _verify_jwt(token: str) -> dict[str, Any]:
    secret = _require_sandbox_jwt_runtime()
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("Invalid token")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        actual = _b64url_decode(parts[2])
    except Exception as exc:  # noqa: BLE001
        raise AuthError("Invalid token") from exc
    if not hmac.compare_digest(expected, actual):
        raise AuthError("Invalid token")
    try:
        claims = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AuthError("Invalid token") from exc
    exp = int(claims.get("exp") or 0)
    if exp and int(time.time()) >= exp:
        raise AuthError("Token expired")
    return claims


@dataclass
class AuthContext:
    user_id: str
    email: str
    workspace_id: str
    workspace: str
    plan: str
    access_token: str
    jti: str
    mode: str = "sandbox-jwt"
    trial_started_at: str | None = None
    trial_ends_at: str | None = None
    trial_status: str | None = None
    trial_days_remaining: int | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user_id": self.user_id,
            "email": self.email,
            "workspace_id": self.workspace_id,
            "workspace": self.workspace,
            "plan": self.plan,
            "access_token": self.access_token,
            "jti": self.jti,
            "mode": self.mode,
        }
        if self.trial_started_at is not None:
            payload["trial_started_at"] = self.trial_started_at
        if self.trial_ends_at is not None:
            payload["trial_ends_at"] = self.trial_ends_at
        if self.trial_status is not None:
            payload["trial_status"] = self.trial_status
        if self.trial_days_remaining is not None:
            payload["trial_days_remaining"] = self.trial_days_remaining
        return payload


class _FileAuthStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else _DEFAULT_FILE
        self._data = {"users": {}, "memberships": {}, "revoked": {}}
        self.load()

    def load(self) -> None:
        with _LOCK:
            if self.path.exists():
                try:
                    self._data = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    self._data = {"users": {}, "memberships": {}, "revoked": {}}
            else:
                self._data = {"users": {}, "memberships": {}, "revoked": {}}

    def save(self) -> None:
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def clear(self) -> None:
        with _LOCK:
            self._data = {"users": {}, "memberships": {}, "revoked": {}}
            self.save()

    def ensure_schema(self) -> None:
        self.load()

    def upsert_user(
        self,
        *,
        email: str,
        password: str,
        workspace_id: str,
        workspace: str,
        plan: str,
    ) -> str:
        email_n = email.strip().lower()
        with _LOCK:
            for uid, row in self._data["users"].items():
                if row.get("email") == email_n:
                    row["password_hash"] = _hash_password(password)
                    row["plan"] = plan
                    self._data["memberships"][uid] = {
                        "user_id": uid,
                        "workspace_id": workspace_id,
                        "workspace_name": workspace,
                        "role": "owner",
                    }
                    self.save()
                    return uid
            uid = str(uuid.uuid4())
            self._data["users"][uid] = {
                "id": uid,
                "email": email_n,
                "password_hash": _hash_password(password),
                "plan": plan,
                "created_at": int(time.time()),
            }
            self._data["memberships"][uid] = {
                "user_id": uid,
                "workspace_id": workspace_id,
                "workspace_name": workspace,
                "role": "owner",
            }
            self.save()
            return uid

    def find_user_by_email(self, email: str) -> dict[str, Any] | None:
        email_n = email.strip().lower()
        with _LOCK:
            for row in self._data["users"].values():
                if row.get("email") == email_n:
                    return dict(row)
        return None

    def membership_for_user(self, user_id: str) -> dict[str, Any] | None:
        with _LOCK:
            row = self._data["memberships"].get(user_id)
            return dict(row) if row else None

    def ensure_supabase_owner(
        self,
        *,
        user_id: str,
        email: str,
        workspace_id: str,
        workspace: str,
        plan: str = "Trial",
    ) -> dict[str, Any]:
        """Link a verified Supabase owner and start a first-login trial once."""
        email_n = email.strip().lower()
        with _LOCK:
            for uid, row in list(self._data["users"].items()):
                if row.get("email") == email_n and uid != user_id:
                    self._data["users"].pop(uid, None)
                    self._data["memberships"].pop(uid, None)
            self._data["users"][user_id] = {
                "id": user_id,
                "email": email_n,
                "password_hash": _hash_password("__supabase_auth_managed__"),
                "plan": plan,
            }
            membership = self._data["memberships"].get(user_id, {})
            started = membership.get("trial_started_at") or datetime.now(timezone.utc).isoformat()
            ends = membership.get("trial_ends_at") or (
                datetime.fromisoformat(started.replace("Z", "+00:00"))
                + timedelta(days=14)
            ).isoformat()
            status = membership.get("subscription_status") or "trialing"
            self._data["memberships"][user_id] = {
                "user_id": user_id,
                "workspace_id": workspace_id,
                "workspace_name": workspace,
                "role": "owner",
                "trial_started_at": started,
                "trial_ends_at": ends,
                "subscription_status": status,
            }
            self.save()
            return {
                "user_id": user_id,
                "email": email_n,
                "workspace_id": workspace_id,
                "workspace": workspace,
                "plan": plan,
                "trial_started_at": started,
                "trial_ends_at": ends,
                "subscription_status": status,
            }

    def revoke(self, jti: str, exp: int) -> None:
        with _LOCK:
            self._data["revoked"][jti] = {"exp": exp, "revoked_at": int(time.time())}
            self.save()

    def is_revoked(self, jti: str) -> bool:
        with _LOCK:
            return jti in self._data["revoked"]


class _PostgresAuthStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._ready = False

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.database_url, row_factory=dict_row)

    def ensure_schema(self) -> None:
        with _LOCK:
            if self._ready:
                return
            sql = """
            CREATE TABLE IF NOT EXISTS migration_users (
              id TEXT PRIMARY KEY,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              plan TEXT NOT NULL DEFAULT 'Trial',
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS migration_workspace_members (
              user_id TEXT PRIMARY KEY REFERENCES migration_users(id) ON DELETE CASCADE,
              workspace_id TEXT NOT NULL,
              workspace_name TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'owner',
              trial_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              trial_ends_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '14 days'),
              subscription_status TEXT NOT NULL DEFAULT 'trialing',
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            ALTER TABLE migration_workspace_members
              ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
            ALTER TABLE migration_workspace_members
              ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ NOT NULL
              DEFAULT (NOW() + INTERVAL '14 days');
            ALTER TABLE migration_workspace_members
              ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT 'trialing';
            CREATE INDEX IF NOT EXISTS migration_ws_members_ws_idx
              ON migration_workspace_members (workspace_id);
            CREATE TABLE IF NOT EXISTS migration_revoked_tokens (
              jti TEXT PRIMARY KEY,
              exp BIGINT NOT NULL,
              revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
            with self._connect() as conn:
                conn.execute(sql)
                conn.commit()
            self._ready = True

    def clear(self) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                "TRUNCATE migration_revoked_tokens, migration_workspace_members, "
                "migration_users CASCADE"
            )
            conn.commit()

    def upsert_user(
        self,
        *,
        email: str,
        password: str,
        workspace_id: str,
        workspace: str,
        plan: str,
    ) -> str:
        self.ensure_schema()
        email_n = email.strip().lower()
        with _LOCK:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id FROM migration_users WHERE email = %s",
                    (email_n,),
                ).fetchone()
                password_hash = _hash_password(password)
                if row:
                    uid = str(row["id"])
                    conn.execute(
                        "UPDATE migration_users SET password_hash = %s, plan = %s WHERE id = %s",
                        (password_hash, plan, uid),
                    )
                else:
                    uid = str(uuid.uuid4())
                    conn.execute(
                        """
                        INSERT INTO migration_users (id, email, password_hash, plan)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (uid, email_n, password_hash, plan),
                    )
                conn.execute(
                    """
                    INSERT INTO migration_workspace_members
                      (user_id, workspace_id, workspace_name, role)
                    VALUES (%s, %s, %s, 'owner')
                    ON CONFLICT (user_id) DO UPDATE SET
                      workspace_id = EXCLUDED.workspace_id,
                      workspace_name = EXCLUDED.workspace_name,
                      role = EXCLUDED.role
                    """,
                    (uid, workspace_id, workspace),
                )
                conn.commit()
                return uid

    def find_user_by_email(self, email: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM migration_users WHERE email = %s",
                (email.strip().lower(),),
            ).fetchone()
            return dict(row) if row else None

    def membership_for_user(self, user_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM migration_workspace_members WHERE user_id = %s",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None

    def ensure_supabase_owner(
        self,
        *,
        user_id: str,
        email: str,
        workspace_id: str,
        workspace: str,
        plan: str = "Trial",
    ) -> dict[str, Any]:
        """Link a verified Supabase owner and start a first-login trial once."""
        self.ensure_schema()
        email_n = email.strip().lower()
        password_hash = _hash_password("__supabase_auth_managed__")
        with _LOCK:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM migration_users WHERE email = %s AND id <> %s",
                    (email_n, user_id),
                )
                conn.execute(
                    """
                    INSERT INTO migration_users (id, email, password_hash, plan)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      email = EXCLUDED.email,
                      plan = EXCLUDED.plan
                    """,
                    (user_id, email_n, password_hash, plan),
                )
                conn.execute(
                    """
                    INSERT INTO migration_workspace_members
                      (user_id, workspace_id, workspace_name, role)
                    VALUES (%s, %s, %s, 'owner')
                    ON CONFLICT (user_id) DO UPDATE SET
                      workspace_id = EXCLUDED.workspace_id,
                      workspace_name = EXCLUDED.workspace_name,
                      role = EXCLUDED.role
                    """,
                    (user_id, workspace_id, workspace),
                )
                membership = conn.execute(
                    "SELECT trial_started_at, trial_ends_at, subscription_status "
                    "FROM migration_workspace_members WHERE user_id = %s",
                    (user_id,),
                ).fetchone()
                conn.commit()
        membership = dict(membership or {})
        return {
            "user_id": user_id,
            "email": email_n,
            "workspace_id": workspace_id,
            "workspace": workspace,
            "plan": plan,
            "trial_started_at": membership.get("trial_started_at"),
            "trial_ends_at": membership.get("trial_ends_at"),
            "subscription_status": membership.get("subscription_status") or "trialing",
        }

    def revoke(self, jti: str, exp: int) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO migration_revoked_tokens (jti, exp)
                VALUES (%s, %s)
                ON CONFLICT (jti) DO NOTHING
                """,
                (jti, exp),
            )
            conn.commit()

    def is_revoked(self, jti: str) -> bool:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM migration_revoked_tokens WHERE jti = %s",
                (jti,),
            ).fetchone()
            return bool(row)


_STORE: Any | None = None
_SEEDED = False


def get_auth_store(path: Path | None = None) -> Any:
    global _STORE
    if path is not None:
        return _FileAuthStore(path)
    db_url = (os.environ.get("CADIVOR_MIGRATION_DATABASE_URL") or "").strip()
    if db_url:
        if _STORE is None or not isinstance(_STORE, _PostgresAuthStore):
            _STORE = _PostgresAuthStore(db_url)
        return _STORE
    if (os.environ.get("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE") or "").strip() == "1" or not (
        os.environ.get("RAILWAY_ENVIRONMENT") or ""
    ).strip():
        if _STORE is None or not isinstance(_STORE, _FileAuthStore):
            _STORE = _FileAuthStore()
        return _STORE
    raise AuthNotConfiguredError(
        "Sandbox auth store requires CADIVOR_MIGRATION_DATABASE_URL on Railway"
    )


def reset_auth_store_for_tests(
    path: Path,
    *,
    accounts: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> Any:
    """Reset ephemeral auth store for tests. Pass fixture accounts to seed explicitly."""
    global _STORE, _SEEDED
    os.environ.setdefault("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    os.environ.setdefault("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    os.environ.setdefault("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    os.environ.pop("CADIVOR_MIGRATION_DATABASE_URL", None)
    os.environ.pop("CADIVOR_FORCE_PRODUCTION_AUTH", None)
    os.environ.pop("RAILWAY_ENVIRONMENT", None)
    _STORE = _FileAuthStore(path)
    _STORE.clear()
    _SEEDED = False
    if accounts:
        seed_demo_users(accounts, store=_STORE)
    return _STORE


def seed_demo_users(
    accounts: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    store: Any | None = None,
) -> list[str]:
    """Explicit sandbox-only demo user seed. Passwords must be supplied by caller.

    Never called implicitly from login/resolve. Blocked on production runtimes.
    """
    global _SEEDED
    _require_sandbox_jwt_runtime()
    if is_production_runtime():
        raise AuthNotConfiguredError(
            "Sandbox demo user seeding is disabled outside sandbox (fail closed)."
        )
    if not accounts:
        raise ValueError("accounts must be a non-empty sequence")
    store = store or get_auth_store()
    store.ensure_schema()
    seeded: list[str] = []
    with _LOCK:
        for account in accounts:
            email = str(account.get("email") or "").strip().lower()
            password = str(account.get("password") or "")
            workspace_id = str(account.get("workspace_id") or "").strip()
            workspace = str(account.get("workspace") or workspace_id).strip()
            plan = str(account.get("plan") or "Trial").strip() or "Trial"
            if not email or not password or not workspace_id:
                raise ValueError(
                    "Each account requires email, password, and workspace_id"
                )
            store.upsert_user(
                email=email,
                password=password,
                workspace_id=workspace_id,
                workspace=workspace,
                plan=plan,
            )
            seeded.append(email)
        _SEEDED = True
    return seeded


def login(email: str, password: str, *, requested_workspace_id: str | None = None) -> dict[str, Any]:
    """Authenticate and return session. Ignores client workspace_id."""
    _require_sandbox_jwt_runtime()
    # Explicitly ignore any client-supplied workspace claim.
    _ = requested_workspace_id
    store = get_auth_store()
    user = store.find_user_by_email(email)
    if not user or not _verify_password(password, str(user.get("password_hash") or "")):
        raise AuthError("Invalid credentials")
    membership = store.membership_for_user(str(user["id"]))
    if not membership:
        raise AuthError("No workspace membership for user", 403)
    now = int(time.time())
    jti = str(uuid.uuid4())
    claims = {
        "sub": str(user["id"]),
        "email": str(user["email"]),
        "jti": jti,
        "iat": now,
        "exp": now + _TOKEN_TTL_SECONDS,
        # workspace_id is NOT a trusted claim — membership is re-resolved on each request
    }
    token = _sign_jwt(claims)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": _TOKEN_TTL_SECONDS,
        "email": str(user["email"]),
        "user_id": str(user["id"]),
        "workspace": str(membership.get("workspace_name") or membership["workspace_id"]),
        "workspace_id": str(membership["workspace_id"]),
        "plan": str(user.get("plan") or "Trial"),
        "mode": "sandbox-jwt",
        "sandbox_only": True,
    }


def logout(access_token: str) -> None:
    _require_sandbox_jwt_runtime()
    claims = _verify_jwt(access_token)
    jti = str(claims.get("jti") or "")
    if not jti:
        raise AuthError("Invalid token")
    get_auth_store().revoke(jti, int(claims.get("exp") or 0))


def resolve_bearer(access_token: str) -> AuthContext:
    _require_sandbox_jwt_runtime()
    claims = _verify_jwt(access_token)
    jti = str(claims.get("jti") or "")
    user_id = str(claims.get("sub") or "")
    if not jti or not user_id:
        raise AuthError("Invalid token")
    store = get_auth_store()
    if store.is_revoked(jti):
        raise AuthError("Token revoked")
    membership = store.membership_for_user(user_id)
    if not membership:
        raise AuthError("No workspace membership for user", 403)
    email = str(claims.get("email") or "")
    user = store.find_user_by_email(email) if email else None
    plan = str((user or {}).get("plan") or "Trial")
    return AuthContext(
        user_id=user_id,
        email=email,
        workspace_id=str(membership["workspace_id"]),
        workspace=str(membership.get("workspace_name") or membership["workspace_id"]),
        plan=plan,
        access_token=access_token,
        jti=jti,
    )


def issue_expired_token_for_tests(email: str) -> str:
    """Test helper: valid signature, already expired. Caller must have seeded users."""
    store = get_auth_store()
    user = store.find_user_by_email(email)
    if not user:
        raise AuthError("Unknown user")
    now = int(time.time())
    return _sign_jwt(
        {
            "sub": str(user["id"]),
            "email": str(user["email"]),
            "jti": str(uuid.uuid4()),
            "iat": now - 3600,
            "exp": now - 10,
        }
    )
