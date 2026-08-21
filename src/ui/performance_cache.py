"""Sprint 71 — Session-scoped memoization for expensive engineering computations."""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Mapping, Optional, TypeVar

import pandas as pd
import streamlit as st

T = TypeVar("T")


def _session_bucket(name: str) -> Dict[str, Any]:
    key = f"_cv71_cache_{name}"
    if key not in st.session_state:
        st.session_state[key] = {}
    return st.session_state[key]


def _analysis_fingerprint(
    analysis_id: Any,
    analysis: Mapping[str, Any] | None,
    parts: Iterable[Mapping[str, Any]] | None,
    *,
    alerts_count: int = 0,
    alternatives_count: int = 0,
) -> str:
    part_list = list(parts or [])
    health = int((analysis or {}).get("health_score") or 0)
    return (
        f"{analysis_id}:{len(part_list)}:{health}:"
        f"{alerts_count}:{alternatives_count}"
    )


def memoize_session(
    namespace: str,
    cache_key: str,
    fingerprint: str,
    builder: Callable[[], T],
) -> T:
    """Return a cached value for a stable fingerprint, or rebuild once per session."""
    bucket = _session_bucket(namespace)
    entry = bucket.get(cache_key)
    if isinstance(entry, dict) and entry.get("fp") == fingerprint:
        return entry["value"]
    value = builder()
    bucket[cache_key] = {"fp": fingerprint, "value": value}
    return value


def cached_bom_intelligence(
    analysis_id: Any,
    results_df: pd.DataFrame,
    *,
    analyzer: Callable[[pd.DataFrame], Dict[str, Any]],
) -> Dict[str, Any]:
    fingerprint = f"{analysis_id}:{len(results_df)}:{tuple(results_df.columns[:12])}"
    return memoize_session(
        "bom_intelligence",
        str(analysis_id),
        fingerprint,
        lambda: analyzer(results_df),
    )


def cached_engineering_advisor(
    analysis_id: Any,
    *,
    analysis: Mapping[str, Any],
    parts: Iterable[Mapping[str, Any]],
    alerts: Iterable[Mapping[str, Any]] | None,
    alternatives: Iterable[Mapping[str, Any]] | None,
    builder: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    alerts_list = list(alerts or [])
    alternatives_list = list(alternatives or [])
    fingerprint = _analysis_fingerprint(
        analysis_id,
        analysis,
        parts,
        alerts_count=len(alerts_list),
        alternatives_count=len(alternatives_list),
    )
    return memoize_session(
        "advisor",
        str(analysis_id),
        fingerprint,
        lambda: builder(
            analysis=dict(analysis),
            parts=list(parts),
            alerts=alerts_list,
            alternatives=alternatives_list,
        ),
    )


def cached_engineering_context(
    analysis_id: Any,
    *,
    fingerprint: str,
    builder: Callable[[], Any],
) -> Any:
    return memoize_session("context", str(analysis_id), fingerprint, builder)


def cached_knowledge_graph(
    analysis_id: Any,
    *,
    fingerprint: str,
    builder: Callable[[], Any],
) -> Any:
    return memoize_session("knowledge_graph", str(analysis_id), fingerprint, builder)
