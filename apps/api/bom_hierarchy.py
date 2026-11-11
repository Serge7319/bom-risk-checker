"""Multi-level BOM quantity and risk roll-up for the migration API.

Pure functions over analyzed part rows. Does not invent supplier evidence.
Flat BOMs (no parent_mpn / assembly lines) pass through unchanged.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.normalizer import normalize_part_number

# Needs verification must outrank Low/Healthy so missing evidence never
# collapses to "zero risk" / Low during assembly roll-up.
_RISK_RANK = {
    "high": 4,
    "medium": 3,
    "needs verification": 2,
    "not assessed": 2,
    "unknown": 2,
    "low": 1,
    "healthy": 1,
    "": 0,
}


def _text(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null", "<na>"}:
        return ""
    return text


def _mpn_key(value: Any) -> str:
    """Canonical hierarchy key so hyphenated MPNs still link to normalized parents."""
    raw = _text(value)
    if not raw:
        return ""
    return normalize_part_number(raw) or raw.casefold()


def _risk_rank(level: Any) -> int:
    return _RISK_RANK.get(_text(level).casefold(), 0)


def _max_risk_label(levels: list[str]) -> str:
    if not levels:
        return "Unknown"
    best = max(levels, key=_risk_rank)
    cleaned = _text(best)
    return cleaned or "Unknown"


def _qty(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def has_hierarchy(parts: list[dict[str, Any]]) -> bool:
    for part in parts:
        if _text(part.get("parent_mpn") or part.get("Parent MPN")):
            return True
        line = _text(part.get("line_type") or part.get("Line Type")).casefold()
        if line in {"assembly", "subassembly", "sub-assembly"}:
            return True
    return False


def _index_parts(parts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for part in parts:
        key = _mpn_key(part.get("MPN") or part.get("mpn"))
        if not key:
            continue
        # Last write wins for assembly metadata; children still listed separately.
        indexed[key] = part
    return indexed


def _children_map(parts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    children: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for part in parts:
        parent = _mpn_key(part.get("parent_mpn") or part.get("Parent MPN"))
        if parent:
            children[parent].append(part)
    return children


def compute_effective_quantities(
    parts: list[dict[str, Any]], *, top_build_quantity: float = 1.0
) -> list[dict[str, Any]]:
    """Multiply quantity-per-parent along each path to the top product.

    Keeps quantity_per_parent as the BOM line quantity. effective_quantity is
    the product of that line quantity and every parent assembly quantity in the
    path (including the optional top_build_quantity multiplier).
    """
    by_mpn = _index_parts(parts)
    children = _children_map(parts)
    roots = [
        p
        for p in parts
        if not _text(p.get("parent_mpn") or p.get("Parent MPN"))
    ]
    if not roots:
        roots = list(parts)

    effective: dict[str, float] = {}

    def walk(node: dict[str, Any], inherited: float, trail: list[str]) -> None:
        key = _mpn_key(node.get("MPN") or node.get("mpn"))
        if not key:
            return
        if key in trail:
            return
        per_parent = _qty(node.get("Quantity") if "Quantity" in node else node.get("quantity"))
        if per_parent <= 0:
            per_parent = 1.0
        rolled = inherited * per_parent
        effective[key] = effective.get(key, 0.0) + rolled
        for child in children.get(key, []):
            walk(child, rolled, trail + [key])

    for root in roots:
        walk(root, float(top_build_quantity), [])

    enriched: list[dict[str, Any]] = []
    for part in parts:
        row = dict(part)
        key = _mpn_key(part.get("MPN") or part.get("mpn"))
        per_parent = _qty(
            part.get("Quantity") if "Quantity" in part else part.get("quantity")
        )
        row["quantity_per_parent"] = per_parent
        row["Quantity per Parent"] = per_parent
        row["effective_quantity"] = effective.get(key, per_parent)
        row["Effective Quantity"] = row["effective_quantity"]
        row["bom_path"] = _path_for(key, by_mpn)
        enriched.append(row)
    return enriched


def _path_for(mpn_key: str, by_mpn: dict[str, dict[str, Any]]) -> str:
    trail: list[str] = []
    seen: set[str] = set()
    current = mpn_key
    while current and current not in seen:
        seen.add(current)
        node = by_mpn.get(current) or {}
        display = _text(node.get("MPN") or node.get("mpn")) or current
        trail.append(display)
        parent = _mpn_key(node.get("parent_mpn") or node.get("Parent MPN"))
        current = parent
    return " / ".join(reversed(trail))


def rollup_assemblies(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll component risk to each assembly and the top-level product."""
    enriched = compute_effective_quantities(parts)
    children = _children_map(enriched)
    by_mpn = _index_parts(enriched)

    assemblies: list[dict[str, Any]] = []

    def _leaf_evidence_source(node: dict[str, Any]) -> str:
        for key in (
            "evidence_source",
            "evidence_class",
            "Source",
            "source",
            "price_source",
        ):
            value = _text(node.get(key))
            if value:
                return value
        return "missing"

    def child_risk_summary(mpn_key: str) -> dict[str, Any]:
        stack = list(children.get(mpn_key, []))
        leaf_risks: list[str] = []
        contributors: list[dict[str, Any]] = []
        seen: set[str] = set()
        while stack:
            node = stack.pop()
            child_key = _mpn_key(node.get("MPN") or node.get("mpn"))
            if not child_key or child_key in seen:
                continue
            seen.add(child_key)
            kids = children.get(child_key, [])
            if kids:
                stack.extend(kids)
                continue
            level = _text(node.get("Risk Level") or node.get("risk_level") or "Unknown")
            leaf_risks.append(level)
            # Surface High/Medium and Needs verification contributors; Low stays out.
            if _risk_rank(level) >= _RISK_RANK["needs verification"]:
                contributors.append(
                    {
                        "mpn": _text(node.get("MPN") or node.get("mpn")) or child_key,
                        "risk_level": level,
                        "risk_score": node.get("Risk Score") or node.get("risk_score"),
                        "effective_quantity": node.get("effective_quantity"),
                        "quantity_per_parent": node.get("quantity_per_parent"),
                        "bom_path": node.get("bom_path"),
                        "evidence_source": _leaf_evidence_source(node),
                        "why": node.get("Risk Reasons") or node.get("risk_reasons") or "",
                    }
                )
        rolled = _max_risk_label(leaf_risks)
        high = sum(1 for level in leaf_risks if _risk_rank(level) >= _RISK_RANK["high"])
        medium = sum(
            1 for level in leaf_risks if _risk_rank(level) == _RISK_RANK["medium"]
        )
        needs = sum(
            1
            for level in leaf_risks
            if _risk_rank(level) == _RISK_RANK["needs verification"]
        )
        return {
            "rolled_risk_level": rolled,
            "leaf_count": len(leaf_risks),
            "high_risk_leaves": high,
            "medium_risk_leaves": medium,
            "needs_verification_leaves": needs,
            "contributors": sorted(
                contributors,
                key=lambda row: (-_risk_rank(row["risk_level"]), str(row["mpn"])),
            ),
        }

    assembly_nodes = []
    for part in enriched:
        key = _mpn_key(part.get("MPN") or part.get("mpn"))
        line = _text(part.get("line_type") or part.get("Line Type")).casefold()
        is_assembly = line in {"assembly", "subassembly", "sub-assembly"} or bool(
            children.get(key)
        )
        if is_assembly:
            assembly_nodes.append(part)

    for part in assembly_nodes:
        key = _mpn_key(part.get("MPN") or part.get("mpn"))
        display = _text(part.get("MPN") or part.get("mpn")) or key
        summary = child_risk_summary(key)
        parent_raw = _text(part.get("parent_mpn") or part.get("Parent MPN"))
        assemblies.append(
            {
                "mpn": display,
                "description": _text(part.get("Description") or part.get("description")),
                "parent_mpn": parent_raw or None,
                "quantity_per_parent": part.get("quantity_per_parent"),
                "effective_quantity": part.get("effective_quantity"),
                "bom_path": part.get("bom_path"),
                "line_type": "assembly",
                **summary,
            }
        )

    assembly_keys = {_mpn_key(a["mpn"]) for a in assemblies}
    roots = [
        a
        for a in assemblies
        if not a.get("parent_mpn") or _mpn_key(a["parent_mpn"]) not in assembly_keys
    ]
    if not roots and assemblies:
        roots = assemblies[:1]
    top = roots[0] if roots else None

    return {
        "has_hierarchy": True,
        "parts": enriched,
        "assemblies": assemblies,
        "top_level": top,
        "priority_contributors": (top or {}).get("contributors", [])[:12],
    }


def attach_hierarchy_fields(source_df_row: dict[str, Any]) -> dict[str, Any]:
    """Copy optional hierarchy columns from the cleaned BOM frame into a result row."""
    parent_raw = _text(source_df_row.get("parent_mpn"))
    # Normalized key for joins only; keep the BOM spelling (including hyphens)
    # for customer-facing Parent MPN display.
    parent_key = normalize_part_number(parent_raw) if parent_raw else ""
    # Only keep Line Type when the BOM supplied/mapped it. Do not invent "part".
    line_type = _text(source_df_row.get("line_type") or source_df_row.get("Line Type"))
    level = source_df_row.get("bom_level")
    return {
        "parent_mpn": parent_key or None,
        "parent_mpn_display": parent_raw or None,
        "Parent MPN": parent_raw or None,
        "line_type": line_type or None,
        "Line Type": line_type or None,
        "bom_level": level,
    }
