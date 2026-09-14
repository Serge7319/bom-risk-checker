"""Short budget for non-critical authenticated boot reads.

A hung PostgREST call must not pin the Opening overlay. The worker is a daemon
so a timeout returns control to the page. Do not log exception text.

The first authenticated page shares one deadline. Later reads in that run use
whatever time remains, so two hung calls cannot stack past the budget.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

BOOT_READ_BUDGET_SECONDS = 8.0
FIRST_PAGE_BUDGET_SECONDS = 8.0
SECONDARY_DATA_DELAYED_KEY = "cadivor_secondary_data_delayed"
_FIRST_PAGE_DEADLINE: float | None = None
_FIRST_PAGE_RUN_ID: str | None = None


def _current_script_run_id() -> str | None:
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import (
            get_script_run_ctx,
        )

        ctx = get_script_run_ctx()
    except Exception:
        return None
    if ctx is None:
        return None
    run_id = getattr(ctx, "script_run_id", None)
    return str(run_id) if run_id else None


def begin_first_page_budget(seconds: float = FIRST_PAGE_BUDGET_SECONDS) -> float:
    """Start the shared Opening → first interactive page deadline."""
    global _FIRST_PAGE_DEADLINE, _FIRST_PAGE_RUN_ID
    _FIRST_PAGE_RUN_ID = _current_script_run_id()
    _FIRST_PAGE_DEADLINE = time.monotonic() + max(0.0, float(seconds))
    return _FIRST_PAGE_DEADLINE


def end_first_page_budget() -> None:
    global _FIRST_PAGE_DEADLINE, _FIRST_PAGE_RUN_ID
    _FIRST_PAGE_DEADLINE = None
    _FIRST_PAGE_RUN_ID = None


def remaining_first_page_budget() -> float | None:
    """Seconds left on this script run's first-page deadline.

    An expired deadline from a previous Streamlit run must not keep returning
    timeout. Within the run that armed it, a spent deadline still returns 0 so
    later hangs cannot stack.
    """
    global _FIRST_PAGE_DEADLINE, _FIRST_PAGE_RUN_ID
    if _FIRST_PAGE_DEADLINE is None:
        return None
    current_run = _current_script_run_id()
    if (
        _FIRST_PAGE_RUN_ID
        and current_run
        and current_run != _FIRST_PAGE_RUN_ID
    ):
        _FIRST_PAGE_DEADLINE = None
        _FIRST_PAGE_RUN_ID = None
        return None
    return max(0.0, _FIRST_PAGE_DEADLINE - time.monotonic())


def run_with_read_budget(
    fn: Callable[[], Any],
    *,
    budget_seconds: float = BOOT_READ_BUDGET_SECONDS,
    respect_first_page: bool = True,
) -> tuple[Any, str]:
    """Run ``fn`` until ``budget_seconds``. Return (value, "ok"|"timeout"|"error").

    On timeout the call may still finish in the background. Callers must treat
    that as empty secondary data, never as a successful empty result to persist
    over a known cache. While a first-page budget is armed, ``budget_seconds``
    is capped to the time still left on that shared deadline. Nonessential
    calls pass ``respect_first_page=False`` so a hang cannot exhaust the
    deadline before the saved-BOM read.
    """
    budget = float(budget_seconds)
    remaining = remaining_first_page_budget() if respect_first_page else None
    if remaining is not None:
        budget = min(budget, remaining)
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
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import (
            add_script_run_ctx,
        )

        add_script_run_ctx(thread)
    except Exception:
        pass
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
