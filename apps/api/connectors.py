"""PLM/ERP/CAD interchange groundwork for the migration API.

Generic CSV import/export paths are **file workflows** — they accept uploaded
files and do not call live design-tool or vendor APIs. Vendor-specific
connectors remain blocked until customer discovery and credentials exist.
A configured flag or file-workflow availability alone must not be reported as
live service readiness.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class ConnectorCapability:
    id: str
    category: str  # plm | erp | cad
    display_name: str
    priority: int
    status: str  # file_workflow | blocked | configured_unverified | ready
    kind: str = "vendor"  # file_workflow | vendor
    supports_bom_import: bool = False
    supports_bom_export: bool = False
    supports_change_orders: bool = False
    requires_customer_decision: bool = True
    decision_needed: str = ""
    notes: str = ""
    last_verified_at: str | None = None


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
        display_name="Generic PLM BOM CSV (file workflow)",
        priority=1,
        status="file_workflow",
        kind="file_workflow",
        supports_bom_import=True,
        supports_bom_export=True,
        requires_customer_decision=False,
        notes=(
            "File-based CSV interchange only. Not a live PLM/vendor integration; "
            "usable before a vendor-specific connector is chosen."
        ),
    ),
    ConnectorCapability(
        id="plm.arena_or_propel",
        category="plm",
        display_name="Arena / Propel (candidate)",
        priority=2,
        status="blocked",
        kind="vendor",
        supports_bom_import=True,
        supports_change_orders=True,
        decision_needed="Customer discovery must choose Arena vs Propel (or other) and provide sandbox credentials.",
    ),
    ConnectorCapability(
        id="erp.generic_item_master",
        category="erp",
        display_name="Generic ERP item master CSV (file workflow)",
        priority=1,
        status="file_workflow",
        kind="file_workflow",
        supports_bom_import=True,
        supports_bom_export=True,
        requires_customer_decision=False,
        notes="File-based item-master CSV mapping. Not a live ERP API integration.",
    ),
    ConnectorCapability(
        id="erp.netsuite_or_sap",
        category="erp",
        display_name="NetSuite / SAP (candidate)",
        priority=2,
        status="blocked",
        kind="vendor",
        supports_bom_import=True,
        decision_needed="Pick NetSuite vs SAP (or other ERP) after customer discovery; sandbox OAuth required.",
    ),
    ConnectorCapability(
        id="cad.altium_or_solidworks",
        category="cad",
        display_name="Altium / SolidWorks BOM file import (file workflow)",
        priority=1,
        status="file_workflow",
        kind="file_workflow",
        supports_bom_import=True,
        requires_customer_decision=False,
        notes=(
            "Accepts CAD-exported BOM CSV/TSV files with Designator/MPN/Quantity columns. "
            "Not a live Altium or SolidWorks connector."
        ),
    ),
]


def list_connectors() -> list[dict[str, Any]]:
    items = [asdict(item) for item in REGISTRY]
    items.extend(_supplier_connector_records())
    return sorted(items, key=lambda c: (c["category"], c["priority"], c["id"]))


def _supplier_connector_records() -> list[dict[str, Any]]:
    """Expose existing distributor adapters without overstating credential health.

    These catalog integrations are implemented in the supplier aggregator. This
    readiness check only verifies that expected environment variables exist; it
    never contacts a distributor or claims those credentials were accepted.
    """
    configured = {
        "supplier.digikey": bool(
            (os.environ.get("DIGIKEY_CLIENT_ID") or "").strip()
            and (os.environ.get("DIGIKEY_CLIENT_SECRET") or "").strip()
        ),
        "supplier.mouser": bool((os.environ.get("MOUSER_API_KEY") or "").strip()),
        "supplier.newark": bool((os.environ.get("NEWARK_API_KEY") or "").strip()),
        "supplier.nexar_octopart": bool(
            ((os.environ.get("NEXAR_CLIENT_ID") or os.environ.get("OCTOPART_CLIENT_ID") or "").strip())
            and ((os.environ.get("NEXAR_CLIENT_SECRET") or os.environ.get("OCTOPART_CLIENT_SECRET") or "").strip())
        ),
    }
    names = {
        "supplier.digikey": ("DigiKey catalog search", "DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET"),
        "supplier.mouser": ("Mouser catalog search", "MOUSER_API_KEY"),
        "supplier.newark": ("Newark catalog search", "NEWARK_API_KEY"),
        "supplier.nexar_octopart": ("Nexar / Octopart search", "NEXAR_CLIENT_ID and NEXAR_CLIENT_SECRET"),
    }
    rows = []
    for priority, (connector_id, (name, requirements)) in enumerate(names.items(), start=1):
        has_credentials = configured[connector_id]
        provider_key = connector_id.rsplit(".", 1)[-1].replace("_octopart", "")
        verified_at = _recent_provider_verification(provider_key)
        status = (
            "ready" if has_credentials and verified_at else
            "configured_unverified" if has_credentials else
            "blocked"
        )
        if status == "ready":
            decision_needed = ""
            notes = (
                f"A live catalog request succeeded on {verified_at}. "
                "Verification remains current for 30 days."
            )
        elif has_credentials:
            decision_needed = ""
            notes = (
                "Credential variables are present, but no successful live catalog request "
                "is recorded within the last 30 days."
            )
        else:
            decision_needed = f"Configure {requirements} in the API environment."
            notes = f"Distributor adapter is implemented; credentials are missing ({requirements})."
        rows.append(asdict(ConnectorCapability(
            id=connector_id,
            category="supplier",
            display_name=name,
            priority=priority,
            status=status,
            kind="vendor",
            requires_customer_decision=False,
            decision_needed=decision_needed,
            notes=notes,
            last_verified_at=verified_at,
        )))
    return rows


def _recent_provider_verification(provider_key: str) -> str | None:
    """Return an operator-recorded live-check time while it is still fresh."""
    raw = (os.environ.get(f"CADIVOR_SUPPLIER_{provider_key.upper()}_VERIFIED_AT") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    age = datetime.now(timezone.utc) - parsed
    if age < timedelta(0) or age > timedelta(days=30):
        return None
    return parsed.isoformat()

def get_connector(connector_id: str) -> ConnectorCapability | None:
    for item in REGISTRY:
        if item.id == connector_id:
            return item
    for row in _supplier_connector_records():
        if row["id"] == connector_id:
            return ConnectorCapability(**row)
    return None


def sync_generic_bom_csv(
    rows: list[dict[str, Any]],
    *,
    connector_id: str = "plm.generic_bom_csv",
) -> ConnectorSyncResult:
    """Normalize a synthetic/generic BOM file import without calling external systems."""
    connector = get_connector(connector_id)
    if connector is None:
        return ConnectorSyncResult(
            connector_id=connector_id,
            ok=False,
            mode="stub",
            gap="Unknown connector",
            ran_at=datetime.now(timezone.utc).isoformat(),
        )
    if connector.status == "blocked" or connector.kind == "vendor":
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
                "source_kind": "file_workflow",
            }
        )
    return ConnectorSyncResult(
        connector_id=connector_id,
        ok=True,
        mode="file-workflow",
        records=normalized,
        gap=None if normalized else "No rows with MPN found",
        ran_at=datetime.now(timezone.utc).isoformat(),
    )


def connector_status_payload() -> dict[str, Any]:
    items = list_connectors()
    file_workflows = [c for c in items if c.get("kind") == "file_workflow" or c.get("status") == "file_workflow"]
    vendor_items = [c for c in items if c.get("kind") == "vendor"]
    live_ready = [c for c in vendor_items if c.get("status") == "ready"]
    blocked = [c for c in vendor_items if c.get("status") == "blocked"]
    configured_unverified = [c for c in vendor_items if c.get("status") == "configured_unverified"]
    # Live vendor readiness is independent of file-workflow availability.
    if live_ready and not blocked:
        live_status = "ready"
    elif live_ready or configured_unverified:
        live_status = "partial"
    else:
        live_status = "not_connected"
    return {
        "ok": True,
        "connectors": items,
        "file_workflow_count": len(file_workflows),
        "live_ready_count": len(live_ready),
        "ready_count": len(live_ready),  # live only — never counts CSV file workflows
        "blocked_count": len(blocked),
        "live_status": live_status,
        "gap": (
            "CSV file workflows accept uploaded files only. Distributor credential presence is "
            "shown as configured but unverified until an authorized live request succeeds. "
            "Direct PLM, ERP, and CAD integrations still need a provider decision and sandbox access."
        ),
        "configured_unverified_count": len(configured_unverified),
    }
