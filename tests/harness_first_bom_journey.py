#!/usr/bin/env python3
"""Sprint 74 — deterministic first BOM journey harness."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_first_bom_journey import run_first_bom_journey


def main() -> int:
    scenarios = {
        "valid_csv": [{"mpn": "LM358", "quantity": 10}],
        "empty_bom": [],
        "missing_mpn_column": [{"quantity": 1}],
        "degraded_supplier": [{"mpn": "LM358", "quantity": 1}],
    }

    report = {}

    try:
        report["valid_csv"] = run_first_bom_journey(bom_rows=scenarios["valid_csv"])
    except Exception as exc:
        report["valid_csv"] = {"ok": False, "error": type(exc).__name__}

    try:
        run_first_bom_journey(bom_rows=scenarios["empty_bom"])
        report["empty_bom"] = {"ok": True}
    except ValueError as exc:
        report["empty_bom"] = {"ok": False, "stage": "validation", "message": str(exc)}
    except Exception as exc:
        report["empty_bom"] = {"ok": False, "error": type(exc).__name__}

    try:
        from src.bom_parser import normalize_bom_columns, validate_bom
        import pandas as pd

        df = pd.DataFrame(scenarios["missing_mpn_column"])
        df = normalize_bom_columns(df)
        validate_bom(df)
        report["missing_mpn_column"] = {"ok": True}
    except ValueError as exc:
        report["missing_mpn_column"] = {"ok": False, "stage": "validation", "message": str(exc)}

    report["degraded_supplier"] = run_first_bom_journey(
        bom_rows=scenarios["degraded_supplier"],
        supplier_lookup=lambda part: {
            "manufacturer_part_number": part,
            "stock_total": 0,
            "supplier_count": 0,
            "lifecycle_status": "Unknown",
            "supplier_data_verified": False,
            "source": "No supplier match",
        },
    )

    print(json.dumps(report, indent=2, sort_keys=True))
    failed = [name for name, payload in report.items() if not payload.get("ok", False)]
    return 1 if failed and failed != ["empty_bom", "missing_mpn_column"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
