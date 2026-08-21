"""Offline probe for _script_run_id stability (no Streamlit server required)."""
from __future__ import annotations

import types
import sys


def _script_run_id() -> str | None:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx is None:
            return None
        run_id = getattr(ctx, "script_run_id", None)
        return str(run_id) if run_id is not None else str(id(ctx))
    except Exception:
        return None


class _Ctx:
    def __init__(self, run_id: str):
        self.script_run_id = run_id


def main() -> None:
    ctx_a = _Ctx("run-a")
    ctx_b = _Ctx("run-b")

    def get_ctx():
        return _CtxHolder.current

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = get_ctx
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner
    st = types.ModuleType("streamlit")
    st.runtime = runtime
    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner

    class _CtxHolder:
        current = ctx_a

    same_run = {_script_run_id() for _ in range(5)}
    _CtxHolder.current = ctx_b
    next_run = _script_run_id()

    print("same_run_ids", same_run)
    print("all_same_in_one_run", len(same_run) == 1)
    print("next_run_id", next_run)
    print("changes_between_runs", next_run != next(iter(same_run)))


if __name__ == "__main__":
    main()
