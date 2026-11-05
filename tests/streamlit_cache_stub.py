"""Minimal Streamlit stub for unit tests that only need cache/fragment decorators.

Keeps product `@st.fragment` / `@st.cache_data` as no-op identity wrappers in tests.
Does not replace or weaken the real Streamlit decorators in application code.
"""
from __future__ import annotations

import sys
import types
from typing import Any, Callable


def identity_decorator(func: Callable | None = None, **_kwargs: Any):
    """Support both ``@decorator`` and ``@decorator(...)`` forms."""

    def wrap(target: Callable) -> Callable:
        return target

    if func is not None and callable(func):
        return wrap(func)
    return wrap


def install_streamlit_cache_stub(**extra: Any) -> types.SimpleNamespace:
    """Install ``sys.modules['streamlit']`` with ``cache_data`` and ``fragment``."""
    st = types.SimpleNamespace(
        cache_data=identity_decorator,
        fragment=identity_decorator,
        **extra,
    )
    sys.modules["streamlit"] = st
    return st
