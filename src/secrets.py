"""Centralized secret and configuration resolution for Cadivor.

Resolution order:
1. os.getenv(variable_name)
2. st.secrets.get(variable_name) when Streamlit secrets are available
3. documented default for optional variables only

Railway supplies environment variables. Streamlit Community Cloud and local
development may use st.secrets or environment variables interchangeably.
"""
from __future__ import annotations

import os
from typing import Any

from src.configuration_errors import ConfigurationError

__all__ = ("ConfigurationError", "get_secret", "get_secret_bool")


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    if value is None:
        return None
    return value


def _truthy(value: Any) -> bool:
    normalized = _normalize_value(value)
    if normalized is None:
        return False
    if isinstance(normalized, bool):
        return normalized
    return str(normalized).lower() in {"1", "true", "yes", "on"}


def get_secret(
    name: str,
    *,
    default: Any = None,
    required: bool = False,
) -> Any:
    """Resolve a configuration value without logging secret contents."""
    env_value = _normalize_value(os.getenv(name))
    if env_value is not None:
        return env_value

    secret_value = None
    try:
        import streamlit as st

        if name in st.secrets:
            secret_value = _normalize_value(st.secrets.get(name))
    except Exception:
        secret_value = None

    if secret_value is not None:
        return secret_value

    if required:
        raise ConfigurationError(f"Missing required configuration variable: {name}")

    return default


def get_secret_bool(name: str, *, default: bool = False) -> bool:
    """Resolve a boolean configuration flag."""
    env_value = os.getenv(name)
    if env_value is not None and str(env_value).strip() != "":
        return _truthy(env_value)

    try:
        import streamlit as st

        if name in st.secrets:
            return _truthy(st.secrets.get(name))
    except Exception:
        pass

    return default
