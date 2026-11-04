"""Cadivor Next.js migration API — sandbox / synthetic preview only.

Uses Starlette (already pinned with Streamlit) so Railway sandbox installs do
not fight FastAPI's older Starlette bound. Production Streamlit is unchanged.
No Stripe charges, email, or live supplier HTTP calls.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.synthetic_analyze import analyze_upload, get_report  # noqa: E402

SMOKE_EMAIL = "auth-smoke@cadivor.test"
SMOKE_PASSWORD = "cadivor-auth-smoke"
SMOKE_TOKEN = "cadivor-nextjs-smoke-token"

_origins = [
    origin.strip()
    for origin in os.environ.get(
        "CADIVOR_WEB_ORIGINS",
        "http://127.0.0.1:3000,http://localhost:3000",
    ).split(",")
    if origin.strip()
]


def _json(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status_code)


def _require_smoke_token(request: Request) -> JSONResponse | None:
    authorization = request.headers.get("authorization") or ""
    if not authorization.startswith("Bearer "):
        return _json({"detail": "Missing bearer token"}, 401)
    token = authorization.removeprefix("Bearer ").strip()
    if token != SMOKE_TOKEN:
        return _json({"detail": "Invalid smoke token"}, 401)
    return None


async def health(_: Request) -> JSONResponse:
    return _json(
        {
            "ok": True,
            "service": "cadivor-migration-api",
            "mode": "synthetic-preview",
            "suppliers": "disabled",
            "stripe": "disabled",
            "email": "disabled",
        }
    )


async def smoke_login(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json({"detail": "Invalid JSON"}, 400)
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    if email != SMOKE_EMAIL or password != SMOKE_PASSWORD:
        return _json({"detail": "Invalid smoke credentials"}, 401)
    return _json(
        {
            "access_token": SMOKE_TOKEN,
            "email": SMOKE_EMAIL,
            "workspace": "CADIVOR SMOKE",
            "plan": "Trial",
            "mode": "synthetic-preview",
        }
    )


async def boms_analyze(request: Request) -> JSONResponse:
    denied = _require_smoke_token(request)
    if denied:
        return denied
    form = await request.form()
    upload = form.get("file")
    if upload is None:
        return _json({"detail": "Missing file"}, 400)
    filename = getattr(upload, "filename", None) or "bom.csv"
    payload = await upload.read()
    if not payload:
        return _json({"detail": "Empty file"}, 400)
    os.environ.pop("MOUSER_API_KEY", None)
    os.environ.pop("DIGIKEY_CLIENT_ID", None)
    os.environ.pop("DIGIKEY_CLIENT_SECRET", None)
    os.environ.pop("NEWARK_API_KEY", None)
    os.environ.pop("RESEND_API_KEY", None)
    try:
        report = analyze_upload(filename=filename, payload=payload)
    except Exception as exc:  # noqa: BLE001
        return _json({"detail": str(exc)}, 400)
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
        }
    )


async def reports_get(request: Request) -> JSONResponse:
    denied = _require_smoke_token(request)
    if denied:
        return denied
    analysis_id = request.path_params["analysis_id"]
    report = get_report(analysis_id)
    if not report:
        return _json({"detail": "Report not found"}, 404)
    return _json(report)


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/auth/smoke-login", smoke_login, methods=["POST"]),
        Route("/boms/analyze", boms_analyze, methods=["POST"]),
        Route("/reports/{analysis_id}", reports_get, methods=["GET"]),
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
