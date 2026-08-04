import os

CADIVOR_MARKETING_URL = os.getenv(
    "CADIVOR_MARKETING_URL",
    "https://www.cadivor.com/",
)

# Sprint 67 — structured Engineering Decision Engine v2 renderer and report sections.
# Set ENABLE_DECISION_ENGINE_V2=false to fall back to Sprint 66 v1 during debugging.
ENABLE_DECISION_ENGINE_V2 = os.getenv(
    "ENABLE_DECISION_ENGINE_V2",
    "true",
).strip().lower() in ("1", "true", "yes", "on")
