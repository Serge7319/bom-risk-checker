"""Reusable PLM/ERP/CAD connector groundwork for the migration API.

No live vendor credentials are required. Connectors are registered as stubs with
capability contracts and synthetic sync tests. Choosing a production vendor
needs customer discovery (see gap notes).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass(frozen=True)
class ConnectorCapability:
    id: str
    category: str  # plm | erp | cad
    display_name: str
    priority: int
    status: str  # stub | ready | blocked
    supports_bom_import: bool = False
    supports_bom_export: bool = False
    supports_change_orders: bool = False
    requires_customer_decision: bool = True
    decision_needed: str = ""
    notes: str = ""


@dataclass
class ConnectorSyncResult:
    connector_id: str
    ok: bool
    mode: str
    records: list[dict[str, Any]] = field(default_factory=list)
    gap: str | None = None
    ran_at: str = ""


REGISTRY: list[ConnectorCapability] = [
    ConnectorCapability(
        id="plm.generic_bom_csv",
        category="plm",
        display_name="Generic PLM BOM CSV",
        priority=1,
        status="ready",
        supports_bom_import=True,
        supports_bom_export=True,
        requires_customer_decision=False,
        notes="File-based interchange usable before a vendor-specific connector.",
    ),
    ConnectorCapability(
        id="plm.arena_or_propel",
        category="plm",
        display_name="Arena / Propel (candidate)",
        priority=2,
        status="blocked",
        supports_bom_import=True,
        supports_change_orders=True,
        decision_needed="Customer discovery must choose Arena vs Propel (or other) and provide sandbox credentials.",
    ),
    ConnectorCapability(
        id="erp.generic_item_master",
        category="erp",
        display_name="Generic ERP item master CSV",
        priority=1,
        status="ready",
        supports_bom_import=True,
        supports_bom_export=True,
        requires_customer_decision=False,
        notes="Maps item number, MPN, manufacturer, and revision fields.",
    ),
    ConnectorCapability(
        id="erp.netsuite_or_sap",
        category="erp",
        display_name="NetSuite / SAP (candidate)",
        priority=2,
        status="blocked",
        supports_bom_import=True,
        decision_needed="Pick NetSuite vs SAP (or other ERP) after customer discovery; sandbox OAuth required.",
    ),
    ConnectorCapability(
        id="cad.altium_or_solidworks",
        category="cad",
        display_name="Altium / SolidWorks BOM export",
        priority=1,
        status="ready",
        supports_bom_import=True,
        requires_customer_decision=False,
        notes="Accepts CAD-exported BOM CSV/TSV with Designator/MPN/Quantity columns.",
    ),
]


def list_connectors() -> list[dict[str, Any]]:
    return [asdict(item) for item in sorted(REGISTRY, key=lambda c: (c.category, c.priority, c.id))]


def get_connector(connector_id: str) -> ConnectorCapability | None:
    for item in REGISTRY:
        if item.id == connector_id:
            return item
    return None


def sync_generic_bom_csv(
    rows: list[dict[str, Any]],
    *,
    connector_id: str = "plm.generic_bom_csv",
) -> ConnectorSyncResult:
    """Normalize a synthetic/generic BOM import without calling external systems."""
    connector = get_connector(connector_id)
    if connector is None:
        return ConnectorSyncResult(
            connector_id=connector_id,
            ok=False,
            mode="stub",
            gap="Unknown connector",
            ran_at=datetime.now(timezone.utc).isoformat(),
        )
    if connector.status == "blocked":
        return ConnectorSyncResult(
            connector_id=connector_id,
            ok=False,
            mode="blocked",
            gap=connector.decision_needed or "Vendor decision required",
            ran_at=datetime.now(timezone.utc).isoformat(),
        )
    normalized = []
    for row in rows:
        mpn = str(row.get("MPN") or row.get("mpn") or row.get("manufacturer_part_number") or "").strip()
        if not mpn:
            continue
        normalized.append(
            {
                "mpn": mpn,
                "manufacturer": str(row.get("Manufacturer") or row.get("manufacturer") or "").strip(),
                "quantity": row.get("Quantity") or row.get("quantity") or 1,
                "designator": str(row.get("Designator") or row.get("RefDes") or "").strip(),
                "revision": str(row.get("Revision") or row.get("revision") or "").strip(),
                "source_connector": connector_id,
            }
        )
    return ConnectorSyncResult(
        connector_id=connector_id,
        ok=True,
        mode="synthetic-file",
        records=normalized,
        gap=None if normalized else "No rows with MPN found",
        ran_at=datetime.now(timezone.utc).isoformat(),
    )


def connector_status_payload() -> dict[str, Any]:
    items = list_connectors()
    return {
        "ok": True,
        "connectors": items,
        "ready_count": sum(1 for c in items if c["status"] == "ready"),
        "blocked_count": sum(1 for c in items if c["status"] == "blocked"),
        "gap": (
            "Vendor-specific PLM/ERP connectors need a customer discovery decision "
            "and sandbox credentials before live sync."
        ),
    }
