"""Bounded transport retries for idempotent Supabase SELECT reads only."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TRANSIENT_READ_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.TransportError,
)

DEFAULT_READ_ATTEMPTS = 3
DEFAULT_READ_BACKOFF_SECONDS = 0.15


class SupabaseReadTransportError(Exception):
    """Raised when an idempotent read exhausts transport retries."""

    def __init__(self, operation: str, cause: BaseException) -> None:
        self.operation = operation
        self.cause = cause
        super().__init__(f"{operation}: {cause.__class__.__name__}")


def execute_supabase_read(
    builder: Any,
    *,
    attempts: int = DEFAULT_READ_ATTEMPTS,
    operation: str = "supabase_read",
    backoff_seconds: float = DEFAULT_READ_BACKOFF_SECONDS,
) -> Any:
    """Execute a PostgREST SELECT builder with bounded transport retries.

    For GET/idempotent reads only. Do not use for INSERT, UPDATE, DELETE, UPSERT,
    mutation RPCs, or auth token operations.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    from src.performance_timing import (
        emit_timing,
        normalize_operation,
        timing_enabled,
    )

    op_name = normalize_operation(operation)
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        started = time.perf_counter()
        try:
            result = builder.execute()
            if timing_enabled():
                row_count = None
                try:
                    data = getattr(result, "data", None)
                    if isinstance(data, list):
                        row_count = len(data)
                except Exception:
                    row_count = None
                emit_timing(
                    "supabase.read",
                    duration_ms=round((time.perf_counter() - started) * 1000.0, 1),
                    outcome="success",
                    provider="supabase",
                    operation=op_name,
                    attempt=attempt,
                    max_attempts=attempts,
                    row_count=row_count,
                )
            return result
        except TRANSIENT_READ_EXCEPTIONS as exc:
            last_exc = exc
            if timing_enabled():
                emit_timing(
                    "supabase.read",
                    duration_ms=round((time.perf_counter() - started) * 1000.0, 1),
                    outcome="retry" if attempt < attempts else "error",
                    provider="supabase",
                    operation=op_name,
                    attempt=attempt,
                    max_attempts=attempts,
                )
            logger.warning(
                "supabase_read_transport_retry operation=%s attempt=%s/%s error=%s",
                operation,
                attempt,
                attempts,
                exc.__class__.__name__,
            )
            if attempt >= attempts:
                raise SupabaseReadTransportError(operation, exc) from exc
            time.sleep(backoff_seconds * attempt)

    if last_exc is not None:
        raise SupabaseReadTransportError(operation, last_exc) from last_exc
    raise RuntimeError("execute_supabase_read reached an unexpected state")
