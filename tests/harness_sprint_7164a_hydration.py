"""Sprint 71.6.4A — empirical hydration termination harness (NOT production).

Run:
  streamlit run tests/harness_sprint_7164a_hydration.py --server.headless true

Modes (query param ``mode``):
  no_cookie   — default; browser has no cadivor_auth (termination test)
  with_cookie — seeds a dummy cookie via CookieManager.set on first pass
  run_id      — prints _script_run_id stability only (no st.stop loop)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

try:
    import extra_streamlit_components as stx
except Exception as exc:
    st.error(f"extra_streamlit_components unavailable: {exc}")
    st.stop()

AUTH_COOKIE_NAME = "cadivor_auth"
COMPONENT_KEY = "cadivor_auth_cookie_manager"
RUN_ID_KEY = "_h7164a_run_id"
INSTANCE_KEY = "_h7164a_manager"
ATTEMPTS_KEY = "_h7164a_attempts"
DONE_KEY = "_h7164a_done"
LOG_PATH = Path(__file__).with_name("harness_sprint_7164a_runs.log")
MAX_ATTEMPTS = 6


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
    line = f"[h7164a] ts={ts} event={event}"
    if parts:
        line = f"{line} {parts}"
    print(line, flush=True)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


def get_manager():
    run_id = _script_run_id()
    if run_id is not None and st.session_state.get(RUN_ID_KEY) == run_id:
        return st.session_state.get(INSTANCE_KEY), run_id

    manager = stx.CookieManager(key=COMPONENT_KEY)
    if run_id is not None:
        st.session_state[RUN_ID_KEY] = run_id
        st.session_state[INSTANCE_KEY] = manager
    return manager, run_id


def _read_auth(manager) -> str | None:
    raw = manager.get(cookie=AUTH_COOKIE_NAME)
    return str(raw) if raw is not None else None


st.set_page_config(page_title="7164A Hydration Harness", layout="centered")

mode = st.query_params.get("mode", "no_cookie")
if isinstance(mode, list):
    mode = mode[0] if mode else "no_cookie"
mode = str(mode or "no_cookie").strip().lower()

run_id = _script_run_id()
manager, _ = get_manager()
attempts_before = int(st.session_state.get(ATTEMPTS_KEY) or 0)

_log(
    "script_run",
    mode=mode,
    script_run_id=run_id,
    attempts_before=attempts_before,
    done=bool(st.session_state.get(DONE_KEY)),
)

# --- run_id-only mode: prove per-run dedup without hydration loop ---
if mode == "run_id":
    st.subheader("script_run_id probe")
    first_call_run_id = _script_run_id()
    m1, _ = get_manager()
    m2, _ = get_manager()
    st.write(
        {
            "script_run_id": first_call_run_id,
            "same_manager_instance": m1 is m2,
            "manager_key": getattr(m1, "key", None),
        }
    )
    _log(
        "run_id_probe",
        script_run_id=first_call_run_id,
        same_instance=m1 is m2,
    )
    st.stop()

# --- optional seed cookie (dummy values only) ---
if mode == "with_cookie" and not st.session_state.get("_h7164a_seeded"):
    payload = json.dumps(
        {"access_token": "dummy-access-token", "refresh_token": "dummy-refresh-token"}
    )
    manager.set(
        cookie=AUTH_COOKIE_NAME,
        val=payload,
        key="h7164a_seed_cookie",
        path="/",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    st.session_state["_h7164a_seeded"] = True
    _log("seed_cookie_requested", cookie_name=AUTH_COOKIE_NAME)

raw = _read_auth(manager)
cookies_snapshot = {}
try:
    cookies_snapshot = manager.get_all(key=COMPONENT_KEY) or {}
except Exception as exc:
    cookies_snapshot = {"__error__": type(exc).__name__}

present = raw is not None
_log(
    "cookie_read",
    present=present,
    cookie_keys=",".join(sorted(str(k) for k in cookies_snapshot.keys())),
    get_all_empty=not bool(cookies_snapshot),
)

if st.session_state.get(DONE_KEY):
    st.success("TERMINATED: reached fail-closed signed-out state.")
    st.write({"attempts": st.session_state.get(ATTEMPTS_KEY), "raw_present": present})
    st.stop()

if present:
    st.session_state[DONE_KEY] = True
    st.session_state[ATTEMPTS_KEY] = 0
    _log("restoration_success", attempts_used=attempts_before)
    st.success("RESTORED: dummy cadivor_auth cookie read successfully.")
    st.write({"attempts_before_success": attempts_before, "raw_length": len(raw or "")})
    st.stop()

attempts = attempts_before + 1
st.session_state[ATTEMPTS_KEY] = attempts
_log("hydration_pending", attempt=attempts, max_attempts=MAX_ATTEMPTS)

if attempts >= MAX_ATTEMPTS:
    st.session_state[DONE_KEY] = True
    _log("fallback_signed_out", reason="hydration_timeout", attempts=attempts)
    st.warning("FAIL-CLOSED: max hydration attempts reached with no cookie.")
    st.write({"attempts": attempts, "mode": mode})
    st.stop()

st.markdown("### Restoring your secure workspace… (harness)")
st.caption(f"attempt {attempts}/{MAX_ATTEMPTS} | mode={mode} | run_id={run_id}")
_log("hydration_wait_stop", attempt=attempts)
st.stop()
