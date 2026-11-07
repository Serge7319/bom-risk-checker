"""Cadivor API for the Next.js application.

Production uses Supabase Auth, the established BOM/supplier analysis modules,
and a dedicated Railway Postgres workspace store. One-time report and monthly
subscription billing use Supabase Edge Functions with the existing Stripe setup.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
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
from apps.api.synthetic_analyze import (  # noqa: E402
    analyze_upload,
    delete_project as delete_project_record,
    delete_report,
    get_report,
    list_reports,
    parse_bom_bytes,
)
from apps.api.sandbox_auth import (  # noqa: E402
    AuthError,
    AuthNotConfiguredError,
    auth_configured as sandbox_auth_configured,
    describe_auth as describe_sandbox_auth,
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
from apps.api import connectors  # noqa: E402
from apps.api import monitoring_store  # noqa: E402
from apps.api import monitoring_scheduler  # noqa: E402
from apps.api import plan_limits  # noqa: E402
from apps.api import supplier_lookup  # noqa: E402
from apps.api import one_time_report_service  # noqa: E402
from apps.api import subscription_billing_service  # noqa: E402
from apps.api import team_service  # noqa: E402
from apps.api.team_service import TeamError  # noqa: E402
from apps.api.evidence_contract import annotate_report_parts  # noqa: E402
from apps.api.report_exports import (  # noqa: E402
    build_report_export,
    safe_download_stem,
)
from src.datasheet_comparison import MAX_DATASHEET_BYTES  # noqa: E402

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
    return ctx.as_dict(), None


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


async def auth_signup_config(_: Request) -> JSONResponse:
    """Expose public onboarding availability without exposing auth configuration."""
    enabled = bool(_use_supabase_auth() and supabase_auth.signup_enabled())
    return _json({"signup_enabled": enabled, "trial_length_days": supabase_auth.TRIAL_DAYS})


async def auth_signup(request: Request) -> JSONResponse:
    if not _use_supabase_auth() or not supabase_auth.signup_enabled():
        return _json({"detail": "Self-serve signup is not enabled"}, 503)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    try:
        supabase_auth.signup(
            str(body.get("email") or ""),
            str(body.get("password") or ""),
            str(body.get("workspace_name") or ""),
            captcha_token=str(body.get("captcha_token") or "") or None,
        )
    except AuthNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    except AuthError as exc:
        return _json({"detail": exc.detail}, exc.status_code)
    return _json(
        {
            "accepted": True,
            "message": "If this address can be registered, a verification link will arrive by email.",
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


async def boms_analyze(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    form = await request.form()
    upload = form.get("file")
    if upload is None:
        return _json({"detail": "Missing file"}, 400)
    filename = getattr(upload, "filename", None) or "bom.csv"
    payload = await upload.read()
    if not payload:
        return _json({"detail": "Empty file"}, 400)
    project_name = str(form.get("project_name") or "").strip() or None
    bom_name = str(form.get("bom_name") or "").strip() or None
    revision = str(form.get("revision") or "").strip() or None
    try:
        parsed_bom = parse_bom_bytes(filename, payload)
        part_numbers = parsed_bom.get("mpn_normalized", parsed_bom.get("mpn"))
        unique_part_count = len({str(value).strip().casefold() for value in part_numbers if str(value).strip()})
    except Exception as exc:  # noqa: BLE001
        return _json({"detail": str(exc)}, 400)

    analysis_id = str(uuid.uuid4())
    reserved_order_id = ""
    try:
        plan_limits.assert_analysis_allowed(
            workspace_id=ctx["workspace_id"],
            ctx=ctx,
            part_count=unique_part_count,
        )
    except plan_limits.PlanLimitError as exc:
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
        )
    except PersistenceNotConfiguredError as exc:
        if reserved_order_id:
            _release_one_time_credit_if_report_was_not_saved(
                access_token=access_token,
                order_id=reserved_order_id,
                analysis_id=analysis_id,
                workspace_id=ctx["workspace_id"],
            )
        return _json({"detail": str(exc)}, 503)
    except Exception as exc:  # noqa: BLE001
        if reserved_order_id:
            _release_one_time_credit_if_report_was_not_saved(
                access_token=access_token,
                order_id=reserved_order_id,
                analysis_id=analysis_id,
                workspace_id=ctx["workspace_id"],
            )
        return _json({"detail": str(exc)}, 400)

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
            "persisted": bool(report.get("persisted")),
            "has_hierarchy": bool(hierarchy.get("has_hierarchy")),
            "top_rolled_risk": top.get("rolled_risk_level"),
        }
    )


async def reports_list(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    persistence = describe_persistence()
    try:
        reports = list_reports(workspace_id=ctx["workspace_id"])
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    # Do not surface deployment service gaps (billing/email/connectors) as a
    # Reports warning card — those belong in Settings / health diagnostics.
    return _json(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "workspace_id": ctx["workspace_id"],
            "persistence": persistence["backend"],
            "gap": None,
            "reports": reports,
        }
    )


async def reports_delete(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = request.path_params["analysis_id"]
    try:
        deleted = delete_report(analysis_id, workspace_id=ctx["workspace_id"])
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    if not deleted:
        return _json({"detail": "Report not found"}, 404)
    return _json({"ok": True, "deleted": analysis_id, "workspace_id": ctx["workspace_id"]})


async def projects_list(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    persistence = describe_persistence()
    try:
        store = get_store()
        projects = store.list_projects(workspace_id=ctx["workspace_id"])
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "workspace_id": ctx["workspace_id"],
            "persistence": persistence["backend"],
            "projects": projects,
        }
    )


async def projects_update(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
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


async def projects_delete(request: Request) -> JSONResponse:
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


async def workspace_home(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        return _json(get_store().home_dashboard(workspace_id=ctx["workspace_id"]))
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)


async def reports_csv_get(request: Request) -> Response:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = request.path_params["analysis_id"]
    try:
        report = get_report(analysis_id, workspace_id=ctx["workspace_id"])
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


async def reports_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = request.path_params["analysis_id"]
    try:
        report = get_report(analysis_id, workspace_id=ctx["workspace_id"])
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    if not report:
        return _json({"detail": "Report not found"}, 404)
    return _json(annotate_report_parts(report))


async def reports_export(request: Request) -> Response:
    """Export one saved report, scoped to the authenticated workspace."""
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = request.path_params["analysis_id"]
    file_format = str(request.path_params["file_format"] or "").lower()
    try:
        report = get_report(analysis_id, workspace_id=ctx["workspace_id"])
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    if not report:
        return _json({"detail": "Report not found"}, 404)
    if file_format not in {"pdf", "csv", "xlsx"}:
        return _json({"detail": "Choose one of the supported export formats: PDF, Excel, or CSV."}, 400)

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


async def monitoring_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = request.query_params.get("analysis_id") or None
    try:
        return _json(
            migration_tools.monitoring_payload(
                workspace_id=ctx["workspace_id"], analysis_id=analysis_id
            )
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)


async def compare_parts_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    datasheet_uploads: dict[str, Any] = {}
    if "multipart/form-data" in str(request.headers.get("content-type") or "").lower():
        try:
            form = await request.form(max_files=2, max_fields=8)
        except Exception:  # noqa: BLE001
            return _json({"detail": "Invalid multipart comparison request."}, 400)
        body = {
            "part_a": form.get("part_a"),
            "part_b": form.get("part_b"),
            "analysis_id": form.get("analysis_id"),
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
            use_latest_if_missing=False,
            datasheet_uploads=datasheet_uploads or None,
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
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


async def decision_records_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = (request.query_params.get("analysis_id") or "").strip()
    try:
        if analysis_id and not get_report(analysis_id, workspace_id=ctx["workspace_id"]):
            return _json({"detail": "Report not found"}, 404)
        records = get_store().list_decision_records(
            workspace_id=ctx["workspace_id"],
            analysis_id=analysis_id or None,
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, "records": records})


async def decision_records_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    datasheet_uploads: dict[str, Any] = {}
    if "multipart/form-data" in str(request.headers.get("content-type") or "").lower():
        try:
            form = await request.form(max_files=2, max_fields=32)
            body = {key: form.get(key) for key in (
                "analysis_id", "part_a", "part_b", "decision", "reviewer", "rationale",
                "validation_checks", "follow_up_action", "follow_up_owner",
                "follow_up_due_date", "residual_risk",
            )}
            raw_checks = body.get("validation_checks")
            body["validation_checks"] = json.loads(raw_checks) if raw_checks else []
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
        if requested_analysis_id and not get_report(
            requested_analysis_id, workspace_id=ctx["workspace_id"]
        ):
            return _json({"detail": "Report not found"}, 404)
        comparison = await run_in_threadpool(
            migration_tools.compare_parts_payload,
            workspace_id=ctx["workspace_id"],
            part_a=part_a,
            part_b=part_b,
            analysis_id=requested_analysis_id,
            use_latest_if_missing=False,
            datasheet_uploads=datasheet_uploads or None,
        )
        if not comparison.get("ok"):
            return _json({"detail": comparison.get("detail") or "Comparison unavailable."}, 400)
        analysis_id = str(comparison.get("analysis_id") or "").strip() or None
        report = (
            get_report(analysis_id, workspace_id=ctx["workspace_id"])
            if analysis_id
            else None
        )
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
            )
        }
        record = get_store().create_decision_record(
            {
                "analysis_id": analysis_id,
                "project_name": split_project_and_bom(report or {})[0] or None,
                "bom_name": (report or {}).get("bom_name") or (report or {}).get("filename"),
                "revision": (report or {}).get("revision"),
                "part_a": part_a,
                "part_b": part_b,
                "decision": decision,
                "decision_label": _DECISION_LABELS[decision],
                "reviewer": reviewer,
                "rationale": rationale,
                "validation_checks": validation_checks,
                "follow_up_action": follow_up_action,
                "follow_up_owner": follow_up_owner,
                "follow_up_due_date": follow_up_due_date or None,
                "residual_risk": residual_risk,
                "verified_primary_evidence": required_approval_checks.issubset(set(validation_checks)),
                "qualification_status": "not-qualified-by-cadivor",
                "qualification_note": (
                    "This record captures a human decision and did not automatically qualify "
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
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
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
            filename=filename, payload=payload, question=question
        )
    except Exception as exc:  # noqa: BLE001
        return _json({"detail": str(exc)}, 400)
    status = 200 if result.get("ok") else 400
    return _json(result, status)


async def procurement_get(request: Request) -> JSONResponse:
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


async def design_impact_get(request: Request) -> JSONResponse:
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


async def cost_optimization_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    qty = request.query_params.get("build_quantity") or "100"
    try:
        build_quantity = int(qty)
    except ValueError:
        build_quantity = 100
    try:
        return _json(
            migration_tools.cost_optimization_payload(
                workspace_id=ctx["workspace_id"],
                analysis_id=request.query_params.get("analysis_id") or None,
                build_quantity=build_quantity,
            )
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)


async def supply_risk_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
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


async def portfolio_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    return _json(migration_tools.portfolio_payload(workspace_id=ctx["workspace_id"]))


async def detailed_risk_get(request: Request) -> JSONResponse:
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
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    result = supplier_lookup.lookup_exact_part(str(body.get("mpn") or ""))
    return _json(result)


async def find_replacement_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
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
    ctx, denied = _auth_context(request)
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
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    status = 200 if result.get("ok") else 400
    return _json(result, status)


async def monitoring_preferences_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    return _json({"ok": True, "preferences": monitoring_store.get_preferences(ctx["workspace_id"])})


async def monitoring_preferences_put(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    prefs = monitoring_store.update_preferences(ctx["workspace_id"], body if isinstance(body, dict) else {})
    return _json({"ok": True, "preferences": prefs})


async def monitoring_alerts_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    return _json(
        {
            "ok": True,
            "alerts": monitoring_store.list_alerts(ctx["workspace_id"]),
            "refresh_history": monitoring_store.list_refresh_history(ctx["workspace_id"]),
            "preferences": monitoring_store.get_preferences(ctx["workspace_id"]),
        }
    )


async def monitoring_acknowledge_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
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
    """Exercise notification wiring with the mock sink (no real email by default)."""
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    alert_id = str((body or {}).get("alert_id") or "")
    alerts = monitoring_store.list_alerts(ctx["workspace_id"])
    alert = next((a for a in alerts if a.get("id") == alert_id), None) or (alerts[0] if alerts else None)
    if not alert:
        return _json({"detail": "No alerts to notify"}, 404)
    result = monitoring_store.deliver_alert_email(ctx["workspace_id"], alert)
    return _json(result)


async def plan_usage_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    return _json({"ok": True, **plan_limits.usage_snapshot(ctx["workspace_id"], ctx)})


async def billing_status_get(request: Request) -> JSONResponse:
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
    ctx, denied = _auth_context(request)
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
            payload={"plan": body.get("plan") or body.get("plan_token") or ""},
            origin=request.headers.get("origin", ""),
        )
    except subscription_billing_service.SubscriptionBillingError as exc:
        return _json({"ok": False, "detail": str(exc)}, 503)
    return _json(result, status)


async def billing_portal_post(request: Request) -> JSONResponse:
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
    ctx, denied = _auth_context(request)
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


async def one_time_report_status_get(request: Request) -> JSONResponse:
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


async def one_time_report_checkout_post(request: Request) -> JSONResponse:
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


async def connectors_get(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
    if denied or not ctx:
        return denied or _json({"detail": "Unauthorized"}, 401)
    return _json(connectors.connector_status_payload())


async def connectors_sync_post(request: Request) -> JSONResponse:
    ctx, denied = _auth_context(request)
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


async def compliance_pack_get(request: Request) -> JSONResponse:
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




async def monitoring_refresh_post(request: Request) -> JSONResponse:
    """On-demand or cron-authenticated monitoring refresh (mock delivery by default)."""
    cron_header = request.headers.get("x-cadivor-cron-token")
    cron_ok = monitoring_scheduler.authorize_cron(cron_header)
    ctx, denied = _auth_context(request)
    if denied and not cron_ok:
        return denied or _json({"detail": "Unauthorized"}, 401)
    analysis_id = None
    workspace_id = None
    if cron_ok:
        workspace_id = (request.query_params.get("workspace_id") or "").strip()
        analysis_id = request.query_params.get("analysis_id") or None
        if not workspace_id:
            return _json({"detail": "workspace_id required for cron refresh"}, 400)
    else:
        assert ctx is not None
        workspace_id = ctx["workspace_id"]
        analysis_id = request.query_params.get("analysis_id") or None
    return _json(
        monitoring_scheduler.run_workspace_refresh(
            workspace_id, analysis_id=analysis_id
        )
    )


def _team_error(exc: TeamError) -> JSONResponse:
    payload: dict[str, Any] = {"detail": exc.detail}
    if exc.code:
        payload["code"] = exc.code
    return _json(payload, exc.status_code)


async def invitations_lookup_get(request: Request) -> JSONResponse:
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


def _throttled(request: Request, bucket: str, *, limit: int = 10, window: int = 60) -> bool:
    """Best-effort per-process throttle for unauthenticated routes."""
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    client = forwarded or (request.client.host if request.client else "unknown")
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
    try:
        result = await run_in_threadpool(
            lambda: team_service.register_from_invitation_sandbox(
                str(body.get("token") or ""),
                str(body.get("email") or ""),
                str(body.get("password") or ""),
            )
        )
    except TeamError as exc:
        return _team_error(exc)
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    return _json({"ok": True, **result})


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
        # Compatibility aliases for the Next web client / sandbox tests.
        Route("/workspaces/switch", workspaces_switch_post, methods=["POST"]),
        Route(
            "/workspace/invitations/{invite_id}/cancel",
            workspace_invitation_cancel_post,
            methods=["POST"],
        ),
        Route("/settings/security", security_status_get, methods=["GET"]),
        Route("/boms/analyze", boms_analyze, methods=["POST"]),
        Route("/reports", reports_list, methods=["GET"]),
        Route("/reports/{analysis_id}/export.csv", reports_csv_get, methods=["GET"]),
        Route("/reports/{analysis_id}/export/{file_format}", reports_export, methods=["GET"]),
        Route("/reports/{analysis_id}", reports_get, methods=["GET"]),
        Route("/reports/{analysis_id}", reports_delete, methods=["DELETE"]),
        Route("/projects", projects_list, methods=["GET"]),
        Route("/projects/{project_id}", projects_update, methods=["PATCH"]),
        Route("/projects/{project_id}", projects_delete, methods=["DELETE"]),
        Route("/workspace/home", workspace_home, methods=["GET"]),
        Route("/tools/monitoring", monitoring_get, methods=["GET"]),
        Route("/tools/compare-parts", compare_parts_post, methods=["POST"]),
        Route("/decision-records", decision_records_get, methods=["GET"]),
        Route("/decision-records", decision_records_post, methods=["POST"]),
        Route("/tools/datasheet-qa", datasheet_qa_post, methods=["POST"]),
        Route("/tools/procurement", procurement_get, methods=["GET"]),
        Route("/tools/design-impact", design_impact_get, methods=["GET"]),
        Route("/tools/cost-optimization", cost_optimization_get, methods=["GET"]),
        Route("/tools/supply-risk", supply_risk_post, methods=["POST"]),
        Route("/tools/portfolio", portfolio_get, methods=["GET"]),
        Route("/tools/detailed-risk", detailed_risk_get, methods=["GET"]),
        Route("/tools/supplier-lookup", supplier_lookup_post, methods=["POST"]),
        Route("/tools/find-replacement", find_replacement_post, methods=["POST"]),
        Route("/tools/ask-cadivor", ask_cadivor_post, methods=["POST"]),
        Route("/tools/monitoring/preferences", monitoring_preferences_get, methods=["GET"]),
        Route("/tools/monitoring/preferences", monitoring_preferences_put, methods=["PUT"]),
        Route("/tools/monitoring/alerts", monitoring_alerts_get, methods=["GET"]),
        Route("/tools/monitoring/acknowledge", monitoring_acknowledge_post, methods=["POST"]),
        Route("/tools/monitoring/notify", monitoring_notify_post, methods=["POST"]),
        Route("/tools/monitoring/refresh", monitoring_refresh_post, methods=["POST"]),
        Route("/billing/status", billing_status_get, methods=["GET"]),
        Route("/billing/checkout", billing_checkout_post, methods=["POST"]),
        Route("/billing/portal", billing_portal_post, methods=["POST"]),
        Route("/billing/checkout-prep", billing_checkout_prep_post, methods=["POST"]),
        Route("/billing/one-time-report", one_time_report_status_get, methods=["GET"]),
        Route("/billing/one-time-report/checkout", one_time_report_checkout_post, methods=["POST"]),
        Route("/plan/usage", plan_usage_get, methods=["GET"]),
        Route("/integrations/connectors", connectors_get, methods=["GET"]),
        Route("/integrations/connectors/sync", connectors_sync_post, methods=["POST"]),
        Route("/compliance/{pack_type}", compliance_pack_get, methods=["GET"]),
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
