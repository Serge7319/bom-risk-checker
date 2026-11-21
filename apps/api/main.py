"""Cadivor API for the Next.js application.

Production uses Supabase Auth, the established BOM/supplier analysis modules,
and a dedicated Railway Postgres workspace store. One-time report and monthly
subscription billing use Supabase Edge Functions with the existing Stripe setup.
"""
from __future__ import annotations

import json
import hashlib
import logging
import math
import os
import re
import secrets
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api import migration_tools  # noqa: E402
from apps.api.report_visibility import (
    customer_visible_analyses,
    customer_visible_projects,
    is_internal_test_fixture_analysis,
)  # noqa: E402
from apps.api.synthetic_analyze import (  # noqa: E402
    PersistenceVerifyError,
    analyze_upload,
    delete_project as delete_project_record,
    delete_report,
    get_report,
    list_reports,
    parse_bom_bytes,
    recalculate_report_health,
)
from apps.api.sandbox_auth import (  # noqa: E402
    AuthError,
    AuthNotConfiguredError,
    auth_configured as sandbox_auth_configured,
    describe_auth as describe_sandbox_auth,
    get_auth_store,
    is_production_runtime,
    login as sandbox_login,
    logout as sandbox_logout,
    resolve_bearer as sandbox_resolve_bearer,
    sandbox_jwt_permitted,
)
from apps.api import supabase_auth  # noqa: E402
from src.ui.detailed_risk_export import detailed_risk_csv_bytes  # noqa: E402
from apps.api.workspace_store import (  # noqa: E402
    PersistenceNotConfiguredError,
    WorkspaceAccessError,
    describe_persistence,
    get_store,
)
from src.saved_bom_project import split_project_and_bom  # noqa: E402

from apps.api import billing_prep  # noqa: E402
from apps.api import compliance_packs  # noqa: E402
from apps.api import decision_record_exports  # noqa: E402
from apps.api import developer_webhooks  # noqa: E402
from apps.api import connectors  # noqa: E402
from apps.api import bom_validation  # noqa: E402
from apps.api import legal_acceptance  # noqa: E402
from apps.api import monitoring_store  # noqa: E402
from apps.api import monitoring_scheduler  # noqa: E402
from apps.api import slack_notifications  # noqa: E402
from apps.api import marketing_leads  # noqa: E402
from apps.api import marketing_analytics  # noqa: E402
from apps.api.marketing_attribution import sanitize_marketing_attribution  # noqa: E402
from apps.api import plan_limits  # noqa: E402
from apps.api import invitation_email  # noqa: E402
from apps.api import supplier_lookup  # noqa: E402
from apps.api import one_time_report_service  # noqa: E402
from apps.api import subscription_billing_service  # noqa: E402
from apps.api import team_service  # noqa: E402
from apps.api.team_service import TeamError  # noqa: E402
from apps.api.evidence_contract import annotate_report_parts  # noqa: E402
from apps.api.comparison_snapshot_trust import (  # noqa: E402
    attach_snapshot_token,
    materialize_snapshot_for_reuse,
    server_verified_primary_evidence,
)
from apps.api.report_exports import (  # noqa: E402
    build_report_export,
    safe_download_stem,
)
from src.datasheet_comparison import MAX_DATASHEET_BYTES  # noqa: E402


def _get_visible_report(analysis_id: str, *, workspace_id: str) -> dict[str, Any] | None:
    report = get_report(analysis_id, workspace_id=workspace_id)
    if report and is_production_runtime() and is_internal_test_fixture_analysis(report):
        return None
    return report

# Demo passwords are not shipped in the API. Tests import
# tests.fixtures.sandbox_auth_accounts; operators seed via
# python -m apps.api.seed_sandbox_demo (sandbox-only).

_origins = [
    origin.strip()
    for origin in os.environ.get(
        "CADIVOR_WEB_ORIGINS",
        "http://127.0.0.1:3000,http://localhost:3000,"
        "https://app.cadivor.com,"
        "https://cadivor-next-web-sandbox.up.railway.app",
    ).split(",")
    if origin.strip()
]


def _json(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status_code)


def _use_supabase_auth() -> bool:
    """Production runtimes always use Supabase Auth; HS256 stays sandbox-only."""
    if is_production_runtime():
        return True
    if (os.environ.get("CADIVOR_USE_SUPABASE_AUTH") or "").strip() == "1":
        return True
    return False


def auth_configured() -> bool:
    if _use_supabase_auth():
        return supabase_auth.supabase_auth_configured()
    return sandbox_auth_configured()


def describe_auth() -> dict[str, Any]:
    if _use_supabase_auth():
        return supabase_auth.describe_supabase_auth()
    return describe_sandbox_auth()


def _auth_context(request: Request) -> tuple[dict[str, str] | None, JSONResponse | None]:
    """Verify bearer JWT and derive workspace from membership (never from client)."""
    authorization = request.headers.get("authorization") or ""
    if not authorization.startswith("Bearer "):
        return None, _json({"detail": "Missing bearer token"}, 401)
    token = authorization.removeprefix("Bearer ").strip()
    # Ignore any client-supplied workspace claim on the request.
    _ = request.query_params.get("workspace_id")
    try:
        if _use_supabase_auth():
            ctx = supabase_auth.resolve_bearer(token)
        else:
            ctx = sandbox_resolve_bearer(token)
    except AuthNotConfiguredError as exc:
        payload: dict[str, Any] = {"detail": str(exc)}
        if _use_supabase_auth():
            payload["missing_config_vars"] = supabase_auth.missing_config_vars()
            payload["setup_required"] = describe_auth().get("setup_required")
        return None, _json(payload, 503)
    except AuthError as exc:
        return None, _json({"detail": exc.detail}, exc.status_code)
    payload = ctx.as_dict()
    payload["entitlement_overrides"] = plan_limits.account_feature_overrides(
        str(payload.get("user_id") or "")
    )
    return payload, None


def _require_smoke_token(request: Request) -> JSONResponse | None:
    """Back-compat wrapper — prefer _auth_context for workspace scoping."""
    _ctx, err = _auth_context(request)
    return err


def _release_one_time_credit_if_report_was_not_saved(
    *, access_token: str, order_id: str, analysis_id: str, workspace_id: str
) -> None:
    """Release only when the durable workspace store confirms no report exists."""
    try:
        if get_report(analysis_id, workspace_id=workspace_id):
            return
    except Exception:  # noqa: BLE001
        # An uncertain store state must not recycle a paid credit.
        return
    try:
        one_time_report_service.request_action(
            access_token=access_token,
            action="release",
            payload={"order_id": order_id},
        )
    except one_time_report_service.OneTimeReportServiceError:
        pass


async def health(_: Request) -> JSONResponse:
    persistence = describe_persistence()
    store_path_basename = None
    try:
        store = get_store()
        store_path_basename = getattr(getattr(store, "path", None), "name", None)
    except PersistenceNotConfiguredError:
        store_path_basename = None
    auth = describe_auth()
    using_supabase = _use_supabase_auth()
    from apps.api.legacy_supplier_workflow import (
        configured_supplier_count,
        production_analysis_enabled,
    )
    supplier_count = configured_supplier_count()
    legacy_engine = production_analysis_enabled()
    return _json(
        {
            "ok": True,
            "service": "cadivor-migration-api",
            "mode": "legacy-supplier-engine" if legacy_engine else "synthetic-preview",
            "suppliers": (
                "configured"
                if supplier_count
                else "credentials-not-present" if legacy_engine else "disabled"
            ),
            "stripe": "one-time-report-managed-by-supabase-edge-function",
            "email": (
                "signup-verification-only"
                if _use_supabase_auth() and supabase_auth.signup_enabled()
                else "disabled"
            ),
            "alert_email": "disabled",
            "auth": auth,
            "auth_configured": auth_configured(),
            "self_serve_signup_enabled": bool(
                _use_supabase_auth() and supabase_auth.signup_enabled()
            ),
            "trial_length_days": supabase_auth.TRIAL_DAYS,
            "auth_path": "supabase" if using_supabase else "sandbox-jwt",
            "sandbox_jwt_permitted": sandbox_jwt_permitted(),
            "production_runtime": is_production_runtime(),
            "tools": [
                "monitoring",
                "compare-parts",
                "decision-records",
                "datasheet-qa",
                "procurement",
                "procurement-quotes",
                "design-impact",
                "cost-optimization",
                "supply-risk",
                "portfolio",
                "detailed-risk",
                "supplier-lookup",
                "compliance",
                "connectors",
                "billing-status",
                "one-time-report",
                "plan-usage",
            ],
            "foundation": [
                "workspace-store",
                "projects",
                "bom-hierarchy-rollup",
                "home-dashboard",
                "workspace-isolation",
                "sandbox-jwt-auth",
                "supabase-jwt-auth",
                "plan-limits",
                "monitoring-store",
                "evidence-contract",
            ],
            "suppliers_live": bool(legacy_engine and supplier_count),
            "supplier_provider_count": supplier_count,
            "stripe_checkout_enabled": billing_prep.checkout_enabled(),
            "one_time_report_bridge": "supabase-edge-function",
            "monitoring_email_enabled": monitoring_store.email_delivery_enabled(),
            "monitoring_scheduler_enabled": monitoring_scheduler.scheduler_enabled(),
            "persistence": {
                **persistence,
                "store_path_basename": store_path_basename,
                # Auth may use Cadivor Supabase; migration *records* never use
                # the Streamlit Supabase data store.
                "streamlit_supabase_data_store_unused": True,
                "migration_database_required": True,
            },
        }
    )


async def auth_login(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    # Client may send workspace_id; it is ignored — membership decides.
    requested_ws = body.get("workspace_id")
    try:
        if _use_supabase_auth():
            session = supabase_auth.login(
                email,
                password,
                requested_workspace_id=str(requested_ws or "") or None,
                invite_token=str(body.get("invite_token") or "") or None,
            )
        else:
            session = sandbox_login(
                email,
                password,
                requested_workspace_id=str(requested_ws or "") or None,
            )
    except AuthNotConfiguredError as exc:
        payload: dict[str, Any] = {
            "detail": str(exc),
            "setup_required": describe_auth().get("setup_required"),
        }
        if _use_supabase_auth():
            payload["missing_config_vars"] = supabase_auth.missing_config_vars()
        return _json(payload, 503)
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    return _json(session)


def _web_origin(request: Request) -> str:
    """Prefer an allowlisted Origin / Referer; fall back to the first CADIVOR_WEB_ORIGINS entry."""
    candidates = [
        str(request.headers.get("origin") or "").strip().rstrip("/"),
        str(request.headers.get("referer") or "").strip().rstrip("/"),
    ]
    allowed = {origin.rstrip("/") for origin in _origins}
    for candidate in candidates:
        if not candidate:
            continue
        # Referer may include a path.
        origin = candidate.split("/login", 1)[0].split("/settings", 1)[0]
        if origin in allowed:
            return origin
        if any(origin.startswith(item) for item in allowed):
            return next(item for item in allowed if origin.startswith(item))
    https = [o for o in _origins if o.startswith("https://")]
    return (https[0] if https else (_origins[0] if _origins else "http://localhost:3000")).rstrip("/")



def _accepted_terms(body: dict) -> bool:
    value = body.get("accepted_terms")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _legal_acceptance_error(exc: legal_acceptance.LegalAcceptanceError) -> JSONResponse:
    return _json({"detail": exc.detail, "code": exc.code}, exc.status_code)


def _record_legal_acceptance(**kwargs):
    """Persist consent or raise LegalAcceptanceError (never creates accounts)."""
    return legal_acceptance.record_acceptance(**kwargs)


async def auth_signup_config(_: Request) -> JSONResponse:
    """Expose public onboarding availability without exposing auth configuration."""
    enabled = bool(_use_supabase_auth() and supabase_auth.signup_enabled())
    return _json(
        {
            "signup_enabled": enabled,
            "trial_length_days": supabase_auth.TRIAL_DAYS,
            "invitations_enabled": True,
            **legal_acceptance.published_versions(),
        }
    )


async def auth_signup(request: Request) -> JSONResponse:
    if not _use_supabase_auth() or not supabase_auth.signup_enabled():
        return _json({"detail": "Self-serve signup is not enabled"}, 503)
    # Rate-limit before any consent write so retries cannot flood the audit log.
    if _throttled(request, "signup", limit=5, window=600):
        return _json(
            {"detail": "Too many signup attempts. Wait a few minutes and try again.", "code": "signup_rate_limited"},
            429,
        )
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Invalid JSON"}, 400)
    if not _accepted_terms(body):
        return _json(
            {"detail": "Agree to the Terms of Service and Privacy Policy to continue."},
            400,
        )
    # Validate payload + CAPTCHA before inserting consent.
    try:
        email_n, workspace_n, captcha_token = supabase_auth.validate_signup_fields(
            str(body.get("email") or ""),
            str(body.get("password") or ""),
            str(body.get("workspace_name") or ""),
            captcha_token=str(body.get("captcha_token") or "") or None,
        )
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    try:
        acceptance = legal_acceptance.record_acceptance_for_signup(
            email=email_n,
            source="signup",
            workspace_name=workspace_n or None,
            terms_version=str(body.get("terms_version") or "") or None,
            privacy_version=str(body.get("privacy_version") or "") or None,
        )
    except legal_acceptance.LegalAcceptanceError as exc:
        return _legal_acceptance_error(exc)
    try:
        result = supabase_auth.signup(
            email_n,
            str(body.get("password") or ""),
            workspace_n,
            captcha_token=captcha_token,
            marketing_attribution=sanitize_marketing_attribution(
        