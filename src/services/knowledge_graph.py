"""Lightweight engineering relationship graph for Cadivor.

Builds a provider-neutral, in-memory graph from the unified engineering context
and the user's saved BOM records. No graph database or schema migration is
required.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.services.engineering_context import EngineeringContext


def _text(value: Any, default: str = "") -> str:
    value = "" if value is None else str(value).strip()
    return value or default


def _rows(query: Any) -> list[dict[str, Any]]:
    try:
        result = query.execute()
        return [dict(row) for row in (result.data or [])]
    except Exception:
        return []


@dataclass(slots=True)
class GraphNode:
    id: str
    kind: str
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphEdge:
    source: str
    target: str
    relation: str


@dataclass(slots=True)
class EngineeringKnowledgeGraph:
    analysis_id: str
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    where_used: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "nodes": [asdict(node) for node in self.nodes],
            "edges": [asdict(edge) for edge in self.edges],
            "where_used": self.where_used,
            "summary": self.summary,
        }


class KnowledgeGraphService:
    def __init__(self, supabase: Any):
        self.supabase = supabase

    def build(
        self,
        *,
        context: EngineeringContext,
        user_id: str,
        workspace_id: str = "",
    ) -> EngineeringKnowledgeGraph:
        analysis_id = _text(context.analysis.get("analysis_id"))
        graph = EngineeringKnowledgeGraph(analysis_id=analysis_id)
        seen_nodes: set[str] = set()
        seen_edges: set[tuple[str, str, str]] = set()

        def add_node(node_id: str, kind: str, label: str, **metadata: Any) -> None:
            if not node_id or node_id in seen_nodes:
                return
            seen_nodes.add(node_id)
            graph.nodes.append(GraphNode(node_id, kind, label, metadata))

        def add_edge(source: str, target: str, relation: str) -> None:
            key = (source, target, relation)
            if not source or not target or key in seen_edges:
                return
            seen_edges.add(key)
            graph.edges.append(GraphEdge(source, target, relation))

        analysis_node = f"analysis:{analysis_id}"
        add_node(analysis_node, "analysis", _text(context.analysis.get("project_name"), "Saved BOM"))

        component_ids: dict[str, str] = {}
        manufacturer_counts: dict[str, int] = {}
        supplier_counts: dict[str, int] = {}

        for component in context.components:
            part = _text(component.get("part_number"), "Unknown part")
            part_key = part.upper()
            component_id = f"component:{part_key}"
            component_ids[part_key] = component_id
            add_node(component_id, "component", part, risk_level=component.get("risk_level"))
            add_edge(analysis_node, component_id, "contains")

            manufacturer = _text(component.get("manufacturer"))
            if manufacturer and manufacturer.lower() != "unknown manufacturer":
                manufacturer_id = f"manufacturer:{manufacturer.lower()}"
                add_node(manufacturer_id, "manufacturer", manufacturer)
                add_edge(component_id, manufacturer_id, "manufactured_by")
                manufacturer_counts[manufacturer] = manufacturer_counts.get(manufacturer, 0) + 1

            supplier = _text(component.get("best_source"))
            if supplier:
                supplier_id = f"supplier:{supplier.lower()}"
                add_node(supplier_id, "supplier", supplier)
                add_edge(component_id, supplier_id, "sourced_from")
                supplier_counts[supplier] = supplier_counts.get(supplier, 0) + 1

        for alternative in context.alternatives:
            original = _text(alternative.get("original_part")).upper()
            replacement = _text(alternative.get("alternative_part"))
            source_id = component_ids.get(original)
            if source_id and replacement:
                alt_id = f"alternative:{replacement.upper()}"
                add_node(alt_id, "alternative", replacement, status=alternative.get("status"))
                add_edge(source_id, alt_id, "has_alternative")

        for alert in context.monitoring:
            part = _text(alert.get("part_number")).upper()
            source_id = component_ids.get(part)
            alert_id = _text(alert.get("id")) or f"{part}:{alert.get('created_at','')}:{alert.get('type','')}"
            if source_id and alert_id:
                node_id = f"monitoring:{alert_id}"
                add_node(node_id, "monitoring", _text(alert.get("type"), "Risk change"), severity=alert.get("severity"))
                add_edge(source_id, node_id, "has_monitoring_event")

        for decision in context.decisions:
            part = _text(decision.get("part_number")).upper()
            source_id = component_ids.get(part)
            decision_id = _text(decision.get("id")) or f"{part}:{decision.get('updated_at','')}"
            if source_id and decision_id:
                node_id = f"decision:{decision_id}"
                add_node(node_id, "decision", _text(decision.get("decision"), "Review"))
                add_edge(source_id, node_id, "has_decision")

        graph.where_used = self._where_used(user_id=user_id, workspace_id=workspace_id)
        current_parts = {part.upper() for part in component_ids}
        reuse_counts = {
            part: len(records)
            for part, records in graph.where_used.items()
            if part in current_parts
        }
        reused_part = max(reuse_counts, key=reuse_counts.get) if reuse_counts else ""
        most_connected_supplier = max(supplier_counts, key=supplier_counts.get) if supplier_counts else "Not recorded"
        most_connected_manufacturer = max(manufacturer_counts, key=manufacturer_counts.get) if manufacturer_counts else "Not recorded"
        parts_with_alternatives = {
            edge.source for edge in graph.edges if edge.relation == "has_alternative"
        }
        parts_requiring_review = sum(
            1 for component in context.components
            if _text(component.get("risk_level")).lower() in {"high", "medium"}
        )

        counts: dict[str, int] = {}
        for node in graph.nodes:
            counts[node.kind] = counts.get(node.kind, 0) + 1

        graph.summary = {
            "counts": counts,
            "relationship_count": len(graph.edges),
            "most_connected_supplier": most_connected_supplier,
            "most_connected_manufacturer": most_connected_manufacturer,
            "most_reused_component": reused_part or "No cross-BOM reuse found",
            "most_reused_component_count": reuse_counts.get(reused_part, 0) if reused_part else 0,
            "components_without_alternatives": max(0, len(context.components) - len(parts_with_alternatives)),
            "components_requiring_review": parts_requiring_review,
        }
        return graph

    def _where_used(self, *, user_id: str, workspace_id: str = "") -> dict[str, list[dict[str, str]]]:
        try:
            query = self.supabase.table("analyses").select("id,project_name,filename,workspace_id").eq("user_id", user_id)
            if workspace_id:
                query = query.eq("workspace_id", workspace_id)
            analyses = _rows(query.limit(500))
        except Exception:
            analyses = []
        if not analyses:
            return {}

        analysis_map = {
            _text(row.get("id")): {
                "analysis_id": _text(row.get("id")),
                "project_name": _text(row.get("project_name") or row.get("filename"), "Saved BOM"),
            }
            for row in analyses if _text(row.get("id"))
        }
        ids = list(analysis_map)
        parts: list[dict[str, Any]] = []
        for start in range(0, len(ids), 100):
            chunk = ids[start:start + 100]
            try:
                parts.extend(_rows(self.supabase.table("analysis_parts").select("analysis_id,mpn,part_number,manufacturer_part_number").in_("analysis_id", chunk).limit(10000)))
            except Exception:
                for analysis_id in chunk:
                    parts.extend(_rows(self.supabase.table("analysis_parts").select("analysis_id,mpn,part_number,manufacturer_part_number").eq("analysis_id", analysis_id).limit(5000)))

        result: dict[str, list[dict[str, str]]] = {}
        seen: set[tuple[str, str]] = set()
        for row in parts:
            part = _text(row.get("mpn") or row.get("part_number") or row.get("manufacturer_part_number")).upper()
            analysis_id = _text(row.get("analysis_id"))
            if not part or analysis_id not in analysis_map or (part, analysis_id) in seen:
                continue
            seen.add((part, analysis_id))
            result.setdefault(part, []).append(analysis_map[analysis_id])
        for records in result.values():
            records.sort(key=lambda row: row["project_name"].lower())
        return result


def build_knowledge_graph(**kwargs: Any) -> EngineeringKnowledgeGraph:
    supabase = kwargs.pop("supabase")
    return KnowledgeGraphService(supabase).build(**kwargs)
