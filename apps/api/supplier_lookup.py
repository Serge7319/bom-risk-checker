"""Authorized supplier lookup path for the migration API (mocked by default).

Live HTTP calls stay disabled unless CADIVOR_MIGRATION_SUPPLIER_LIVE=1 AND
provider credentials are present on the migration service. Until then, callers
receive clearly labeled mock/synthetic responses. Never copy Streamlit secrets.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable

from apps.api.evidence_contract import EVIDENCE_LIVE, EVIDENCE_SYNTHETIC, EVIDENCE_MISSING
from src.decision_packet_evidence import exact_supplier_evidence
from src.normalizer import normalize_part_number


def live_lookups_enabled() -> bool:
    if (os.environ.get("CADIVOR_MIGRATION_SUPPLIER_LIVE") or "").strip() != "1":
        return False
    # Require at least one provider credential to be present locally; still do
    # not auto-call until a transport is wired and authorized.
    has_cred = any(
        (os.environ.get(name) or "").strip()
        for name in (
            "MOUSER_API_KEY",
            "DIGIKEY_CLIENT_ID",
            "NEWARK_API_KEY",
        )
    )
    return has_cred and (os.environ.get("CADIVOR_MIGRATION_SUPPLIER_TRANSPORT_READY") or "").strip() == "1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mock_authorized_match(mpn: str) -> dict[str, Any] | None:
    """Deterministic mock catalog for regression tests (not live evidence)."""
    key = normalize_part_number(mpn)
    catalog = {
        "RES10K": {
            "manufacturer_part_number": "RES10K",
            "manufacturer": "Mock Components Inc",
            "source": "Mock Authorized Distributor",
            "lifecycle_status": "Active",
            "product_detail_url": "https://example.test/parts/RES10K",
            "datasheet_url": "https://example.test/datasheets/RES10K.pdf",
            "unit_price": 0.12,
            "currency": "USD",
            "stock": 1500,
            "supplier_data_verified": True,
            "provider_status": "AVAILABLE",
        },
        "CAP100U": {
            "manufacturer_part_number": "CAP100U",
            "manufacturer": "Mock Caps Ltd",
            "source": "Mock Authorized Distributor",
            "lifecycle_status": "NRND",
            "product_detail_url": "https://example.test/parts/CAP100U",
            "datasheet_url": "https://example.test/datasheets/CAP100U.pdf",
            "unit_price": 0.45,
            "currency": "USD",
            "stock": 80,
            "supplier_data_verified": True,
            "provider_status": "AVAILABLE",
        },
    }
    return catalog.get(key)


def lookup_exact_part(
    mpn: str,
    *,
    transport: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Return an evidence envelope for an exact part match.

    Default path uses the mock catalog and labels results as synthetic-preview.
    When live mode is fully authorized, ``transport`` may supply a live record;
    exact MPN matching is still enforced via ``exact_supplier_evidence``.
    """
    requested = str(mpn or "").strip()
    if not requested:
        return {
            "ok": False,
            "evidence_class": EVIDENCE_MISSING,
            "gap": "MPN required",
            "live_lookups_enabled": live_lookups_enabled(),
        }

    record: dict[str, Any] | None = None
    used_live = False
    if live_lookups_enabled() and transport is not None:
        record = transport(requested)
        used_live = True
    else:
        record = mock_authorized_match(requested)

    if not record:
        return {
            "ok": True,
            "requested_mpn": requested,
            "evidence_class": EVIDENCE_MISSING,
            "match": None,
            "synthetic": True,
            "live_lookups_enabled": live_lookups_enabled(),
            "gap": "No exact authorized-distributor match in the configured catalog.",
        }

    stamped = dict(record)
    stamped.setdefault("retrieved_at", _utc_now())
    exact = exact_supplier_evidence(requested, stamped)
    if not exact:
        return {
            "ok": True,
            "requested_mpn": requested,
            "evidence_class": EVIDENCE_MISSING,
            "match": None,
            "synthetic": True,
            "live_lookups_enabled": live_lookups_enabled(),
            "gap": "Supplier result rejected: not an exact MPN identity match.",
        }

    evidence_class = EVIDENCE_LIVE if used_live else EVIDENCE_SYNTHETIC
    return {
        "ok": True,
        "requested_mpn": requested,
        "evidence_class": evidence_class,
        "synthetic": not used_live,
        "live_lookups_enabled": live_lookups_enabled(),
        "match": {
            **exact,
            "unit_price": stamped.get("unit_price"),
            "currency": stamped.get("currency") or "USD",
            "stock": stamped.get("stock"),
            "units": {
                "unit_price": stamped.get("unit_price"),
                "currency": stamped.get("currency") or "USD",
                "stock": stamped.get("stock"),
            },
            "retrieved_at": exact.get("retrieved_at") or stamped.get("retrieved_at"),
            "source_url": exact.get("product_detail_url") or "",
        },
        "gap": (
            None
            if used_live
            else "Mock authorized-distributor path. Not live supplier evidence."
        ),
    }
