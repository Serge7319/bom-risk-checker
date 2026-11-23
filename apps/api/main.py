Warning: truncated output (original token count: 58707)
Total output lines: 5555

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
    current_priority_items,
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


async def auth_logout(request: Request) -> JSONResponse:
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


async def auth_me(request: Request) -> JSONResponse:
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


async def smoke_login(request: Request) -> JSONResponse:
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
    ctx, denied = _auth_context(request)
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
    ctx, denied = _auth_context(request)
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
        # Backward compatible for callers that send only approved decisions.
        used_decision_ids = list(applied_decision_ids)
    if set(applied_decision_ids) - set(used_decision_ids):
        return _json({"detail": "Approved decisions must also be listed as applied candidates."}, 400)
    if (applied_decision_ids or used_decision_ids) and not derived_from_analysis_id:
        return _json({"detail": "Replacement decisions require a source BOM report."}, 400)
    if derived_from_analysis_id:
        source_report = _get_visible_report(
            derived_from_analysis_id, workspace_id=ctx["workspace_id"]
        )
        if not source_report:
            return _json({"detail": "Source BOM report not found"}, 404)
        if applied_decision_ids or used_decision_ids:
            source_decisions = get_store().list_decision_records(
                workspace_id=ctx["workspace_id"],
                analysis_id=derived_from_analysis_id,
            )
            decisions_by_id = {
                str(record.get("id") or record.get("decision_id") or ""): record
                for record in source_decisions
            }
            approved_by_id = {
                str(record.get("id") or record.get("decision_id") or ""): record
                for record in source_decisions
                if record.get("decision") == "approve_alternate"
            }
            if any(decision_id not in approved_by_id for decision_id in applied_decision_ids):
                return _json(
                    {"detail": "Only approved alternate decisions can be linked as approval evidence."},
                    400,
                )
            if any(
                decision_id not in decisions_by_id
                or decisions_by_id[decision_id].get("decision") == "reject_alternate"
                for decision_id in used_decision_ids
            ):
                return _json(
                    {"detail": "Only non-rejected replacement candidates from the source BOM can be applied."},
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
                candidate_mpn = str(decision.get("part_b") or "").strip().casefold()
                if not candidate_mpn or candidate_mpn not in revised_mpns or current_mpn in revised_mpns:
                    return _json(
                        {
                            "detail": (
                                "The new BOM must contain each approved replacement and remove its current part before the decision can be linked."
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
   …38707 tokens truncated…pted.",
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
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(team_service.list_invitations(ctx))
    except TeamError as exc:
        return _team_error(exc)


async def workspace_invitations_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
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


async def workspace_invitation_resend_post(request: Request) -> JSONResponse:
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


async def workspace_invitation_cancel_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    invite_id = str(request.path_params.get("invite_id") or "")
    try:
        return _json(team_service.cancel_invitation(ctx, invite_id))
    except TeamError as exc:
        return _team_error(exc)


async def workspace_members_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(team_service.list_members(ctx))
    except TeamError as exc:
        return _team_error(exc)


async def workspace_activity_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
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
    ctx, denied = _auth_context(request)
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
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(team_service.workspace_snapshot(ctx))
    except TeamError as exc:
        return _team_error(exc)


async def workspace_settings_patch(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
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


async def workspaces_list_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(team_service.list_workspaces(ctx))
    except TeamError as exc:
        return _team_error(exc)


async def workspaces_create_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
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
    ctx, denied = _auth_context(request)
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


async def settings_profile_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(team_service.get_profile(ctx))
    except TeamError as exc:
        return _team_error(exc)


async def settings_profile_patch(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
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


async def settings_preferences_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(team_service.get_preferences(ctx))
    except TeamError as exc:
        return _team_error(exc)


async def settings_preferences_patch(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
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
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    supabase = _use_supabase_auth()
    return _json(
        {
            "ok": True,
            "auth_mode": "supabase" if supabase else "sandbox",
            "password_change_available": supabase,
            "password_reset_available": supabase,
            "mfa": {"status": "planned", "enabled": False},
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
    ctx, denied = _auth_context(request)
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
    ctx, denied = _auth_context(request)
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
    ctx, denied = _auth_context(request)
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
    """Accurate account-security status; planned items are labelled, not faked."""
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    managed = _use_supabase_auth()
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
            "two_factor": {
                "status": "planned",
                "label": "Planned - two-factor authentication is not available yet.",
            },
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
        Route("/tools/design-impact", design_impact_get, methods=["GET"]),
        Route("/tools/cost-optimization", cost_optimization_get, methods=["GET"]),
        Route("/tools/supply-risk", supply_risk_post, methods=["POST"]),
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
        Route("/billing/portal", billing_portal_post, methods=["POST"]),
        Route("/billing/public-catalog", billing_public_catalog_get, methods=["GET"]),
        Route("/billing/checkout-prep", billing_checkout_prep_post, methods=["POST"]),
        Route("/billing/one-time-report", one_time_report_status_get, methods=["GET"]),
        Route("/billing/one-time-report/checkout", one_time_report_checkout_post, methods=["POST"]),
        Route("/plan/usage", plan_usage_get, methods=["GET"]),
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
        Route("/admin/account-entitlements", account_entitlements_admin_get, methods=["GET"]),
        Route("/admin/account-entitlements", account_entitlements_admin_put, methods=["PUT"]),
        Route("/admin/users", admin_users_get, methods=["GET"]),
        Route("/admin/users/{target_user_id}", admin_user_profile_get, methods=["GET"]),
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
