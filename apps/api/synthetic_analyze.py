"""Headless synthetic BOM analyze using production parse/risk/health modules.

Supplier HTTP, Stripe, email, and persistence are not used. Part enrichment is
deterministic synthetic evidence so health scoring can complete offline.
"""
from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from src.bom_parser import (
    aggregate_bom_rows,
    clean_bom_data,
    normalize_bom_columns,
    validate_bom,
)
from src.health_score import calculate_bom_health_score
from src.risk_engine import calculate_risk

# In-memory report store for the Next.js migration preview (sandbox only).
_REPORTS: dict[str, dict[str, Any]] = {}


def _synthetic_part(mpn: str, manufacturer: str, description: str, quantity: Any) -> dict[str, Any]:
    """Build verified-looking part evidence without calling distributors."""
    digest = int(hashlib.sha256(str(mpn).encode("utf-8")).hexdigest()[:8], 16)
    stock = 50 + (digest % 450)
    lifecycle = "Active" if digest % 7 else "NRND"
    return {
        "mpn": mpn,
        "manufacturer": manufacturer,
        "description": description,
        "quantity": quantity,
        "lifecycle_status": lifecycle,
        "stock_total": stock,
        "stock_available": stock,
        "total_market_stock": stock,
        "stock_data_complete": True,
        "supplier_data_verified": True,
        "unit_price": round(0.15 + (digest % 100) / 100.0, 3),
        "source": "synthetic-preview",
    }


def parse_bom_bytes(filename: str, payload: bytes) -> pd.DataFrame:
    buffer = io.BytesIO(payload)
    buffer.name = filename or "bom.csv"
    # load_bom expects a path; write through pandas for CSV/XLSX bytes.
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xls")):
        df = pd.read_excel(buffer)
    else:
        df = pd.read_csv(buffer)
    df = normalize_bom_columns(df)
    df = validate_bom(df)
    df = aggregate_bom_rows(df)
    return clean_bom_data(df)


def analyze_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        mpn = str(row.get("mpn_normalized") or row.get("mpn") or "").strip()
        manufacturer = str(row.get("manufacturer") or "").strip()
        description = str(row.get("description") or "").strip()
        quantity = row.get("quantity", 1)
        part = _synthetic_part(mpn, manufacturer, description, quantity)
        risk = calculate_risk(part)
        rows.append(
            {
                "MPN": mpn,
                "Manufacturer": manufacturer,
                "Description": description,
                "Quantity": quantity,
                "Lifecycle": part["lifecycle_status"],
                "Stock": part["stock_total"],
                "Risk Score": risk.get("risk_score"),
                "Risk Level": risk.get("risk_level"),
                "Risk Reasons": "; ".join(risk.get("reasons") or []),
                "Supplier Data Verified": True,
                "Stock Data Complete": True,
                "Source": "synthetic-preview",
            }
        )

    results = pd.DataFrame(rows)
    health = calculate_bom_health_score(results)
    levels = results["Risk Level"].fillna("").astype(str).str.casefold()
    analysis_id = str(uuid.uuid4())
    report = {
        "id": analysis_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "synthetic-preview",
        "filename": "",
        "total_parts": int(len(results)),
        "health_score": health.get("health_score"),
        "health_status": health.get("health_status"),
        "summary_message": health.get("summary_message"),
        "high_risk_count": int(levels.eq("high").sum()),
        "medium_risk_count": int(levels.eq("medium").sum()),
        "low_risk_count": int(levels.isin(["low", "healthy"]).sum()),
        "needs_verification_count": int(health.get("needs_verification_count") or 0),
        "parts": rows,
    }
    _REPORTS[analysis_id] = report
    return report


def analyze_upload(*, filename: str, payload: bytes) -> dict[str, Any]:
    df = parse_bom_bytes(filename, payload)
    report = analyze_dataframe(df)
    report["filename"] = filename or "bom.csv"
    _REPORTS[report["id"]] = report
    return report


def get_report(analysis_id: str) -> dict[str, Any] | None:
    return _REPORTS.get(analysis_id)


def list_report_ids() -> list[str]:
    return list(_REPORTS.keys())
