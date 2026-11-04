"""Railway sandbox entry for the Next.js migration API.

Production Streamlit continues to use scripts/railway_start.sh. This module
exists so Railpack's default `uvicorn main:app` target resolves in sandbox.
"""
from apps.api.main import app

__all__ = ["app"]
