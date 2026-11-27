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
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, ParamSpec, TypeVar
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
    current_priority_items,
    delete_project as delete_project_record,
    delete_report,
    get_report,
    list_reports,
    list_reports_with_parts,
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
from apps.api import account_admin_service  # noqa: E402
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


P = ParamSpec("P")
R = TypeVar("R")


def offload_sync_handler(
    handler: Callable[P, R],
) -> Callable[P, Coroutine[Any, Any, R]]:
    """Run a synchronous route body in Starlette's bounded worker pool."""

    @wraps(handler)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        return await run_in_threadpool(handler, *args, **kwargs)

    return wrapped


def _get_visible_report(analysis_id: str, *, workspace_id: str) -> dict[str, Any] | None:
    report = get_report(analysis_id, workspace_id=workspace_id)
    if report and is_production_runtime() and is_internal_test_fixture_analysis(report):
        return None
    return report


def _refresh_project_report_summaries(
    projects: list[dict[str, Any]], reports: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Overlay evidence-recalculated report summaries on saved project views."""
    report_by_id = {
        str(row.get("id") or row.get("analysis_id") or ""): row
        for row in reports
        if isinstance(row, dict)
    }
    refreshed: list[dict[str, Any]] = []
    for project in projects:
        project_copy = dict(project)
        boms = []
        for bom in project.get("boms") or []:
            if not isinstance(bom, dict):
                continue
            bom_copy = dict(bom)
            analysis_id = str(
                bom.get("latest_analysis_id")
                or (bom.get("latest_analysis") or {}).get("id")
                or ""
            )
            report = report_by_id.get(analysis_id)
            if report:
                bom_copy.update({
                    "latest_analysis": report,
                    "health_score": report.get("health_score"),
                    "health_status": report.get("health_status"),
                    "summary_message": report.get("summary_message"),
                    "needs_verification_count": report.get("needs_verification_count"),
                    "high_risk_count": report.get("high_risk_count"),
                    "medium_risk_count": report.get("medium_risk_count"),
                    "low_risk_count": report.get("low_risk_count"),
                    "has_hierarchy": report.get("has_hierarchy"),
                })
            boms.append(bom_copy)
        project_copy["boms"] = boms
        refreshed.append(project_copy)
    return refreshed

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


def _auth_context(
    request: Request, *, enforce_maintenance: bool = True
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
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
    if (
        enforce_maintenance
        and _use_supabase_auth()
        and payload.get("maintenance_mode") is True
        and payload.get("platform_role") != "admin"
    ):
        message = str(payload.get("maintenance_message") or "").strip()
        return None, _json(
            {
                "detail": message
                or "Cadivor is undergoing scheduled maintenance. Please try again shortly.",
                "code": "maintenance_mode",
            },
            503,
        )
    payload["entitlement_overrides"] = plan_limits.account_feature_overrides(
        str(payload.get("user_id") or "")
    )
    return payload, None



async def _auth_context_async(
    request: Request, *, enforce_maintenance: bool = True
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Resolve user/workspace auth without blocking concurrent API requests."""
    return await run_in_threadpool(
        _auth_context, request, enforce_maintenance=enforce_maintenance
    )

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


@offload_sync_handler
def health(_: Request) -> JSONResponse:
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


async def auth_login_complete(request: Request) -> JSONResponse:
    """Finish Supabase sign-in after the user's MFA challenge has succeeded."""
    if not _use_supabase_auth():
        return _json({"detail": "Multi-factor sign-in requires Supabase Auth."}, 409)
    authorization = request.headers.get("authorization") or ""
    if not authorization.startswith("Bearer "):
        return _json({"detail": "Missing bearer token"}, 401)
    token = authorization.removeprefix("Bearer ").strip()
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        return _json({"detail": "Invalid JSON"}, 400)
    try:
        session = await run_in_threadpool(
            lambda: supabase_auth.complete_login_session(
                token,
                invite_token=str(body.get("invite_token") or "") or None,
            )
        )
    except AuthNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
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


@offload_sync_handler
def auth_signup_config(_: Request) -> JSONResponse:
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
                body.get("marketing_attribution")
            ),
        )
    except AuthNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    user_id = str((result or {}).get("user_id") or "") or None
    if user_id and acceptance and not acceptance.get("user_id"):
        linked = legal_acceptance.attach_user_id(
            acceptance_id=str(acceptance["id"]), user_id=user_id
        )
        if linked:
            acceptance = linked
    return _json(
        {
            "accepted": True,
            "message": "If this address can be registered, a verification link will arrive by email.",
            "acceptance_id": acceptance.get("id") if acceptance else None,
            "acceptance_user_linked": bool(acceptance and acceptance.get("user_id")),
            "acceptance_identity": (
                "user_id" if acceptance and acceptance.get("user_id") else "email"
            ),
            **legal_acceptance.published_versions(),
        },
        202,
    )


@offload_sync_handler
def auth_logout(request: Request) -> JSONResponse:
    authorization = request.headers.get("authorization") or ""
    if not authorization.startswith("Bearer "):
        return _json({"detail": "Missing bearer token"}, 401)
    token = authorization.removeprefix("Bearer ").strip()
    try:
        if _use_supabase_auth():
            supabase_auth.logout(token)
        else:
            sandbox_logout(token)
    except AuthNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    return _json({"ok": True, "logged_out": True})


@offload_sync_handler
def auth_me(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    return _json(
        {
            "ok": True,
            "email": ctx["email"],
            "user_id": ctx["user_id"],
            "workspace": ctx["workspace"],
            "workspace_id": ctx["workspace_id"],
            "plan": ctx["plan"],
            "mode": ctx.get("mode") or "sandbox-jwt",
            "platform_role": ctx.get("platform_role"),
            "client_workspace_id_trusted": False,
            "trial_started_at": ctx.get("trial_started_at"),
            "trial_ends_at": ctx.get("trial_ends_at"),
            "trial_status": ctx.get("trial_status"),
            "trial_days_remaining": ctx.get("trial_days_remaining"),
        }
    )


@offload_sync_handler
def smoke_login(request: Request) -> JSONResponse:
    """Removed as the auth path — returns 410. Use POST /auth/login."""
    return _json(
        {
            "detail": "Smoke login removed. Use POST /auth/login with sandbox JWT auth.",
            "setup_required": describe_auth().get("setup_required"),
        },
        410,
    )



_INTAKE_TRUE = {"1", "true", "yes", "on"}


def _intake_options_from_form(form: Any) -> tuple[dict[str, Any], JSONResponse | None]:
    """Read the optional BOM intake choices (mapping, supplier mode, exclusions).

    Returns ``(options, error_response)``. The mapping is keyed by zero-based
    column index and is only ever the user's explicit choice.
    """
    mapping: dict[str, str] | None = None
    raw_mapping = str(form.get("column_mapping") or "").strip()
    if raw_mapping:
        try:
            parsed = json.loads(raw_mapping)
        except (TypeError, ValueError):
            parsed = None
        if (
            not isinstance(parsed, dict)
            or len(parsed) > 200
            or any(not isinstance(value, (str, type(None))) for value in parsed.values())
        ):
            return {}, _json(
                {"detail": "The column mapping is invalid.", "code": "invalid_column_mapping"},
                400,
            )
        mapping = {str(key): str(value or "ignore") for key, value in parsed.items()}
    corrections: dict[str, dict[str, str]] | None = None
    raw_corrections = str(form.get("row_corrections") or "").strip()
    if raw_corrections:
        try:
            parsed_corrections = json.loads(raw_corrections)
        except (TypeError, ValueError):
            parsed_corrections = None
        if not isinstance(parsed_corrections, dict) or any(
            not isinstance(fields, dict) for fields in parsed_corrections.values()
        ):
            return {}, _json(
                {"detail": "The row corrections are invalid.", "code": "invalid_row_corrections"},
                400,
            )
        corrections = {
            str(row): {str(k): "" if v is None else str(v) for k, v in fields.items()}
            for row, fields in parsed_corrections.items()
        }
    return (
        {
            "column_mapping": mapping,
            "row_corrections": corrections,
            "supplier_specific": str(form.get("supplier_specific") or "").strip().lower() in _INTAKE_TRUE,
            "default_supplier": str(form.get("default_supplier") or "").strip()[:120],
            "exclude_invalid_rows": str(form.get("exclude_invalid_rows") or "").strip().lower()
            in _INTAKE_TRUE,
        },
        None,
    )


async def boms_validate(request: Request) -> JSONResponse:
    """Validate a BOM upload without running the analysis engine."""
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    form = await request.form()
    upload = form.get("file")
    if upload is None:
        return _json({"detail": "Missing file"}, 400)
    filename = getattr(upload, "filename", None) or "bom.csv"
    limit = bom_validation.MAX_BOM_UPLOAD_BYTES
    payload = await upload.read(limit + 1)
    if len(payload) > limit:
        return _json(
            {
                "detail": "BOM file must be 10 MB or smaller.",
                "code": "payload_too_large",
                "ok": False,
                "can_analyze": False,
            },
            413,
        )
    intake_options, option_error = _intake_options_from_form(form)
    if option_error:
        return option_error
    preview = bom_validation.validation_preview(filename, payload, **intake_options)
    # Always return the preview payload so the UI can show column detection and
    # actionable errors without treating soft validation failure as a transport error.
    return _json({**preview, "workspace_id": ctx["workspace_id"]})


async def boms_analyze(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    form = await request.form()
    return await _analyze_bom_form(request, ctx, form, allow_one_time_purchase=True)


async def developer_api_analyze_post(request: Request) -> JSONResponse:
    ctx, denied = await _developer_api_key_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if not _developer_api_entitled(ctx):
        return _json({"detail": "Developer API access is not active for this account."}, 403)
    if _throttled(request, "developer-api-analysis", limit=5, window=60, identity=ctx["key_id"]):
        return _json({"detail": "Analysis submission rate limit reached. Retry shortly."}, 429)
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Expected a multipart/form-data upload."}, 400)
    result = await _analyze_bom_form(request, ctx, form, allow_one_time_purchase=False)
    if result.status_code == 200:
        try:
            payload = json.loads(result.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return result
        analysis_id = str(payload.get("analysis_id") or "").strip()
        if analysis_id:
            origin = _web_origin(request)
            payload["report_url"] = f"{origin}/reports/{analysis_id}"
            payload["report_endpoint"] = f"/v1/reports/{analysis_id}"
            response = JSONResponse(payload, headers={"Cache-Control": "no-store"})
            try:
                await run_in_threadpool(
                    developer_webhooks.queue_event,
                    get_store(),
                    workspace_id=ctx["workspace_id"],
                        event_type="analysis.completed",
                        event_id=(
                            "evt_analysis_"
                            + hashlib.sha256(str(analysis_id).encode("utf-8")).hexdigest()[:32]
                        ),
                    data={
                        "analysis_id": analysis_id,
                        "report_url": payload["report_url"],
                        "total_parts": payload.get("total_parts"),
                        "high_risk_count": payload.get("high_risk_count"),
                        "medium_risk_count": payload.get("medium_risk_count"),
                        "low_risk_count": payload.get("low_risk_count"),
                    },
                )
                response.background = BackgroundTask(
                    developer_webhooks.dispatch_due,
                    get_store(),
                    workspace_id=ctx["workspace_id"],
                    limit=100,
                )
            except Exception:  # noqa: BLE001
                logging.error("developer_webhook_analysis_event_queue_failed")
            return response
    return result


async def _analyze_bom_form(
    request: Request,
    ctx: dict[str, Any],
    form: Any,
    *,
    allow_one_time_purchase: bool,
) -> JSONResponse:
    upload = form.get("file")
    if upload is None:
        return _json({"detail": "Missing file"}, 400)
    filename = getattr(upload, "filename", None) or "bom.csv"
    # Keep the analyze endpoint under the same upload limit as the validation
    # preview. The browser disables oversized files, but the API must enforce
    # the contract independently for direct callers as well.
    payload = await upload.read(bom_validation.MAX_BOM_UPLOAD_BYTES + 1)
    if len(payload) > bom_validation.MAX_BOM_UPLOAD_BYTES:
        return _json(
            {
                "detail": "BOM file must be 10 MB or smaller.",
                "code": "payload_too_large",
                "ok": False,
                "can_analyze": False,
            },
            413,
        )
    if not payload:
        return _json(
            {
                "detail": "Empty file",
                "code": "bom_validation_failed",
                "ok": False,
                "can_analyze": False,
            },
            400,
        )

    # Validation is authoritative on the server. Do not depend on the UI's
    # preview gate: malformed or empty-part files must not consume plan/report
    # credits or create projects, BOMs, revisions, and empty analyses.
    intake_options, option_error = _intake_options_from_form(form)
    if option_error:
        return option_error
    preview = bom_validation.validation_preview(filename, payload, **intake_options)
    if not preview.get("can_analyze"):
        return _json(
            {
                "detail": "BOM validation failed. Analysis was not saved.",
                "code": "bom_validation_failed",
                "ok": False,
                "can_analyze": False,
                "validation": preview,
            },
            400,
        )
    project_name = str(form.get("project_name") or "").strip() or None
    bom_name = str(form.get("bom_name") or "").strip() or None
    revision = str(form.get("revision") or "").strip() or None
    derived_from_analysis_id = str(form.get("source_analysis_id") or "").strip() or None
    applied_decision_ids_raw = str(form.get("applied_decision_ids") or "").strip()
    applied_decision_ids: list[str] = []
    if applied_decision_ids_raw:
        try:
            parsed_decision_ids = json.loads(applied_decision_ids_raw)
        except (TypeError, ValueError):
            return _json({"detail": "Applied decision references are invalid."}, 400)
        if not isinstance(parsed_decision_ids, list) or any(
            not isinstance(item, str) or not item.strip() for item in parsed_decision_ids
        ):
            return _json({"detail": "Applied decision references are invalid."}, 400)
        applied_decision_ids = list(dict.fromkeys(item.strip() for item in parsed_decision_ids))
    used_decision_ids_raw = str(form.get("used_decision_ids") or "").strip()
    used_decision_ids: list[str] = []
    if used_decision_ids_raw:
        try:
            parsed_decision_ids = json.loads(used_decision_ids_raw)
        except (TypeError, ValueError):
            return _json({"detail": "Replacement decision references are invalid."}, 400)
        if not isinstance(parsed_decision_ids, list) or any(
            not isinstance(item, str) or not item.strip() for item in parsed_decision_ids
        ):
            return _json({"detail": "Replacement decision references are invalid."}, 400)
        used_decision_ids = list(dict.fromkeys(item.strip() for item in parsed_decision_ids))
    elif applied_decision_ids:
        # Keep parsing deterministic; the request is rejected below because
        # an earlier approval cannot approve a newly analyzed revision.
        used_decision_ids = list(applied_decision_ids)
    if set(applied_decision_ids) - set(used_decision_ids):
        return _json({"detail": "Approved decisions must also be listed as applied candidates."}, 400)
    if applied_decision_ids:
        return _json(
            {
                "detail": (
                    "Earlier approvals are historical context only. Create the new revision, "
                    "then record a fresh decision against that revision."
                )
            },
            400,
        )
    if (applied_decision_ids or used_decision_ids) and not derived_from_analysis_id:
        return _json({"detail": "Replacement decisions require a source BOM report."}, 400)
    if derived_from_analysis_id:
        source_report = _get_visible_report(
            derived_from_analysis_id, workspace_id=ctx["workspace_id"]
        )
        if not source_report:
            return _json({"detail": "Source BOM report not found"}, 404)
        if applied_decision_ids or used_decision_ids:
            decisions_by_id: dict[str, dict[str, Any]] = {}
            # Carry decision records as review context across same-BOM history.
            # Their prior approval never transfers to the new revision.
            cursor_report = source_report
            seen_report_ids = {derived_from_analysis_id}
            inherited_decision_ids = set(source_report.get("used_decision_ids") or [])
            inherited_decision_ids.update(source_report.get("applied_decision_ids") or [])
            for depth in range(12):
                cursor_id = str(cursor_report.get("id") or cursor_report.get("analysis_id") or "").strip()
                if not cursor_id:
                    break
                records = get_store().list_decision_records(
                    workspace_id=ctx["workspace_id"],
                    analysis_id=cursor_id,
                )
                for record in records:
                    record_id = str(record.get("id") or record.get("decision_id") or "")
                    if depth == 0 or record_id in inherited_decision_ids:
                        if record_id:
                            decisions_by_id[record_id] = record
                ancestor_id = str(cursor_report.get("derived_from_analysis_id") or "").strip()
                if not ancestor_id or ancestor_id in seen_report_ids:
                    break
                seen_report_ids.add(ancestor_id)
                ancestor = _get_visible_report(ancestor_id, workspace_id=ctx["workspace_id"])
                source_bom_id = str(source_report.get("bom_id") or "")
                if not ancestor or not source_bom_id or str(ancestor.get("bom_id") or "") != source_bom_id:
                    break
                cursor_report = ancestor
            if any(
                decision_id not in decisions_by_id
                or decisions_by_id[decision_id].get("decision") == "reject_alternate"
                for decision_id in used_decision_ids
            ):
                return _json(
                    {"detail": "Only non-rejected candidates linked to this BOM's revision history can be applied."},
                    400,
                )
            revised_parts = parse_bom_bytes(filename, payload, **intake_options)
            revised_mpns = {
                str(value or "").strip().casefold()
                for value in revised_parts.get("mpn", [])
                if str(value or "").strip()
            }
            for decision_id in used_decision_ids:
                decision = decisions_by_id[decision_id]
                current_mpn = str(decision.get("part_a") or "").strip().casefold()
                if decision.get("decision_candidate_scope") == "all_selected":
                    candidates = decision.get("decision_candidate_mpns")
                    if not isinstance(candidates, list):
                        candidates = []
                else:
                    candidates = [decision.get("part_b")]
                present_candidates = {
                    str(candidate or "").strip().casefold()
                    for candidate in candidates
                    if str(candidate or "").strip().casefold() in revised_mpns
                }
                if not present_candidates or len(present_candidates) != 1 or current_mpn in revised_mpns:
                    return _json(
                        {
                            "detail": (
                                "The new BOM must contain exactly one saved candidate for each linked decision and remove its source part."
                            )
                        },
                        400,
                    )
    unique_part_count = int(preview.get("unique_part_count") or 0)

    analysis_id = str(uuid.uuid4())
    reserved_order_id = ""
    reserved_usage_credit_id = ""
    try:
        usage_limits = plan_limits.assert_analysis_allowed(
            workspace_id=ctx["workspace_id"],
            ctx=ctx,
            part_count=unique_part_count,
            analysis_id=analysis_id,
        )
        reserved_usage_credit_id = str(
            (usage_limits.get("usage") or {}).get("overage_credit_reservation_id") or ""
        )
    except plan_limits.PlanLimitError as exc:
        if not allow_one_time_purchase:
            return _json(
                {
                    "code": exc.code,
                    "detail": exc.detail,
                    "limits": exc.limits,
                    "billing_action": "none",
                },
                402,
            )
        if unique_part_count > 100:
            return _json(
                {
                    "code": "one_time_report_size_limit",
                    "detail": (
                        f"This BOM has {unique_part_count} unique components. "
                        "The existing one-time report covers up to 100."
                    ),
                    "limits": exc.limits,
                    "one_time_report": {"href": "/single-bom-report", "max_components": 100},
                },
                402,
            )
        try:
            purchase, purchase_status = one_time_report_service.request_action(
                access_token=request.headers.get("authorization", "").removeprefix("Bearer ").strip(),
                action="reserve",
                payload={"analysis_id": analysis_id},
            )
        except one_time_report_service.OneTimeReportServiceError:
            purchase, purchase_status = {}, 503
        if purchase_status == 200 and purchase.get("ok") and purchase.get("order_id"):
            reserved_order_id = str(purchase["order_id"])
        else:
            status_code = purchase_status if purchase_status in {401, 403} else 402
            detail = (
                str(purchase.get("detail") or "Verify your email before using a one-time report.")
                if status_code == 403
                else (
                    "Your plan limit has been reached. A paid one-time report credit can "
                    "unlock one complete BOM analysis for up to 100 unique components."
                )
            )
            return _json(
                {
                    "code": "one_time_report_required",
                    "detail": detail,
                    "plan_limit": {"code": exc.code, "detail": exc.detail},
                    "limits": exc.limits,
                    "one_time_report": {
                        "href": "/single-bom-report",
                        "max_components": 100,
                    },
                },
                status_code,
            )

    access_token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    try:
        report = analyze_upload(
            filename=filename,
            payload=payload,
            workspace_id=ctx["workspace_id"],
            project_name=project_name,
            bom_name=bom_name,
            revision=revision,
            analysis_id=analysis_id,
            derived_from_analysis_id=derived_from_analysis_id,
            applied_decision_ids=applied_decision_ids,
            used_decision_ids=used_decision_ids,
            **intake_options,
        )
    except PersistenceNotConfiguredError as exc:
        if reserved_usage_credit_id:
            plan_limits._finish_overage_credit(ctx, reserved_usage_credit_id, commit=False)
        if reserved_order_id:
            _release_one_time_credit_if_report_was_not_saved(
                access_token=access_token,
                order_id=reserved_order_id,
                analysis_id=analysis_id,
                workspace_id=ctx["workspace_id"],
            )
        return _json({"detail": str(exc), "code": "persistence_not_configured"}, 503)
    except PersistenceVerifyError as exc:
        if reserved_usage_credit_id:
            plan_limits._finish_overage_credit(ctx, reserved_usage_credit_id, commit=False)
        if reserved_order_id:
            _release_one_time_credit_if_report_was_not_saved(
                access_token=access_token,
                order_id=reserved_order_id,
                analysis_id=analysis_id,
                workspace_id=ctx["workspace_id"],
            )
        return _json(
            {
                "detail": str(exc),
                "code": "persistence_verify_failed",
                "persisted": False,
            },
            503,
        )
    except Exception as exc:  # noqa: BLE001
        if reserved_usage_credit_id:
            plan_limits._finish_overage_credit(ctx, reserved_usage_credit_id, commit=False)
        if reserved_order_id:
            _release_one_time_credit_if_report_was_not_saved(
                access_token=access_token,
                order_id=reserved_order_id,
                analysis_id=analysis_id,
                workspace_id=ctx["workspace_id"],
            )
        return _json({"detail": str(exc)}, 400)

    if not report.get("persisted"):
        if reserved_usage_credit_id:
            plan_limits._finish_overage_credit(ctx, reserved_usage_credit_id, commit=False)
        if reserved_order_id:
            _release_one_time_credit_if_report_was_not_saved(
                access_token=access_token,
                order_id=reserved_order_id,
                analysis_id=str(report.get("id") or analysis_id),
                workspace_id=ctx["workspace_id"],
            )
        return _json(
            {
                "detail": (
                    "BOM analysis completed but was not saved to workspace storage. "
                    "Retry the analysis."
                ),
                "code": "persistence_verify_failed",
                "analysis_id": report.get("id"),
                "persisted": False,
            },
            503,
        )

    if reserved_usage_credit_id and not plan_limits._finish_overage_credit(
        ctx, reserved_usage_credit_id, commit=True
    ):
        return _json(
            {
                "code": "overage_credit_reconciliation_pending",
                "detail": "Your BOM analysis was saved. Usage credit reconciliation is still processing; open it from Reports.",
                "analysis_id": report["id"],
                "persisted": True,
            },
            503,
        )

    payment_reconciled = True
    if reserved_order_id:
        try:
            consumed, consume_status = one_time_report_service.request_action(
                access_token=access_token,
                action="consume",
                payload={"order_id": reserved_order_id, "analysis_id": report["id"]},
            )
            payment_reconciled = consume_status == 200 and bool(consumed.get("ok"))
        except one_time_report_service.OneTimeReportServiceError:
            payment_reconciled = False

    if reserved_order_id and not payment_reconciled:
        return _json(
            {
                "code": "one_time_report_reconciliation_pending",
                "detail": "Your paid report was saved. Payment reconciliation is still processing; open it from Reports.",
                "analysis_id": report["id"],
                "persisted": bool(report.get("persisted")),
            },
            503,
        )
    hierarchy = report.get("hierarchy") or {}
    top = hierarchy.get("top_level") or {}
    return _json(
        {
            "analysis_id": report["id"],
            "total_parts": report["total_parts"],
            "health_score": report["health_score"],
            "health_status": report["health_status"],
            "high_risk_count": report["high_risk_count"],
            "medium_risk_count": report["medium_risk_count"],
            "low_risk_count": report["low_risk_count"],
            "mode": report["mode"],
            "workspace_id": report.get("workspace_id"),
            "project_id": report.get("project_id"),
            "project_name": report.get("project_name"),
            "bom_id": report.get("bom_id"),
            "bom_name": report.get("bom_name"),
            "revision": report.get("revision"),
            "persisted": True,
            "has_hierarchy": bool(hierarchy.get("has_hierarchy")),
            "top_rolled_risk": top.get("rolled_risk_level"),
        }
    )


@offload_sync_handler
def reports_list(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    persistence = describe_persistence()
    try:
        reports = list_reports(workspace_id=ctx["workspace_id"])
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    reports = customer_visible_analyses(
        reports, production=is_production_runtime()
    )
    # Do not surface deployment service gaps (billing/email/connectors) as a
    # Reports warning card — those belong in Settings / health diagnostics.
    return _json(
        {
            "ok": True,
            "mode": "workspace-reports",
            "workspace_id": ctx["workspace_id"],
            "persistence": persistence["backend"],
            "gap": None,
            "reports": reports,
        }
    )


@offload_sync_handler
def reports_delete(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = request.path_params["analysis_id"]
    try:
        store = get_store()
        deleted = delete_report(analysis_id, workspace_id=ctx["workspace_id"])
        if not deleted:
            return _json({"detail": "Report not found"}, 404)
        if getattr(store, "backend", "file") != "postgres":
            monitoring_store.delete_analysis_scopes(ctx["workspace_id"], [analysis_id])
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, "deleted": analysis_id, "workspace_id": ctx["workspace_id"]})


@offload_sync_handler
def projects_list(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    persistence = describe_persistence()
    try:
        store = get_store()
        projects = store.list_projects(workspace_id=ctx["workspace_id"])
        reports = customer_visible_analyses(
            list_reports(workspace_id=ctx["workspace_id"]),
            production=is_production_runtime(),
        )
        projects = customer_visible_projects(
            projects, reports, production=is_production_runtime()
        )
        projects = _refresh_project_report_summaries(projects, reports)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json(
        {
            "ok": True,
            "mode": "workspace-projects",
            "workspace_id": ctx["workspace_id"],
            "persistence": persistence["backend"],
            "projects": projects,
        }
    )


async def boms_update(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    bom_id = request.path_params["bom_id"]
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "A project name or project id is required."}, 400)
    if "name" not in body and not str(body.get("project_id") or "").strip():
        return _json({"detail": "A project name or project id is required."}, 400)
    try:
        updated = get_store().update_bom(
            bom_id,
            workspace_id=ctx["workspace_id"],
            name=(str(body["name"]) if body.get("name") is not None else None),
            project_id=(str(body.get("project_id") or "").strip() or None),
        )
    except WorkspaceAccessError:
        return _json({"detail": "BOM not found"}, 404)
    except LookupError:
        return _json({"detail": "BOM not found"}, 404)
    except ValueError as exc:
        return _json({"detail": str(exc)}, 400)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, "bom": updated, "workspace_id": ctx["workspace_id"]})


@offload_sync_handler
def boms_delete(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    bom_id = request.path_params["bom_id"]
    try:
        store = get_store()
        analysis_ids = store.delete_bom(
            bom_id, workspace_id=ctx["workspace_id"]
        )
        if analysis_ids is None:
            return _json({"detail": "BOM not found"}, 404)
        if getattr(store, "backend", "file") != "postgres":
            monitoring_store.delete_analysis_scopes(ctx["workspace_id"], analysis_ids)
    except WorkspaceAccessError:
        return _json({"detail": "BOM not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json(
        {
            "ok": True,
            "deleted": bom_id,
            "deleted_analysis_count": len(analysis_ids),
            "workspace_id": ctx["workspace_id"],
        }
    )


async def projects_update(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    project_id = request.path_params["project_id"]
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    try:
        updated = get_store().update_project(
            project_id,
            workspace_id=ctx["workspace_id"],
            name=str(body.get("name") or ""),
        )
    except WorkspaceAccessError:
        return _json({"detail": "Project not found"}, 404)
    except LookupError:
        return _json({"detail": "Project not found"}, 404)
    except ValueError as exc:
        return _json({"detail": str(exc)}, 400)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, "project": updated, "workspace_id": ctx["workspace_id"]})


@offload_sync_handler
def projects_delete(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    project_id = request.path_params["project_id"]
    try:
        deleted = delete_project_record(project_id, workspace_id=ctx["workspace_id"])
    except WorkspaceAccessError:
        return _json({"detail": "Project not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    if not deleted:
        return _json({"detail": "Project not found"}, 404)
    return _json({"ok": True, "deleted": project_id, "workspace_id": ctx["workspace_id"]})


@offload_sync_handler
def workspace_home(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        workspace_id = ctx["workspace_id"]
        store = get_store()
        payload = store.home_dashboard(
            workspace_id=workspace_id,
            production=is_production_runtime(),
        )
        report_rows, saved_parts = list_reports_with_parts(workspace_id=workspace_id)
        reports = customer_visible_analyses(
            report_rows, production=is_production_runtime()
        )
        payload = dict(payload)
        payload["projects"] = _refresh_project_report_summaries(
            list(payload.get("projects") or []), reports
        )
        payload["recent_analyses"] = reports[:12]
        parts_by_analysis: dict[str, list[dict[str, Any]]] = {}
        for part in saved_parts:
            if not isinstance(part, dict):
                continue
            part_analysis_id = str(part.get("analysis_id") or "").strip()
            if part_analysis_id:
                parts_by_analysis.setdefault(part_analysis_id, []).append(part)
        current_priorities = []
        for summary in reports[:8]:
            analysis_id = str(summary.get("id") or summary.get("analysis_id") or "")
            if analysis_id:
                current_priorities.extend(
                    current_priority_items(
                        {"parts": parts_by_analysis.get(analysis_id, [])}, summary
                    )[:3]
                )
        payload["priority_risks"] = current_priorities
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "needs_verification": 0}
        for item in current_priorities:
            level = str(item.get("risk_level") or "").casefold()
            bucket = "high" if level == "critical" else next(
                (candidate for candidate in ("high", "medium", "low") if candidate in level),
                "needs_verification",
            )
            counts[bucket] += 1
        payload["priority_severity_counts"] = counts
        metrics = dict(payload.get("metrics") or {})
        metrics["saved_analyses"] = len(reports)
        metrics["priority_items"] = len(current_priorities)
        metrics["open_blockers"] = counts["critical"] + counts["high"]
        payload["metrics"] = metrics
        return _json(payload)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)


@offload_sync_handler
def workspace_priority_queue(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        workspace_id = ctx["workspace_id"]
        try:
            offset = max(0, int(request.query_params.get("offset") or 0))
        except (TypeError, ValueError):
            return _json({"detail": "Invalid priority queue offset"}, 400)
        report_page_size = 8
        reports = customer_visible_analyses(
            list_reports(workspace_id=workspace_id),
            production=is_production_runtime(),
        )
        report_page = reports[offset : offset + report_page_size]
        items: list[dict[str, Any]] = []
        for summary in report_page:
            analysis_id = str(summary.get("id") or summary.get("analysis_id") or "")
            report = get_report(analysis_id, workspace_id=workspace_id) if analysis_id else None
            if not report:
                continue
            for item in current_priority_items(report, summary):
                items.append({
                    **item,
                    "filename": summary.get("filename"),
                    "revision": summary.get("revision"),
                    "created_at": summary.get("created_at"),
                })
        next_offset = offset + len(report_page)
        return _json({
            "ok": True,
            "items": items,
            "reports_total": len(reports),
            "reports_loaded": next_offset,
            "reports_scanned": len(report_page),
            "next_offset": next_offset,
            "has_more": next_offset < len(reports),
        })
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)


@offload_sync_handler
def reports_csv_get(request: Request) -> Response:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = request.path_params["analysis_id"]
    try:
        report = _get_visible_report(analysis_id, workspace_id=ctx["workspace_id"])
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    if not report:
        return _json({"detail": "Report not found"}, 404)
    csv_bytes = detailed_risk_csv_bytes(report.get("parts") or [])
    return Response(
        csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="cadivor-report.csv"',
            "Cache-Control": "no-store",
        },
    )


@offload_sync_handler
def reports_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = request.path_params["analysis_id"]
    try:
        report = _get_visible_report(analysis_id, workspace_id=ctx["workspace_id"])
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    if not report:
        return _json({"detail": "Report not found"}, 404)
    enriched = annotate_report_parts(report)
    try:
        workspace_store = get_store()
        enriched["supply_scenarios"] = workspace_store.list_supply_scenarios(
            workspace_id=ctx["workspace_id"], analysis_id=analysis_id
        )
        enriched["cost_decisions"] = workspace_store.list_cost_decisions(
            workspace_id=ctx["workspace_id"], analysis_id=analysis_id
        )
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json(enriched)


@offload_sync_handler
def reports_export(request: Request) -> Response:
    """Export one saved report, scoped to the authenticated workspace."""
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = request.path_params["analysis_id"]
    file_format = str(request.path_params["file_format"] or "").lower()
    try:
        report = _get_visible_report(analysis_id, workspace_id=ctx["workspace_id"])
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    if not report:
        return _json({"detail": "Report not found"}, 404)
    if file_format not in {"pdf", "csv", "xlsx", "plm-csv"}:
        return _json({"detail": "Choose one of the supported export formats: PDF, Excel, or CSV; PLM/ERP CSV is also available."}, 400)

    export_report = annotate_report_parts(report)
    try:
        payload, media_type, extension = build_report_export(export_report, file_format)
    except ValueError as exc:
        return _json({"detail": str(exc)}, 400)
    filename = f"{safe_download_stem(report)}.{extension}"
    return Response(
        payload,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@offload_sync_handler
def monitoring_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = request.query_params.get("analysis_id") or None
    try:
        payload = migration_tools.monitoring_payload(
            workspace_id=ctx["workspace_id"], analysis_id=analysis_id
        )
        payload["preferences"] = monitoring_store.get_user_preferences(
            ctx["workspace_id"], ctx["user_id"], ctx["email"]
        )
        payload["live_refresh"] = monitoring_scheduler.supplier_refresh_readiness()
        payload["scheduler"] = monitoring_scheduler.scheduler_readiness()
        return _json(payload)
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)


async def compare_parts_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if not plan_limits.effective_plan(ctx).get("datasheet_comparison"):
        return _json({
            "code": "feature_unavailable",
            "detail": "Datasheet comparison is not included in this account's entitlements.",
        }, 402)
    datasheet_uploads: dict[str, Any] = {}
    if "multipart/form-data" in str(request.headers.get("content-type") or "").lower():
        try:
            # part_a/b, analysis_id, manufacturer_a/b (+ optional extras)
            form = await request.form(max_files=2, max_fields=16)
        except Exception:  # noqa: BLE001
            return _json({"detail": "Invalid multipart comparison request."}, 400)
        body = {
            "part_a": form.get("part_a"),
            "part_b": form.get("part_b"),
            "analysis_id": form.get("analysis_id"),
            "manufacturer_a": form.get("manufacturer_a"),
            "manufacturer_b": form.get("manufacturer_b"),
        }
        for side, field_name in (("a", "datasheet_a"), ("b", "datasheet_b")):
            upload = form.get(field_name)
            if upload is None or not callable(getattr(upload, "read", None)):
                continue
            filename = str(getattr(upload, "filename", "") or "datasheet.pdf").strip()
            if not filename.casefold().endswith(".pdf"):
                return _json({"detail": f"Part {side.upper()} datasheet must be a PDF."}, 400)
            payload = await upload.read(MAX_DATASHEET_BYTES + 1)
            if len(payload) > MAX_DATASHEET_BYTES:
                return _json({"detail": "Each datasheet must be 8 MB or smaller."}, 413)
            if not payload.startswith(b"%PDF"):
                return _json({"detail": f"Part {side.upper()} upload is not a readable PDF file."}, 400)
            datasheet_uploads[side] = {"bytes": payload, "filename": filename}
    else:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Comparison payload must be an object."}, 400)
    try:
        result = await run_in_threadpool(
            migration_tools.compare_parts_payload,
            workspace_id=ctx["workspace_id"],
            part_a=str(body.get("part_a") or ""),
            part_b=str(body.get("part_b") or ""),
            analysis_id=body.get("analysis_id") or None,
            manufacturer_a=str(body.get("manufacturer_a") or "") or None,
            manufacturer_b=str(body.get("manufacturer_b") or "") or None,
            use_latest_if_missing=False,
            datasheet_uploads=datasheet_uploads or None,
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    if isinstance(result, dict) and result.get("ok"):
        result = attach_snapshot_token(
            result,
            workspace_id=str(ctx.get("workspace_id") or ""),
            user_id=str(ctx.get("user_id") or "") or None,
        )
    status = 200 if result.get("ok") else 400
    return _json(result, status)


_DECISION_LABELS = {
    "hold_for_review": "Hold for review",
    "approve_alternate": "Approve alternate",
    "conditional_approval": "Conditional approval",
    "reject_alternate": "Reject alternate",
    "retain_current_part": "Retain current part",
    "defer_for_validation": "Defer pending validation",
    "accept_residual_risk": "Accept residual risk",
}

_DECISION_VALIDATION_CHECKS = {
    "manufacturer_datasheet_reviewed",
    "package_pinout_verified",
    "electrical_limits_verified",
    "thermal_environmental_limits_verified",
    "lifecycle_and_supply_reviewed",
    "prototype_validation_completed",
}
_DECISION_RISK_LEVELS = {"unknown", "low", "medium", "high"}


@offload_sync_handler
def decision_records_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = (request.query_params.get("analysis_id") or "").strip()
    try:
        if analysis_id and not _get_visible_report(analysis_id, workspace_id=ctx["workspace_id"]):
            return _json({"detail": "Report not found"}, 404)
        records = get_store().list_decision_records(
            workspace_id=ctx["workspace_id"],
            analysis_id=analysis_id or None,
        )
        if not analysis_id and is_production_runtime():
            visible_ids = {
                str(row.get("id") or row.get("analysis_id") or "")
                for row in customer_visible_analyses(
                    list_reports(workspace_id=ctx["workspace_id"]), production=True
                )
            }
            records = [
                record
                for record in records
                if not record.get("analysis_id")
                or str(record.get("analysis_id")) in visible_ids
            ]
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, "records": records})


async def decision_records_export_get(request: Request) -> Response:
    """Export workspace decisions using an explicitly review-required layout."""
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    template = str(request.path_params.get("template") or "").strip().lower()
    if template not in decision_record_exports.TEMPLATES:
        return _json({"detail": "Choose the medical-device or aerospace draft template."}, 400)
    analysis_id = (request.query_params.get("analysis_id") or "").strip()
    try:
        if analysis_id and not _get_visible_report(analysis_id, workspace_id=ctx["workspace_id"]):
            return _json({"detail": "Report not found"}, 404)
        records = await run_in_threadpool(
            get_store().list_decision_records,
            workspace_id=ctx["workspace_id"],
            analysis_id=analysis_id or None,
        )
        if not analysis_id and is_production_runtime():
            visible_ids = {
                str(row.get("id") or row.get("analysis_id") or "")
                for row in customer_visible_analyses(
                    list_reports(workspace_id=ctx["workspace_id"]), production=True
                )
            }
            records = [
                row for row in records
                if not row.get("analysis_id") or str(row.get("analysis_id")) in visible_ids
            ]
        payload = decision_record_exports.build_decision_record_export(records, template)
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    except ValueError as exc:
        return _json({"detail": str(exc)}, 400)
    return Response(
        payload,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="cadivor-{template}-decision-draft.csv"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def decision_record_share_post(request: Request) -> JSONResponse:
    """Create a short-lived, read-only link for one workspace decision record."""
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Invalid request"}, 400)
    decision_id = str(body.get("decision_record_id") or "").strip()
    if not decision_id or len(decision_id) > 100:
        return _json({"detail": "Decision record id is required."}, 400)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    try:
        await run_in_threadpool(
            get_store().create_decision_record_share,
            workspace_id=ctx["workspace_id"],
            decision_record_id=decision_id,
            token_hash=token_hash,
            created_by=ctx["user_id"],
            expires_at=expires_at.isoformat(),
        )
    except WorkspaceAccessError:
        return _json({"detail": "Decision record not found."}, 404)
    except Exception:  # noqa: BLE001
        logging.exception("decision_record_share_create_failed")
        return _json({"detail": "Could not create a decision share link."}, 503)
    return JSONResponse(
        {"ok": True, "token": token, "expires_at": expires_at.isoformat()},
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


async def decision_record_share_get(request: Request) -> JSONResponse:
    """Resolve a bearer link into a safe read-only projection of one decision."""
    token = str(request.path_params.get("token") or "").strip()
    if len(token) < 40 or len(token) > 128:
        return _json({"detail": "This decision share link is invalid or expired."}, 404)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        shared = await run_in_threadpool(
            get_store().get_decision_record_share, token_hash
        )
    except Exception:  # noqa: BLE001
        logging.exception("decision_record_share_resolve_failed")
        return _json({"detail": "Shared decision unavailable."}, 503)
    if not isinstance(shared, dict) or not isinstance(shared.get("record"), dict):
        return _json({"detail": "This decision share link is invalid or expired."}, 404)
    record = shared["record"]
    allowed = (
        "created_at", "project_name", "bom_name", "revision", "part_a",
        "part_b", "decision_candidate_scope", "decision_candidate_mpns",
        "manufacturer_a", "manufacturer_b", "decision",
        "decision_label", "reviewer", "rationale", "validation_checks",
        "follow_up_action", "follow_up_owner", "follow_up_due_date",
        "residual_risk", "verified_primary_evidence",
        "qualification_note",
    )
    projection = {key: record[key] for key in allowed if key in record}
    snapshot = record.get("comparison_snapshot")
    if isinstance(snapshot, dict):
        # Share only the small evidence summary that helps explain the decision.
        # The saved comparison payload can contain wider workspace context.
        safe_snapshot_keys = {
            "finding", "engineering_evidence_status", "source_a", "source_b",
            "comparison_status", "qualification_status",
        }
        safe_snapshot = {
            key: snapshot[key]
            for key in safe_snapshot_keys
            if isinstance(snapshot.get(key), (str, int, float, bool))
        }
        candidate_brands = snapshot.get("multi_candidate_manufacturers")
        if isinstance(candidate_brands, dict):
            safe_brands = {
                str(mpn): str(brand)
                for mpn, brand in candidate_brands.items()
                if str(mpn).strip() and str(brand).strip()
            }
            if safe_brands:
                safe_snapshot["multi_candidate_manufacturers"] = safe_brands
        if safe_snapshot:
            projection["comparison_snapshot"] = safe_snapshot
    return JSONResponse(
        {"ok": True, "record": projection, "expires_at": shared.get("expires_at")},
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        },
    )


async def decision_record_approver_post(request: Request) -> JSONResponse:
    """Email a bearer link that can review exactly one decision record."""
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if _throttled(
        request,
        "decision-approver-invite",
        limit=10,
        window=3600,
        identity=str(ctx.get("user_id") or ""),
    ):
        return _json({"detail": "Too many approval invitations were sent. Try again later."}, 429)
    try:
        team_service.require_admin(ctx)
    except TeamError as exc:
        return _team_error(exc)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Invalid request"}, 400)
    decision_id = str(body.get("decision_record_id") or "").strip()
    try:
        recipient = team_service.normalize_email(str(body.get("email") or ""))
    except TeamError as exc:
        return _team_error(exc)
    if not decision_id or len(decision_id) > 100:
        return _json({"detail": "Decision record id is required."}, 400)
    if not invitation_email.delivery_ready():
        return _json({"detail": "Transactional email is not configured."}, 503)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    store = get_store()
    try:
        await run_in_threadpool(
            store.create_decision_record_approver,
            workspace_id=ctx["workspace_id"],
            decision_record_id=decision_id,
            token_hash=token_hash,
            created_by=ctx["user_id"],
            email=recipient,
            expires_at=expires_at.isoformat(),
        )
        records = await run_in_threadpool(
            store.list_decision_records,
            workspace_id=ctx["workspace_id"],
        )
        record = next((row for row in records if str(row.get("id") or row.get("decision_id") or "") == decision_id), None)
        if not record:
            raise WorkspaceAccessError("Decision record was not found.")
        summary = " → ".join(
            value for value in (
                str(record.get("part_a") or "").strip(),
                str(record.get("part_b") or "").strip(),
            ) if value
        ) or "Engineering decision"
        if record.get("decision_label"):
            summary = f"{summary} · {str(record['decision_label'])[:80]}"
        approval_url = f"{_web_origin(request)}/decision-approval/{token}"
        await run_in_threadpool(
            invitation_email.send_decision_approver_invitation,
            to_email=recipient,
            inviter_name=str(ctx.get("email") or "A Cadivor teammate"),
            decision_summary=summary,
            approval_url=approval_url,
            expires_in_days=7,
        )
    except WorkspaceAccessError:
        return _json({"detail": "Decision record was not found."}, 404)
    except Exception:  # noqa: BLE001
        try:
            await run_in_threadpool(store.revoke_decision_record_approver, token_hash)
        except Exception:  # noqa: BLE001
            pass
        logging.exception("decision_record_approver_invitation_failed")
        return _json({"detail": "Could not send the decision approval invitation."}, 503)
    return _json({"ok": True, "sent": True, "expires_at": expires_at.isoformat()}, 201)


async def decision_record_approver_get(request: Request) -> JSONResponse:
    token = str(request.path_params.get("token") or "").strip()
    if len(token) < 40 or len(token) > 128:
        return _json({"detail": "This approval link is invalid or expired."}, 404)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        invite = await run_in_threadpool(get_store().get_decision_record_approver, token_hash)
    except Exception:  # noqa: BLE001
        logging.exception("decision_record_approver_resolve_failed")
        return _json({"detail": "This approval link is temporarily unavailable."}, 503)
    if not isinstance(invite, dict) or not isinstance(invite.get("record"), dict):
        return _json({"detail": "This approval link is invalid or expired."}, 404)
    record = invite["record"]
    allowed = (
        "created_at", "project_name", "bom_name", "revision", "part_a",
        "part_b", "decision_candidate_scope", "decision_candidate_mpns",
        "manufacturer_a", "manufacturer_b", "decision",
        "decision_label", "reviewer", "rationale", "validation_checks",
        "follow_up_action", "follow_up_owner", "follow_up_due_date",
        "residual_risk", "verified_primary_evidence", "qualification_note",
    )
    projection = {key: record[key] for key in allowed if key in record}
    snapshot = record.get("comparison_snapshot")
    candidate_brands = (
        snapshot.get("multi_candidate_manufacturers")
        if isinstance(snapshot, dict) and isinstance(snapshot.get("multi_candidate_manufacturers"), dict)
        else {}
    )
    safe_brands = {
        str(mpn): str(brand)
        for mpn, brand in candidate_brands.items()
        if str(mpn).strip() and str(brand).strip()
    }
    if safe_brands:
        projection["comparison_snapshot"] = {
            "multi_candidate_manufacturers": safe_brands,
        }
    return JSONResponse(
        {
            "ok": True,
            "record": projection,
            "status": invite.get("status"),
            "response_rationale": invite.get("response_rationale"),
            "expires_at": invite.get("expires_at"),
        },
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow, noarchive"},
    )


async def decision_record_approver_respond(request: Request) -> JSONResponse:
    token = str(request.path_params.get("token") or "").strip()
    if len(token) < 40 or len(token) > 128:
        return _json({"detail": "This approval link is invalid or expired."}, 404)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    decision = str((body or {}).get("decision") or "").strip().lower()
    rationale = " ".join(str((body or {}).get("rationale") or "").split())
    if decision not in {"approved", "rejected"}:
        return _json({"detail": "Choose approve or reject."}, 400)
    if len(rationale) > 3000:
        return _json({"detail": "Rationale must be 3,000 characters or fewer."}, 400)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        saved = await run_in_threadpool(
            get_store().respond_to_decision_record_approver,
            token_hash,
            decision=decision,
            rationale=rationale,
        )
    except Exception:  # noqa: BLE001
        logging.exception("decision_record_approver_response_failed")
        return _json({"detail": "Could not save the approval response."}, 503)
    if not saved:
        return _json({"detail": "This link is expired, revoked, or already answered."}, 409)
    return _json({"ok": True, "status": decision})


async def decision_records_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    datasheet_uploads: dict[str, Any] = {}
    if "multipart/form-data" in str(request.headers.get("content-type") or "").lower():
        try:
            form = await request.form(max_files=2, max_fields=40)
            body = {key: form.get(key) for key in (
                "analysis_id", "part_a", "part_b", "manufacturer_a", "manufacturer_b",
                "decision", "reviewer", "rationale",
                "validation_checks", "follow_up_action", "follow_up_owner",
                "follow_up_due_date", "residual_risk", "comparison_snapshot",
                "decision_candidate_scope",
            )}
            raw_checks = body.get("validation_checks")
            body["validation_checks"] = json.loads(raw_checks) if raw_checks else []
            raw_snapshot = body.get("comparison_snapshot")
            if isinstance(raw_snapshot, str) and raw_snapshot.strip():
                body["comparison_snapshot"] = json.loads(raw_snapshot)
            elif not raw_snapshot:
                body["comparison_snapshot"] = None
        except Exception:  # noqa: BLE001
            return _json({"detail": "Invalid multipart decision request."}, 400)
        for side, field_name in (("a", "datasheet_a"), ("b", "datasheet_b")):
            upload = form.get(field_name)
            if upload is None or not callable(getattr(upload, "read", None)):
                continue
            filename = str(getattr(upload, "filename", "") or "datasheet.pdf").strip()
            if not filename.casefold().endswith(".pdf"):
                return _json({"detail": f"Part {side.upper()} datasheet must be a PDF."}, 400)
            payload = await upload.read(MAX_DATASHEET_BYTES + 1)
            if len(payload) > MAX_DATASHEET_BYTES:
                return _json({"detail": "Each datasheet must be 8 MB or smaller."}, 413)
            if not payload.startswith(b"%PDF"):
                return _json({"detail": f"Part {side.upper()} upload is not a readable PDF file."}, 400)
            datasheet_uploads[side] = {"bytes": payload, "filename": filename}
    else:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Decision payload must be an object."}, 400)

    part_a = str(body.get("part_a") or "").strip()
    part_b = str(body.get("part_b") or "").strip()
    snapshot_in_early = body.get("comparison_snapshot")
    manufacturer_a = str(
        body.get("manufacturer_a")
        or (
            (snapshot_in_early or {}).get("manufacturer_a")
            if isinstance(snapshot_in_early, dict)
            else ""
        )
        or ""
    ).strip()
    manufacturer_b = str(
        body.get("manufacturer_b")
        or (
            (snapshot_in_early or {}).get("manufacturer_b")
            if isinstance(snapshot_in_early, dict)
            else ""
        )
        or ""
    ).strip()
    decision = str(body.get("decision") or "").strip()
    reviewer = str(body.get("reviewer") or "").strip()
    rationale = str(body.get("rationale") or "").strip()
    validation_checks = body.get("validation_checks") or []
    if not isinstance(validation_checks, list) or any(
        not isinstance(item, str) or item not in _DECISION_VALIDATION_CHECKS
        for item in validation_checks
    ):
        return _json({"detail": "Choose valid engineering validation items."}, 400)
    validation_checks = list(dict.fromkeys(validation_checks))
    follow_up_action = str(body.get("follow_up_action") or "").strip()
    follow_up_owner = str(body.get("follow_up_owner") or "").strip()
    follow_up_due_date = str(body.get("follow_up_due_date") or "").strip()
    residual_risk = str(body.get("residual_risk") or "unknown").strip().lower()
    requested_analysis_id = str(body.get("analysis_id") or "").strip() or None
    if not part_a or not part_b or part_a.casefold() == part_b.casefold():
        return _json({"detail": "Compare two different parts before recording a decision."}, 400)
    if len(part_a) > 160 or len(part_b) > 160:
        return _json({"detail": "Manufacturer part numbers must be 160 characters or fewer."}, 400)
    if decision not in _DECISION_LABELS:
        return _json({"detail": "Choose a supported engineering decision."}, 400)
    if not reviewer or len(reviewer) > 120:
        return _json({"detail": "Enter a reviewer name (up to 120 characters)."}, 400)
    if not rationale or len(rationale) > 3000:
        return _json({"detail": "Enter a rationale (up to 3,000 characters)."}, 400)
    if residual_risk not in _DECISION_RISK_LEVELS:
        return _json({"detail": "Choose a valid residual-risk level."}, 400)
    if len(follow_up_action) > 1000 or len(follow_up_owner) > 120:
        return _json({"detail": "Follow-up details exceed the allowed length."}, 400)
    if follow_up_due_date:
        try:
            from datetime import date

            date.fromisoformat(follow_up_due_date)
        except ValueError:
            return _json({"detail": "Follow-up due date must use YYYY-MM-DD."}, 400)
    if decision in {"conditional_approval", "defer_for_validation"} and not follow_up_action:
        return _json({"detail": "Add the follow-up action for a conditional or deferred decision."}, 400)
    if decision == "accept_residual_risk" and residual_risk == "unknown":
        return _json({"detail": "Choose a residual-risk level before recording risk acceptance."}, 400)
    required_approval_checks = {
        "manufacturer_datasheet_reviewed",
        "package_pinout_verified",
        "electrical_limits_verified",
    }
    if decision == "approve_alternate" and not required_approval_checks.issubset(set(validation_checks)):
        return _json(
            {
                "detail": (
                    "Before approving an alternate, record that its manufacturer datasheet, "
                    "package/pinout, and electrical limits were reviewed."
                )
            },
            400,
        )

    try:
        if requested_analysis_id and not _get_visible_report(
            requested_analysis_id, workspace_id=ctx["workspace_id"]
        ):
            return _json({"detail": "Report not found"}, 404)
        # Reuse an on-screen comparison only when its server-issued snapshot
        # token still binds this workspace/user, analysis, part pair, and
        # evidence contents. Invalid/mismatched tokens force a recompute.
        snapshot_in = body.get("comparison_snapshot")
        if isinstance(snapshot_in, str) and snapshot_in.strip():
            try:
                snapshot_in = json.loads(snapshot_in)
            except Exception:  # noqa: BLE001
                snapshot_in = None
        # Multi-candidate assemblies must verify every candidate token, then the
        # server rebuilds aggregate matrix/source/identity fields from those
        # verified pairwise payloads only (never trust client aggregates).
        # Stale/invalid multi tokens fail closed with a refresh-required error —
        # never silently recompute and persist only the primary candidate.
        multi_candidate_snapshots = (
            snapshot_in.get("candidate_snapshots")
            if isinstance(snapshot_in, dict)
            else None
        )
        is_multi_candidate_submission = (
            isinstance(multi_candidate_snapshots, list)
            and len(multi_candidate_snapshots) >= 2
        )
        trusted_snapshot = None
        if (
            isinstance(snapshot_in, dict)
            and snapshot_in.get("ok") is not False
            and not datasheet_uploads
        ):
            trusted_snapshot = materialize_snapshot_for_reuse(
                snapshot_in,
                workspace_id=str(ctx.get("workspace_id") or ""),
                user_id=str(ctx.get("user_id") or "") or None,
                analysis_id=requested_analysis_id,
                part_a=part_a,
                part_b=part_b,
            )
        if trusted_snapshot is not None:
            comparison = trusted_snapshot
            comparison.setdefault("ok", True)
            comparison["part_a"] = part_a
            comparison["part_b"] = part_b
            comparison["analysis_id"] = requested_analysis_id
            comparison["snapshot_reused"] = True
        elif is_multi_candidate_submission:
            return _json(
                {
                    "ok": False,
                    "code": "comparison_refresh_required",
                    "detail": (
                        "Multi-candidate comparison evidence does not match this BOM scope or its signed snapshot. "
                        "Re-compare every candidate under the selected Project / BOM, "
                        "then record the decision again. Cadivor will not silently save "
                        "only the primary candidate."
                    ),
                },
                409,
            )
        else:
            comparison = await run_in_threadpool(
                migration_tools.compare_parts_payload,
                workspace_id=ctx["workspace_id"],
                part_a=part_a,
                part_b=part_b,
                analysis_id=requested_analysis_id,
                manufacturer_a=manufacturer_a or None,
                manufacturer_b=manufacturer_b or None,
                use_latest_if_missing=False,
                datasheet_uploads=datasheet_uploads or None,
            )
            if isinstance(comparison, dict):
                comparison["snapshot_reused"] = False
        if not comparison.get("ok"):
            return _json({"detail": comparison.get("detail") or "Comparison unavailable."}, 400)
        decision_candidate_scope = "primary"
        decision_candidate_mpns = [part_b]
        if str(body.get("decision_candidate_scope") or "").strip().lower() == "all_selected":
            verified_candidates = comparison.get("candidate_snapshots")
            if isinstance(verified_candidates, list) and len(verified_candidates) > 1:
                seen_candidate_mpns: set[str] = set()
                selected_mpns: list[str] = []
                for candidate in verified_candidates:
                    if not isinstance(candidate, dict):
                        continue
                    candidate_mpn = str(candidate.get("part_b") or candidate.get("mpn") or "").strip()
                    key = candidate_mpn.casefold()
                    if candidate_mpn and key not in seen_candidate_mpns:
                        seen_candidate_mpns.add(key)
                        selected_mpns.append(candidate_mpn)
                if len(selected_mpns) > 1 and selected_mpns[0].casefold() == part_b.casefold():
                    decision_candidate_scope = "all_selected"
                    decision_candidate_mpns = selected_mpns
        analysis_id = str(comparison.get("analysis_id") or "").strip() or None
        report = (
            _get_visible_report(analysis_id, workspace_id=ctx["workspace_id"])
            if analysis_id
            else None
        )
        # Preserve requested identities even when snapshot reuse omitted them.
        if isinstance(comparison, dict):
            if manufacturer_a and not comparison.get("manufacturer_a"):
                comparison["manufacturer_a"] = manufacturer_a
            if manufacturer_b and not comparison.get("manufacturer_b"):
                comparison["manufacturer_b"] = manufacturer_b
        snapshot = {
            key: comparison.get(key)
            for key in (
                "mode",
                "finding",
                "engineering_evidence_summary",
                "engineering_evidence_status",
                "counts",
                "family",
                "family_mismatch",
                "rows",
                "part_cards",
                "source_a",
                "source_b",
                "evidence_sources",
                "datasheet_identity",
                "package_dimension_evidence",
                "review_warnings",
                "gap",
                "manufacturer_a",
                "manufacturer_b",
                "multi_candidate_mpns",
                "multi_candidate_manufacturers",
                "multi_matrix",
                "multi_source_records",
                "candidate_snapshots",
                "snapshot_aggregate_rebuilt",
            )
        }
        # Never trust client-supplied verified_primary_evidence — derive it
        # only from the server-verified comparison payload above.
        verified_primary = server_verified_primary_evidence(
            comparison,
            validation_checks=validation_checks,
            required_approval_checks=required_approval_checks,
        )
        record = get_store().create_decision_record(
            {
                "analysis_id": analysis_id,
                "project_name": split_project_and_bom(report or {})[0] or None,
                "bom_name": (report or {}).get("bom_name") or (report or {}).get("filename"),
                "revision": (report or {}).get("revision"),
                "part_a": part_a,
                "part_b": part_b,
                "decision_candidate_scope": decision_candidate_scope,
                "decision_candidate_mpns": decision_candidate_mpns,
                "manufacturer_a": manufacturer_a or comparison.get("manufacturer_a") or None,
                "manufacturer_b": manufacturer_b or comparison.get("manufacturer_b") or None,
                "decision": decision,
                "decision_label": _DECISION_LABELS[decision],
                "reviewer": reviewer,
                "rationale": rationale,
                "validation_checks": validation_checks,
                "follow_up_action": follow_up_action,
                "follow_up_owner": follow_up_owner,
                "follow_up_due_date": follow_up_due_date or None,
                "residual_risk": residual_risk,
                "verified_primary_evidence": verified_primary,
                "qualification_status": "not-qualified-by-cadivor",
                "qualification_note": (
                    "This record captures your decision and did not automatically qualify "
                    "a drop-in replacement or update the BOM."
                ),
                "comparison_snapshot": snapshot,
                "created_by": ctx.get("user_id"),
                "created_by_email": ctx.get("email"),
            },
            workspace_id=ctx["workspace_id"],
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, "record": record}, 201)


async def datasheet_qa_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if not plan_limits.effective_plan(ctx).get("datasheet_comparison"):
        return _json({
            "code": "feature_unavailable",
            "detail": "Datasheet tools are not included in this account's entitlements.",
        }, 402)
    form = await request.form()
    upload = form.get("file")
    question = str(form.get("question") or "").strip()
    if upload is None:
        return _json({"detail": "Missing datasheet file"}, 400)
    if not question:
        return _json({"detail": "Missing question"}, 400)
    filename = getattr(upload, "filename", None) or "datasheet.pdf"
    payload = await upload.read()
    if not payload:
        return _json({"detail": "Empty file"}, 400)
    try:
        result = migration_tools.datasheet_qa_payload(
            filename=filename,
            payload=payload,
            question=question,
            requested_mpn=str(form.get("mpn") or form.get("requested_mpn") or "").strip(),
            manufacturer=str(form.get("manufacturer") or "").strip(),
        )
    except Exception as exc:  # noqa: BLE001
        return _json({"detail": str(exc)}, 400)
    status = 200 if result.get("ok") else 400
    return _json(result, status)


@offload_sync_handler
def procurement_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = request.query_params.get("analysis_id") or None
    try:
        return _json(
            migration_tools.procurement_payload(
                workspace_id=ctx["workspace_id"], analysis_id=analysis_id
            )
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)


def _quote_report_part(report: dict[str, Any], mpn: str, manufacturer: str) -> dict[str, Any] | None:
    """Resolve a requested BOM part without allowing client identity substitution."""
    candidates = []
    for raw in report.get("parts") or []:
        if not isinstance(raw, dict):
            continue
        row_mpn = str(
            raw.get("MPN") or raw.get("mpn") or raw.get("Part Number") or raw.get("part_number") or ""
        ).strip()
        if row_mpn.casefold() == mpn.casefold():
            candidates.append(raw)
    if not candidates:
        return None
    makers = {
        str(row.get("Manufacturer") or row.get("manufacturer") or "").strip().casefold()
        for row in candidates
    }
    makers.discard("")
    if manufacturer:
        return next(
            (
                row
                for row in candidates
                if str(row.get("Manufacturer") or row.get("manufacturer") or "").strip().casefold()
                == manufacturer.casefold()
            ),
            None,
        )
    if len(makers) > 1:
        raise ValueError("This MPN belongs to multiple manufacturers in the saved BOM; select the manufacturer.")
    return candidates[0]


def _quote_number(value: Any, label: str, *, positive: bool = True, integer: bool = False) -> float | int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        raise ValueError(f"{label} must be greater than zero." if positive else f"{label} must be zero or greater.")
    if integer and not number.is_integer():
        raise ValueError(f"{label} must be a whole number.")
    return int(number) if integer else number


def _normalized_price_breaks(body: dict[str, Any]) -> list[dict[str, Any]]:
    raw_breaks = body.get("price_breaks")
    if raw_breaks is None:
        unit_price = body.get("unit_price")
        break_quantity = body.get("price_break_quantity")
        if unit_price in (None, "") and break_quantity in (None, ""):
            return []
        raw_breaks = [{"quantity": break_quantity or 1, "unit_price": unit_price}]
    if not isinstance(raw_breaks, list) or len(raw_breaks) > 20:
        raise ValueError("Enter no more than 20 price breaks.")
    result: list[dict[str, Any]] = []
    seen_quantities: set[int] = set()
    for index, raw in enumerate(raw_breaks, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Price break {index} is invalid.")
        quantity = _quote_number(raw.get("quantity"), f"Price break {index} quantity", integer=True)
        price = _quote_number(raw.get("unit_price"), f"Price break {index} unit price")
        if quantity is None or price is None:
            raise ValueError(f"Enter both quantity and unit price for price break {index}.")
        if quantity in seen_quantities:
            raise ValueError("Price break quantities must be unique.")
        seen_quantities.add(quantity)
        result.append({"quantity": quantity, "unit_price": price})
    return sorted(result, key=lambda row: row["quantity"])


def _valid_quote_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if len(url) > 2048:
        raise ValueError("Source URL must be 2,048 characters or fewer.")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Source URL must start with http:// or https://.")
    return url


@offload_sync_handler
def procurement_quotes_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = (request.query_params.get("analysis_id") or "").strip()
    requested_mpn = (request.query_params.get("mpn") or "").strip()
    requested_manufacturer = (request.query_params.get("manufacturer") or "").strip()
    if not analysis_id:
        return _json({"detail": "Select a saved BOM analysis before loading quotes."}, 400)
    try:
        report = _get_visible_report(analysis_id, workspace_id=ctx["workspace_id"])
        if not report:
            return _json({"detail": "Report not found"}, 404)
        if requested_mpn:
            try:
                part = _quote_report_part(report, requested_mpn, requested_manufacturer)
            except ValueError as exc:
                return _json({"detail": str(exc)}, 409)
            if not part:
                return _json({"detail": "Part not found in the selected saved BOM revision."}, 404)
        quotes = get_store().list_procurement_quotes(
            workspace_id=ctx["workspace_id"],
            analysis_id=analysis_id,
            requested_mpn=requested_mpn or None,
            requested_manufacturer=requested_manufacturer or None,
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, "analysis_id": analysis_id, "quotes": quotes})


class ProcurementQuoteIdentityError(ValueError):
    """A quote's requested MPN cannot be safely resolved against the saved BOM."""


def _prepare_procurement_quote_record(
    body: dict[str, Any],
    *,
    report: dict[str, Any],
    ctx: dict[str, Any],
    analysis_id: str,
) -> dict[str, Any]:
    """Validate and canonicalize one user-entered quote for a saved BOM."""
    body_analysis_id = str(body.get("analysis_id") or analysis_id).strip()
    requested_mpn = str(body.get("requested_mpn") or "").strip()
    requested_manufacturer = str(body.get("requested_manufacturer") or "").strip()
    supplier = str(body.get("supplier") or "").strip()
    offered_mpn = str(body.get("offered_mpn") or "").strip()
    offered_manufacturer = str(body.get("offered_manufacturer") or "").strip()
    currency = str(body.get("currency") or "").strip().upper()
    quote_reference = str(body.get("quote_reference") or "").strip()
    notes = str(body.get("notes") or "").strip()
    if body_analysis_id != analysis_id:
        raise ValueError("All quote rows must belong to the selected saved BOM revision.")
    if not analysis_id or not requested_mpn:
        raise ValueError("Select a saved BOM analysis and part.")
    if len(requested_mpn) > 160 or len(requested_manufacturer) > 160:
        raise ValueError("Requested part identity is too long.")
    if not supplier or len(supplier) > 120:
        raise ValueError("Enter a supplier name (up to 120 characters).")
    if not offered_mpn or len(offered_mpn) > 160 or len(offered_manufacturer) > 160:
        raise ValueError("Enter the quoted MPN and a manufacturer of 160 characters or fewer.")
    if len(quote_reference) > 160 or len(notes) > 3000:
        raise ValueError("Quote reference or notes exceed the allowed length.")
    if currency and not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Currency must be a three-letter code such as USD.")

    price_breaks = _normalized_price_breaks(body)
    if price_breaks and not currency:
        raise ValueError("Choose a currency for the quoted prices.")
    minimum_order_quantity = _quote_number(
        body.get("minimum_order_quantity"), "Minimum order quantity", integer=True
    )
    pack_quantity = _quote_number(body.get("pack_quantity"), "Pack quantity", integer=True)
    stock = _quote_number(body.get("stock"), "Available stock", positive=False, integer=True)
    lead_time_weeks = _quote_number(body.get("lead_time_weeks"), "Lead time", positive=False)
    valid_until = str(body.get("valid_until") or "").strip()
    price_date = str(body.get("price_date") or "").strip()
    if valid_until:
        from datetime import date

        date.fromisoformat(valid_until)
    if price_date:
        from datetime import date

        date.fromisoformat(price_date)
    source_url = _valid_quote_url(body.get("source_url"))
    try:
        requested_part = _quote_report_part(report, requested_mpn, requested_manufacturer)
    except ValueError as exc:
        raise ProcurementQuoteIdentityError(str(exc)) from exc
    if not requested_part:
        raise ValueError("Requested part does not match a part in this saved BOM revision.")
    canonical_mpn = str(
        requested_part.get("MPN") or requested_part.get("mpn") or requested_part.get("Part Number") or requested_mpn
    ).strip()
    canonical_manufacturer = str(
        requested_part.get("Manufacturer") or requested_part.get("manufacturer") or ""
    ).strip()
    exact_mpn = offered_mpn.casefold() == canonical_mpn.casefold()
    exact_manufacturer = bool(canonical_manufacturer) and (
        offered_manufacturer.casefold() == canonical_manufacturer.casefold()
    )
    if exact_mpn and exact_manufacturer:
        identity_status = "exact_part"
    elif exact_mpn and (not canonical_manufacturer or not offered_manufacturer):
        identity_status = "manufacturer_unconfirmed"
    else:
        identity_status = "alternate_candidate"
    return {
        "analysis_id": analysis_id,
        "project_name": report.get("project_name"),
        "bom_name": report.get("bom_name") or report.get("filename"),
        "revision": report.get("revision"),
        "requested_mpn": canonical_mpn,
        "requested_manufacturer": canonical_manufacturer,
        "supplier": supplier,
        "quote_reference": quote_reference,
        "offered_mpn": offered_mpn,
        "offered_manufacturer": offered_manufacturer,
        "identity_status": identity_status,
        "requires_engineering_review": identity_status != "exact_part",
        "currency": currency,
        "unit_price": price_breaks[0]["unit_price"] if price_breaks else None,
        "price_break_quantity": price_breaks[0]["quantity"] if price_breaks else None,
        "price_breaks": price_breaks,
        "minimum_order_quantity": minimum_order_quantity,
        "pack_quantity": pack_quantity,
        "stock": stock,
        "lead_time_weeks": lead_time_weeks,
        "price_date": price_date,
        "valid_until": valid_until,
        "source_url": source_url,
        "notes": notes,
        "recorded_by": str(ctx.get("user_id") or ""),
        "evidence_kind": "user_entered_supplier_quote",
    }


async def procurement_quotes_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Quote payload must be an object."}, 400)

    analysis_id = str(body.get("analysis_id") or "").strip()
    if not analysis_id:
        return _json({"detail": "Select a saved BOM analysis and part."}, 400)
    try:
        report = _get_visible_report(analysis_id, workspace_id=ctx["workspace_id"])
        if not report:
            return _json({"detail": "Report not found"}, 404)
        record = _prepare_procurement_quote_record(body, report=report, ctx=ctx, analysis_id=analysis_id)
        saved = get_store().create_procurement_quote(
            record, workspace_id=ctx["workspace_id"]
        )
    except ProcurementQuoteIdentityError as exc:
        return _json({"detail": str(exc)}, 409)
    except ValueError as exc:
        return _json({"detail": str(exc)}, 400)
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, "quote": saved}, 201)


async def procurement_quotes_bulk_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Quote import payload must be an object."}, 400)
    analysis_id = str(body.get("analysis_id") or "").strip()
    batch_id = str(body.get("import_batch_id") or "").strip()
    raw_quotes = body.get("quotes")
    if not analysis_id:
        return _json({"detail": "Select a saved BOM analysis before importing prices."}, 400)
    try:
        uuid.UUID(batch_id)
    except (ValueError, AttributeError):
        return _json({"detail": "Import batch identifier is invalid. Choose the file again and retry."}, 400)
    if not isinstance(raw_quotes, list) or not raw_quotes or len(raw_quotes) > 1000:
        return _json({"detail": "Import between 1 and 1,000 price rows at a time."}, 400)
    try:
        report = _get_visible_report(analysis_id, workspace_id=ctx["workspace_id"])
        if not report:
            return _json({"detail": "Report not found"}, 404)
        records = []
        for index, raw in enumerate(raw_quotes, start=1):
            if not isinstance(raw, dict):
                return _json({"detail": f"Row {index}: quote row must be an object."}, 400)
            try:
                record = _prepare_procurement_quote_record(
                    raw, report=report, ctx=ctx, analysis_id=analysis_id
                )
                row_number = int(raw.get("import_row_number") or index)
                if row_number < 1:
                    raise ValueError("Source row number must be positive.")
            except (ValueError, TypeError) as exc:
                return _json({"detail": f"Row {index}: {exc}"}, 400)
            record["import_batch_id"] = batch_id
            record["import_row_number"] = row_number
            records.append(record)
        fingerprint = hashlib.sha256(
            json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for record in records:
            record["import_batch_fingerprint"] = fingerprint

        store = get_store()
        existing = [
            quote for quote in store.list_procurement_quotes(
                workspace_id=ctx["workspace_id"], analysis_id=analysis_id
            )
            if quote.get("import_batch_id") == batch_id
        ]
        if existing:
            if len(existing) == len(records) and all(
                quote.get("import_batch_fingerprint") == fingerprint for quote in existing
            ):
                saved = sorted(existing, key=lambda quote: int(quote.get("import_row_number") or 0))
            else:
                return _json({"detail": "This import ID was already used with different rows. Choose the file again to create a new import."}, 409)
        else:
            saved = store.create_procurement_quotes(records, workspace_id=ctx["workspace_id"])
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, "analysis_id": analysis_id, "quotes": saved, "saved_count": len(saved)}, 201)


@offload_sync_handler
def design_impact_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(
            migration_tools.design_impact_payload(
                workspace_id=ctx["workspace_id"],
                analysis_id=request.query_params.get("analysis_id") or None,
                selected_mpn=request.query_params.get("mpn") or "",
            )
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)


@offload_sync_handler
def cost_optimization_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    qty = request.query_params.get("build_quantity") or "100"
    try:
        build_quantity = int(qty)
    except ValueError:
        return _json({"detail": "Build quantity must be a whole number."}, 400)
    if build_quantity < 1 or build_quantity > 10_000_000:
        return _json({"detail": "Build quantity must be between 1 and 10,000,000."}, 400)
    target_raw = request.query_params.get("target_unit_cost")
    try:
        target_unit_cost = float(target_raw) if target_raw not in (None, "") else None
    except (TypeError, ValueError):
        return _json({"detail": "Target unit cost must be a valid number."}, 400)
    if target_unit_cost is not None and (not math.isfinite(target_unit_cost) or target_unit_cost <= 0):
        return _json({"detail": "Target unit cost must be greater than zero."}, 400)
    try:
        return _json(
            migration_tools.cost_optimization_payload(
                workspace_id=ctx["workspace_id"],
                analysis_id=request.query_params.get("analysis_id") or None,
                build_quantity=build_quantity,
                target_unit_cost=target_unit_cost,
            )
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)


async def cost_optimization_decisions(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        workspace_store = get_store()
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)

    if request.method == "GET":
        analysis_id = str(request.query_params.get("analysis_id") or "").strip()
        if not analysis_id:
            return _json({"detail": "analysis_id is required."}, 400)
        try:
            decisions = workspace_store.list_cost_decisions(
                workspace_id=ctx["workspace_id"], analysis_id=analysis_id
            )
        except WorkspaceAccessError:
            return _json({"detail": "Report not found."}, 404)
        return _json({"ok": True, "decisions": decisions})

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Decision payload must be an object."}, 400)
    analysis_id = str(body.get("analysis_id") or "").strip()
    part_number = str(body.get("part_number") or "").strip()
    manufacturer = str(body.get("manufacturer") or "").strip()
    category = str(body.get("category") or "").strip()
    supplier = str(body.get("supplier") or "").strip()
    reviewer = str(body.get("reviewer") or "").strip()
    rationale = str(body.get("rationale") or "").strip()
    if not analysis_id or not part_number or not manufacturer or not category or not supplier:
        return _json({"detail": "Select a saved BOM and a current savings opportunity."}, 400)
    if not reviewer or len(reviewer) > 120:
        return _json({"detail": "Enter a reviewer name (up to 120 characters)."}, 400)
    if not rationale or len(rationale) > 3000:
        return _json({"detail": "Enter a rationale (up to 3,000 characters)."}, 400)
    try:
        build_quantity = int(body.get("build_quantity") or 0)
        target_raw = body.get("target_unit_cost")
        target_unit_cost = float(target_raw) if target_raw not in (None, "") else None
        purchase_quantity = int(body.get("recommended_purchase_quantity") or 0)
        target_unit_price = float(body.get("target_unit_price") or 0)
    except (TypeError, ValueError):
        return _json({"detail": "Cost decision inputs must be valid numbers."}, 400)
    if build_quantity < 1 or build_quantity > 10_000_000:
        return _json({"detail": "Build quantity must be between 1 and 10,000,000."}, 400)
    if target_unit_cost is not None and (not math.isfinite(target_unit_cost) or target_unit_cost <= 0):
        return _json({"detail": "Target cost must be greater than zero."}, 400)
    try:
        current = migration_tools.cost_optimization_payload(
            workspace_id=ctx["workspace_id"],
            analysis_id=analysis_id,
            build_quantity=build_quantity,
            target_unit_cost=target_unit_cost,
        )
        optimization = current.get("optimization") or {}
        candidate = next(
            (
                row for row in optimization.get("opportunities", [])
                if str(row.get("Part Number") or "").strip().casefold() == part_number.casefold()
                and str(row.get("Manufacturer") or "").strip().casefold() == manufacturer.casefold()
                and str(row.get("Category") or "").strip().casefold() == category.casefold()
                and str(row.get("Supplier") or "").strip().casefold() == supplier.casefold()
                and int(row.get("Recommended Purchase Quantity") or row.get("Required Order Quantity") or 0) == purchase_quantity
                and math.isclose(float(row.get("Estimated Target Price") or 0), target_unit_price, rel_tol=1e-8, abs_tol=1e-8)
            ),
            None,
        )
        if not candidate:
            return _json(
                {"detail": "This savings option is no longer verified for the selected report and quantity. Recalculate the page and review current evidence."},
                409,
            )
        saved = workspace_store.create_cost_decision(
            {
                "analysis_id": analysis_id,
                "created_by": str(ctx.get("user_id") or ""),
                "reviewer": reviewer,
                "rationale": rationale,
                "status": "Pending review",
                "decision_type": (
                    "supplier_selection"
                    if category.casefold() == "cheaper authorized source"
                    else "price_break"
                ),
                "title": f"{part_number} · {category}",
                "part_number": part_number,
                "manufacturer": str(candidate.get("Manufacturer") or ""),
                "current_supplier": str(candidate.get("Current Supplier") or ""),
                "recommended_supplier": supplier,
                "currency": str(candidate.get("Currency") or ""),
                "build_quantity": build_quantity,
                "required_order_quantity": candidate.get("Required Order Quantity"),
                "recommended_purchase_quantity": candidate.get("Recommended Purchase Quantity") or candidate.get("Required Order Quantity"),
                "estimated_extra_quantity": candidate.get("Extra Quantity") or 0,
                "current_unit_price": candidate.get("Current Unit Price"),
                "recommended_unit_price": candidate.get("Estimated Target Price"),
                "estimated_net_savings": candidate.get("Estimated Run Savings"),
                "evidence_snapshot": candidate,
                "target_unit_cost": target_unit_cost,
            },
            workspace_id=ctx["workspace_id"],
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found."}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, "decision": saved}, 201)


async def supply_risk_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    try:
        return _json(
            migration_tools.supply_risk_payload(
                workspace_id=ctx["workspace_id"],
                analysis_id=body.get("analysis_id") or None,
                build_quantity=int(body.get("build_quantity") or 100),
                stock_reduction_percent=int(body.get("stock_reduction_percent") or 25),
                supplier_loss=int(body.get("supplier_loss") or 0),
                demand_growth_percent=int(body.get("demand_growth_percent") or 0),
                include_lifecycle_event=bool(body.get("include_lifecycle_event")),
            )
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)


async def supply_risk_scenarios(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        store = get_store()
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    if request.method == "GET":
        analysis_id = str(request.query_params.get("analysis_id") or "").strip()
        if not analysis_id:
            return _json({"detail": "analysis_id is required."}, 400)
        try:
            scenarios = store.list_supply_scenarios(
                workspace_id=ctx["workspace_id"], analysis_id=analysis_id
            )
        except WorkspaceAccessError:
            return _json({"detail": "Report not found."}, 404)
        except PersistenceNotConfiguredError as exc:
            return _json({"detail": str(exc)}, 503)
        return _json({"ok": True, "scenarios": scenarios})

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Scenario payload must be an object."}, 400)
    analysis_id = str(body.get("analysis_id") or "").strip()
    if not analysis_id:
        return _json({"detail": "Select a saved analysis before saving a scenario."}, 400)
    try:
        build_quantity = int(body.get("build_quantity") or 0)
        stock_reduction_percent = int(body.get("stock_reduction_percent") or 0)
        supplier_loss = int(body.get("supplier_loss") or 0)
        demand_growth_percent = int(body.get("demand_growth_percent") or 0)
    except (TypeError, ValueError):
        return _json({"detail": "Scenario inputs must be whole numbers."}, 400)
    if build_quantity < 1 or build_quantity > 10_000_000:
        return _json({"detail": "Build quantity must be between 1 and 10,000,000."}, 400)
    if not 0 <= stock_reduction_percent <= 100:
        return _json({"detail": "Stock reduction must be between 0 and 100 percent."}, 400)
    if supplier_loss < 0 or demand_growth_percent < 0:
        return _json({"detail": "Supplier loss and demand growth cannot be negative."}, 400)
    include_lifecycle_event = bool(body.get("include_lifecycle_event"))
    try:
        payload = migration_tools.supply_risk_payload(
            workspace_id=ctx["workspace_id"],
            analysis_id=analysis_id,
            build_quantity=build_quantity,
            stock_reduction_percent=stock_reduction_percent,
            supplier_loss=supplier_loss,
            demand_growth_percent=demand_growth_percent,
            include_lifecycle_event=include_lifecycle_event,
        )
        if payload.get("scope") != "analysis" or not payload.get("scenario"):
            return _json({"detail": "A saved BOM analysis is required."}, 400)
        scenario = payload["scenario"]
        saved = store.create_supply_scenario(
            {
                "analysis_id": analysis_id,
                "created_by": str(ctx.get("user_id") or ""),
                "title": str(body.get("title") or "").strip()[:120]
                or f"Stock reduction {stock_reduction_percent}% · build {build_quantity}",
                "mode": payload.get("mode"),
                "parameters": payload.get("parameters") or {},
                "summary": {
                    "buildable_units": scenario.get("buildable_units"),
                    "baseline_buildable_units": scenario.get("baseline_buildable_units"),
                    "buildability_status": scenario.get("buildability_status"),
                    "limiting_part": scenario.get("limiting_part"),
                    "shortage_components": scenario.get("shortage_components"),
                    "stock_coverage": payload.get("stock_coverage"),
                    "stock_coverage_gap": payload.get("stock_coverage_gap"),
                },
                "scenario": scenario,
            },
            workspace_id=ctx["workspace_id"],
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found."}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, "scenario": saved}, 201)


@offload_sync_handler
def portfolio_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    return _json(migration_tools.portfolio_payload(workspace_id=ctx["workspace_id"]))


async def portfolio_health_recalculate_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    analysis_id = str(body.get("analysis_id") or "").strip() if isinstance(body, dict) else ""
    if not analysis_id:
        return _json({"detail": "analysis_id is required"}, 400)
    try:
        result = recalculate_report_health(
            analysis_id,
            workspace_id=ctx["workspace_id"],
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    if not result:
        return _json({"detail": "Report not found"}, 404)
    return _json(result)


@offload_sync_handler
def detailed_risk_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = request.query_params.get("analysis_id") or None
    try:
        return _json(
            migration_tools.detailed_risk_payload(
                workspace_id=ctx["workspace_id"], analysis_id=analysis_id
            )
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)



async def supplier_lookup_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    result = supplier_lookup.lookup_exact_part(str(body.get("mpn") or ""))
    return _json(result)


async def find_replacement_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    # Optional analysis_id is soft context only. Stale/inaccessible IDs must not
    # 404 the search — find_replacement_payload degrades to standalone.
    result = migration_tools.find_replacement_payload(
        workspace_id=ctx["workspace_id"],
        mpn=str(body.get("mpn") or body.get("part_number") or ""),
        manufacturer=str(body.get("manufacturer") or ""),
        analysis_id=body.get("analysis_id") or None,
    )
    status = 200 if result.get("ok") else 400
    return _json(result, status)


async def ask_cadivor_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    history = body.get("history") if isinstance(body.get("history"), list) else []
    clean_history: list[dict[str, str]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or item.get("text") or "").strip()
        if role and content:
            clean_history.append({"role": role, "content": content})
    try:
        result = migration_tools.ask_cadivor_payload(
            workspace_id=ctx["workspace_id"],
            analysis_id=str(body.get("analysis_id") or ""),
            question=str(body.get("question") or ""),
            history=clean_history,
            user_context=ctx,
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    if result.get("ok"):
        status = 200
    elif result.get("code") == "ai_credit_limit":
        status = 429
    elif result.get("code") == "ai_credits_unavailable":
        status = 503
    else:
        status = 400
    return _json(result, status)


@offload_sync_handler
def monitoring_preferences_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    return _json({
        "ok": True,
        "preferences": monitoring_store.get_user_preferences(
            ctx["workspace_id"], ctx["user_id"], ctx["email"]
        ),
    })


async def monitoring_preferences_put(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Expected a JSON object."}, 400)
    if "supplier_checks" in body and not isinstance(body["supplier_checks"], bool):
        return _json({"detail": "supplier_checks must be true or false."}, 400)
    if body.get("supplier_checks") is True:
        plan = plan_limits.effective_plan(ctx)
        base_limit = plan.get("monitored_parts_limit")
        desired_parts = sum(
            max(0, int(row.get("total_parts") or 0))
            for row in get_store().list_monitoring_analyses()
            if str(row.get("workspace_id") or "") == str(ctx["workspace_id"])
        )
        if base_limit is None:
            monitoring_store.set_workspace_monitoring_capacity(ctx["workspace_id"], None)
        else:
            over_limit = max(0, desired_parts - max(0, int(base_limit)))
            if over_limit:
                token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
                try:
                    allocation, allocation_status = subscription_billing_service.request_action(
                        access_token=token,
                        action="allocate_monitored_part_credits",
                        payload={
                            "workspace_id": ctx["workspace_id"],
                            "required_credits": over_limit,
                        },
                        origin=request.headers.get("origin", ""),
                        timeout_seconds=8,
                        internal_context={
                            "user_id": str(ctx["user_id"]),
                            "workspace_id": str(ctx["workspace_id"]),
                        },
                    )
                except subscription_billing_service.SubscriptionBillingError:
                    return _json({"detail": "Monitoring capacity could not be confirmed. Try again shortly."}, 503)
                if allocation_status != 200 or allocation.get("allocated") is not True:
                    return _json({
                        "code": "monitored_parts_limit",
                        "detail": (
                            f"This workspace has {desired_parts:,} component slots to monitor, above the "
                            f"included limit of {int(base_limit):,}. Add monitored-parts capacity or remove analyses "
                            "from monitoring before enabling scheduled checks."
                        ),
                        "required_overage_credits": over_limit,
                    }, 402)
            monitoring_store.set_workspace_monitoring_capacity(
                ctx["workspace_id"],
                max(max(0, int(base_limit)), desired_parts),
            )
    try:
        prefs = monitoring_store.update_user_preferences(
            ctx["workspace_id"],
            ctx["user_id"],
            ctx["email"],
            body if isinstance(body, dict) else {},
        )
    except ValueError as exc:
        return _json({"detail": str(exc)}, 400)
    if body.get("supplier_checks") is False and not any(
        row.get("workspace_id") == ctx["workspace_id"]
        for row in monitoring_store.list_user_preferences(supplier_checks=True)
    ):
        monitoring_store.set_workspace_monitoring_capacity(ctx["workspace_id"], 0)
    return _json({"ok": True, "preferences": prefs})


@offload_sync_handler
def monitoring_slack_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        team_service.require_admin(ctx)
        can_manage = True
    except TeamError:
        can_manage = False
    return _json({
        "ok": True,
        "integration": {
            **monitoring_store.get_workspace_slack_integration(ctx["workspace_id"]),
            "can_manage": can_manage,
        },
    })


async def monitoring_slack_put(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        team_service.require_admin(ctx)
    except TeamError as exc:
        return _team_error(exc)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        return _json({"detail": "enabled must be true or false."}, 400)
    webhook_url = str(body.get("webhook_url") or "").strip()
    clear = body.get("clear") is True
    if clear and webhook_url:
        return _json({"detail": "Clear the saved Slack connection or replace it, not both."}, 400)
    replace_webhook = bool(webhook_url or clear)
    encrypted: str | None = None
    if webhook_url:
        try:
            encrypted = slack_notifications.encrypt_webhook_url(webhook_url)
        except slack_notifications.SlackConfigurationError as exc:
            return _json({"detail": str(exc)}, 400)
    current = monitoring_store.get_workspace_slack_integration(ctx["workspace_id"])
    configured_after = False if clear else (bool(encrypted) or bool(current.get("configured")))
    if body["enabled"] and not configured_after:
        return _json({"detail": "Add a Slack incoming webhook URL before enabling Slack alerts."}, 400)
    if body["enabled"] and not current.get("encryption_ready"):
        return _json({"detail": "Slack webhook encryption is not configured on Cadivor."}, 503)
    try:
        integration = monitoring_store.set_workspace_slack_integration(
            ctx["workspace_id"],
            enabled=bool(body["enabled"]) and not clear,
            webhook_ciphertext=encrypted,
            replace_webhook=replace_webhook,
        )
    except Exception:  # noqa: BLE001
        logging.exception("monitoring_slack_integration_update_failed")
        return _json({"detail": "Slack alerts could not be updated."}, 503)
    return _json({"ok": True, "integration": {**integration, "can_manage": True}})


@offload_sync_handler
def monitoring_alerts_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = (request.query_params.get("analysis_id") or "").strip() or None
    return _json(
        {
            "ok": True,
            "analysis_id": analysis_id,
            "alerts": monitoring_store.list_alerts(
                ctx["workspace_id"], analysis_id=analysis_id
            ),
            "refresh_history": monitoring_store.list_refresh_history(ctx["workspace_id"]),
            "preferences": monitoring_store.get_user_preferences(
                ctx["workspace_id"], ctx["user_id"], ctx["email"]
            ),
        }
    )


async def monitoring_acknowledge_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    alert = monitoring_store.acknowledge_alert(ctx["workspace_id"], str(body.get("alert_id") or ""))
    if not alert:
        return _json({"detail": "Alert not found"}, 404)
    return _json({"ok": True, "alert": alert})


async def monitoring_notify_post(request: Request) -> JSONResponse:
    """Explicit email notification action — never implied by refresh or page GET.

    Requires a specific ``alert_id`` owned by the caller's workspace. Delivery
    still respects preference and ``CADIVOR_MONITORING_EMAIL_ENABLED`` gates.
    """
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    alert_id = str((body or {}).get("alert_id") or "").strip()
    if not alert_id:
        return _json(
            {
                "detail": (
                    "alert_id is required. Refresh never sends email — "
                    "Notify is the explicit delivery action."
                )
            },
            400,
        )
    alerts = monitoring_store.list_alerts(ctx["workspace_id"])
    alert = next((a for a in alerts if str(a.get("id") or "") == alert_id), None)
    if not alert:
        return _json({"detail": "Alert not found"}, 404)
    if alert.get("active") is False or str(alert.get("status") or "").lower() == "inactive":
        return _json({"detail": "Alert is inactive and cannot be notified"}, 409)
    result = monitoring_store.deliver_alert_email(
        ctx["workspace_id"],
        alert,
        user_id=ctx["user_id"],
        recipient_email=ctx["email"],
    )
    return _json({**result, "explicit_notify": True, "alert_id": alert_id})


@offload_sync_handler
def plan_usage_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    return _json({"ok": True, **plan_limits.usage_snapshot(ctx["workspace_id"], ctx)})


def _sync_workspace_monitoring_entitlement(
    ctx: dict[str, Any],
    *,
    addon_capacity: int,
) -> None:
    updated = {**ctx, "monitored_parts_addon_capacity": max(0, int(addon_capacity))}
    capacity = plan_limits.effective_plan(updated).get("monitored_parts_limit")
    monitoring_store.set_workspace_monitoring_capacity(
        str(ctx["workspace_id"]),
        None if capacity is None else max(0, int(capacity)),
    )


@offload_sync_handler
def billing_status_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    try:
        result, status = subscription_billing_service.request_action(
            access_token=token,
            action="status",
            origin=request.headers.get("origin", ""),
        )
        if status < 200 or status >= 300:
            raise subscription_billing_service.SubscriptionBillingError("Billing status unavailable")
    except subscription_billing_service.SubscriptionBillingError:
        result = {
            "ok": False,
            "checkout_enabled": False,
            "charges_created": False,
            "has_active_subscription": False,
            "can_manage_billing": False,
            "stripe_mode": "unavailable",
            "plans": [],
            "gap": "Plan billing is temporarily unavailable. Please try again or contact support.",
        }
    result["plan_catalog"] = billing_prep.plan_catalog()
    return _json(result)


async def billing_checkout_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    try:
        result, status = subscription_billing_service.request_action(
            access_token=token,
            action="checkout",
            payload={
                "plan": body.get("plan") or body.get("plan_token") or "",
                "billing_interval": body.get("billing_interval") or "month",
            },
            origin=request.headers.get("origin", ""),
        )
    except subscription_billing_service.SubscriptionBillingError as exc:
        return _json({"ok": False, "detail": str(exc)}, 503)
    return _json(result, status)


@offload_sync_handler
def billing_professional_api_addon_checkout_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    try:
        result, status = subscription_billing_service.request_action(
            access_token=token,
            action="professional_api_addon_checkout",
            origin=request.headers.get("origin", ""),
        )
    except subscription_billing_service.SubscriptionBillingError as exc:
        return _json({"ok": False, "detail": str(exc)}, 503)
    return _json(result, status)


async def billing_monitored_parts_addon_checkout_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Invalid request"}, 400)
    interval = str(body.get("billing_interval") or "").strip().lower()
    if interval not in {"month", "year"}:
        return _json({"detail": "Choose monthly or annual billing."}, 400)
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    try:
        result, status = subscription_billing_service.request_action(
            access_token=token,
            action="monitored_parts_addon_checkout",
            payload={"billing_interval": interval},
            origin=request.headers.get("origin", ""),
        )
    except subscription_billing_service.SubscriptionBillingError as exc:
        return _json({"ok": False, "detail": str(exc)}, 503)
    if status == 200 and result.get("addon_added") is True:
        try:
            _sync_workspace_monitoring_entitlement(
                ctx,
                addon_capacity=int(result.get("capacity") or 0),
            )
            supabase_auth.invalidate_account_entitlements(token)
            result["monitoring_capacity_synced"] = True
        except Exception as exc:  # noqa: BLE001
            logging.warning("monitored_parts_capacity_sync_failed exception=%s", type(exc).__name__)
            result["monitoring_capacity_synced"] = False
            result["detail"] = (
                str(result.get("detail") or "Capacity is active.")
                + " The monitoring schedule will refresh its capacity shortly."
            )
    return _json(result, status)


@offload_sync_handler
def billing_monitored_parts_addon_remove_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    try:
        result, status = subscription_billing_service.request_action(
            access_token=token,
            action="monitored_parts_addon_remove",
            origin=request.headers.get("origin", ""),
        )
    except subscription_billing_service.SubscriptionBillingError as exc:
        return _json({"ok": False, "detail": str(exc)}, 503)
    if status == 200 and result.get("addon_removed") is True:
        try:
            _sync_workspace_monitoring_entitlement(ctx, addon_capacity=0)
            supabase_auth.invalidate_account_entitlements(token)
            result["monitoring_capacity_synced"] = True
        except Exception as exc:  # noqa: BLE001
            logging.warning("monitored_parts_capacity_sync_failed exception=%s", type(exc).__name__)
            result["monitoring_capacity_synced"] = False
            result["detail"] = (
                str(result.get("detail") or "Capacity was removed.")
                + " The monitoring schedule will refresh its capacity shortly."
            )
    return _json(result, status)


async def billing_usage_overage_checkout_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Invalid request"}, 400)
    kind = str(body.get("credit_kind") or "").strip()
    payload: dict[str, Any]
    if kind == "bom_analysis":
        payload = {"credit_kind": kind}
    elif kind == "ask_cadivor":
        pack_id = str(body.get("pack_id") or "").strip()
        if pack_id not in {"ask_100", "ask_500", "ask_1500"}:
            return _json({"detail": "Choose a supported Ask Cadivor credit pack."}, 400)
        payload = {"credit_kind": kind, "pack_id": pack_id}
    else:
        return _json({"detail": "Choose a supported usage pack."}, 400)
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    try:
        result, status = subscription_billing_service.request_action(
            access_token=token,
            action="usage_overage_checkout",
            payload=payload,
            origin=request.headers.get("origin", ""),
        )
    except subscription_billing_service.SubscriptionBillingError as exc:
        return _json({"ok": False, "detail": str(exc)}, 503)
    return _json(result, status)


def _developer_api_entitled(ctx: dict[str, Any]) -> bool:
    return bool(plan_limits.effective_plan(ctx).get("api_access"))


@offload_sync_handler
def developer_api_keys_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if not _developer_api_entitled(ctx):
        return _json({"detail": "Developer API access is not active for this account."}, 403)
    try:
        team_service.require_admin(ctx)
        result, status = subscription_billing_service.request_action(
            access_token=ctx["access_token"],
            action="developer_api_keys_list",
            payload={"workspace_id": ctx["workspace_id"]},
            timeout_seconds=8,
            internal_context={
                "user_id": str(ctx["user_id"]),
                "workspace_id": str(ctx["workspace_id"]),
            },
        )
    except TeamError as exc:
        return _team_error(exc)
    except subscription_billing_service.SubscriptionBillingError:
        return _json({"detail": "Developer API settings are temporarily unavailable."}, 503)
    if status != 200:
        return _json({"detail": result.get("detail") or "Developer API keys could not be loaded."}, status)
    return JSONResponse(
        {"ok": True, "keys": result.get("keys") or []},
        headers={"Cache-Control": "no-store"},
    )


async def developer_api_keys_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if not _developer_api_entitled(ctx):
        return _json({"detail": "Developer API access is not active for this account."}, 403)
    try:
        team_service.require_admin(ctx)
    except TeamError as exc:
        return _team_error(exc)
    body, bad = await _read_json_object(request)
    if bad is not None or body is None:
        return bad or _json({"detail": "Invalid JSON"}, 400)
    name = " ".join(str(body.get("name") or "").split())
    if not name or len(name) > 80:
        return _json({"detail": "Enter an API key name of 1 to 80 characters."}, 400)
    try:
        result, status = subscription_billing_service.request_action(
            access_token=ctx["access_token"],
            action="developer_api_key_create",
            payload={"workspace_id": ctx["workspace_id"], "name": name},
            origin=request.headers.get("origin", ""),
            timeout_seconds=8,
            internal_context={
                "user_id": str(ctx["user_id"]),
                "workspace_id": str(ctx["workspace_id"]),
            },
        )
    except subscription_billing_service.SubscriptionBillingError:
        return _json({"detail": "Developer API settings are temporarily unavailable."}, 503)
    if status != 201 or not isinstance(result.get("key"), dict):
        return _json({"detail": result.get("detail") or "API key could not be created."}, status or 503)
    return JSONResponse(
        {"ok": True, "key": result["key"]},
        status_code=201,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@offload_sync_handler
def developer_api_key_delete(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if not _developer_api_entitled(ctx):
        return _json({"detail": "Developer API access is not active for this account."}, 403)
    try:
        team_service.require_admin(ctx)
    except TeamError as exc:
        return _team_error(exc)
    key_id = str(request.path_params.get("key_id") or "").strip()
    try:
        result, status = subscription_billing_service.request_action(
            access_token=ctx["access_token"],
            action="developer_api_key_revoke",
            payload={"workspace_id": ctx["workspace_id"], "key_id": key_id},
            timeout_seconds=8,
            internal_context={
                "user_id": str(ctx["user_id"]),
                "workspace_id": str(ctx["workspace_id"]),
            },
        )
    except subscription_billing_service.SubscriptionBillingError:
        return _json({"detail": "Developer API settings are temporarily unavailable."}, 503)
    if status != 200:
        return _json({"detail": result.get("detail") or "API key could not be revoked."}, status)
    return _json({"ok": True, "revoked": True})


def _developer_webhook_admin_context(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return None, denied or _json({"detail": "Unauthorized"}, 401)
    if not _developer_api_entitled(ctx):
        return None, _json({"detail": "Developer API access is not active for this account."}, 403)
    try:
        team_service.require_admin(ctx)
    except TeamError as exc:
        return None, _team_error(exc)
    return ctx, None


async def developer_webhooks_get(request: Request) -> JSONResponse:
    ctx, denied = _developer_webhook_admin_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        store = get_store()
        rows, deliveries = await run_in_threadpool(
            lambda: (
                store.list_developer_webhooks(ctx["workspace_id"]),
                store.list_developer_webhook_deliveries(ctx["workspace_id"], limit=50),
            )
        )
    except Exception as exc:  # noqa: BLE001
        logging.warning("developer_webhooks_load_failed exception=%s", type(exc).__name__)
        return _json({"detail": "Webhook settings are temporarily unavailable."}, 503)
    return JSONResponse(
        {
            "ok": True,
            "encryption_configured": developer_webhooks.encryption_key_configured(),
            "allowed_event_types": developer_webhooks.allowed_event_types(),
            "webhooks": [developer_webhooks.public_webhook(row) for row in rows],
            "deliveries": deliveries,
        },
        headers={"Cache-Control": "no-store"},
    )


async def developer_webhooks_post(request: Request) -> JSONResponse:
    ctx, denied = _developer_webhook_admin_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if not developer_webhooks.encryption_key_configured():
        return _json({"detail": "Webhook encryption is not configured on the Cadivor API service."}, 503)
    body, bad = await _read_json_object(request)
    if bad is not None or body is None:
        return bad or _json({"detail": "Invalid JSON"}, 400)
    try:
        prepared, signing_secret = developer_webhooks.prepare_webhook(
            workspace_id=ctx["workspace_id"],
            created_by=ctx["user_id"],
            name=str(body.get("name") or ""),
            url=str(body.get("url") or ""),
            event_types=body.get("event_types"),
        )
    except developer_webhooks.DeveloperWebhookError as exc:
        return _json({"detail": str(exc)}, 400 if "not configured" not in str(exc).lower() else 503)
    try:
        saved = await run_in_threadpool(get_store().create_developer_webhook, prepared)
    except Exception as exc:  # noqa: BLE001
        logging.warning("developer_webhook_create_failed exception=%s", type(exc).__name__)
        return _json({"detail": "Webhook could not be saved."}, 503)
    return JSONResponse(
        {"ok": True, "webhook": developer_webhooks.public_webhook(saved), "signing_secret": signing_secret},
        status_code=201,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


async def developer_webhook_delete(request: Request) -> JSONResponse:
    ctx, denied = _developer_webhook_admin_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    webhook_id = str(request.path_params.get("webhook_id") or "").strip()
    try:
        removed = await run_in_threadpool(
            get_store().delete_developer_webhook, ctx["workspace_id"], webhook_id
        )
    except Exception as exc:  # noqa: BLE001
        logging.warning("developer_webhook_delete_failed exception=%s", type(exc).__name__)
        return _json({"detail": "Webhook could not be removed."}, 503)
    if not removed:
        return _json({"detail": "Webhook not found."}, 404)
    return _json({"ok": True, "removed": True})


async def developer_webhook_test_post(request: Request) -> JSONResponse:
    ctx, denied = _developer_webhook_admin_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    webhook_id = str(request.path_params.get("webhook_id") or "").strip()
    store = get_store()
    try:
        hook = await run_in_threadpool(
            store.get_developer_webhook, ctx["workspace_id"], webhook_id
        )
        if not hook or hook.get("active") is not True:
            return _json({"detail": "Webhook not found."}, 404)
        queued = await run_in_threadpool(
            developer_webhooks.queue_event,
            store,
            workspace_id=ctx["workspace_id"],
            webhook_id=webhook_id,
            event_type="webhook.test",
            data={"message": "Cadivor webhook test delivery."},
        )
        if not queued.get("queued"):
            return _json({"detail": "The test delivery could not be queued."}, 409)
        delivery_counts = await run_in_threadpool(
            developer_webhooks.dispatch_due, store,
            workspace_id=ctx["workspace_id"], webhook_id=webhook_id, limit=20,
        )
        delivery = await run_in_threadpool(
            store.get_developer_webhook_delivery,
            ctx["workspace_id"], webhook_id, queued["event_id"],
        )
    except developer_webhooks.DeveloperWebhookError as exc:
        return _json({"detail": str(exc)}, 400)
    except Exception as exc:  # noqa: BLE001
        logging.warning("developer_webhook_test_failed exception=%s", type(exc).__name__)
        return _json({"detail": "Webhook test could not be delivered."}, 503)
    return _json({
        "ok": True,
        "delivery": delivery or {},
        "dispatch": delivery_counts,
    })


@offload_sync_handler
def _developer_api_key_context(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    authorization = str(request.headers.get("authorization") or "")
    candidate = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    api_key = candidate or str(request.headers.get("x-api-key") or "").strip()
    if not api_key or not api_key.startswith("cdv_live_"):
        return None, _json({"detail": "A valid Cadivor API key is required."}, 401)
    try:
        result, status = subscription_billing_service.request_public_action(
            action="developer_api_key_resolve",
            payload={"api_key": api_key},
            timeout_seconds=5,
        )
    except subscription_billing_service.SubscriptionBillingError:
        return None, _json({"detail": "Developer API authentication is temporarily unavailable."}, 503)
    if status != 200 or result.get("ok") is not True:
        code = status if status in {401, 403} else 503
        return None, _json({"detail": result.get("detail") or "API key could not be verified."}, code)
    user_id = str(result.get("user_id") or "").strip()
    workspace_id = str(result.get("workspace_id") or "").strip()
    key_id = str(result.get("key_id") or "").strip()
    if not user_id or not workspace_id or not key_id:
        return None, _json({"detail": "API key could not be verified."}, 401)
    try:
        membership = get_auth_store().membership_for_user_workspace(user_id, workspace_id)
    except Exception:  # noqa: BLE001
        return None, _json({"detail": "Workspace access could not be checked."}, 503)
    if not membership:
        return None, _json({"detail": "This API key no longer has active workspace access."}, 403)
    if _throttled(request, "developer-api", limit=180, window=60, identity=key_id):
        return None, _json({"detail": "API request rate limit reached. Retry shortly."}, 429)
    credits = result.get("usage_credits")
    ctx: dict[str, Any] = {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "key_id": key_id,
        "plan": str(result.get("plan") or "Subscription inactive"),
        "trial_status": result.get("trial_status"),
        "api_access_addon_active": result.get("api_access_addon_active") is True,
        "monitored_parts_addon_capacity": (
            max(0, min(100_000, int(result.get("monitored_parts_addon_capacity") or 0)))
            if isinstance(result.get("monitored_parts_addon_capacity", 0), (int, float))
            and not isinstance(result.get("monitored_parts_addon_capacity", 0), bool)
            else 0
        ),
        "usage_credits": credits if isinstance(credits, dict) else {},
    }
    ctx["entitlement_overrides"] = plan_limits.account_feature_overrides(user_id)
    return ctx, None


async def developer_api_reports_get(request: Request) -> JSONResponse:
    ctx, denied = await _developer_api_key_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        limit = int(request.query_params.get("limit") or 25)
    except ValueError:
        limit = 25
    if limit < 1 or limit > 100:
        return _json({"detail": "limit must be between 1 and 100."}, 400)
    try:
        offset = int(request.query_params.get("offset") or 0)
    except ValueError:
        offset = 0
    if offset < 0 or offset > 100_000:
        return _json({"detail": "offset must be between 0 and 100000."}, 400)
    try:
        rows = customer_visible_analyses(
            list_reports(workspace_id=ctx["workspace_id"]),
            production=is_production_runtime(),
        )
    except PersistenceNotConfiguredError:
        return _json({"detail": "Report storage is unavailable."}, 503)
    summaries = [
        {
            key: row.get(key)
            for key in (
                "id", "analysis_id", "created_at", "project_name", "bom_name",
                "revision", "total_parts", "health_score", "health_status",
                "high_risk_count", "medium_risk_count", "low_risk_count", "mode",
            )
            if key in row
        }
        for row in rows[offset : offset + limit]
    ]
    next_offset = offset + len(summaries)
    return _json({
        "ok": True,
        "reports": summaries,
        "limit": limit,
        "offset": offset,
        "total": len(rows),
        "next_offset": next_offset if next_offset < len(rows) else None,
    })


async def developer_api_report_get(request: Request) -> JSONResponse:
    ctx, denied = await _developer_api_key_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = str(request.path_params.get("analysis_id") or "").strip()
    try:
        report = _get_visible_report(analysis_id, workspace_id=ctx["workspace_id"])
    except (WorkspaceAccessError, PersistenceNotConfiguredError):
        report = None
    if not report:
        return _json({"detail": "Report not found."}, 404)
    return JSONResponse(
        {"ok": True, "report": annotate_report_parts(report)},
        headers={"Cache-Control": "no-store"},
    )


async def developer_api_release_gate_get(request: Request) -> JSONResponse:
    """Return an advisory release review for one saved report and its decisions."""
    ctx, denied = await _developer_api_key_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = str(request.path_params.get("analysis_id") or "").strip()
    if not analysis_id or len(analysis_id) > 160:
        return _json({"detail": "A valid saved analysis_id is required."}, 400)

    try:
        report = _get_visible_report(analysis_id, workspace_id=ctx["workspace_id"])
    except PersistenceNotConfiguredError:
        return _json({"detail": "Report storage is unavailable."}, 503)
    except WorkspaceAccessError:
        report = None
    if not report:
        return _json({"detail": "Report not found."}, 404)

    try:
        from src.normalizer import normalize_part_number

        report = annotate_report_parts(report)
        store = get_store()
        records = await run_in_threadpool(
            store.list_decision_records,
            workspace_id=ctx["workspace_id"],
            analysis_id=analysis_id,
        )
        approvals_by_record: dict[str, list[str]] = {}
        for approval_status in ("pending", "approved", "rejected"):
            approvals = await run_in_threadpool(
                store.list_decision_record_approvers,
                workspace_id=ctx["workspace_id"],
                status=approval_status,
            )
            for approval in approvals:
                record_id = str(approval.get("decision_record_id") or "").strip()
                if record_id:
                    statuses = approvals_by_record.setdefault(record_id, [])
                    status = str(approval.get("status") or approval_status).strip().lower()
                    if status and status not in statuses:
                        statuses.append(status)
    except PersistenceNotConfiguredError:
        return _json({"detail": "Decision storage is unavailable."}, 503)
    except Exception as exc:  # noqa: BLE001
        logging.warning("developer_api_release_gate_failed exception=%s", type(exc).__name__)
        return _json({"detail": "Release review is temporarily unavailable."}, 503)

    def normalized_mpn(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            return str(normalize_part_number(text) or "").casefold()
        except Exception:  # noqa: BLE001
            return text.casefold()

    records_by_source_part: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        source_part_key = normalized_mpn(record.get("part_a"))
        if not source_part_key:
            continue
        record_id = str(record.get("id") or record.get("decision_id") or "").strip()
        records_by_source_part.setdefault(source_part_key, []).append({
            "id": record_id,
            "decision": str(record.get("decision") or ""),
            "decision_label": str(record.get("decision_label") or ""),
            "reviewer": str(record.get("reviewer") or ""),
            "created_at": record.get("created_at"),
            "validation_checks": [
                str(item) for item in (record.get("validation_checks") or [])
                if isinstance(item, str)
            ],
            "follow_up_action": str(record.get("follow_up_action") or ""),
            "follow_up_owner": str(record.get("follow_up_owner") or ""),
            "follow_up_due_date": record.get("follow_up_due_date"),
            "approver_statuses": approvals_by_record.get(record_id, []),
        })

    review_findings: list[dict[str, Any]] = []
    missing_decisions: list[dict[str, Any]] = []
    pending_approval_record_ids: set[str] = set()
    for part in report.get("parts") or []:
        if not isinstance(part, dict):
            continue
        risk_level = str(part.get("risk_level") or part.get("Risk Level") or "Needs verification").strip()
        normalized_risk = risk_level.casefold()
        if normalized_risk not in {"high", "critical", "needs verification", "unknown", "not assessed"}:
            continue
        mpn = ""
        for key in (
            "manufacturer_part_number", "Manufacturer Part Number", "MPN", "mpn",
            "Mfr Part Number", "Mfr. Part Number", "Part Number", "part_number",
        ):
            value = part.get(key)
            if value is not None and str(value).strip():
                mpn = str(value).strip()
                break
        part_records = records_by_source_part.get(normalized_mpn(mpn), []) if mpn else []
        if not part_records:
            missing_decisions.append({
                "mpn": mpn or None,
                "risk_level": risk_level,
                "reason": "No decision record is linked to this part in the selected saved report.",
            })
        for record in part_records:
            if "pending" in record["approver_statuses"] and record["id"]:
                pending_approval_record_ids.add(record["id"])
        review_findings.append({
            "mpn": mpn or None,
            "manufacturer": str(part.get("manufacturer") or part.get("Manufacturer") or ""),
            "risk_level": risk_level,
            "risk_reasons": [
                str(item) for item in (part.get("risk_reasons") or [])
                if isinstance(item, str)
            ],
            "decision_records": part_records,
            "decision_record_missing": not bool(part_records),
        })

    needs_verification_count = sum(
        1 for finding in review_findings
        if str(finding.get("risk_level") or "").casefold() in {"needs verification", "unknown", "not assessed"}
    )
    status = "review_required" if review_findings else "no_high_or_unverified_findings"
    return _json({
        "ok": True,
        "analysis_id": analysis_id,
        "status": status,
        "advisory_only": True,
        "release_authorized": False,
        "report": {
            "project_name": report.get("project_name"),
            "bom_name": report.get("bom_name") or report.get("filename"),
            "revision": report.get("revision"),
            "created_at": report.get("created_at"),
            "mode": report.get("mode"),
            "total_parts": report.get("total_parts") or len(report.get("parts") or []),
        },
        "summary": {
            "high_risk_count": report.get("high_risk_count", 0),
            "medium_risk_count": report.get("medium_risk_count", 0),
            "needs_verification_count": needs_verification_count,
            "review_finding_count": len(review_findings),
            "missing_decision_record_count": len(missing_decisions),
            "pending_approval_record_count": len(pending_approval_record_ids),
        },
        "review_findings": review_findings,
        "missing_decision_records": missing_decisions,
        "data_note": (
            "This check uses the selected saved report and its linked decision records. "
            "It does not refresh supplier data, block an Altium export, or authorize product release."
        ),
    }, 200)


@offload_sync_handler
def billing_portal_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    try:
        result, status = subscription_billing_service.request_action(
            access_token=token,
            action="portal",
            origin=request.headers.get("origin", ""),
        )
    except subscription_billing_service.SubscriptionBillingError as exc:
        return _json({"ok": False, "detail": str(exc)}, 503)
    return _json(result, status)


async def billing_checkout_prep_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    result = billing_prep.prepare_checkout_intent(
        workspace_id=ctx["workspace_id"],
        plan_token=str(body.get("plan") or body.get("plan_token") or ""),
        user_id=ctx["user_id"],
    )
    status = 200 if result.get("ok") else 409
    return _json(result, status)


@offload_sync_handler
def billing_public_catalog_get(request: Request) -> JSONResponse:
    """Expose only public plan prices for the marketing pricing page."""
    try:
        result, status = subscription_billing_service.request_public_catalog()
    except subscription_billing_service.SubscriptionBillingError:
        return _json({"ok": False, "detail": "Pricing is temporarily unavailable."}, 503)
    if status < 200 or status >= 300 or result.get("ok") is not True:
        return _json({"ok": False, "detail": "Pricing is temporarily unavailable."}, 503)

    raw_plans = result.get("plans")
    if not isinstance(raw_plans, list):
        return _json({"ok": False, "detail": "Pricing is temporarily unavailable."}, 503)
    plans = []
    for value in raw_plans:
        if not isinstance(value, dict):
            continue
        annual = value.get("annual") if isinstance(value.get("annual"), dict) else {}
        plans.append(
            {
                "name": str(value.get("name") or ""),
                "token": str(value.get("token") or ""),
                "enabled": value.get("enabled") is True,
                "amount": value.get("amount") if isinstance(value.get("amount"), int) else None,
                "currency": str(value.get("currency") or ""),
                "interval": str(value.get("interval") or ""),
                "annual": {
                    "enabled": annual.get("enabled") is True,
                    "amount": annual.get("amount") if isinstance(annual.get("amount"), int) else None,
                    "currency": str(annual.get("currency") or ""),
                    "interval": str(annual.get("interval") or ""),
                    "discount_percent": annual.get("discount_percent")
                    if isinstance(annual.get("discount_percent"), (int, float))
                    else None,
                },
            }
        )
    response = _json({"ok": True, "plans": plans}, 200)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@offload_sync_handler
def billing_public_addons_catalog_get(request: Request) -> JSONResponse:
    """Expose configured add-on amounts without Stripe identifiers."""
    try:
        result, status = subscription_billing_service.request_public_action(
            action="addons_catalog"
        )
    except subscription_billing_service.SubscriptionBillingError:
        return _json({"ok": False, "detail": "Usage pack pricing is temporarily unavailable."}, 503)
    if status < 200 or status >= 300 or result.get("ok") is not True:
        return _json({"ok": False, "detail": "Usage pack pricing is temporarily unavailable."}, 503)

    raw_addons = result.get("addons") if isinstance(result.get("addons"), dict) else {}
    addons: dict[str, dict[str, Any]] = {}
    analysis = raw_addons.get("bom_analysis") if isinstance(raw_addons.get("bom_analysis"), dict) else {}
    analysis_amount = analysis.get("amount")
    analysis_credits = analysis.get("credits")
    addons["bom_analysis"] = {
        "enabled": analysis.get("enabled") is True,
        "amount": analysis_amount if isinstance(analysis_amount, int) and not isinstance(analysis_amount, bool) else None,
        "currency": str(analysis.get("currency") or "").lower(),
        "credits": analysis_credits if isinstance(analysis_credits, int) and not isinstance(analysis_credits, bool) and analysis_credits > 0 else None,
        "interval": "one_time",
    }
    monitored = raw_addons.get("monitored_parts") if isinstance(raw_addons.get("monitored_parts"), dict) else {}
    monitored_capacity = monitored.get("capacity")
    addons["monitored_parts"] = {
        "enabled": monitored.get("enabled") is True,
        "capacity": monitored_capacity if isinstance(monitored_capacity, int) and not isinstance(monitored_capacity, bool) and monitored_capacity > 0 else None,
        "monthly": monitored.get("monthly") if isinstance(monitored.get("monthly"), dict) else {},
        "annual": monitored.get("annual") if isinstance(monitored.get("annual"), dict) else {},
    }
    response = _json({"ok": True, "addons": addons}, 200)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@offload_sync_handler
def one_time_report_status_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        result, status = one_time_report_service.request_action(
            access_token=request.headers.get("authorization", "").removeprefix("Bearer ").strip(),
            action="status",
        )
    except one_time_report_service.OneTimeReportServiceError as exc:
        return _json({"ok": False, "detail": str(exc)}, 503)
    return _json(result, status)


@offload_sync_handler
def one_time_report_checkout_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        result, status = one_time_report_service.request_action(
            access_token=request.headers.get("authorization", "").removeprefix("Bearer ").strip(),
            action="checkout",
        )
    except one_time_report_service.OneTimeReportServiceError as exc:
        return _json({"ok": False, "detail": str(exc)}, 503)
    return _json(result, status)


@offload_sync_handler
def connectors_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    return _json(connectors.connector_status_payload())


def _subscription_billing_readiness(
    *, access_token: str, origin: str = ""
) -> dict[str, Any]:
    """Report readiness from the Stripe integration the app actually uses.

    ``billing_prep`` only describes the unused migration checkout prototype.
    Settings plan changes and the billing portal route through the Supabase
    ``subscription-checkout`` Edge Function, so readiness must probe that path.
    """
    try:
        result, status_code = subscription_billing_service.request_action(
            access_token=access_token,
            action="status",
            origin=origin,
        )
    except subscription_billing_service.SubscriptionBillingError:
        return {
            "status": "unknown",
            "enabled": False,
            "gap": "Stripe billing status could not be reached.",
        }

    if status_code < 200 or status_code >= 300 or result.get("ok") is not True:
        return {
            "status": "unknown",
            "enabled": False,
            "gap": "Stripe billing status could not be verified.",
        }

    checkout_enabled = result.get("checkout_enabled") is True
    can_manage_billing = result.get("can_manage_billing") is True
    status = (
        "ready"
        if checkout_enabled
        else "partial"
        if can_manage_billing
        else "not_connected"
    )
    enabled_plans = sum(
        1
        for plan in (result.get("plans") or [])
        if isinstance(plan, dict) and plan.get("enabled") is True
    )
    return {
        "status": status,
        "enabled": checkout_enabled,
        "stripe_mode": result.get("stripe_mode"),
        "enabled_plan_count": enabled_plans,
        "can_manage_billing": can_manage_billing,
        "gap": None if checkout_enabled else result.get("gap"),
    }


@offload_sync_handler
def service_readiness_get(request: Request) -> JSONResponse:
    """Authenticated readiness for Settings: email, scheduler, connectors, billing.

    Status values reflect operational capability, not enable flags alone.
    Does not infer monitoring-email state from billing or plan-usage payloads.
    """
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        connector_payload = connectors.connector_status_payload()
        email = monitoring_store.monitoring_email_readiness()
        scheduler = monitoring_scheduler.scheduler_readiness()
        billing = _subscription_billing_readiness(
            access_token=request.headers.get("authorization", "").removeprefix("Bearer ").strip(),
            origin=request.headers.get("origin", ""),
        )
        # File workflows must not imply live design-tool/vendor readiness.
        live_ready_count = int(
            connector_payload.get("live_ready_count")
            or connector_payload.get("ready_count")
            or 0
        )
        blocked_count = int(connector_payload.get("blocked_count") or 0)
        file_workflow_count = int(connector_payload.get("file_workflow_count") or 0)
        connector_status = str(connector_payload.get("live_status") or "not_connected")
        if connector_status not in {"ready", "partial", "not_connected", "unknown"}:
            if live_ready_count > 0 and blocked_count == 0:
                connector_status = "ready"
            elif live_ready_count > 0:
                connector_status = "partial"
            else:
                connector_status = "not_connected"
        return _json(
            {
                "ok": True,
                "monitoring_email": email,
                "scheduler": scheduler,
                "connectors": {
                    "status": connector_status,
                    "ready_count": live_ready_count,
                    "live_ready_count": live_ready_count,
                    "file_workflow_count": file_workflow_count,
                    "blocked_count": blocked_count,
                    "configured_unverified_count": int(
                        connector_payload.get("configured_unverified_count") or 0
                    ),
                    "connectors": connector_payload.get("connectors") or [],
                    "gap": connector_payload.get("gap"),
                },
                "billing_checkout": billing,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).exception(
            "service_readiness_get failed: %s", type(exc).__name__
        )
        return _json(
            {
                "ok": False,
                "detail": "Service readiness could not be determined.",
                "monitoring_email": {"status": "unknown"},
                "scheduler": {"status": "unknown"},
                "connectors": {"status": "unknown"},
                "billing_checkout": {"status": "unknown"},
            },
            503,
        )


async def connectors_sync_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    connector_id = str(body.get("connector_id") or "plm.generic_bom_csv")
    rows = body.get("rows") if isinstance(body.get("rows"), list) else []
    result = connectors.sync_generic_bom_csv(rows, connector_id=connector_id)
    payload = {
        "ok": result.ok,
        "connector_id": result.connector_id,
        "mode": result.mode,
        "records": result.records,
        "gap": result.gap,
        "ran_at": result.ran_at,
        "workspace_id": ctx["workspace_id"],
    }
    return _json(payload, 200 if result.ok else 400)


@offload_sync_handler
def compliance_pack_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    pack_type = request.path_params.get("pack_type") or "rohs"
    analysis_id = request.query_params.get("analysis_id") or None
    try:
        report = migration_tools._require_analysis(analysis_id, workspace_id=ctx["workspace_id"])
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    if pack_type == "audit":
        return _json(compliance_packs.export_audit_bundle(report))
    return _json(compliance_packs.build_pack(report, pack_type))


def _visitor_header(request: Request) -> str:
    """Cloudflare Worker signed identity for anonymous public-audit rate limits."""
    for name, value in request.headers.items():
        if str(name).lower() == "x-cadivor-visitor":
            return str(value or "")
    return ""


@offload_sync_handler
def public_bom_stress_status(request: Request) -> JSONResponse:
    """Feature flag for the marketing free audit; optional bearer for QA verify.

    ``qa_verified`` is set only after server-side allowlist + confirmed-email
    checks. Query/body/client QA flags are ignored.
    """
    from src.public_bom_stress_test import (
        MAX_BYTES,
        MAX_ROWS,
        PREVIEW_ROWS,
        daily_enriched_row_limit,
        enabled,
        resolve_qa_session,
        turnstile_enabled,
    )

    # Never trust client qa flags — only Authorization → resolve_qa_session.
    qa = resolve_qa_session(_bearer_token(request) or None)
    return _json(
        {
            "ok": True,
            "enabled": bool(enabled()),
            "preview_rows": PREVIEW_ROWS,
            "max_rows": MAX_ROWS,
            "max_bytes": MAX_BYTES,
            "turnstile_required": bool(turnstile_enabled()),
            "qa_verified": bool(qa),
            "daily_enriched_row_limit": int(daily_enriched_row_limit()),
        }
    )


async def public_bom_stress_audit(request: Request) -> JSONResponse:
    """Check the small BOM and reveal only its top-five ranked preview."""
    from src.public_bom_stress_test import (
        MAX_BYTES,
        PUBLIC_BOM_BUDGET_MESSAGE,
        PUBLIC_BOM_LIMIT_MESSAGE,
        StressTestError,
        enabled,
        run_audit,
    )

    if not enabled():
        return _json(
            {"detail": "The free BOM stress test is being prepared. Please check back soon."},
            503,
        )
    try:
        form = await request.form(max_files=1, max_fields=12)
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid multipart upload."}, 400)
    upload = form.get("file")
    if upload is None or not callable(getattr(upload, "read", None)):
        return _json({"detail": "Missing file"}, 400)
    filename = str(getattr(upload, "filename", None) or "bom.csv")
    payload = await upload.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        return _json({"detail": "Upload a CSV or XLSX BOM smaller than 1 MB."}, 413)
    # Never authorize from client qa/email flags — only optional bearer for QA allowlist.
    turnstile_token = str(
        form.get("cf-turnstile-response")
        or form.get("turnstile_token")
        or ""
    ).strip() or None
    access_token = _bearer_token(request) or None
    remoteip = None
    forwarded = (request.headers.get("cf-connecting-ip") or "").strip()
    if forwarded:
        remoteip = forwarded.split(",")[0].strip()
    try:
        from functools import partial

        report = await run_in_threadpool(
            partial(
                run_audit,
                turnstile_token=turnstile_token,
                access_token=access_token,
                remoteip=remoteip,
            ),
            filename,
            payload,
            _visitor_header(request),
        )
    except StressTestError as exc:
        detail = str(exc)
        if detail in {PUBLIC_BOM_LIMIT_MESSAGE, PUBLIC_BOM_BUDGET_MESSAGE}:
            status = 429
        else:
            status = 400
        return _json({"detail": detail}, status)
    except Exception:  # noqa: BLE001
        logging.exception("public_bom_stress_audit_failed")
        return _json({"detail": "The audit could not be completed. Please try later."}, 503)
    return _json({"ok": True, **report})


async def public_bom_stress_lead(request: Request) -> JSONResponse:
    """Capture email + send verification link for the locked remaining rows."""
    from src.public_bom_stress_test import (
        StressTestError,
        enabled,
        lead_source_from_query,
        request_full_report,
    )

    if not enabled():
        return _json(
            {"detail": "The free BOM stress test is being prepared. Please check back soon."},
            503,
        )
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Invalid JSON"}, 400)
    if not body.get("accepted_terms"):
        return _json(
            {"detail": "Accept the Terms of Service and Privacy Policy to continue."},
            400,
        )
    report_id = str(body.get("report_id") or "").strip()
    email = str(body.get("email") or "").strip()
    if not report_id or not email:
        return _json({"detail": "Report id and email are required."}, 400)
    source = str(body.get("source") or "").strip()
    if not source:
        source = lead_source_from_query(request.query_params)
    try:
        address, verification_sent = await run_in_threadpool(
            request_full_report,
            report_id,
            email,
            _visitor_header(request),
            source=source,
        )
    except StressTestError as exc:
        return _json({"detail": str(exc)}, 400)
    except Exception:  # noqa: BLE001
        logging.exception("public_bom_stress_lead_failed")
        return _json({"detail": "Could not send the verification link. Please try again later."}, 503)
    return _json(
        {"ok": True, "email": address, "verification_sent": bool(verification_sent)}
    )


async def public_bom_stress_share_post(request: Request) -> JSONResponse:
    """Create a read-only aggregate share after verifying the audit visitor."""
    from src.public_bom_stress_test import StressTestError, create_summary_share, enabled

    if not enabled():
        return _json({"detail": "The public audit is temporarily unavailable."}, 503)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Invalid JSON"}, 400)
    report_id = str(body.get("report_id") or "").strip()
    if not report_id:
        return _json({"detail": "Audit id is required."}, 400)
    try:
        share = await run_in_threadpool(
            create_summary_share, report_id, _visitor_header(request)
        )
    except StressTestError as exc:
        return _json({"detail": str(exc)}, 404)
    except Exception:  # noqa: BLE001
        logging.exception("public_bom_stress_share_create_failed")
        return _json({"detail": "Could not create a share link."}, 503)
    return JSONResponse(
        {"ok": True, **share}, headers={"Cache-Control": "no-store"}
    )


async def public_bom_stress_share_get(request: Request) -> JSONResponse:
    """Return a sanitized audit summary for a non-expired share token."""
    from src.public_bom_stress_test import get_shared_summary

    token = str(request.path_params.get("token") or "").strip()
    try:
        summary = await run_in_threadpool(get_shared_summary, token)
    except Exception:  # noqa: BLE001
        logging.exception("public_bom_stress_share_resolve_failed")
        return _json({"detail": "Shared audit summary unavailable."}, 503)
    if not summary:
        return _json({"detail": "This audit share link is invalid or expired."}, 404)
    return JSONResponse(
        {"ok": True, "summary": summary}, headers={"Cache-Control": "no-store"}
    )


async def public_contact_post(request: Request) -> JSONResponse:
    """Persist a public contact/demo/student request and notify Cadivor."""
    throttle_identity = request.client.host if request.client else "unknown"
    signed_visitor = _visitor_header(request)
    if signed_visitor:
        try:
            from src.public_bom_stress_test import visitor_hash

            throttle_identity = visitor_hash(signed_visitor)
        except Exception:  # noqa: BLE001
            return _json({"detail": "Refresh the page and try again."}, 403)
    if _throttled(
        request,
        "public-contact",
        limit=5,
        window=600,
        identity=throttle_identity,
    ):
        return _json({"detail": "Too many requests. Please try again later."}, 429)

    try:
        content_length = int(request.headers.get("content-length") or "0")
    except ValueError:
        return _json({"detail": "Invalid request size."}, 400)
    if content_length > 16_384:
        return _json({"detail": "Request is too large."}, 413)
    raw = await request.body()
    if len(raw) > 16_384:
        return _json({"detail": "Request is too large."}, 413)
    try:
        body = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json({"detail": "Invalid JSON."}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Invalid request."}, 400)

    # Quietly accept honeypot hits so automated form fillers do not learn the
    # spam rule. The visitor still gets the standard confirmation state.
    if str(body.get("website") or "").strip():
        return _json({"ok": True, "received": True, "notification_status": "sent"}, 201)

    def field(name: str, limit: int, *, required: bool = False) -> str:
        value = str(body.get(name) or "").strip()
        if len(value) > limit:
            raise ValueError(f"{name}_too_long")
        if required and not value:
            raise ValueError(f"{name}_required")
        return value

    try:
        name = field("name", 120, required=True)
        email = field("email", 254, required=True).lower()
        company = field("company", 160)
        role = field("role", 120)
        team_size = field("team_size", 40)
        bom_volume = field("bom_volume", 60)
        plan_interest = field("plan_interest", 80)
        message = field("message", 4000, required=True)
        source = field("source", 80) or "marketing-site"
    except ValueError as exc:
        reason = str(exc)
        return _json({"detail": reason.replace("_", " ").capitalize() + "."}, 400)

    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return _json({"detail": "Enter a valid email address."}, 400)
    consent = body.get("consent")
    if consent is not True and str(consent or "").strip().lower() not in {"true", "on", "1"}:
        return _json(
            {"detail": "Please allow Cadivor to use these details to respond to your request."},
            400,
        )

    from src.email_routing import normalize_intent

    topic = normalize_intent(str(body.get("topic") or "general"))
    utm = sanitize_marketing_attribution(body.get("utm"))
    fields = {
        "name": name,
        "email": email,
        "company": company,
        "role": role,
        "team_size": team_size,
        "bom_volume": bom_volume,
        "plan_interest": plan_interest,
        "topic": topic,
        "message": message,
        "source": source,
        "utm": utm,
    }

    try:
        lead = await run_in_threadpool(marketing_leads.create_submission, fields)
    except PersistenceNotConfiguredError:
        return _json({"detail": "Contact requests are temporarily unavailable."}, 503)
    except marketing_leads.MarketingLeadError:
        logging.exception("public_contact_persistence_failed")
        return _json({"detail": "Contact requests are temporarily unavailable."}, 503)

    notification_status = "sent"
    try:
        from src.email_delivery import email_delivery_configured

        if not email_delivery_configured():
            notification_status = "not_configured"
        else:
            await run_in_threadpool(marketing_leads.send_contact_notification, lead)
    except Exception:  # noqa: BLE001
        notification_status = "failed"
        logging.warning("public_contact_notification_failed")
    try:
        await run_in_threadpool(
            marketing_leads.update_notification, str(lead["id"]), notification_status
        )
    except Exception:  # noqa: BLE001
        # The lead is already durable. Keep the user-facing success truthful
        # while allowing the team to find rows whose status is still pending.
        logging.warning("public_contact_notification_status_update_failed")

    status_code = 201 if notification_status == "sent" else 202
    return _json(
        {
            "ok": True,
            "received": True,
            "notification_status": notification_status,
        },
        status_code,
    )


async def public_marketing_analytics_post(request: Request) -> JSONResponse:
    """Store allowlisted first-party events without PII or BOM data."""
    throttle_identity = request.client.host if request.client else "unknown"
    signed_visitor = _visitor_header(request)
    if signed_visitor:
        try:
            from src.public_bom_stress_test import visitor_hash

            throttle_identity = visitor_hash(signed_visitor)
        except Exception:  # noqa: BLE001
            return _json({"ok": True, "accepted": False}, 202)
    if _throttled(
        request,
        "public-marketing-analytics",
        limit=180,
        window=60,
        identity=throttle_identity,
    ):
        return _json({"ok": True, "accepted": False}, 202)
    try:
        content_length = int(request.headers.get("content-length") or "0")
    except ValueError:
        return _json({"detail": "Invalid request size."}, 400)
    if content_length > 4096:
        return _json({"detail": "Request is too large."}, 413)
    raw = await request.body()
    if len(raw) > 4096:
        return _json({"detail": "Request is too large."}, 413)
    try:
        body = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json({"detail": "Invalid JSON."}, 400)
    if marketing_analytics.validate_event(body) is None:
        return _json({"detail": "Unsupported or invalid analytics event."}, 400)
    try:
        await run_in_threadpool(marketing_analytics.record_event, body)
    except PersistenceNotConfiguredError:
        logging.warning("marketing_analytics_storage_unavailable")
        return _json({"ok": False, "accepted": False}, 202)
    except marketing_analytics.MarketingAnalyticsError:
        logging.warning("marketing_analytics_event_not_stored")
        return _json({"ok": False, "accepted": False}, 202)
    return _json({"ok": True, "accepted": True}, 202)


async def marketing_analytics_admin_get(request: Request) -> JSONResponse:
    """Show aggregated funnel counts to verified platform admins only."""
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if ctx.get("platform_role") != "admin":
        return _json({"detail": "Platform administrator access is required."}, 403)
    try:
        days = int(request.query_params.get("days") or 30)
    except ValueError:
        days = 30
    try:
        return _json(await run_in_threadpool(marketing_analytics.get_store().summary, days))
    except PersistenceNotConfiguredError:
        return _json({"detail": "Marketing analytics storage is not configured."}, 503)
    except Exception:  # noqa: BLE001
        logging.exception("marketing_analytics_summary_failed")
        return _json({"detail": "Marketing analytics summary is unavailable."}, 503)


@offload_sync_handler
def runtime_maintenance_get(request: Request) -> JSONResponse:
    """Return the maintenance notice so signed-in users can see a branded screen."""
    ctx, denied = _auth_context(request, enforce_maintenance=False)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    return _json(
        {
            "maintenance_mode": bool(ctx.get("maintenance_mode")),
            "maintenance_message": str(ctx.get("maintenance_message") or ""),
            "is_admin": ctx.get("platform_role") == "admin",
            "planned_maintenance_message": str(
                ctx.get("planned_maintenance_message") or ""
            ),
            "planned_maintenance_starts_at": ctx.get(
                "planned_maintenance_starts_at"
            ),
            "planned_maintenance_ends_at": ctx.get(
                "planned_maintenance_ends_at"
            ),
        }
    )


async def public_service_status_get(request: Request) -> JSONResponse:
    """Return public maintenance notices for the sign-in screen."""
    if not _use_supabase_auth():
        return _json(
            {
                "maintenance_mode": False,
                "maintenance_message": "",
                "planned_maintenance_message": "",
                "planned_maintenance_starts_at": None,
                "planned_maintenance_ends_at": None,
            }
        )
    try:
        status = await run_in_threadpool(supabase_auth.public_service_status)
    except AuthNotConfiguredError:
        return _json({"detail": "Cadivor service status is temporarily unavailable."}, 503)
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    except Exception:  # noqa: BLE001
        logging.exception("public_service_status_failed")
        return _json({"detail": "Cadivor service status is temporarily unavailable."}, 503)
    return _json(status)


async def admin_platform_settings_get(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request, enforce_maintenance=False)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if ctx.get("platform_role") != "admin":
        return _json({"detail": "Platform administrator access is required."}, 403)
    if not _use_supabase_auth():
        return _json({"detail": "Platform settings require production Supabase Auth."}, 503)
    try:
        overview = await run_in_threadpool(
            supabase_auth.admin_platform_overview,
            str(ctx.get("access_token") or ""),
        )
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    except Exception:  # noqa: BLE001
        logging.exception("admin_platform_overview_failed")
        return _json({"detail": "Platform settings are temporarily unavailable."}, 503)
    return _json({"ok": True, "overview": overview})


async def admin_platform_maintenance_put(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request, enforce_maintenance=False)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if ctx.get("platform_role") != "admin":
        return _json({"detail": "Platform administrator access is required."}, 403)
    if not _use_supabase_auth():
        return _json({"detail": "Platform settings require production Supabase Auth."}, 503)
    body, bad = await _read_json_object(request)
    if bad is not None or body is None:
        return bad or _json({"detail": "Invalid JSON."}, 400)
    enabled = body.get("maintenance_mode")
    if not isinstance(enabled, bool):
        return _json({"detail": "Choose whether maintenance mode should be enabled."}, 400)
    message = str(body.get("maintenance_message") or "").strip()
    if len(message) > 280:
        return _json({"detail": "The maintenance message must be 280 characters or fewer."}, 400)
    if enabled and not message:
        return _json({"detail": "Add a customer message before enabling maintenance mode."}, 400)
    current_enabled = bool(ctx.get("maintenance_mode"))
    expected_confirmation = (
        ("ENABLE MAINTENANCE" if enabled else "DISABLE MAINTENANCE")
        if enabled != current_enabled
        else "UPDATE MAINTENANCE MESSAGE"
    )
    if str(body.get("confirmation") or "").strip() != expected_confirmation:
        return _json({"detail": f"Type {expected_confirmation} exactly to apply this change."}, 400)
    try:
        await run_in_threadpool(
            supabase_auth.admin_set_maintenance_mode,
            access_token=str(ctx.get("access_token") or ""),
            enabled=enabled,
            message=message,
        )
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    except Exception:  # noqa: BLE001
        logging.exception("admin_platform_maintenance_update_failed")
        return _json({"detail": "Cadivor could not update maintenance mode. No change was confirmed."}, 503)
    return _json(
        {
            "ok": True,
            "maintenance_mode": enabled,
            "maintenance_message": message
            or "Cadivor is undergoing scheduled maintenance. Please try again shortly.",
        }
    )


async def admin_platform_planned_maintenance_put(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request, enforce_maintenance=False)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if ctx.get("platform_role") != "admin":
        return _json({"detail": "Platform administrator access is required."}, 403)
    if not _use_supabase_auth():
        return _json({"detail": "Platform settings require production Supabase Auth."}, 503)
    body, bad = await _read_json_object(request)
    if bad is not None or body is None:
        return bad or _json({"detail": "Invalid JSON."}, 400)

    message = str(body.get("message") or "").strip()
    starts_at_raw = str(body.get("starts_at") or "").strip()
    ends_at_raw = str(body.get("ends_at") or "").strip()
    if len(message) > 280:
        return _json({"detail": "The notice must be 280 characters or fewer."}, 400)
    if bool(message) != bool(starts_at_raw) or bool(message) != bool(ends_at_raw):
        return _json(
            {"detail": "Enter a notice and both dates, or clear all three fields."},
            400,
        )

    def parse_notice_time(value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None

    starts_at = parse_notice_time(starts_at_raw)
    ends_at = parse_notice_time(ends_at_raw)
    if bool(starts_at_raw) and (starts_at is None or ends_at is None):
        return _json({"detail": "Enter valid start and end dates with a time zone."}, 400)
    if starts_at and ends_at and ends_at <= starts_at:
        return _json({"detail": "The end time must be after the start time."}, 400)

    try:
        await run_in_threadpool(
            supabase_auth.admin_set_planned_maintenance,
            access_token=str(ctx.get("access_token") or ""),
            message=message,
            starts_at=starts_at.isoformat() if starts_at else None,
            ends_at=ends_at.isoformat() if ends_at else None,
        )
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    except Exception:  # noqa: BLE001
        logging.exception("admin_platform_planned_maintenance_update_failed")
        return _json({"detail": "The planned maintenance notice could not be saved."}, 503)

    return _json(
        {
            "ok": True,
            "planned_maintenance_message": message,
            "planned_maintenance_starts_at": starts_at.isoformat() if starts_at else None,
            "planned_maintenance_ends_at": ends_at.isoformat() if ends_at else None,
        }
    )


async def account_entitlements_admin_get(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if ctx.get("platform_role") != "admin":
        return _json({"detail": "Platform administrator access is required."}, 403)
    try:
        email = team_service.normalize_email(request.query_params.get("email") or "")
    except TeamError as exc:
        return _team_error(exc)
    store = get_store()
    finder = getattr(store, "find_account_by_email", None)
    getter = getattr(store, "get_account_entitlement_overrides", None)
    if not callable(finder) or not callable(getter):
        return _json({"detail": "Account entitlement storage is unavailable."}, 503)
    try:
        account = await run_in_threadpool(finder, email)
        if not account:
            return _json({"detail": "Account not found."}, 404)
        overrides = await run_in_threadpool(getter, str(account["user_id"]))
    except Exception:  # noqa: BLE001
        logging.exception("account_entitlements_admin_read_failed")
        return _json({"detail": "Account entitlements are temporarily unavailable."}, 503)
    return _json({"ok": True, "account": {"email": account["email"], "feature_overrides": overrides}})


async def account_entitlements_admin_put(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if ctx.get("platform_role") != "admin":
        return _json({"detail": "Platform administrator access is required."}, 403)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Expected a JSON object."}, 400)
    try:
        email = team_service.normalize_email(str(body.get("email") or ""))
        feature_overrides = plan_limits.validated_feature_overrides(body.get("feature_overrides"))
    except TeamError as exc:
        return _team_error(exc)
    except ValueError as exc:
        return _json({"detail": str(exc)}, 400)
    store = get_store()
    finder = getattr(store, "find_account_by_email", None)
    setter = getattr(store, "set_account_entitlement_overrides", None)
    if not callable(finder) or not callable(setter):
        return _json({"detail": "Account entitlement storage is unavailable."}, 503)
    try:
        account = await run_in_threadpool(finder, email)
        if not account:
            return _json({"detail": "Account not found."}, 404)
        await run_in_threadpool(
            setter,
            user_id=str(account["user_id"]),
            feature_overrides=feature_overrides,
            updated_by=str(ctx["user_id"]),
        )
        if _use_supabase_auth():
            try:
                synced, sync_status = subscription_billing_service.request_action(
                    access_token=ctx["access_token"],
                    action="developer_api_access_override_sync",
                    payload={
                        "target_user_id": str(account["user_id"]),
                        "enabled": feature_overrides.get("api_access"),
                    },
                    timeout_seconds=8,
                )
            except subscription_billing_service.SubscriptionBillingError:
                return _json({"detail": "Feature overrides were saved, but API access could not be synchronized. Retry this save."}, 503)
            if sync_status != 200 or synced.get("synced") is not True:
                return _json({"detail": "Feature overrides were saved, but API access could not be synchronized. Retry this save."}, 503)
    except Exception:  # noqa: BLE001
        logging.exception("account_entitlements_admin_write_failed")
        return _json({"detail": "Account entitlements could not be saved."}, 503)
    return _json({"ok": True, "account": {"email": account["email"], "feature_overrides": feature_overrides}})


async def admin_users_get(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if ctx.get("platform_role") != "admin":
        return _json({"detail": "Platform administrator access is required."}, 403)
    try:
        users = await run_in_threadpool(
            supabase_auth.admin_list_accounts, str(ctx.get("access_token") or "")
        )
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    except Exception:  # noqa: BLE001
        logging.exception("admin_users_list_failed")
        return _json({"detail": "Account list is temporarily unavailable."}, 503)
    return _json({"ok": True, "users": users})


async def admin_user_profile_get(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if ctx.get("platform_role") != "admin":
        return _json({"detail": "Platform administrator access is required."}, 403)
    raw_user_id = str(request.path_params.get("target_user_id") or "").strip()
    try:
        target_user_id = str(uuid.UUID(raw_user_id))
    except (ValueError, TypeError):
        return _json({"detail": "Account was not found."}, 404)
    try:
        profile = await run_in_threadpool(
            lambda: supabase_auth.admin_get_account_profile(
                access_token=str(ctx.get("access_token") or ""),
                target_user_id=target_user_id,
            )
        )
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    except Exception:  # noqa: BLE001
        logging.exception("admin_user_profile_read_failed")
        return _json({"detail": "The user profile is temporarily unavailable."}, 503)
    return _json({"ok": True, "user": profile})


async def admin_user_billing_get(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if ctx.get("platform_role") != "admin":
        return _json({"detail": "Platform administrator access is required."}, 403)
    try:
        target_user_id = str(uuid.UUID(str(request.path_params.get("target_user_id") or "")))
    except (ValueError, TypeError):
        return _json({"detail": "Account was not found."}, 404)
    try:
        result, status = await run_in_threadpool(
            lambda: subscription_billing_service.request_action(
                access_token=str(ctx.get("access_token") or ""),
                action="admin_manual_plan_billing_list",
                payload={"target_user_id": target_user_id},
                timeout_seconds=12,
            )
        )
    except subscription_billing_service.SubscriptionBillingError:
        return _json({"detail": "Manual billing history is temporarily unavailable."}, 503)
    return _json(result, status)


async def admin_user_billing_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if ctx.get("platform_role") != "admin":
        return _json({"detail": "Platform administrator access is required."}, 403)
    try:
        target_user_id = str(uuid.UUID(str(request.path_params.get("target_user_id") or "")))
    except (ValueError, TypeError):
        return _json({"detail": "Account was not found."}, 404)
    body, bad = await _read_json_object(request)
    if bad is not None or body is None:
        return bad or _json({"detail": "Invalid JSON."}, 400)
    requested_action = str(body.get("action") or "").strip().lower()
    action_map = {
        "create_invoice": "admin_manual_plan_invoice_create",
        "send_invoice": "admin_manual_plan_invoice_send",
        "record_payment": "admin_manual_plan_payment_record",
        "void_invoice": "admin_manual_plan_invoice_void",
    }
    edge_action = action_map.get(requested_action)
    if not edge_action:
        return _json({"detail": "Choose a supported manual billing action."}, 400)
    payload: dict[str, Any] = {"target_user_id": target_user_id}
    if requested_action == "create_invoice":
        payload.update({
            "plan": body.get("plan"),
            "billing_interval": body.get("billing_interval"),
            "due_days": body.get("due_days", 30),
        })
    else:
        payload.update({
            "invoice_id": body.get("invoice_id"),
            **({
                "payment_method": body.get("payment_method"),
                "payment_reference": body.get("payment_reference", ""),
            } if requested_action == "record_payment" else {}),
        })
    try:
        result, status = await run_in_threadpool(
            lambda: subscription_billing_service.request_action(
                access_token=str(ctx.get("access_token") or ""),
                action=edge_action,
                payload=payload,
                timeout_seconds=45,
            )
        )
    except subscription_billing_service.SubscriptionBillingError:
        return _json({"detail": "Manual billing is temporarily unavailable. Check Stripe before retrying."}, 503)
    return _json(result, status)


async def admin_user_status_patch(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if ctx.get("platform_role") != "admin":
        return _json({"detail": "Platform administrator access is required."}, 403)
    raw_user_id = str(request.path_params.get("target_user_id") or "").strip()
    try:
        target_user_id = str(uuid.UUID(raw_user_id))
    except (ValueError, TypeError):
        return _json({"detail": "Account was not found."}, 404)
    body, bad = await _read_json_object(request)
    if bad is not None or body is None:
        return bad or _json({"detail": "Invalid JSON."}, 400)
    status = str(body.get("status") or "").strip().lower()
    if status not in {"active", "suspended"}:
        return _json({"detail": "Choose active or suspended."}, 400)
    reason = " ".join(str(body.get("reason") or "").split())[:500]
    if target_user_id == str(ctx.get("user_id") or ""):
        return _json({"detail": "Administrators cannot change their own account status."}, 409)
    try:
        await run_in_threadpool(
            lambda: supabase_auth.admin_set_account_status(
                access_token=str(ctx.get("access_token") or ""),
                target_user_id=target_user_id,
                status=status,
                reason=reason,
            )
        )
        sync_result, sync_status = await run_in_threadpool(
            lambda: subscription_billing_service.request_action(
                access_token=str(ctx.get("access_token") or ""),
                action="admin_sync_account_status",
                payload={"target_user_id": target_user_id, "status": status},
                timeout_seconds=12,
            )
        )
        if sync_status != 200 or sync_result.get("ok") is not True:
            return _json(
                {"detail": "Account status was saved, but sign-in controls did not sync. Retry this update."},
                503,
            )
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    except subscription_billing_service.SubscriptionBillingError:
        return _json(
            {"detail": "Account status was saved, but sign-in controls did not sync. Retry this update."},
            503,
        )
    except Exception:  # noqa: BLE001
        logging.exception("admin_user_status_update_failed")
        return _json({"detail": "Account status could not be updated."}, 503)
    return _json({"ok": True, "account_status": status})


async def admin_user_delete(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if ctx.get("platform_role") != "admin":
        return _json({"detail": "Platform administrator access is required."}, 403)
    raw_user_id = str(request.path_params.get("target_user_id") or "").strip()
    try:
        target_user_id = str(uuid.UUID(raw_user_id))
    except (ValueError, TypeError):
        return _json({"detail": "Account was not found."}, 404)
    if target_user_id == str(ctx.get("user_id") or ""):
        return _json({"detail": "Administrators cannot delete their own account."}, 409)
    body, bad = await _read_json_object(request)
    if bad is not None or body is None:
        return bad or _json({"detail": "Invalid JSON."}, 400)
    try:
        confirmation_email = team_service.normalize_email(
            str(body.get("confirmation_email") or "")
        )
    except TeamError as exc:
        return _team_error(exc)

    token = str(ctx.get("access_token") or "")
    payload = {
        "target_user_id": target_user_id,
        "confirmation_email": confirmation_email,
    }
    try:
        preflight, preflight_status = await run_in_threadpool(
            lambda: subscription_billing_service.request_action(
                access_token=token,
                action="admin_validate_account_deletion",
                payload=payload,
                timeout_seconds=12,
            )
        )
    except subscription_billing_service.SubscriptionBillingError:
        return _json({"detail": "Account deletion could not be validated. Try again shortly."}, 503)
    if preflight_status != 200 or preflight.get("ok") is not True:
        return _json(
            {"detail": str(preflight.get("detail") or "Account deletion could not be validated.")},
            preflight_status if 400 <= preflight_status < 600 else 503,
        )

    try:
        await run_in_threadpool(
            lambda: account_admin_service.validate_migration_account_data(
                user_id=target_user_id
            )
        )
    except account_admin_service.AccountAdminError as exc:
        return _json({"detail": exc.detail}, exc.status_code)

    try:
        prepared, prepare_status = await run_in_threadpool(
            lambda: subscription_billing_service.request_action(
                access_token=token,
                action="admin_prepare_account_deletion",
                payload=payload,
                timeout_seconds=25,
            )
        )
    except subscription_billing_service.SubscriptionBillingError:
        return _json({"detail": "Account deletion could not be prepared. Try again shortly."}, 503)
    if prepare_status != 200 or prepared.get("prepared") is not True:
        return _json(
            {"detail": str(prepared.get("detail") or "Account deletion could not be prepared.")},
            prepare_status if 400 <= prepare_status < 600 else 503,
        )

    try:
        migration_cleanup = await run_in_threadpool(
            lambda: account_admin_service.delete_migration_account_data(
                user_id=target_user_id,
                email=confirmation_email,
            )
        )
    except account_admin_service.AccountAdminError as exc:
        return _json(
            {
                "detail": (
                    exc.detail
                    + " The account is suspended with deletion pending; retry after resolving the workspace issue."
                )
            },
            exc.status_code,
        )

    try:
        deletion, deletion_status = await run_in_threadpool(
            lambda: subscription_billing_service.request_action(
                access_token=token,
                action="admin_delete_account",
                payload=payload,
                timeout_seconds=30,
            )
        )
    except subscription_billing_service.SubscriptionBillingError:
        logging.exception("admin_user_delete_bridge_failed")
        return _json(
            {
                "detail": (
                    "Private workspace data was cleaned, but account removal did not finish. "
                    "Retry the deletion to complete it."
                )
            },
            503,
        )
    if deletion_status != 200 or deletion.get("deleted") is not True:
        return _json(
            {
                "detail": (
                    "Private workspace data was cleaned, but account removal did not finish. "
                    + str(deletion.get("detail") or "Retry the deletion to complete it.")
                ),
                "cleanup": migration_cleanup,
            },
            deletion_status if 400 <= deletion_status < 600 else 503,
        )
    return _json({"ok": True, "deleted": True, "cleanup": migration_cleanup})




async def public_bom_stress_verified_get(request: Request) -> JSONResponse:
    """Return the full public audit only for the verified session email owner.

    Authorization uses the bearer JWT → Supabase user email (via
    ``verified_report``). Caller-supplied email query/body values are ignored.
    """
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    token = _bearer_token(request)
    # Explicitly ignore any client-supplied email; ownership is token-derived.
    _ = request.query_params.get("email")
    from src.public_bom_stress_test import normalize_stress_report_id, verified_report

    # Selector only — verified_report still requires the session email owns it.
    report_id = normalize_stress_report_id(request.query_params.get("report_id"))
    try:
        from functools import partial

        report = await run_in_threadpool(
            partial(verified_report, report_id=report_id), token
        )
    except Exception:  # noqa: BLE001
        logging.exception("public_bom_stress_verified_failed")
        return _json({"detail": "Verified public audit unavailable."}, 503)
    if not report:
        return _json({"detail": "Verified public audit not found."}, 404)
    return _json({"ok": True, "report": report})


async def public_bom_stress_complete_post(request: Request) -> JSONResponse:
    """Enrich remaining pending rows after confirmed email ownership."""
    from src.public_bom_stress_test import (
        PUBLIC_BOM_BUDGET_MESSAGE,
        PUBLIC_BOM_COMPLETE_IN_PROGRESS_MESSAGE,
        PUBLIC_BOM_EMAIL_QUOTA_MESSAGE,
        StressTestError,
        complete_audit,
        enabled,
        normalize_stress_report_id,
    )

    if not enabled():
        return _json(
            {"detail": "The free BOM stress test is being prepared. Please check back soon."},
            503,
        )
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    token = _bearer_token(request)
    body: dict[str, Any] = {}
    try:
        raw = await request.body()
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                body = parsed
    except Exception:  # noqa: BLE001
        body = {}
    # Ignore any client email/qa flags; ownership is bearer-derived inside complete_audit.
    _ = body.get("email")
    _ = body.get("qa")
    report_id = normalize_stress_report_id(
        body.get("report_id") or request.query_params.get("report_id")
    )
    try:
        report = await run_in_threadpool(complete_audit, token, report_id)
    except StressTestError as exc:
        detail = str(exc)
        if detail in {PUBLIC_BOM_EMAIL_QUOTA_MESSAGE, PUBLIC_BOM_BUDGET_MESSAGE}:
            return _json({"detail": detail}, 429)
        if detail == PUBLIC_BOM_COMPLETE_IN_PROGRESS_MESSAGE:
            return _json({"detail": detail}, 409)
        if "not found" in detail.lower():
            return _json({"detail": detail}, 404)
        return _json({"detail": detail}, 400)
    except Exception:  # noqa: BLE001
        logging.exception("public_bom_stress_complete_failed")
        return _json({"detail": "Could not finish the audit. Please try later."}, 503)
    return _json({"ok": True, "report": report})


async def public_bom_stress_verified_export_get(request: Request) -> Response:
    """CSV/XLSX download for an owned, fully enriched public audit."""
    from src.public_bom_stress_test import (
        StressTestError,
        enabled,
        export_verified_report,
        normalize_stress_report_id,
    )

    if not enabled():
        return _json(
            {"detail": "The free BOM stress test is being prepared. Please check back soon."},
            503,
        )
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    token = _bearer_token(request)
    _ = request.query_params.get("email")
    report_id = normalize_stress_report_id(request.query_params.get("report_id"))
    fmt = str(request.query_params.get("format") or "csv").strip().lower()
    try:
        from functools import partial

        body, media_type, filename = await run_in_threadpool(
            partial(export_verified_report, report_id=report_id, format=fmt),
            token,
        )
    except StressTestError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail.lower() else 400
        return _json({"detail": detail}, status)
    except Exception:  # noqa: BLE001
        logging.exception("public_bom_stress_export_failed")
        return _json({"detail": "Export unavailable."}, 503)
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


async def monitoring_refresh_post(request: Request) -> JSONResponse:
    """Explicit monitoring refresh (the only monitoring path that persists).

    Scope (never inferred silently):
    - ``analysis_id`` (+ optional ``part_number``): refresh that analysis / part
    - ``scope=portfolio``: clearly labeled workspace-wide refresh
    Mock delivery by default; supports ``dry_run=1`` (derive only, no writes,
    no email). Cron callers authenticate with ``x-cadivor-cron-token``.
    """
    cron_header = request.headers.get("x-cadivor-cron-token")
    cron_ok = monitoring_scheduler.authorize_cron(cron_header)
    ctx, denied = await _auth_context_async(request)
    if denied and not cron_ok:
        return denied or _json({"detail": "Unauthorized"}, 401)
    body: dict[str, Any] = {}
    try:
        raw = await request.body()
        if raw:
            parsed = json.loads(raw)
            body = parsed if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001
        body = {}

    def _param(name: str) -> str:
        return str(request.query_params.get(name) or body.get(name) or "").strip()

    if cron_ok:
        workspace_id = _param("workspace_id")
        if not workspace_id:
            return _json({"detail": "workspace_id required for cron refresh"}, 400)
    else:
        assert ctx is not None
        workspace_id = ctx["workspace_id"]
    analysis_id = _param("analysis_id") or None
    part_number = _param("part_number") or None
    portfolio = _param("scope").casefold() == "portfolio"
    dry_run = _param("dry_run").casefold() in {"1", "true", "yes"}
    if not portfolio and not analysis_id:
        return _json(
            {
                "detail": "analysis_id is required, or pass scope=portfolio for a "
                "workspace-wide refresh.",
            },
            400,
        )
    if portfolio and (analysis_id or part_number):
        return _json(
            {"detail": "scope=portfolio cannot be combined with analysis_id or part_number."},
            400,
        )
    try:
        return _json(
            monitoring_scheduler.run_workspace_refresh(
                workspace_id,
                analysis_id=analysis_id,
                part_number=part_number,
                portfolio=portfolio,
                dry_run=dry_run,
            )
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except ValueError as exc:
        return _json({"detail": str(exc)}, 400)


async def monitoring_live_refresh_post(request: Request) -> JSONResponse:
    """Explicit live supplier poll for one saved analysis or exact MPN."""
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"detail": "Invalid request"}, 400)
    analysis_id = str(body.get("analysis_id") or "").strip()
    part_number = str(body.get("part_number") or "").strip() or None
    if not analysis_id:
        return _json({"detail": "analysis_id is required for live supplier refresh"}, 400)
    result = monitoring_scheduler.run_live_analysis_refresh(
        ctx["workspace_id"], analysis_id, part_number=part_number
    )
    status = 200 if result.get("ok") else (404 if result.get("status") == "not_found" else 409)
    return _json(result, status)


async def monitoring_scheduled_post(request: Request) -> JSONResponse:
    """Accept a cron cycle quickly; supplier and email work runs in the background."""
    if not monitoring_scheduler.authorize_cron(
        request.headers.get("x-cadivor-cron-token")
    ):
        return _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    dry_run = isinstance(body, dict) and body.get("dry_run") is True
    if dry_run:
        result = await run_in_threadpool(
            monitoring_scheduler.run_scheduled_cycle, dry_run=True
        )
        return _json(result, 200 if result.get("ok") else 409)

    run_id = str(body.get("run_id") or uuid.uuid4()).strip()
    try:
        run = await run_in_threadpool(monitoring_store.begin_scheduled_run, run_id)
    except ValueError as exc:
        return _json({"detail": str(exc)}, 400)
    if run.get("busy"):
        return _json(
            {
                "ok": False,
                "status": "already_running",
                "active_run_id": run.get("id"),
            },
            409,
        )
    if not run.get("created"):
        status = str(run.get("status") or "failed")
        return _json(
            {
                "ok": status == "running" or status == "succeeded",
                "status": status,
                "run_id": run_id,
                "result": run.get("result") or {},
                "error": run.get("error"),
            },
            202 if status == "running" else 200,
        )
    return JSONResponse(
        {
            "ok": True,
            "status": "accepted",
            "run_id": run_id,
        },
        status_code=202,
        background=BackgroundTask(_execute_scheduled_monitoring_run, run_id),
    )


def _execute_scheduled_monitoring_run(run_id: str) -> None:
    """Run the slow supplier cycle off-request and persist an observable result."""
    try:
        result = monitoring_scheduler.run_scheduled_cycle(
            dry_run=False,
            progress_callback=lambda: monitoring_store.touch_scheduled_run(run_id)
        )
        if not result.get("ok"):
            status = "failed"
        elif result.get("failures"):
            status = "completed_with_failures"
        else:
            status = "succeeded"
        monitoring_store.finish_scheduled_run(run_id, status=status, result=result)
    except Exception as exc:  # noqa: BLE001
        logging.exception("scheduled_monitoring_cycle_failed", extra={"run_id": run_id})
        try:
            monitoring_store.finish_scheduled_run(
                run_id,
                status="failed",
                error="Scheduled supplier checks did not complete. See API logs for the run ID.",
            )
        except Exception:  # noqa: BLE001
            logging.exception("scheduled_monitoring_status_write_failed", extra={"run_id": run_id})


async def monitoring_scheduled_get(request: Request) -> JSONResponse:
    """Cron-only polling endpoint for a previously accepted scheduled cycle."""
    if not monitoring_scheduler.authorize_cron(
        request.headers.get("x-cadivor-cron-token")
    ):
        return _json({"detail": "Unauthorized"}, 401)
    run_id = str(request.path_params.get("run_id") or "").strip()
    run = await run_in_threadpool(monitoring_store.get_scheduled_run, run_id)
    if not run:
        return _json({"detail": "Monitoring run not found"}, 404)
    status = str(run.get("status") or "failed")
    return _json(
        {
            "ok": status == "succeeded",
            "status": status,
            "run_id": run_id,
            "result": run.get("result") or {},
            "error": run.get("error"),
            "started_at": run.get("started_at"),
            "updated_at": run.get("updated_at"),
            "finished_at": run.get("finished_at"),
        },
        200 if status != "running" else 202,
    )


def _team_error(exc: TeamError) -> JSONResponse:
    payload: dict[str, Any] = {"detail": exc.detail}
    if exc.code:
        payload["code"] = exc.code
    return _json(payload, exc.status_code)


@offload_sync_handler
def invitations_lookup_get(request: Request) -> JSONResponse:
    token = str(request.query_params.get("token") or "").strip()
    preview = team_service.lookup_invitation(token)
    if not preview:
        return _json({"detail": "This invitation is not valid or has expired."}, 404)
    return _json({"ok": True, **preview})


async def invitations_register_post(request: Request) -> JSONResponse:
    """Invite-only account creation (sandbox membership store).

    Public self-serve signup remains gated separately. This path never creates
    an empty personal workspace that bypasses the invitation.
    """
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
    token = str(body.get("token") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    preview = team_service.lookup_invitation(token)
    if not preview:
        return _json({"detail": "This invitation is not valid or has expired."}, 404)
    if email != str(preview["email"]).lower():
        return _json({"detail": "Use the email address this invitation was sent to."}, 400)
    if len(password) < 12:
        return _json({"detail": "Password must be at least 12 characters."}, 400)
    try:
        _record_legal_acceptance(
            email=email,
            source="invitation",
            workspace_name=str(preview.get("workspace_name") or "") or None,
            terms_version=str(body.get("terms_version") or "") or None,
            privacy_version=str(body.get("privacy_version") or "") or None,
        )
    except legal_acceptance.LegalAcceptanceError as exc:
        return _legal_acceptance_error(exc)
    if _use_supabase_auth():
        # Production: Supabase signup + verified login accepts pending invites.
        try:
            supabase_auth.signup(
                email,
                password,
                str(preview.get("workspace_name") or "Workspace"),
                captcha_token=str(body.get("captcha_token") or "") or None,
            )
        except AuthNotConfiguredError as exc:
            return _json({"detail": str(exc)}, 503)
        except AuthError as exc:
            return _json({"detail": exc.detail}, exc.status_code)
        return _json(
            {
                "ok": True,
                "email": email,
                "message": (
                    "If this address can be registered, a verification link will "
                    "arrive by email. After verifying, sign in to join the invited workspace."
                ),
                **legal_acceptance.published_versions(),
            },
            202,
        )
    from apps.api.sandbox_auth import get_auth_store

    store = get_auth_store()
    if not hasattr(store, "create_user_without_membership"):
        return _json({"detail": "Invite registration is unavailable."}, 503)
    try:
        user_id = store.create_user_without_membership(
            email=email, password=password, plan="Trial"
        )
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    try:
        accepted = team_service.accept_pending_invitations(
            user_id=user_id, email=email
        )
    except TeamError as exc:
        return _team_error(exc)
    if not accepted:
        return _json(
            {
                "detail": "Account created but the invitation could not be accepted.",
            },
            409,
        )
    return _json(
        {
            "ok": True,
            "email": email,
            "user_id": user_id,
            "accepted": accepted,
            "message": "Account created. Sign in with this email to open the invited workspace.",
            **legal_acceptance.published_versions(),
        }
    )


async def workspace_invitations_get(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(team_service.list_invitations(ctx))
    except TeamError as exc:
        return _team_error(exc)


async def workspace_invitations_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    try:
        result = team_service.create_invitation(
            ctx,
            email=str(body.get("email") or ""),
            role=str(body.get("role") or "engineer"),
            expires_in_days=body.get("expires_in_days"),
            web_origin=_web_origin(request),
        )
    except TeamError as exc:
        return _team_error(exc)
    return _json(result, 201)


@offload_sync_handler
def workspace_invitation_resend_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    invite_id = str(request.path_params.get("invite_id") or "")
    try:
        return _json(
            team_service.resend_invitation(
                ctx, invite_id, web_origin=_web_origin(request)
            )
        )
    except TeamError as exc:
        return _team_error(exc)


@offload_sync_handler
def workspace_invitation_cancel_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    invite_id = str(request.path_params.get("invite_id") or "")
    try:
        return _json(team_service.cancel_invitation(ctx, invite_id))
    except TeamError as exc:
        return _team_error(exc)


async def workspace_members_get(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(team_service.list_members(ctx))
    except TeamError as exc:
        return _team_error(exc)


async def workspace_activity_get(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        limit = int(request.query_params.get("limit") or 50)
    except ValueError:
        limit = 50
    try:
        return _json(team_service.list_activity(ctx, limit=limit))
    except TeamError as exc:
        return _team_error(exc)


async def workspace_activity_export_get(request: Request) -> Response:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        payload = await run_in_threadpool(team_service.export_activity_csv, ctx)
    except TeamError as exc:
        return _team_error(exc)
    except Exception:  # noqa: BLE001
        logging.exception("workspace_activity_export_failed")
        return _json({"detail": "Workspace activity export is unavailable."}, 503)
    return Response(
        payload,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="cadivor-workspace-activity.csv"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def workspace_settings_get(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(team_service.workspace_snapshot(ctx))
    except TeamError as exc:
        return _team_error(exc)


async def workspace_settings_patch(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    try:
        return _json(team_service.update_workspace_settings(ctx, body))
    except TeamError as exc:
        return _team_error(exc)


@offload_sync_handler
def workspaces_list_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(team_service.list_workspaces(ctx))
    except TeamError as exc:
        return _team_error(exc)


async def workspaces_create_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    try:
        return _json(
            team_service.create_workspace(ctx, str(body.get("name") or "")),
            201,
        )
    except TeamError as exc:
        return _team_error(exc)


async def workspaces_switch_post(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    try:
        return _json(
            team_service.switch_workspace(ctx, str(body.get("workspace_id") or ""))
        )
    except TeamError as exc:
        return _team_error(exc)


@offload_sync_handler
def settings_profile_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(team_service.get_profile(ctx))
    except TeamError as exc:
        return _team_error(exc)


async def settings_profile_patch(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    try:
        return _json(team_service.update_profile(ctx, body))
    except TeamError as exc:
        return _team_error(exc)


@offload_sync_handler
def settings_preferences_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(team_service.get_preferences(ctx))
    except TeamError as exc:
        return _team_error(exc)


async def settings_preferences_patch(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    try:
        return _json(team_service.update_preferences(ctx, body))
    except TeamError as exc:
        return _team_error(exc)


async def settings_security_get(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    supabase = _use_supabase_auth()
    if supabase:
        try:
            mfa = await run_in_threadpool(
                supabase_auth.mfa_status,
                str(ctx.get("access_token") or ""),
                str(ctx.get("user_id") or ""),
                force_refresh=True,
            )
        except AuthError as exc:
            return _json({"detail": exc.detail}, exc.status_code)
    else:
        mfa = {
            "status": "unavailable",
            "enabled": False,
            "label": "Authenticator apps are available with Supabase Auth.",
            "factors": [],
        }
    return _json(
        {
            "ok": True,
            "auth_mode": "supabase" if supabase else "sandbox",
            "password_change_available": supabase,
            "password_reset_available": supabase,
            "mfa": mfa,
            "sessions": {
                "status": "planned" if not supabase else "basic",
                "revoke_others_available": supabase,
            },
            "connected_accounts": {
                "email_password": True,
                "social_sso": {"status": "planned"},
            },
        }
    )


# --------------------------------------------------------------------------
# Invitations, workspaces, profile, preferences, security (Settings)
# --------------------------------------------------------------------------

_THROTTLE: dict[str, list[float]] = {}
_THROTTLE_LOCK = threading.Lock()


def _throttled(
    request: Request,
    bucket: str,
    *,
    limit: int = 10,
    window: int = 60,
    identity: str | None = None,
) -> bool:
    """Best-effort per-process throttle for unauthenticated routes."""
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    client = identity or forwarded or (request.client.host if request.client else "unknown")
    key = f"{bucket}:{client}"
    now = time.monotonic()
    with _THROTTLE_LOCK:
        hits = [t for t in _THROTTLE.get(key, []) if now - t < window]
        if len(hits) >= limit:
            _THROTTLE[key] = hits
            return True
        hits.append(now)
        _THROTTLE[key] = hits
        if len(_THROTTLE) > 2048:
            for stale in [k for k, v in _THROTTLE.items() if not v or now - v[-1] >= window]:
                _THROTTLE.pop(stale, None)
    return False


def _team_error(exc: TeamError) -> JSONResponse:
    payload: dict[str, Any] = {"detail": exc.detail}
    if exc.code:
        payload["code"] = exc.code
    return _json(payload, exc.status_code)


async def _read_json_object(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return None, _json({"detail": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return None, _json({"detail": "Expected a JSON object"}, 400)
    return body, None


async def _team_endpoint(
    request: Request,
    action: Any,
    *,
    body: bool = False,
    status_code: int = 200,
) -> JSONResponse:
    """Authenticate, run ``action(ctx, payload)`` off the event loop, map errors."""
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    payload: dict[str, Any] = {}
    if body:
        parsed, bad = await _read_json_object(request)
        if bad is not None or parsed is None:
            return bad or _json({"detail": "Invalid JSON"}, 400)
        payload = parsed
    try:
        result = await run_in_threadpool(action, ctx, payload)
    except TeamError as exc:
        return _team_error(exc)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    except AuthNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, **result}, status_code)


def _flat(key: str, value: dict[str, Any]) -> dict[str, Any]:
    """Nested under ``key`` and flattened, so simple clients can read fields directly."""
    return {key: value, **{k: v for k, v in value.items() if k != "ok"}}


def _bearer_token(request: Request) -> str:
    return (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()


async def auth_invitation_lookup(request: Request) -> JSONResponse:
    """Token-gated, read-only view used to pre-fill the invitation sign-up form."""
    if _throttled(request, "invite-lookup", limit=30):
        return _json({"detail": "Too many requests. Try again shortly."}, 429)
    token = str(request.query_params.get("token") or "")
    try:
        invitation = await run_in_threadpool(team_service.lookup_invitation, token)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    if invitation is None:
        return _json({"detail": "This invitation is not valid or has expired."}, 404)
    return _json(
        {
            "ok": True,
            "invitation": invitation,
            "signup_available": bool(
                _use_supabase_auth() and supabase_auth.supabase_auth_configured()
            ),
        }
    )


async def auth_invitation_signup(request: Request) -> JSONResponse:
    """Create an account for an invited address (email verification still required).

    Separate from the gated public self-serve ``/auth/signup``; this works only
    with a valid invitation token and never returns or creates a session.
    """
    if not _use_supabase_auth() or not supabase_auth.supabase_auth_configured():
        return _json({"detail": "Invitation account creation is not available"}, 503)
    if _throttled(request, "invite-signup", limit=5):
        return _json({"detail": "Too many requests. Try again shortly."}, 429)
    body, bad = await _read_json_object(request)
    if bad is not None or body is None:
        return bad or _json({"detail": "Invalid JSON"}, 400)
    if not _accepted_terms(body):
        return _json(
            {"detail": "Agree to the Terms of Service and Privacy Policy to continue."},
            400,
        )
    preview = team_service.lookup_invitation(str(body.get("token") or ""))
    if not preview:
        return _json({"detail": "This invitation is not valid or has expired."}, 404)
    invite_email = str(preview.get("email") or "").strip().lower()
    body_email = str(body.get("email") or "").strip().lower()
    if body_email and body_email != invite_email:
        return _json({"detail": "Use the email address this invitation was sent to."}, 400)
    try:
        _record_legal_acceptance(
            email=invite_email,
            source="invitation",
            workspace_name=str(preview.get("workspace_name") or "") or None,
            terms_version=str(body.get("terms_version") or "") or None,
            privacy_version=str(body.get("privacy_version") or "") or None,
        )
    except legal_acceptance.LegalAcceptanceError as exc:
        return _legal_acceptance_error(exc)
    redirect_to = supabase_auth.web_redirect_url(_web_origin(request), "/login", _origins)
    try:
        await run_in_threadpool(
            lambda: supabase_auth.signup_for_invitation(
                token=str(body.get("token") or ""),
                password=str(body.get("password") or ""),
                redirect_to=redirect_to,
                full_name=str(body.get("full_name") or "") or None,
                captcha_token=str(body.get("captcha_token") or "") or None,
            )
        )
    except AuthNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    return _json(
        {
            "accepted": True,
            "message": (
                "If this address can be registered, a verification link will arrive by email. "
                "Verify it, then sign in to join the workspace."
            ),
            **legal_acceptance.published_versions(),
        },
        202,
    )


async def auth_password_reset_request(request: Request) -> JSONResponse:
    if not _use_supabase_auth() or not supabase_auth.supabase_auth_configured():
        return _json({"detail": "Password reset is not available"}, 503)
    if _throttled(request, "password-reset", limit=5):
        return _json({"detail": "Too many requests. Try again shortly."}, 429)
    body, bad = await _read_json_object(request)
    if bad is not None or body is None:
        return bad or _json({"detail": "Invalid JSON"}, 400)
    redirect_to = supabase_auth.web_redirect_url(_web_origin(request), "/reset-password", _origins)
    try:
        await run_in_threadpool(
            lambda: supabase_auth.request_password_reset(
                str(body.get("email") or ""), redirect_to=redirect_to
            )
        )
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    except AuthNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json(
        {
            "accepted": True,
            "message": "If an account exists for this address, a reset link will arrive by email.",
        },
        202,
    )


async def auth_password_reset_complete(request: Request) -> JSONResponse:
    if not _use_supabase_auth() or not supabase_auth.supabase_auth_configured():
        return _json({"detail": "Password reset is not available"}, 503)
    if _throttled(request, "password-reset-complete", limit=10):
        return _json({"detail": "Too many requests. Try again shortly."}, 429)
    body, bad = await _read_json_object(request)
    if bad is not None or body is None:
        return bad or _json({"detail": "Invalid JSON"}, 400)
    try:
        await run_in_threadpool(
            lambda: supabase_auth.complete_password_reset(
                str(body.get("access_token") or ""), str(body.get("password") or "")
            )
        )
    except AuthNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    return _json({"ok": True, "message": "Your password was updated. Sign in with the new password."})


async def auth_password_change(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if not _use_supabase_auth():
        return _json({"detail": "Password changes are managed by Supabase Auth only"}, 409)
    body, bad = await _read_json_object(request)
    if bad is not None or body is None:
        return bad or _json({"detail": "Invalid JSON"}, 400)
    try:
        await run_in_threadpool(
            lambda: supabase_auth.change_password(
                _bearer_token(request),
                ctx["email"],
                str(body.get("current_password") or ""),
                str(body.get("new_password") or ""),
            )
        )
    except AuthNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    return _json({"ok": True, "message": "Your password was updated."})


async def auth_sessions_revoke_others(request: Request) -> JSONResponse:
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    if not _use_supabase_auth():
        return _json({"detail": "Session management is available with Supabase Auth only"}, 409)
    try:
        await run_in_threadpool(supabase_auth.revoke_other_sessions, _bearer_token(request))
    except AuthNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    return _json({"ok": True, "message": "Other devices were signed out."})


async def security_status_get(request: Request) -> JSONResponse:
    """Accurate account-security status; unavailable features are labelled."""
    ctx, denied = await _auth_context_async(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    managed = _use_supabase_auth()
    if managed:
        try:
            two_factor = await run_in_threadpool(
                supabase_auth.mfa_status,
                str(ctx.get("access_token") or ""),
                str(ctx.get("user_id") or ""),
                force_refresh=True,
            )
        except AuthError as exc:
            return _json({"detail": exc.detail}, exc.status_code)
    else:
        two_factor = {
            "status": "unavailable",
            "enabled": False,
            "label": "Authenticator apps are available with Supabase Auth.",
            "factors": [],
        }
    return _json(
        {
            "ok": True,
            "email": ctx["email"],
            "email_verified": True,
            "auth_provider": "supabase" if managed else "sandbox",
            "password": {
                "managed_by": "Supabase Auth" if managed else "Sandbox accounts",
                "change_available": managed,
                "reset_available": managed,
                "min_length": 12,
            },
            "two_factor": two_factor,
            "sessions": {
                "status": "available" if managed else "unavailable",
                "current_device": True,
                "revoke_others_available": managed,
                "device_list": "planned",
            },
            "connected_accounts": [
                {
                    "provider": "email",
                    "label": "Email and password",
                    "status": "connected",
                    "email": ctx["email"],
                }
            ],
            "single_sign_on": {"status": "planned", "label": "Planned - SSO is not available yet."},
        }
    )


async def invitations_accept_post(request: Request) -> JSONResponse:
    """Accept pending invitations addressed to the authenticated, verified email."""

    def _accept(ctx: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        accepted = team_service.accept_pending_invitations(
            user_id=ctx["user_id"], email=ctx["email"]
        )
        return {"accepted": accepted, "count": len(accepted)}

    return await _team_endpoint(request, _accept)


async def profile_get(request: Request) -> JSONResponse:
    return await _team_endpoint(
        request, lambda ctx, _: _flat("profile", team_service.get_profile(ctx))
    )


async def profile_patch(request: Request) -> JSONResponse:
    return await _team_endpoint(
        request,
        lambda ctx, body: _flat("profile", team_service.update_profile(ctx, body)),
        body=True,
    )


async def preferences_get(request: Request) -> JSONResponse:
    return await _team_endpoint(
        request, lambda ctx, _: _flat("preferences", team_service.get_preferences(ctx))
    )


async def preferences_patch(request: Request) -> JSONResponse:
    return await _team_endpoint(
        request,
        lambda ctx, body: _flat("preferences", team_service.update_preferences(ctx, body)),
        body=True,
    )


async def workspace_settings_get(request: Request) -> JSONResponse:
    return await _team_endpoint(
        request, lambda ctx, _: {"workspace": team_service.workspace_snapshot(ctx)}
    )


async def workspace_settings_patch(request: Request) -> JSONResponse:
    return await _team_endpoint(
        request,
        lambda ctx, body: {"workspace": team_service.update_workspace_settings(ctx, body)},
        body=True,
    )


async def workspaces_get(request: Request) -> JSONResponse:
    return await _team_endpoint(request, lambda ctx, _: team_service.list_workspaces(ctx))


async def workspaces_post(request: Request) -> JSONResponse:
    return await _team_endpoint(
        request,
        lambda ctx, body: {"workspace": team_service.create_workspace(ctx, str(body.get("name") or ""))},
        body=True,
        status_code=201,
    )


async def workspaces_active_post(request: Request) -> JSONResponse:
    return await _team_endpoint(
        request,
        lambda ctx, body: {
            "workspace": team_service.switch_workspace(ctx, str(body.get("workspace_id") or ""))
        },
        body=True,
    )


async def workspace_members_get(request: Request) -> JSONResponse:
    return await _team_endpoint(request, lambda ctx, _: team_service.list_members(ctx))


async def workspace_member_patch(request: Request) -> JSONResponse:
    user_id = str(request.path_params.get("user_id") or "")
    return await _team_endpoint(
        request,
        lambda ctx, body: {
            "member": team_service.update_member_role(ctx, user_id, str(body.get("role") or ""))
        },
        body=True,
    )


async def workspace_member_delete(request: Request) -> JSONResponse:
    user_id = str(request.path_params.get("user_id") or "")
    return await _team_endpoint(
        request, lambda ctx, _: {"member": team_service.remove_member(ctx, user_id)}
    )


async def workspace_invitations_get(request: Request) -> JSONResponse:
    return await _team_endpoint(request, lambda ctx, _: team_service.list_invitations(ctx))


async def workspace_invitations_post(request: Request) -> JSONResponse:
    origin = _web_origin(request)
    return await _team_endpoint(
        request,
        lambda ctx, body: team_service.create_invitation(
            ctx,
            email=str(body.get("email") or ""),
            role=str(body.get("role") or ""),
            expires_in_days=body.get("expires_in_days"),
            web_origin=origin,
        ),
        body=True,
        status_code=201,
    )


async def workspace_invitation_resend(request: Request) -> JSONResponse:
    invite_id = str(request.path_params.get("invite_id") or "")
    origin = _web_origin(request)
    # Body is optional (expiry refresh); tolerate an empty request.
    try:
        raw = await request.json()
    except Exception:  # noqa: BLE001
        raw = {}
    expires = raw.get("expires_in_days") if isinstance(raw, dict) else None
    return await _team_endpoint(
        request,
        lambda ctx, _: team_service.resend_invitation(
            ctx, invite_id, expires_in_days=expires, web_origin=origin
        ),
    )


async def workspace_invitation_cancel(request: Request) -> JSONResponse:
    invite_id = str(request.path_params.get("invite_id") or "")
    return await _team_endpoint(
        request, lambda ctx, _: team_service.cancel_invitation(ctx, invite_id)
    )


async def workspace_activity_get(request: Request) -> JSONResponse:
    try:
        limit = int(request.query_params.get("limit") or 50)
    except ValueError:
        limit = 50
    return await _team_endpoint(
        request, lambda ctx, _: team_service.list_activity(ctx, limit=limit)
    )



async def invitations_lookup_alias(request: Request) -> JSONResponse:
    response = await auth_invitation_lookup(request)
    if response.status_code != 200:
        return response
    payload = json.loads(response.body)
    return _json({**payload, **payload.get("invitation", {})})


async def invitations_register(request: Request) -> JSONResponse:
    """Create an account from an invitation.

    Supabase auth (production): creates an *unverified* Supabase user and asks
    them to verify email, then sign in (acceptance happens at verified sign-in).
    Sandbox auth (local/tests only): possession of the emailed token verifies
    the mailbox, so the account is created and the invitation accepted at once.
    """
    if _use_supabase_auth():
        return await auth_invitation_signup(request)
    if not sandbox_jwt_permitted():
        return _json({"detail": "Invitation account creation is not available"}, 503)
    if _throttled(request, "invite-register", limit=20):
        return _json({"detail": "Too many requests. Try again shortly."}, 429)
    body, bad = await _read_json_object(request)
    if bad is not None or body is None:
        return bad or _json({"detail": "Invalid JSON"}, 400)
    if not _accepted_terms(body):
        return _json(
            {"detail": "Agree to the Terms of Service and Privacy Policy to continue."},
            400,
        )
    token = str(body.get("token") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    preview = team_service.lookup_invitation(token)
    if not preview:
        return _json({"detail": "This invitation is not valid or has expired."}, 404)
    if email != str(preview["email"]).lower():
        return _json({"detail": "Use the email address this invitation was sent to."}, 400)
    try:
        _record_legal_acceptance(
            email=email,
            source="invitation",
            workspace_name=str(preview.get("workspace_name") or "") or None,
            terms_version=str(body.get("terms_version") or "") or None,
            privacy_version=str(body.get("privacy_version") or "") or None,
        )
    except legal_acceptance.LegalAcceptanceError as exc:
        return _legal_acceptance_error(exc)
    try:
        result = await run_in_threadpool(
            lambda: team_service.register_from_invitation_sandbox(
                token,
                email,
                str(body.get("password") or ""),
            )
        )
    except TeamError as exc:
        return _team_error(exc)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, **result, **legal_acceptance.published_versions()})


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/auth/config", auth_signup_config, methods=["GET"]),
        Route("/auth/signup", auth_signup, methods=["POST"]),
        Route("/auth/login", auth_login, methods=["POST"]),
        Route("/auth/login/complete", auth_login_complete, methods=["POST"]),
        Route("/auth/logout", auth_logout, methods=["POST"]),
        Route("/auth/me", auth_me, methods=["GET"]),
        Route("/auth/smoke-login", smoke_login, methods=["POST"]),
        Route("/auth/invitations/lookup", auth_invitation_lookup, methods=["GET"]),
        Route("/auth/invitations/signup", auth_invitation_signup, methods=["POST"]),
        Route("/auth/password-reset", auth_password_reset_request, methods=["POST"]),
        Route("/auth/password-reset/complete", auth_password_reset_complete, methods=["POST"]),
        Route("/auth/password", auth_password_change, methods=["POST"]),
        Route("/auth/sessions/revoke-others", auth_sessions_revoke_others, methods=["POST"]),
        Route("/security/status", security_status_get, methods=["GET"]),
        Route("/invitations/accept", invitations_accept_post, methods=["POST"]),
        Route("/invitations/lookup", invitations_lookup_alias, methods=["GET"]),
        Route("/invitations/register", invitations_register, methods=["POST"]),
        Route("/settings/profile", profile_get, methods=["GET"]),
        Route("/settings/profile", profile_patch, methods=["PATCH", "PUT"]),
        Route("/settings/preferences", preferences_get, methods=["GET"]),
        Route("/settings/preferences", preferences_patch, methods=["PATCH", "PUT"]),
        Route("/profile", profile_get, methods=["GET"]),
        Route("/profile", profile_patch, methods=["PATCH", "PUT"]),
        Route("/preferences", preferences_get, methods=["GET"]),
        Route("/preferences", preferences_patch, methods=["PATCH", "PUT"]),
        Route("/workspaces", workspaces_get, methods=["GET"]),
        Route("/workspaces", workspaces_post, methods=["POST"]),
        Route("/workspaces/active", workspaces_active_post, methods=["POST"]),
        Route("/workspace/settings", workspace_settings_get, methods=["GET"]),
        Route("/workspace/settings", workspace_settings_patch, methods=["PATCH", "PUT"]),
        Route("/workspace/members", workspace_members_get, methods=["GET"]),
        Route("/workspace/members/{user_id}", workspace_member_patch, methods=["PATCH"]),
        Route("/workspace/members/{user_id}", workspace_member_delete, methods=["DELETE"]),
        Route("/workspace/invitations", workspace_invitations_get, methods=["GET"]),
        Route("/workspace/invitations", workspace_invitations_post, methods=["POST"]),
        Route(
            "/workspace/invitations/{invite_id}/resend",
            workspace_invitation_resend,
            methods=["POST"],
        ),
        Route(
            "/workspace/invitations/{invite_id}",
            workspace_invitation_cancel,
            methods=["DELETE"],
        ),
        Route("/workspace/activity", workspace_activity_get, methods=["GET"]),
        Route("/workspace/activity/export.csv", workspace_activity_export_get, methods=["GET"]),
        # Compatibility aliases for the Next web client / sandbox tests.
        Route("/workspaces/switch", workspaces_switch_post, methods=["POST"]),
        Route(
            "/workspace/invitations/{invite_id}/cancel",
            workspace_invitation_cancel_post,
            methods=["POST"],
        ),
        Route("/settings/security", security_status_get, methods=["GET"]),
        Route("/boms/validate", boms_validate, methods=["POST"]),
        Route("/boms/analyze", boms_analyze, methods=["POST"]),
        Route("/reports", reports_list, methods=["GET"]),
        Route("/reports/{analysis_id}/export.csv", reports_csv_get, methods=["GET"]),
        Route("/reports/{analysis_id}/export/{file_format}", reports_export, methods=["GET"]),
        Route("/reports/{analysis_id}", reports_get, methods=["GET"]),
        Route("/reports/{analysis_id}", reports_delete, methods=["DELETE"]),
        Route("/projects", projects_list, methods=["GET"]),
        Route("/projects/{project_id}", projects_update, methods=["PATCH"]),
        Route("/projects/{project_id}", projects_delete, methods=["DELETE"]),
        Route("/boms/{bom_id}", boms_update, methods=["PATCH"]),
        Route("/boms/{bom_id}", boms_delete, methods=["DELETE"]),
        Route("/workspace/home", workspace_home, methods=["GET"]),
        Route("/workspace/priority-queue", workspace_priority_queue, methods=["GET"]),
        Route("/tools/monitoring", monitoring_get, methods=["GET"]),
        Route("/tools/compare-parts", compare_parts_post, methods=["POST"]),
        Route("/decision-records", decision_records_get, methods=["GET"]),
        Route("/decision-records/export/{template}", decision_records_export_get, methods=["GET"]),
        Route("/decision-records", decision_records_post, methods=["POST"]),
        Route("/decision-records/share", decision_record_share_post, methods=["POST"]),
        Route("/decision-records/share/{token}", decision_record_share_get, methods=["GET"]),
        Route("/decision-records/approvers", decision_record_approver_post, methods=["POST"]),
        Route("/decision-approvals/{token}", decision_record_approver_get, methods=["GET"]),
        Route("/decision-approvals/{token}/respond", decision_record_approver_respond, methods=["POST"]),
        Route("/tools/datasheet-qa", datasheet_qa_post, methods=["POST"]),
        Route("/tools/procurement", procurement_get, methods=["GET"]),
        Route("/tools/procurement/quotes", procurement_quotes_get, methods=["GET"]),
        Route("/tools/procurement/quotes", procurement_quotes_post, methods=["POST"]),
        Route("/tools/procurement/quotes/bulk", procurement_quotes_bulk_post, methods=["POST"]),
        Route("/tools/design-impact", design_impact_get, methods=["GET"]),
        Route("/tools/cost-optimization", cost_optimization_get, methods=["GET"]),
        Route("/tools/cost-optimization/decisions", cost_optimization_decisions, methods=["GET", "POST"]),
        Route("/tools/supply-risk", supply_risk_post, methods=["POST"]),
        Route("/tools/supply-risk/scenarios", supply_risk_scenarios, methods=["GET", "POST"]),
        Route("/tools/portfolio", portfolio_get, methods=["GET"]),
        Route("/tools/portfolio/recalculate-health", portfolio_health_recalculate_post, methods=["POST"]),
        Route("/tools/detailed-risk", detailed_risk_get, methods=["GET"]),
        Route("/tools/supplier-lookup", supplier_lookup_post, methods=["POST"]),
        Route("/tools/find-replacement", find_replacement_post, methods=["POST"]),
        Route("/tools/ask-cadivor", ask_cadivor_post, methods=["POST"]),
        Route("/tools/monitoring/preferences", monitoring_preferences_get, methods=["GET"]),
        Route("/tools/monitoring/preferences", monitoring_preferences_put, methods=["PUT"]),
        Route("/tools/monitoring/slack", monitoring_slack_get, methods=["GET"]),
        Route("/tools/monitoring/slack", monitoring_slack_put, methods=["PUT"]),
        Route("/tools/monitoring/alerts", monitoring_alerts_get, methods=["GET"]),
        Route("/tools/monitoring/acknowledge", monitoring_acknowledge_post, methods=["POST"]),
        Route("/tools/monitoring/notify", monitoring_notify_post, methods=["POST"]),
        Route("/tools/monitoring/refresh", monitoring_refresh_post, methods=["POST"]),
        Route("/tools/monitoring/live-refresh", monitoring_live_refresh_post, methods=["POST"]),
        Route("/tools/monitoring/scheduled-run", monitoring_scheduled_post, methods=["POST"]),
        Route("/tools/monitoring/scheduled-run/{run_id}", monitoring_scheduled_get, methods=["GET"]),
        Route("/billing/status", billing_status_get, methods=["GET"]),
        Route("/billing/checkout", billing_checkout_post, methods=["POST"]),
        Route("/billing/addons/professional-api/checkout", billing_professional_api_addon_checkout_post, methods=["POST"]),
        Route("/billing/addons/monitored-parts/checkout", billing_monitored_parts_addon_checkout_post, methods=["POST"]),
        Route("/billing/addons/monitored-parts/remove", billing_monitored_parts_addon_remove_post, methods=["POST"]),
        Route("/billing/addons/usage-overage/checkout", billing_usage_overage_checkout_post, methods=["POST"]),
        Route("/developer/api-keys", developer_api_keys_get, methods=["GET"]),
        Route("/developer/api-keys", developer_api_keys_post, methods=["POST"]),
        Route("/developer/api-keys/{key_id}", developer_api_key_delete, methods=["DELETE"]),
        Route("/developer/webhooks", developer_webhooks_get, methods=["GET"]),
        Route("/developer/webhooks", developer_webhooks_post, methods=["POST"]),
        Route("/developer/webhooks/{webhook_id}/test", developer_webhook_test_post, methods=["POST"]),
        Route("/developer/webhooks/{webhook_id}", developer_webhook_delete, methods=["DELETE"]),
        Route("/v1/analyses", developer_api_analyze_post, methods=["POST"]),
        Route("/v1/reports", developer_api_reports_get, methods=["GET"]),
        Route("/v1/reports/{analysis_id}", developer_api_report_get, methods=["GET"]),
        Route("/v1/release-gate/{analysis_id}", developer_api_release_gate_get, methods=["GET"]),
        Route("/billing/portal", billing_portal_post, methods=["POST"]),
        Route("/billing/public-catalog", billing_public_catalog_get, methods=["GET"]),
        Route("/billing/public-addons-catalog", billing_public_addons_catalog_get, methods=["GET"]),
        Route("/billing/checkout-prep", billing_checkout_prep_post, methods=["POST"]),
        Route("/billing/one-time-report", one_time_report_status_get, methods=["GET"]),
        Route("/billing/one-time-report/checkout", one_time_report_checkout_post, methods=["POST"]),
        Route("/plan/usage", plan_usage_get, methods=["GET"]),
        Route("/runtime/maintenance", runtime_maintenance_get, methods=["GET"]),
        Route("/public/service-status", public_service_status_get, methods=["GET"]),
        Route("/integrations/connectors", connectors_get, methods=["GET"]),
        Route("/integrations/connectors/sync", connectors_sync_post, methods=["POST"]),
        Route("/integrations/service-readiness", service_readiness_get, methods=["GET"]),
        Route("/compliance/{pack_type}", compliance_pack_get, methods=["GET"]),
        Route("/public/bom-stress/status", public_bom_stress_status, methods=["GET"]),
        Route("/public/bom-stress/audit", public_bom_stress_audit, methods=["POST"]),
        Route("/public/bom-stress/lead", public_bom_stress_lead, methods=["POST"]),
        Route("/public/bom-stress/share", public_bom_stress_share_post, methods=["POST"]),
        Route("/public/bom-stress/share/{token}", public_bom_stress_share_get, methods=["GET"]),
        Route("/public/contact", public_contact_post, methods=["POST"]),
        Route("/public/analytics", public_marketing_analytics_post, methods=["POST"]),
        Route("/admin/marketing-analytics", marketing_analytics_admin_get, methods=["GET"]),
        Route("/admin/platform-settings", admin_platform_settings_get, methods=["GET"]),
        Route("/admin/platform-settings/maintenance", admin_platform_maintenance_put, methods=["PUT"]),
        Route("/admin/platform-settings/planned-maintenance", admin_platform_planned_maintenance_put, methods=["PUT"]),
        Route("/admin/account-entitlements", account_entitlements_admin_get, methods=["GET"]),
        Route("/admin/account-entitlements", account_entitlements_admin_put, methods=["PUT"]),
        Route("/admin/users", admin_users_get, methods=["GET"]),
        Route("/admin/users/{target_user_id}", admin_user_profile_get, methods=["GET"]),
        Route("/admin/users/{target_user_id}/billing", admin_user_billing_get, methods=["GET"]),
        Route("/admin/users/{target_user_id}/billing", admin_user_billing_post, methods=["POST"]),
        Route("/admin/users/{target_user_id}", admin_user_status_patch, methods=["PATCH"]),
        Route("/admin/users/{target_user_id}", admin_user_delete, methods=["DELETE"]),
        Route(
            "/public/bom-stress/verified-report",
            public_bom_stress_verified_get,
            methods=["GET"],
        ),
        Route(
            "/public/bom-stress/complete",
            public_bom_stress_complete_post,
            methods=["POST"],
        ),
        Route(
            "/public/bom-stress/verified-report/export",
            public_bom_stress_verified_export_get,
            methods=["GET"],
        ),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=_origins or ["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ],
)
