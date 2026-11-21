"""Extract only explicit compliance declarations from supplier catalog records.

These helpers preserve provider wording. They do not infer compliance from a
datasheet URL, lifecycle status, distributor identity, or a missing attribute.
"""
from __future__ import annotations

import re
from typing import Any


EVIDENCE_LIVE = "live-authorized-supplier"


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _plain_value(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("Value", "value", "Name", "name", "Text", "text"):
            if value.get(key) not in (None, ""):
                return _plain_value(value[key])
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(part for item in value if (part := _plain_value(item)))
    return str(value or "").strip()


def _explicit_mapping_value(record: dict[str, Any], aliases: tuple[str, ...]) -> str:
    wanted = {_key(alias) for alias in aliases}
    for name, value in record.items():
        if _key(name) in wanted:
            text = _plain_value(value)
            if text:
                return text
    return ""


def _explicit_classification_value(record: dict[str, Any], aliases: tuple[str, ...]) -> str:
    """Read exact declaration keys from known provider classification blocks."""
    for container_name in ("Classifications", "classifications", "Compliance", "compliance"):
        container = record.get(container_name)
        if isinstance(container, dict):
            value = _explicit_mapping_value(container, aliases)
            if value:
                return value
    return ""


def _explicit_attribute_value(record: dict[str, Any], aliases: tuple[str, ...]) -> str:
    wanted = {_key(alias) for alias in aliases}
    for collection_key in ("ProductAttributes", "attributes", "Attributes", "productAttributes"):
        attributes = record.get(collection_key)
        if not isinstance(attributes, list):
            continue
        for attribute in attributes:
            if not isinstance(attribute, dict):
                continue
            name = next((
                attribute.get(key) for key in (
                    "AttributeName", "attributeName", "attributeLabel", "label", "name"
                ) if attribute.get(key) not in (None, "")
            ), "")
            if _key(name) not in wanted:
                continue
            value = next((
                attribute.get(key) for key in (
                    "AttributeValue", "attributeValue", "value", "displayValue"
                ) if attribute.get(key) not in (None, "")
            ), "")
            text = _plain_value(value)
            if text:
                return text
    return ""


def build_supplier_compliance_evidence(
    *,
    source: str,
    product: dict[str, Any],
    product_url: str = "",
    manufacturer: str = "",
    mpn: str = "",
    retrieved_at: str = "",
    rohs: str = "",
    reach: str = "",
    pfas: str = "",
) -> dict[str, dict[str, Any]]:
    """Build per-topic provenance for non-empty values returned by a supplier."""
    declarations = {"rohs": rohs, "reach": reach, "pfas": pfas}
    metadata = {
        "rohs": ("RohsStatus", "RoHSStatus", "rohsStatusCode"),
        "reach": ("ReachStatus", "REACHStatus", "reachStatus", "reachStatusCode"),
        "pfas": ("PFASStatus", "PfasStatus", "pfasStatus"),
    }
    attribute_aliases = {
        "rohs": ("RoHS", "RoHS Status", "RoHS Compliance", "RoHS Compliant"),
        "reach": ("REACH", "REACH Status", "REACH Compliance"),
        "pfas": ("PFAS", "PFAS Status", "PFAS Compliance"),
    }
    evidence: dict[str, dict[str, Any]] = {}
    for kind in ("rohs", "reach", "pfas"):
        value = str(declarations.get(kind) or "").strip()
        if not value:
            value = _explicit_mapping_value(product, metadata[kind])
        if not value:
            value = _explicit_classification_value(product, metadata[kind])
        if not value:
            value = _explicit_attribute_value(product, attribute_aliases[kind])
        if not value:
            continue
        evidence[kind] = {
            "reported_value": value,
            "source": str(source or "").strip(),
            "source_url": str(product_url or "").strip(),
            "evidence_class": EVIDENCE_LIVE,
            "retrieved_at": str(retrieved_at or "").strip(),
            "manufacturer": str(manufacturer or "").strip(),
            "mpn": str(mpn or "").strip(),
            "basis": "supplier_catalog_field",
        }
    return evidence


def stamp_supplier_compliance_evidence(result: dict[str, Any], retrieved_at: str) -> None:
    """Attach the successful exact-product lookup time to nested declarations."""
    root = result.get("compliance_evidence")
    if not isinstance(root, dict):
        return
    for node in root.values():
        if isinstance(node, dict) and not str(node.get("retrieved_at") or "").strip():
            node["retrieved_at"] = str(retrieved_at or "").strip()

