#!/usr/bin/env python3
"""Sprint 75.2A / 75.2A.1 — harness: deferred modules absent after authenticated_runtime import."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
stub = Path("/tmp/cadivor-752a-measure-stub")
if stub.is_dir():
    sys.path.insert(0, stub)

DEFERRED = [
    "src.pages.analysis_detail",
    "src.components.engineering_assistant",
    "integrations.supplier_aggregator",
    "src.alternative_engine",
    "src.report_generator",
    "src.portfolio_intelligence",
    "src.stripe_helper",
    "src.engineering_decision_engine",
]


def main() -> int:
    import src.authenticated_runtime  # noqa: F401

    report = {
        "deferred_absent": {name: (name not in sys.modules) for name in DEFERRED},
        "pandas_present": "pandas" in sys.modules,
        "plotly_present": "plotly" in sys.modules,
        "reportlab_absent": "reportlab" not in sys.modules,
        "engineering_decision_absent": "src.engineering_decision_engine" not in sys.modules,
    }
    report["all_deferred_absent"] = all(report["deferred_absent"].values())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["all_deferred_absent"] and report["reportlab_absent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
