"""Small diagnostics that identify failure sites without recording payloads."""
from __future__ import annotations

import traceback


def safe_exception_frames(exc: BaseException, *, limit: int = 5) -> str:
    """Return file/function/line hints, excluding exception text and locals."""
    try:
        frames = traceback.extract_tb(exc.__traceback__)
    except Exception:
        return "unavailable"
    return " > ".join(
        f"{frame.filename.rsplit('/', 1)[-1]}:{frame.name}:{frame.lineno}"
        for frame in frames[-max(1, int(limit)):]
    ) or "unavailable"


__all__ = ["safe_exception_frames"]
