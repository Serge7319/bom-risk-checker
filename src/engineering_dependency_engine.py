"""Cadivor Engineering Dependency Engine — Sprint 68.

Pure intelligence layer: structured data only. No HTML, Streamlit, or rendering.
Designed for future Engineering Change Simulation (multi-recommendation evaluation).
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.bom_intelligence import classify_component_type

DOMAIN_DEFAULTS: Dict[str, str] = {
    "Firmware": "Recommended replacement affects programmable logic or software behavior.",
    "PCB Layout": "Package or electrical characteristics may require layout review.",
    "Mechanical": "Mechanical fit, enclosure, or mounting may need verification.",
    "Manufacturing": "Change impacts assembly or production process.",
    "Procurement": "Sourcing or supplier qualification work is required.",
    "Compliance": "Qualification or regulatory evidence may be needed.",
    "Test": "Validation testing is required before release.",
    "Documentation": "Engineering records or change documentation must be updated.",
}

VALIDATION_CATALOG: Dict[str, str] = {
    "Visual inspection": "Confirm footprint and marking compatibility.",
    "Electrical testing": "Verify electrical parameters against design limits.",
    "Functional testing": "Validate system behavior with the new component.",
    "Firmware regression": "Re-run firmware test suite after logic-affecting change.",
    "Environmental testing": "Confirm operation across temperature and humidity.",
    "EMC testing": "Verify emissions and immunity after electrical change.",
    "Production pilot": "Run limited build to confirm assembly yield.",
    "Full qualification": "Complete formal qualification for production release.",
}

DIFFICULTY_LEVELS: tuple[str, ...] = (
    "Very Easy",
    "Easy",
    "Moderate",
    "High",
    "Major Redesign",
)

ENGINEERING_RISK_LEVELS: tuple[str, ...] = ("Low", "Medium", "High", "Critical")
SCHEDULE_IMPACT_LEVELS: tuple[str, ...] = ("Low", "Medium", "High")
ROI_LABELS: tuple[str, ...] = ("Low", "Medium", "High")

PROGRAMMABLE_COMPONENT_TYPES: frozenset[str] = frozenset(
    {"MCU/Processor", "Logic", "Memory", "Power"}
)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_engineering_roi(
    *,
    health_gain: float = 0.0,
    effort_hours: float = 1.0,
    supply_risk_reduction: float = 0.0,
    lifecycle_issues_removed: float = 0.0,
    sourcing_issues_removed: float = 0.0,
    schedule_improvement_weeks: float = 0.0,
    procurement_effort_reduction_hours: float = 0.0,
) -> Dict[str, Any]:
    """Compute engineering ROI with a stable public API.

    Sprint 68 uses ``health_gain / effort_hours``. Additional keyword arguments
    capture future factors (lifecycle, supply chain, procurement, schedule)
    without changing the function signature.
    """
    effort = max(1.0, _number(effort_hours, 1.0))
    risk_removed = _number(health_gain, 0.0)

    # Extension point — apply weights here as simulation matures.
    numerator = risk_removed
    # numerator += lifecycle_issues_removed * _LIFECYCLE_WEIGHT
    # numerator += supply_risk_reduction * _SUPPLY_WEIGHT
    # numerator += schedule_improvement_weeks * _SCHEDULE_WEIGHT
    # numerator += procurement_effort_reduction_hours * _PROCUREMENT_WEIGHT

    score = numerator / effort
    if score >= 1.2:
        label = "High"
    elif score >= 0.5:
        label = "Medium"
    else:
        label = "Low"

    return {
        "label": label,
        "score": round(score, 2),
        "risk_removed": round(risk_removed, 1),
        "effort_hours": int(effort),
        "formula": "health_gain / effort_hours",
        "components": {
            "health_gain": round(risk_removed, 1),
            "effort_hours": int(effort),
            "supply_risk_reduction": round(_number(supply_risk_reduction), 1),
            "lifecycle_issues_removed": int(_number(lifecycle_issues_removed)),
            "sourcing_issues_removed": int(_number(sourcing_issues_removed)),
            "schedule_improvement_weeks": int(_number(schedule_improvement_weeks)),
            "procurement_effort_reduction_hours": round(
                _number(procurement_effort_reduction_hours), 1
            ),
        },
    }


def _part_lookup(parts: Sequence[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    lookup: Dict[str, Mapping[str, Any]] = {}
    for part in parts:
        mpn = _text(part.get("mpn") or part.get("MPN") or part.get("part_number")).upper()
        if mpn:
            lookup[mpn] = part
    return lookup


def _enrich_part_lookup(
    lookup: Dict[str, Mapping[str, Any]],
    intelligence: Optional[Mapping[str, Any]],
) -> None:
    if not intelligence:
        return
    enriched = intelligence.get("enriched_parts")
    rows: List[Mapping[str, Any]] = []
    if enriched is not None and hasattr(enriched, "to_dict"):
        rows = enriched.to_dict("records")  # type: ignore[union-attr]
    elif isinstance(enriched, list):
        rows = enriched
    for row in rows:
        mpn = _text(row.get("MPN") or row.get("mpn") or row.get("part_number")).upper()
        if mpn and mpn not in lookup:
            lookup[mpn] = row


def _impact_level(value: Any) -> str:
    return _text(value).lower()


def _infer_change_difficulty(action: Mapping[str, Any]) -> str:
    effort_hours = int(_number(action.get("effort_hours"), 1))
    route = _text(action.get("action_route")).lower()
    score = int(_number(action.get("score"), 0))
    why = _text(action.get("why")).lower()

    if effort_hours >= 24 or (route == "alternative" and score >= 80):
        return "Major Redesign"
    if effort_hours >= 12 or any(term in why for term in ("obsolete", "eol", "nrnd")):
        return "High"
    if effort_hours >= 6:
        return "Moderate"
    if effort_hours >= 3:
        return "Easy"
    return "Very Easy"


def _infer_schedule_impact(action: Mapping[str, Any]) -> str:
    schedule = _text(action.get("schedule")).lower()
    impacts = action.get("impacts") or {}
    schedule_level = _impact_level(impacts.get("schedule"))

    if "before production" in schedule or schedule_level in {"high", "critical"}:
        return "High"
    if "this week" in schedule or schedule_level == "medium":
        return "Medium"
    return "Low"


def _infer_engineering_risk(action: Mapping[str, Any]) -> str:
    score = int(_number(action.get("score"), 0))
    if score >= 85:
        return "Critical"
    if score >= 65:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def _projected_bom_health(action: Mapping[str, Any]) -> Dict[str, Any]:
    improvement = action.get("improvement") or {}
    decision_impact = action.get("decision_impact") or {}
    health_block = decision_impact.get("health") or {}

    if health_block:
        before = int(_number(health_block.get("before"), improvement.get("health_before", 0)))
        after = int(_number(health_block.get("after"), improvement.get("health_after", 0)))
        gain = int(_number(health_block.get("gain"), after - before if after >= before else 0))
        if not gain:
            gain = int(_number(improvement.get("health_gain"), max(0, after - before)))
        return {
            "before": before,
            "after": after,
            "gain": gain,
            "source": "decision_impact",
        }
    return {
        "before": int(_number(improvement.get("health_before"), 0)),
        "after": int(_number(improvement.get("health_after"), 0)),
        "gain": int(_number(improvement.get("health_gain"), 0)),
        "source": "improvement",
    }


def _infer_engineering_domains(
    action: Mapping[str, Any],
    *,
    component_type: str,
) -> List[Dict[str, str]]:
    domains: List[Dict[str, str]] = []
    seen: set[str] = set()

    def add(domain: str, *, evidence: str = "") -> None:
        if domain in seen:
            return
        seen.add(domain)
        explanation = DOMAIN_DEFAULTS.get(domain, "")
        if evidence:
            explanation = f"{explanation} {evidence}".strip()
        domains.append({"domain": domain, "explanation": explanation})

    category = _text(action.get("category")).lower()
    route = _text(action.get("action_route")).lower()
    recommendation = _text(action.get("recommendation") or action.get("title")).lower()
    owner = _text(action.get("owner")).lower()
    why = _text(action.get("why")).lower()
    impacts = action.get("impacts") or {}

    lifecycle_signal = any(
        term in text
        for text in (why, recommendation)
        for term in ("obsolete", "eol", "end of life", "lifecycle", "nrnd")
    )
    replacement = route in {"alternative", "replacement"} or any(
        term in recommendation for term in ("replace", "substitute", "alternative", "migrate")
    )

    if component_type in PROGRAMMABLE_COMPONENT_TYPES or any(
        term in recommendation or term in why
        for term in ("firmware", "software", "mcu", "microcontroller", "programmable")
    ):
        evidence = f"Component type: {component_type}." if component_type != "Other" else ""
        add("Firmware", evidence=evidence)

    if replacement or route == "alternative" or any(
        term in recommendation for term in ("layout", "footprint", "package")
    ):
        add("PCB Layout")

    if component_type == "Connector" or any(
        term in recommendation for term in ("mechanical", "enclosure", "mount", "connector")
    ):
        add("Mechanical")

    eng_impact = _impact_level(impacts.get("engineering"))
    prod_impact = _impact_level(impacts.get("production"))
    if (
        eng_impact in {"high", "critical"}
        or prod_impact in {"high", "critical"}
        or category in {"engineering", "lifecycle"}
        or replacement
        or lifecycle_signal
    ):
        add("Manufacturing")

    if (
        category in {"procurement", "sourcing", "supply chain"}
        or "procurement" in owner
        or _impact_level(impacts.get("procurement")) in {"high", "critical"}
    ):
        add("Procurement")

    if lifecycle_signal or any(
        term in recommendation for term in ("compliance", "qualification", "regulatory")
    ):
        add("Compliance")

    if replacement or route != "monitor":
        add("Test")

    if replacement or lifecycle_signal:
        add("Documentation")

    if not domains:
        add(
            "Documentation",
            evidence="Confirm engineering records reflect the recommended action.",
        )

    return domains


def _infer_validation_required(
    action: Mapping[str, Any],
    domains: Sequence[Mapping[str, str]],
    *,
    change_difficulty: str,
) -> List[Dict[str, str]]:
    domain_names = {_text(item.get("domain")) for item in domains}
    validations: List[Dict[str, str]] = []
    seen: set[str] = set()

    def add(step: str) -> None:
        if step in seen:
            return
        seen.add(step)
        validations.append(
            {
                "step": step,
                "explanation": VALIDATION_CATALOG.get(step, ""),
            }
        )

    route = _text(action.get("action_route")).lower()
    why = _text(action.get("why")).lower()
    lifecycle_signal = any(term in why for term in ("obsolete", "eol", "nrnd"))

    add("Visual inspection")

    if route in {"alternative", "replacement"} or "PCB Layout" in domain_names:
        add("Electrical testing")

    if route in {"alternative", "replacement"} or "Firmware" in domain_names:
        add("Functional testing")

    if "Firmware" in domain_names:
        add("Firmware regression")

    if lifecycle_signal:
        add("Environmental testing")

    if "Compliance" in domain_names or int(_number(action.get("score"), 0)) >= 75:
        add("EMC testing")

    if change_difficulty in {"Moderate", "High", "Major Redesign"}:
        add("Production pilot")

    if lifecycle_signal and change_difficulty in {"High", "Major Redesign"}:
        add("Full qualification")

    return validations


def analyze_action_dependency(
    action: Mapping[str, Any],
    *,
    component_type: str = "Other",
    action_index: int = 0,
) -> Dict[str, Any]:
    """Analyze engineering dependency footprint for a single recommendation."""
    change_difficulty = _infer_change_difficulty(action)
    domains = _infer_engineering_domains(action, component_type=component_type)
    validation = _infer_validation_required(
        action,
        domains,
        change_difficulty=change_difficulty,
    )
    projected = _projected_bom_health(action)
    improvement = action.get("improvement") or {}
    decision_impact = action.get("decision_impact") or {}

    roi = compute_engineering_roi(
        health_gain=projected["gain"],
        effort_hours=_number(action.get("effort_hours"), 1),
        supply_risk_reduction=_number(improvement.get("supply_risk_reduction"), 0),
        lifecycle_issues_removed=_number(improvement.get("lifecycle_issues_removed"), 0),
        sourcing_issues_removed=_number(improvement.get("sourcing_issues_removed"), 0),
        schedule_improvement_weeks=_number(decision_impact.get("schedule_improvement_weeks"), 0),
    )

    part_number = _text(action.get("part_number"), f"action_{action_index}")
    recommendation_key = (
        f"{part_number}::{_text(action.get('recommendation') or action.get('title'))}"
    )

    return {
        "part_number": part_number,
        "recommendation_key": recommendation_key,
        "action_index": action_index,
        "engineering_impact": domains,
        "validation_required": validation,
        "change_difficulty": change_difficulty,
        "schedule_impact": _infer_schedule_impact(action),
        "engineering_risk": _infer_engineering_risk(action),
        "estimated_effort": _text(action.get("effort")),
        "effort_hours": int(_number(action.get("effort_hours"), 1)),
        "projected_bom_health": projected,
        "engineering_roi": roi,
    }


def build_engineering_dependency_report(
    *,
    raw_actions: Sequence[Mapping[str, Any]],
    parts: Optional[Sequence[Mapping[str, Any]]] = None,
    intelligence: Optional[Mapping[str, Any]] = None,
    advisor: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a simulation-ready dependency report for one or more recommendations."""
    _ = advisor  # reserved for future cross-action context
    part_lookup = _part_lookup(list(parts or []))
    _enrich_part_lookup(part_lookup, intelligence)

    items: List[Dict[str, Any]] = []
    by_part: Dict[str, List[int]] = {}
    by_key: Dict[str, int] = {}

    for idx, action in enumerate(raw_actions):
        mpn = _text(action.get("part_number")).upper()
        part = part_lookup.get(mpn)
        component_type = classify_component_type(dict(part or {"MPN": mpn}))
        item = analyze_action_dependency(
            action,
            component_type=component_type,
            action_index=idx,
        )
        items.append(item)
        if mpn:
            by_part.setdefault(mpn, []).append(idx)
        by_key[item["recommendation_key"]] = idx

    if items:
        highest_roi = max(
            items,
            key=lambda row: _number(row["engineering_roi"].get("score"), 0),
        )
        lowest_effort = min(items, key=lambda row: _number(row.get("effort_hours"), 999))
        firmware_items = [
            row
            for row in items
            if any(domain["domain"] == "Firmware" for domain in row["engineering_impact"])
        ]
    else:
        highest_roi = None
        lowest_effort = None
        firmware_items = []

    return {
        "version": 1,
        "items": items,
        "summary": {
            "action_count": len(items),
            "total_effort_hours": sum(int(_number(row.get("effort_hours"), 0)) for row in items),
            "combined_health_gain": sum(
                int(_number(row["projected_bom_health"].get("gain"), 0)) for row in items
            ),
            "highest_roi": highest_roi,
            "lowest_effort": lowest_effort,
            "firmware_action_count": len(firmware_items),
            "domains_touched": sorted(
                {
                    domain["domain"]
                    for row in items
                    for domain in row["engineering_impact"]
                }
            ),
        },
        "indexes": {
            "by_part_number": by_part,
            "by_recommendation_key": by_key,
        },
    }


def attach_dependency_to_actions(
    formatted_actions: List[Dict[str, Any]],
    report: Mapping[str, Any],
    *,
    raw_actions: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Merge dependency analysis into formatted action dicts."""
    items = list(report.get("items") or [])
    raw = list(raw_actions or [])

    for idx, action in enumerate(formatted_actions):
        item: Optional[Dict[str, Any]] = items[idx] if idx < len(items) else None
        if item is None and idx < len(raw):
            mpn = _text(raw[idx].get("part_number")).upper()
            refs = ((report.get("indexes") or {}).get("by_part_number") or {}).get(mpn) or []
            if refs:
                item = items[refs[0]]
        if item:
            action["dependency"] = item
    return formatted_actions


def query_dependency_report(report: Mapping[str, Any], question: str) -> Dict[str, Any]:
    """Answer common dependency questions from a structured report."""
    q = _text(question).lower()
    items = list(report.get("items") or [])
    summary = report.get("summary") or {}

    if not items:
        return {"answer": None, "reason": "No dependency items in report."}

    if "highest roi" in q or "best roi" in q:
        item = summary.get("highest_roi") or max(
            items,
            key=lambda row: _number(row["engineering_roi"].get("score"), 0),
        )
        return {"answer": item, "metric": "engineering_roi"}

    if "lowest effort" in q or "easiest" in q:
        item = summary.get("lowest_effort") or min(
            items,
            key=lambda row: _number(row.get("effort_hours"), 999),
        )
        return {"answer": item, "metric": "effort_hours"}

    if "firmware" in q:
        matched = [
            row
            for row in items
            if any(domain["domain"] == "Firmware" for domain in row["engineering_impact"])
        ]
        return {"answer": matched, "metric": "engineering_impact", "domain": "Firmware"}

    if "pcb" in q or "layout" in q:
        matched = [
            row
            for row in items
            if any(domain["domain"] == "PCB Layout" for domain in row["engineering_impact"])
        ]
        return {"answer": matched, "metric": "engineering_impact", "domain": "PCB Layout"}

    if "manufacturing" in q:
        matched = [
            row
            for row in items
            if any(domain["domain"] == "Manufacturing" for domain in row["engineering_impact"])
        ]
        return {"answer": matched, "metric": "engineering_impact", "domain": "Manufacturing"}

    if "critical risk" in q or "highest risk" in q:
        rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        item = min(items, key=lambda row: rank.get(_text(row.get("engineering_risk")), 9))
        return {"answer": item, "metric": "engineering_risk"}

    return {"answer": items, "metric": "all", "note": "Unrecognized question; returning all items."}
