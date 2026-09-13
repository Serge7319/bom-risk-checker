"""Short budget for non-critical authenticated boot reads.

A hung PostgREST call must not pin the Opening overlay. The worker is a daemon
so a timeout returns control to the page. Do not log exception text.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

BOOT_READ_BUDGET_SECONDS = 8.0
SECONDARY_DATA_DELAYED_KEY = "cadivor_secondary_data_delayed"


def run_with_read_budget(
    fn: Callable[[], Any],
    *,
    budget_seconds: float = BOOT_READ_BUDGET_SECONDS,
) -> tuple[Any, str]:
    """Run ``fn`` until ``budget_seconds``. Return (value, "ok"|"timeout"|"error").

    On timeout the call may still finish in the background. Callers must treat
    that as empty secondary data, never as a successful empty result to persist
    over a known cache.
    """
    budget = float(budget_seconds)
    if budget <= 0:
        return None, "timeout"
    box: dict[str, Any] = {}
    done = threading.Event()

    def _worker() -> None:
        try:
            box["value"] = fn()
            box["status"] = "ok"
        except Exception:
            box["status"] = "error"
        finally:
            done.set()

    thread = threading.Thread(target=_worker, name="cadivor-boot-read", daemon=True)
    thread.start()
    if not done.wait(budget):
        return None, "timeout"
    status = str(box.get("status") or "error")
    if status != "ok":
        return None, "error"
    return box.get("value"), "ok"


def mark_secondary_data_delayed(session_state: dict, delayed: bool) -> None:
    if delayed:
        session_state[SECONDARY_DATA_DELAYED_KEY] = True
    else:
        session_state.pop(SECONDARY_DATA_DELAYED_KEY, None)


def secondary_data_delayed(session_state: dict) -> bool:
    return bool(session_state.get(SECONDARY_DATA_DELAYED_KEY))
