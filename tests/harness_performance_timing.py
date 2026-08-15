#!/usr/bin/env python3
"""Sprint 75.1 — performance timing harness (disabled-path + enabled smoke)."""
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
    report["no_sleep_in_helper"] = "time.sleep" not in (ROOT / "src/performance_timing.py").read_text()

    ok = all(bool(v) for v in report.values())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
