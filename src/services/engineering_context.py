"""Unified engineering context for Cadivor Sprint 34.3.

This module turns the records already stored across Cadivor into one stable,
provider-neutral context object. UI pages, reports, notifications, simulations,
and the future AI assistant can consume the same structure without knowing the
underlying Supabase table layout.

The implementation is intentionally defensive. Cadivor installations may have
older schemas, missing optional tables, or legacy rows without workspace/user
columns. Missing optional evidence is reported in ``coverage`` rather than
breaking the application.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


def _text(value: Any, default: str = "") -> str:
    value = "" if value is None else str(value).strip()
    return value or default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    return int(round(_number(value, default)))


def _first(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return default


def _execute_rows(query: Any) -> list[dict[str, Any]]:
    try:
        response = query.execute()
        return [dict(row) for row in (response.data or [])]
    except Exception:
        return []


def _query_optional(
    supabase: Any,
    table: str,
    *,
    analysis_id: str,
    user_id: str = "",
    workspace_id: str = "",
    limit: int = 100,
    order: str | None = None,
) -> list[dict[str, Any]]:
    """Query an optional table with schema-compatible fallbacks."""
    attempts: list[tuple[bool, bool]] = []
    if user_id and workspace_id:
        attempts.append((True, True))
    if user_id:
        attempts.append((True, False))
    attempts.append((False, False))

    for use_user, use_workspace in attempts:
        try:
            query = supabase.table(table).select("*").eq("analysis_id", analysis_id)
            if use_user:
                query = query.eq("user_id", user_id)
            if use_workspace:
                query = query.eq("workspace_id", workspace_id)
            if order:
                query = query.order(order, desc=True)
            rows = _execute_rows(query.limit(limit))
            if rows:
                return rows
        except Exception:
            continue
    return []


def _risk_level(row: dict[str, Any]) -> str:
    raw = _text(_first(row, "risk_level", "risk", "Risk Level"), "")
    if raw:
        return raw.title()
    score = _number(_first(row, "risk_score", "Risk Score"), 0)
    if score >= 70:
        return "High"
    if score >= 35:
        return "Medium"
    return "Low"


@dataclass(slots=True)
class ContextCoverage:
    analysis: bool = False
    components: bool = False
    lifecycle: bool = False
    inventory: bool = False
    suppliers: bool = False
    monitoring: bool = False
    alternatives: bool = False
    decisions: bool = False
    collaboration: bool = False

    @property
    def score(self) -> int:
        values = list(asdict(self).values())
        return round((sum(bool(value) for value in values) / max(1, len(values))) * 100)


@dataclass(slots=True)
class EngineeringContext:
    version: str
    generated_at: str
    analysis: dict[str, Any]
    summary: dict[str, Any]
    components: list[dict[str, Any]] = field(default_factory=list)
    monitoring: list[dict[str, Any]] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    collaboration: dict[str, Any] = field(default_factory=dict)
    reports: list[dict[str, Any]] = field(default_factory=list)
    coverage: ContextCoverage = field(default_factory=ContextCoverage)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["coverage"]["score"] = self.coverage.score
        return payload

    def compact(self, *, max_components: int = 12) -> dict[str, Any]:
        """Return a prompt/report-safe subset with bounded component evidence."""
        payload = self.to_dict()
        payload["components"] = payload["components"][:max_components]
        payload["monitoring"] = payload["monitoring"][:10]
        payload["alternatives"] = payload["alternatives"][:10]
        payload["decisions"] = payload["decisions"][:10]
        payload["timeline"] = payload["timeline"][:15]
        return payload


class EngineeringContextService:
    """Build one normalized context from Cadivor engineering records."""

    VERSION = "34.3"

    def __init__(self, supabase: Any):
        self.supabase = supabase

    def build(
        self,
        *,
        analysis: dict[str, Any],
        user_id: str,
        workspace_id: str = "",
        parts: Iterable[dict[str, Any]] | None = None,
        alerts: Iterable[dict[str, Any]] | None = None,
        alternatives: Iterable[dict[str, Any]] | None = None,
        comments: Iterable[dict[str, Any]] | None = None,
        followers: Iterable[dict[str, Any]] | None = None,
    ) -> EngineeringContext:
        analysis_id = _text(_first(analysis, "id", "analysis_id"))
        raw_parts = [dict(row) for row in (parts or [])]
        # Older saved analyses can show a valid part count while the page-level
        # parts query returns no rows because of legacy ownership/workspace columns.
        # Recover the authoritative analysis_parts rows before declaring that
        # component evidence is unavailable.
        if not raw_parts and analysis_id:
            raw_parts = _query_optional(
                self.supabase,
                "analysis_parts",
                analysis_id=analysis_id,
                user_id=user_id,
                workspace_id=workspace_id,
                limit=5000,
            )
        raw_alerts = [dict(row) for row in (alerts or [])]
        raw_alternatives = [dict(row) for row in (alternatives or [])]
        raw_comments = [dict(row) for row in (comments or [])]
        raw_followers = [dict(row) for row in (followers or [])]

        decisions = _query_optional(
            self.supabase,
            "engineering_decisions",
            analysis_id=analysis_id,
            user_id=user_id,
            workspace_id=workspace_id,
            limit=100,
            order="updated_at",
        )
        decision_events = _query_optional(
            self.supabase,
            "engineering_decision_events",
            analysis_id=analysis_id,
            user_id=user_id,
            workspace_id=workspace_id,
            limit=100,
            order="created_at",
        )
        review_events = _query_optional(
            self.supabase,
            "engineering_review_events",
            analysis_id=analysis_id,
            user_id=user_id,
            workspace_id=workspace_id,
            limit=100,
            order="created_at",
        )

        normalized_parts = [self._normalize_part(row) for row in raw_parts]
        normalized_parts.sort(
            key=lambda row: (_number(row.get("risk_score")), row.get("part_number", "")),
            reverse=True,
        )
        normalized_alerts = [self._normalize_alert(row) for row in raw_alerts]
        normalized_alternatives = [self._normalize_alternative(row) for row in raw_alternatives]
        normalized_decisions = [self._normalize_decision(row) for row in decisions]
        timeline = self._build_timeline(
            normalized_alerts,
            normalized_decisions,
            decision_events,
            review_events,
        )

        high = sum(1 for row in normalized_parts if row["risk_level"].lower() == "high")
        medium = sum(1 for row in normalized_parts if row["risk_level"].lower() == "medium")
        no_stock = sum(1 for row in normalized_parts if row["stock_available"] <= 0)
        lifecycle_exposed = sum(
            1
            for row in normalized_parts
            if any(
                token in row["lifecycle_status"].lower()
                for token in ("obsolete", "eol", "end of life", "replacement", "nrnd", "not recommended")
            )
        )
        limited_sources = sum(1 for row in normalized_parts if row["supplier_count"] <= 1)
        top_risks = [row for row in normalized_parts if row["risk_level"].lower() in {"high", "medium"}][:5]

        health = _integer(_first(analysis, "health_score", "bom_health_score"), 0)
        total_parts = _integer(_first(analysis, "total_parts"), len(normalized_parts)) or len(normalized_parts)
        summary = {
            "health_score": health,
            "total_parts": total_parts,
            "high_risk_parts": high,
            "medium_risk_parts": medium,
            "lifecycle_exposed_parts": lifecycle_exposed,
            "no_stock_parts": no_stock,
            "limited_source_parts": limited_sources,
            "monitoring_alerts": len(normalized_alerts),
            "saved_alternatives": len(normalized_alternatives),
            "engineering_decisions": len(normalized_decisions),
            "top_risks": top_risks,
            "release_posture": self._release_posture(health, high, lifecycle_exposed, no_stock),
        }

        coverage = ContextCoverage(
            analysis=bool(analysis_id),
            components=bool(normalized_parts),
            lifecycle=bool(normalized_parts) and any(row["lifecycle_status"] not in ("", "Unknown") for row in normalized_parts),
            inventory=bool(normalized_parts) and any(row["stock_available"] > 0 for row in normalized_parts),
            suppliers=bool(normalized_parts) and any(row["supplier_count"] > 0 for row in normalized_parts),
            monitoring=bool(normalized_alerts),
            alternatives=bool(normalized_alternatives),
            decisions=bool(normalized_decisions),
            collaboration=bool(raw_comments or raw_followers),
        )

        normalized_analysis = {
            "analysis_id": analysis_id,
            "project_name": _text(_first(analysis, "project_name", "filename"), "Saved BOM"),
            "filename": _text(_first(analysis, "filename")),
            "created_at": _text(_first(analysis, "created_at")),
            "updated_at": _text(_first(analysis, "updated_at", "created_at")),
            "workspace_id": workspace_id or _text(_first(analysis, "workspace_id")),
            "user_id": user_id,
        }

        return EngineeringContext(
            version=self.VERSION,
            generated_at=datetime.now(timezone.utc).isoformat(),
            analysis=normalized_analysis,
            summary=summary,
            components=normalized_parts,
            monitoring=normalized_alerts,
            alternatives=normalized_alternatives,
            decisions=normalized_decisions,
            timeline=timeline,
            collaboration={
                "comment_count": len(raw_comments),
                "follower_count": len(raw_followers),
            },
            reports=[
                {"type": "executive", "available": True},
                {"type": "component-risk", "available": bool(normalized_parts)},
                {"type": "procurement", "available": bool(normalized_parts)},
                {"type": "lifecycle-alternatives", "available": bool(normalized_parts)},
            ],
            coverage=coverage,
        )

    @staticmethod
    def _normalize_part(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "part_number": _text(_first(row, "mpn", "part_number", "manufacturer_part_number", "MPN"), "Unknown part"),
            "manufacturer": _text(_first(row, "manufacturer", "Manufacturer"), "Unknown manufacturer"),
            "risk_level": _risk_level(row),
            "risk_score": _integer(_first(row, "risk_score", "Risk Score"), 0),
            "risk_reasons": _text(_first(row, "risk_reasons", "risk_reason", "Risk Reasons")),
            "lifecycle_status": _text(_first(row, "lifecycle_status", "lifecycle", "Lifecycle Status"), "Unknown"),
            "stock_available": _integer(_first(row, "stock_available", "available_stock", "Stock Available"), 0),
            "supplier_count": _integer(_first(row, "supplier_count", "Supplier Count"), 0),
            "lead_time_weeks": _number(_first(row, "lead_time_weeks", "Lead Time Weeks"), 0),
            "best_source": _text(_first(row, "best_source", "supplier", "Best Source")),
        }

    @staticmethod
    def _normalize_alert(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": _text(_first(row, "id")),
            "part_number": _text(_first(row, "part_number", "mpn"), "Component"),
            "type": _text(_first(row, "alert_type", "change_type", "event_type", "type"), "Risk change"),
            "severity": _text(_first(row, "severity"), "Medium"),
            "message": _text(_first(row, "alert_message", "message", "summary")),
            "status": _text(_first(row, "status"), "Open"),
            "created_at": _text(_first(row, "created_at")),
        }

    @staticmethod
    def _normalize_alternative(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": _text(_first(row, "id")),
            "original_part": _text(_first(row, "original_part", "original_mpn")),
            "alternative_part": _text(_first(row, "alternative_part", "alternative_mpn")),
            "supplier": _text(_first(row, "supplier")),
            "score": _number(_first(row, "recommendation_score", "score"), 0),
            "status": _text(_first(row, "status", "decision_status"), "Candidate"),
            "created_at": _text(_first(row, "created_at")),
        }

    @staticmethod
    def _normalize_decision(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": _text(_first(row, "id")),
            "part_number": _text(_first(row, "part_number", "original_part", "mpn"), "Component"),
            "decision": _text(_first(row, "decision", "status", "decision_status"), "Review"),
            "rationale": _text(_first(row, "rationale", "reason", "notes")),
            "confidence": _number(_first(row, "confidence", "confidence_score"), 0),
            "updated_at": _text(_first(row, "updated_at", "created_at")),
        }

    @staticmethod
    def _build_timeline(
        alerts: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        decision_events: list[dict[str, Any]],
        review_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        timeline: list[dict[str, Any]] = []
        for row in alerts:
            timeline.append({
                "type": "monitoring",
                "title": f"{row['part_number']} · {row['type']}",
                "detail": row.get("message", ""),
                "timestamp": row.get("created_at", ""),
            })
        for row in decisions:
            timeline.append({
                "type": "decision",
                "title": f"{row['part_number']} · {row['decision']}",
                "detail": row.get("rationale", ""),
                "timestamp": row.get("updated_at", ""),
            })
        for source, rows in (("decision-event", decision_events), ("review-event", review_events)):
            for row in rows:
                timeline.append({
                    "type": source,
                    "title": _text(_first(row, "event_type", "action", "title"), "Engineering event"),
                    "detail": _text(_first(row, "description", "message", "notes")),
                    "timestamp": _text(_first(row, "created_at", "updated_at")),
                })
        timeline.sort(key=lambda row: row.get("timestamp", ""), reverse=True)
        return timeline

    @staticmethod
    def _release_posture(health: int, high: int, lifecycle: int, no_stock: int) -> str:
        if high >= 3 or health < 55 or no_stock >= 3:
            return "Release hold recommended"
        if high > 0 or health < 80 or lifecycle > 0 or no_stock > 0:
            return "Focused engineering review"
        return "Controlled release"


def build_engineering_context(**kwargs: Any) -> EngineeringContext:
    """Convenience entry point for call sites that prefer a function."""
    supabase = kwargs.pop("supabase")
    return EngineeringContextService(supabase).build(**kwargs)
