import os

from src.urls import (
    CADIVOR_APP_ORIGIN,
    CADIVOR_MARKETING_ORIGIN,
    CADIVOR_MARKETING_URL,
    app_auth_url,
    app_checkout_url,
    app_url,
    marketing_url,
)

# Sprint 67 — structured Engineering Decision Engine v2 renderer and report sections.
# Set ENABLE_DECISION_ENGINE_V2=false to fall back to Sprint 66 v1 during debugging.
ENABLE_DECISION_ENGINE_V2 = os.getenv(
    "ENABLE_DECISION_ENGINE_V2",
    "true",
).strip().lower() in ("1", "true", "yes", "on")

# Sprint 67.1 — Executive Decision Workspace presentation on Analysis Detail only.
# Set ENABLE_DECISION_WORKSPACE_V71=false to fall back to Sprint 67 v2 renderer.
ENABLE_DECISION_WORKSPACE_V71 = os.getenv(
    "ENABLE_DECISION_WORKSPACE_V71",
    "true",
).strip().lower() in ("1", "true", "yes", "on")
