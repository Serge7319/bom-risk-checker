"""Cadivor Milestone 13.2 — persistent engineering decision records."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from src.supabase_read import SupabaseReadTransportError, execute_supabase_read

# Wall-clock budget for the three sequential decision-table reads. Callers may
# pass a tighter deadline; this is the default ceiling so Opening/nav never
# wait unboundedly on PostgREST.
DEFAULT_DECISION_LOAD_BUDGET_SECONDS = 8.0
DECISION_LOAD_TIMEOUT_TOKEN = "decision_load_budget_exceeded"


def _scope_key(workspace_id: str | None) -> str:
    value = str(workspace_id or "").strip()
    return value or "personal"


def _safe_rows(response: Any) -> List[Dict[str, Any]]:
    rows = getattr(response, "data", None)
    return list(rows or [])


def _budget_exceeded(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= float(deadline)


def load_decision_state(
    supabase: Any,
    *,
    user_id: str,
    workspace_id: str | None,
    decision_keys: List[str] | None = None,
    deadline: float | None = None,
    budget_seconds: float | None = None,
) -> Tuple[Dict[str, Dict[str, Any]], str | None]:
    """Load workflow state, notes, and history for the active decision scope.

    Reads are scoped by ``user_id`` + ``scope_key`` (workspace or personal).
    Optional ``deadline`` / ``budget_seconds`` abort with a recoverable timeout
    instead of hanging the Engineering Decisions page indefinitely.
    """
    scope = _scope_key(workspace_id)
    keys = sorted({str(key).strip() for key in (decision_keys or []) if str(key).strip()})
    if decision_keys is not None and not keys:
        return {}, None

    def scoped_query(table_name: str) -> Any:
        query = (
            supabase.table(table_name)
            .select("*")
            .eq("user_id", user_id)
            .eq("scope_key", scope)
        )
        if decision_keys is not None:
            query = query.in_("decision_key", keys)
        return query

    if deadline is None and budget_seconds is not None:
        deadline = time.monotonic() + max(0.1, float(budget_seconds))
    elif deadline is None:
        deadline = time.monotonic() + DEFAULT_DECISION_LOAD_BUDGET_SECONDS

    # Test-only hydrate delay (browser smoke). Production leaves this unset.
    try:
        import os

        smoke_delay = float(os.environ.get("CADIVOR_ED_SMOKE_HYDRATE_DELAY_S") or "0")
    except Exception:
        smoke_delay = 0.0
    if smoke_delay > 0:
        time.sleep(min(smoke_delay, 30.0))

    try:
        if _budget_exceeded(deadline):
            return {}, DECISION_LOAD_TIMEOUT_TOKEN

        decision_rows = _safe_rows(
            execute_supabase_read(
                scoped_query("engineering_decisions"),
                operation="engineering_decisions.select",
                attempts=2,
            )
        )
        if _budget_exceeded(deadline):
            return {}, DECISION_LOAD_TIMEOUT_TOKEN

        note_rows = _safe_rows(
            execute_supabase_read(
                scoped_query("engineering_decision_notes").order("created_at", desc=False),
                operation="engineering_decision_notes.select",
                attempts=2,
            )
        )
        if _budget_exceeded(deadline):
            return {}, DECISION_LOAD_TIMEOUT_TOKEN

        event_rows = _safe_rows(
            execute_supabase_read(
                scoped_query("engineering_decision_events").order("created_at", desc=False),
                operation="engineering_decision_events.select",
                attempts=2,
            )
        )
    except SupabaseReadTransportError as exc:
        return {}, str(exc)
    except Exception as exc:
        return {}, str(exc)

    state: Dict[str, Dict[str, Any]] = {}
    for row in decision_rows:
        key = str(row.get("decision_key") or "").strip()
        if not key:
            continue
        state[key] = {
            "status": row.get("status") or "New",
            "owner": row.get("assigned_owner") or "Engineering",
            "due_date": row.get("due_date"),
            "updated_at": row.get("updated_at"),
            "decision_payload": (
                row.get("decision_payload")
                if isinstance(row.get("decision_payload"), dict)
                else {}
            ),
            "notes": [],
            "history": [],
            "record_id": row.get("id"),
        }

    for row in note_rows:
        key = str(row.get("decision_key") or "").strip()
        if not key:
            continue
        record = state.setdefault(
            key,
            {
                "status": "New",
                "owner": "Engineering",
                "notes": [],
                "history": [],
            },
        )
        record.setdefault("notes", []).append(
            {
                "id": row.get("id"),
                "author": row.get("author_name") or "Engineer",
                "text": row.get("note_text") or "",
                "time": row.get("created_at"),
            }
        )

    for row in event_rows:
        key = str(row.get("decision_key") or "").strip()
        if not key:
            continue
        record = state.setdefault(
            key,
            {
                "status": "New",
                "owner": "Engineering",
                "notes": [],
                "history": [],
            },
        )
        record.setdefault("history", []).append(
            {
                "id": row.get("id"),
                "event": row.get("event_label") or "Decision updated",
                "time": row.get("created_at"),
                "actor": row.get("actor_name"),
            }
        )

    return state, None


def save_decision_workflow(
    supabase: Any,
    *,
    user_id: str,
    workspace_id: str | None,
    decision: Dict[str, Any],
    status: str,
    assigned_owner: str,
    due_date: str | None,
    actor_name: str,
    previous_status: str | None = None,
) -> str | None:
    """Persist a decision workflow record and append an audit event."""
    scope = _scope_key(workspace_id)
    decision_key = str(decision.get("decision_id") or "").strip()
    if not decision_key:
        return "Decision key is missing."

    payload = {
        "user_id": user_id,
        "scope_key": scope,
        "workspace_id": workspace_id or None,
        "decision_key": decision_key,
        "analysis_id": str(
            decision.get("analysis_id") or decision.get("context_analysis_id") or ""
        ) or None,
        "part_number": str(decision.get("part_number") or "") or None,
        "decision_type": str(decision.get("decision_type") or "") or None,
        "title": str(decision.get("title") or "") or None,
        "status": status,
        "assigned_owner": assigned_owner,
        "due_date": due_date or None,
        "priority_score": int(decision.get("priority_score") or 0),
        "confidence": int(decision.get("confidence") or 0),
        "decision_payload": decision,
        "updated_by": user_id,
    }

    try:
        supabase.table("engineering_decisions").upsert(
            payload,
            on_conflict="user_id,scope_key,decision_key",
        ).execute()

        if decision.get("resolution"):
            event_label = str(decision.get("resolution"))
            event_type = "mitigation_recorded"
        elif isinstance(decision.get("inventory_evidence"), dict):
            inventory = decision["inventory_evidence"]
            event_label = (
                "Verified inventory evidence recorded: "
                f"{inventory.get('quantity', 'unknown')} units from "
                f"{inventory.get('supplier', 'supplier')}"
            )
            event_type = "inventory_evidence_recorded"
        elif previous_status and previous_status != status:
            event_label = f"Status changed from {previous_status} to {status}"
            event_type = "workflow_updated"
        else:
            event_label = "Decision workflow updated"
            event_type = "workflow_updated"

        supabase.table("engineering_decision_events").insert(
            {
                "user_id": user_id,
                "scope_key": scope,
                "workspace_id": workspace_id or None,
                "decision_key": decision_key,
                "event_type": event_type,
                "event_label": event_label,
                "actor_name": actor_name,
                "event_payload": {
                    "status": status,
                    "assigned_owner": assigned_owner,
                    "due_date": due_date,
                    "resolution": decision.get("resolution"),
                    "approved_alternative_mpn": decision.get(
                        "approved_alternative_mpn"
                    ),
                    "inventory_evidence": decision.get("inventory_evidence"),
                },
            }
        ).execute()
        return None
    except Exception as exc:
        return str(exc)


def save_decision_source_evidence(
    supabase: Any,
    *,
    user_id: str,
    workspace_id: str | None,
    decision: Dict[str, Any],
    evidence: Dict[str, Any],
    actor_name: str,
) -> str | None:
    """Persist an exact-MPN supplier evidence snapshot without changing status."""
    scope = _scope_key(workspace_id)
    decision_key = str(decision.get("decision_id") or "").strip()
    requested_mpn = str(decision.get("mpn") or decision.get("part_number") or "").strip()
    returned_mpn = str(evidence.get("manufacturer_part_number") or "").strip()
    if not decision_key:
        return "Decision key is missing."
    if not evidence.get("identity_verified") or not requested_mpn or not returned_mpn:
        return "Only verified exact-MPN evidence can be saved."

    from src.normalizer import normalize_part_number

    if normalize_part_number(requested_mpn) != normalize_part_number(returned_mpn):
        return "Supplier evidence part number does not match this decision."

    payload = {**decision, "source_evidence": dict(evidence)}
    status = str(decision.get("status") or "New")
    owner = str(
        decision.get("assigned_owner") or decision.get("owner") or "Engineering"
    )
    try:
        supabase.table("engineering_decisions").upsert(
            {
                "user_id": user_id,
                "scope_key": scope,
                "workspace_id": workspace_id or None,
                "decision_key": decision_key,
                "analysis_id": str(
                    decision.get("analysis_id")
                    or decision.get("context_analysis_id")
                    or ""
                ) or None,
                "part_number": requested_mpn,
                "decision_type": str(decision.get("decision_type") or "") or None,
                "title": str(decision.get("title") or "") or None,
                "status": status,
                "assigned_owner": owner,
                "due_date": decision.get("due_date") or None,
                "priority_score": int(decision.get("priority_score") or 0),
                "confidence": int(decision.get("confidence") or 0),
                "decision_payload": payload,
                "updated_by": user_id,
            },
            on_conflict="user_id,scope_key,decision_key",
        ).execute()
        supabase.table("engineering_decision_events").insert(
            {
                "user_id": user_id,
                "scope_key": scope,
                "workspace_id": workspace_id or None,
                "decision_key": decision_key,
                "event_type": "supplier_evidence_saved",
                "event_label": f"Exact-MPN supplier evidence saved for {requested_mpn}",
                "actor_name": actor_name or "Engineer",
                "event_payload": {
                    "manufacturer_part_number": returned_mpn,
                    "source": str(evidence.get("source") or ""),
                    "retrieved_at": str(evidence.get("retrieved_at") or ""),
                    "product_detail_url": str(evidence.get("product_detail_url") or ""),
                    "datasheet_url": str(evidence.get("datasheet_url") or ""),
                },
            }
        ).execute()
        return None
    except Exception as exc:
        return str(exc)


def add_decision_note(
    supabase: Any,
    *,
    user_id: str,
    workspace_id: str | None,
    decision: Dict[str, Any],
    author_name: str,
    note_text: str,
) -> str | None:
    """Persist a decision note and matching timeline event."""
    scope = _scope_key(workspace_id)
    decision_key = str(decision.get("decision_id") or "").strip()
    if not decision_key:
        return "Decision key is missing."

    try:
        # Ensure a parent workflow record exists before adding the note.
        supabase.table("engineering_decisions").upsert(
            {
                "user_id": user_id,
                "scope_key": scope,
                "workspace_id": workspace_id or None,
                "decision_key": decision_key,
                "analysis_id": str(decision.get("analysis_id") or "") or None,
                "part_number": str(decision.get("part_number") or "") or None,
                "decision_type": str(decision.get("decision_type") or "") or None,
                "title": str(decision.get("title") or "") or None,
                "status": str(decision.get("status") or "New"),
                "assigned_owner": str(
                    decision.get("assigned_owner")
                    or decision.get("owner")
                    or "Engineering"
                ),
                "due_date": decision.get("due_date") or None,
                "priority_score": int(decision.get("priority_score") or 0),
                "confidence": int(decision.get("confidence") or 0),
                "decision_payload": decision,
                "updated_by": user_id,
            },
            on_conflict="user_id,scope_key,decision_key",
        ).execute()

        supabase.table("engineering_decision_notes").insert(
            {
                "user_id": user_id,
                "scope_key": scope,
                "workspace_id": workspace_id or None,
                "decision_key": decision_key,
                "author_name": author_name,
                "note_text": note_text,
            }
        ).execute()

        supabase.table("engineering_decision_events").insert(
            {
                "user_id": user_id,
                "scope_key": scope,
                "workspace_id": workspace_id or None,
                "decision_key": decision_key,
                "event_type": "note_added",
                "event_label": "Engineering note added",
                "actor_name": author_name,
                "event_payload": {"note_preview": note_text[:160]},
            }
        ).execute()
        return None
    except Exception as exc:
        return str(exc)
