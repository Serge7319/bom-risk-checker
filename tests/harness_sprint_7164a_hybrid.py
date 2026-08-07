"""Sprint 71.6.4A — hybrid hydration harness (sleep + spaced rerun).

Tests the proposed fallback when pure st.stop() stalls on identical {} values.

Run:
  streamlit run tests/harness_sprint_7164a_hybrid.py --server.headless true --server.port 8766
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
import extra_streamlit_components as stx

AUTH_COOKIE_NAME = "cadivor_auth"
COMPONENT_KEY = "cadivor_auth_cookie_manager"
RUN_ID_KEY = "_h7164b_run_id"
INSTANCE_KEY = "_h7164b_manager"
ATTEMPTS_KEY = "_h7164b_attempts"
DONE_KEY = "_h7164b_done"
LOG_PATH = Path(__file__).with_name("harness_sprint_7164a_hybrid_runs.log")
MAX_ATTEMPTS = 6
WAIT_SECONDS = 0.25


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


def _log(event: str, **details: object) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    parts = " ".join(f"{k}={v}" for k, v in sorted(details.items()))
    line = f"[h7164b] ts={ts} event={event}" + (f" {parts}" if parts else "")
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def get_manager():
    run_id = _script_run_id()
    if run_id is not None and st.session_state.get(RUN_ID_KEY) == run_id:
        return st.session_state.get(INSTANCE_KEY)
    manager = stx.CookieManager(key=COMPONENT_KEY)
    if run_id is not None:
        st.session_state[RUN_ID_KEY] = run_id
        st.session_state[INSTANCE_KEY] = manager
    return manager


st.set_page_config(page_title="7164A Hybrid Harness", layout="centered")
mode = str(st.query_params.get("mode", "no_cookie") or "no_cookie").strip().lower()

run_id = _script_run_id()
manager = get_manager()
attempts_before = int(st.session_state.get(ATTEMPTS_KEY) or 0)
_log("script_run", mode=mode, script_run_id=run_id, attempts_before=attempts_before)

if mode == "with_cookie" and not st.session_state.get("_h7164b_seeded"):
    payload = json.dumps({"access_token": "dummy-access", "refresh_token": "dummy-refresh"})
    manager.set(
        cookie=AUTH_COOKIE_NAME,
        val=payload,
        key="h7164b_seed",
        path="/",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    st.session_state["_h7164b_seeded"] = True
    _log("seed_cookie_requested")

raw = manager.get(cookie=AUTH_COOKIE_NAME)
present = raw is not None
_log("cookie_read", present=present)

if st.session_state.get(DONE_KEY):
    st.success("TERMINATED")
    st.stop()

if present:
    st.session_state[DONE_KEY] = True
    _log("restoration_success", attempts_before=attempts_before)
    st.success("RESTORED")
    st.stop()

attempts = attempts_before + 1
st.session_state[ATTEMPTS_KEY] = attempts
_log("hydration_pending", attempt=attempts)

if attempts >= MAX_ATTEMPTS:
    st.session_state[DONE_KEY] = True
    _log("fallback_signed_out", attempts=attempts)
    st.warning("FAIL-CLOSED")
    st.stop()

st.markdown(f"### Restoring… attempt {attempts}/{MAX_ATTEMPTS}")
_log("hydration_wait_spaced_rerun", attempt=attempts, wait_seconds=WAIT_SECONDS)
time.sleep(WAIT_SECONDS)
st.rerun()
