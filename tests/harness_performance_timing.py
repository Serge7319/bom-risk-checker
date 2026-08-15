#!/usr/bin/env python3
"""Sprint 75.1 / 75.1.2 — performance timing harness (disabled + control-flow)."""
from __future__ import annotations

import importlib
import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    report = {}
    os.environ.pop("CADIVOR_STARTUP_TIMING", None)
    sys.modules.pop("src.performance_timing", None)
    mod = importlib.import_module("src.performance_timing")

    buf = io.StringIO()
    with redirect_stdout(buf):
        with mod.timed_phase("harness.disabled"):
            pass
    report["disabled_silent"] = "CADIVOR_PERF" not in buf.getvalue()

    from streamlit.runtime.scriptrunner_utils.exceptions import (
        RerunException,
        StopException,
    )
    from streamlit.runtime.scriptrunner_utils.script_requests import RerunData

    # Disabled path must propagate real Streamlit control exceptions.
    continued = False
    try:
        with mod.timed_phase("harness.disabled_rerun"):
            raise RerunException(RerunData())
        continued = True
    except RerunException:
        report["disabled_rerun_propagates"] = True
    else:
        report["disabled_rerun_propagates"] = False
    report["disabled_rerun_no_continue"] = not continued

    continued = False
    try:
        with mod.timed_phase("harness.disabled_stop"):
            raise StopException()
        continued = True
    except StopException:
        report["disabled_stop_propagates"] = True
    else:
        report["disabled_stop_propagates"] = False
    report["disabled_stop_no_continue"] = not continued

    src = (ROOT / "src/performance_timing.py").read_text(encoding="utf-8")
    finally_idx = src.index("finally:", src.index("def timed_phase("))
    next_def = src.find("\ndef ", finally_idx + 1)
    finally_block = src[finally_idx : next_def if next_def > 0 else None]
    report["finally_has_no_return"] = "return" not in finally_block

    os.environ["CADIVOR_STARTUP_TIMING"] = "true"
    sys.modules.pop("src.performance_timing", None)
    mod = importlib.import_module("src.performance_timing")
    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        with mod.timed_phase("harness.enabled", attempt=1, max_attempts=6):
            pass
    line = buf2.getvalue().strip()
    report["enabled_emits"] = line.startswith("CADIVOR_PERF ")
    payload = json.loads(line.split(" ", 1)[1]) if report["enabled_emits"] else {}
    report["has_duration"] = "duration_ms" in payload
    report["phase_ok"] = payload.get("phase") == "harness.enabled"
    report["no_sleep_in_helper"] = "time.sleep" not in src

    continued = False
    try:
        with mod.timed_phase("harness.enabled_rerun"):
            raise RerunException(RerunData())
        continued = True
    except RerunException:
        report["enabled_rerun_propagates"] = True
    else:
        report["enabled_rerun_propagates"] = False
    report["enabled_rerun_no_continue"] = not continued

    ok = all(bool(v) for v in report.values())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
