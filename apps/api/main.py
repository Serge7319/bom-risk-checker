"""Cadivor Next.js migration API — separate test build, synthetic evidence only.

Uses Starlette (already pinned with Streamlit) so Railway installs do
not fight FastAPI's older Starlette bound. Production Streamlit is unchanged.
No Stripe charges, automated email notifications, or live supplier HTTP calls.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
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
from apps.api.workspace_store import (  # noqa: E402
    PersistenceNotConfiguredError,
    WorkspaceAccessError,
    describe_persistence,
    get_store,
)

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


def _disable_live_integrations() -> None:
    os.environ.pop("MOUSER_API_KEY", None)
    os.environ.pop("DIGIKEY_CLIENT_ID", None)
    os.environ.pop("DIGIKEY_CLIENT_SECRET", None)
    os.environ.pop("NEWARK_API_KEY", None)
    os.environ.pop("RESEND_API_KEY", None)


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
    return _json(
        {
            "ok": True,
            "service": "cadivor-migration-api",
            "mode": "synthetic-preview",
            "suppliers": "disabled",
            "stripe": "disabled",
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
                "datasheet-qa",
                "procurement",
                "design-impact",
                "cost-optimization",
                "supply-risk",
                "portfolio",
                "detailed-risk",
            ],
            "foundation": [
                "workspace-store",
                "projects",
                "bom-hierarchy-rollup",
                "home-dashboard",
                "workspace-isolation",
                "sandbox-jwt-auth",
                "supabase-jwt-auth",
            ],
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
    if _use_supabase_auth() and supabase_auth.trial_expired(ctx):
        return _json(
            {
                "code": "trial_expired",
                "detail": "Your 14-day trial has ended. Saved reports remain available; contact Cadivor to continue analysis.",
            },
            402,
        )
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
    _disable_live_integrations()
    try:
        report = analyze_upload(
            filename=filename,
            payload=payload,
            workspace_id=ctx["workspace_id"],
            project_name=project_name,
            bom_name=bom_name,
            revision=revision,
        )
    except PersistenceNotConfiguredError as exc:
        return _json({"detail": str(exc)}, 503)
    except Exception as exc:  # noqa: BLE001
        return _json({"detail": str(exc)}, 400)
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
    return _json(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "workspace_id": ctx["workspace_id"],
            "persistence": persistence["backend"],
            "gap": persistence["label"],
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
    return _json(report)


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
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    _disable_live_integrations()
    try:
        result = migration_tools.compare_parts_payload(
            workspace_id=ctx["workspace_id"],
            part_a=str(body.get("part_a") or ""),
            part_b=str(body.get("part_b") or ""),
            analysis_id=body.get("analysis_id") or None,
        )
    except WorkspaceAccessError:
        return _json({"detail": "Report not found"}, 404)
    status = 200 if result.get("ok") else 400
    return _json(result, status)


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
    _disable_live_integrations()
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


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/auth/config", auth_signup_config, methods=["GET"]),
        Route("/auth/signup", auth_signup, methods=["POST"]),
        Route("/auth/login", auth_login, methods=["POST"]),
        Route("/auth/logout", auth_logout, methods=["POST"]),
        Route("/auth/me", auth_me, methods=["GET"]),
        Route("/auth/smoke-login", smoke_login, methods=["POST"]),
        Route("/boms/analyze", boms_analyze, methods=["POST"]),
        Route("/reports", reports_list, methods=["GET"]),
        Route("/reports/{analysis_id}", reports_get, methods=["GET"]),
        Route("/reports/{analysis_id}", reports_delete, methods=["DELETE"]),
        Route("/projects", projects_list, methods=["GET"]),
        Route("/projects/{project_id}", projects_update, methods=["PATCH"]),
        Route("/projects/{project_id}", projects_delete, methods=["DELETE"]),
        Route("/workspace/home", workspace_home, methods=["GET"]),
        Route("/tools/monitoring", monitoring_get, methods=["GET"]),
        Route("/tools/compare-parts", compare_parts_post, methods=["POST"]),
        Route("/tools/datasheet-qa", datasheet_qa_post, methods=["POST"]),
        Route("/tools/procurement", procurement_get, methods=["GET"]),
        Route("/tools/design-impact", design_impact_get, methods=["GET"]),
        Route("/tools/cost-optimization", cost_optimization_get, methods=["GET"]),
        Route("/tools/supply-risk", supply_risk_post, methods=["POST"]),
        Route("/tools/portfolio", portfolio_get, methods=["GET"]),
        Route("/tools/detailed-risk", detailed_risk_get, methods=["GET"]),
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
