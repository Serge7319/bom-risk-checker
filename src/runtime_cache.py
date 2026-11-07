"""Cache helpers that also work in the headless API container.

The legacy supplier engine uses Streamlit's data cache when running in the
Streamlit app. The Next API image intentionally does not install Streamlit, so
use a small bounded TTL cache there instead of making the engine unimportable.
"""
from __future__ import annotations

import copy
import pickle
import threading
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable


def cache_data(*, ttl: float | None = None, max_entries: int = 128, **options: Any):
    """Use Streamlit's cache when available, otherwise a bounded in-process TTL."""
    try:
        import streamlit as st
    except ImportError:
        st = None
    if st is not None:
        return st.cache_data(ttl=ttl, **options)

    lifetime = float(ttl) if ttl is not None else 300.0

    def decorate(function: Callable):
        entries: OrderedDict[bytes, tuple[float, Any]] = OrderedDict()
        lock = threading.RLock()

        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any):
            try:
                key = pickle.dumps((args, kwargs), protocol=pickle.HIGHEST_PROTOCOL)
            except Exception:
                return function(*args, **kwargs)
            now = time.monotonic()
            with lock:
                item = entries.get(key)
                if item is not None:
                    expires_at, value = item
                    if expires_at > now:
                        entries.move_to_end(key)
                        return copy.deepcopy(value)
                    entries.pop(key, None)
            value = function(*args, **kwargs)
            try:
                cached = copy.deepcopy(value)
            except Exception:
                return value
            with lock:
                entries[key] = (now + lifetime, cached)
                entries.move_to_end(key)
                while len(entries) > max_entries:
                    entries.popitem(last=False)
            return copy.deepcopy(value)

        def clear() -> None:
            with lock:
                entries.clear()

        wrapped.clear = clear  # type: ignore[attr-defined]
        wrapped.clear_cache = clear  # type: ignore[attr-defined]
        return wrapped

    return decorate
