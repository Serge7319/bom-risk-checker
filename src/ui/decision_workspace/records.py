"""Persist recommendation decisions from the Engineering Intelligence page."""
from __future__ import annotations

from datetime import date
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from src.decision_engine import STATUSES as DECISION_RECORD_STATUSES
from src.decision_repository import (
    add_decision_note,
    load_decision_state,
    save_decision_workflow,
)


def recommendation_decision_key(analysis_id: str, action: Mapping[str, Any]) -> str:
    """Return a stable key scoped to one saved analysis and one recommendation."""
    identity = {
        "analysis_id": str(analysis_id or "").strip(),
        "part_number": str(action.get("part_number") or "").strip().casefold(),
        "category": str(action.get("category") or "").strip().casefold(),
        "title": str(action.get("title") or action.get("action") or "").strip().casefold(),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    return f"analysis:{identity['analysis_id']}:recommendation:{digest}"


def _confidence_score(value: Any) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else 0


def recommendation_record_payload(
    analysis_id: str,
    action: Mapping[str, Any],
    *,
    decision_key: str,
    status: str,
    owner: str,
    due_date: str | None,
) -> dict[str, Any]:
    """Create the persisted record payload from the displayed recommendation."""
    record = {
        "decision_id": decision_key,
        "analysis_id": str(analysis_id),
        "part_number": str(action.get("part_number") or "").strip(),
        "decision_type": str(action.get("category") or "Engineering Review"),
        "title": str(action.get("title") or action.get("action") or "Engineering action"),
        "recommendation": str(action.get("action") or ""),
        "rationale": str(action.get("reason") or ""),
        "evidence": str(action.get("evidence") or ""),
        "expected_result": str(action.get("expected_result") or ""),
        "priority_score": int(action.get("score") or 0),
        "confidence": _confidence_score(action.get("confidence")),
        "status": status,
        "owner": owner,
        "assigned_owner": owner,
        "due_date": due_date,
        "decision_payload": dict(action),
    }
    # Supabase JSON columns must receive JSON-safe values even if future
    # recommendation builders add dates or numeric scalar types.
    return json.loads(json.dumps(record, default=str))


def normalize_due_date(value: str) -> tuple[str | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    try:
        return date.fromisoformat(text).isoformat(), None
    except ValueError:
        return None, "Enter a due date in YYYY-MM-DD format, or leave it blank."


def render_recommendation_records(
    actions: Sequence[Mapping[str, Any]],
    *,
    supabase: Any,
    user_id: str,
    workspace_id: str | None,
    analysis_id: str,
    actor_name: str,
    can_edit: bool = True,
) -> None:
    """Render scoped, durable decision records for this analysis only."""
    import streamlit as st

    rows = list(actions or [])
    if not rows:
        return

    keys = [recommendation_decision_key(analysis_id, row) for row in rows]
    saved, load_error = load_decision_state(
        supabase,
        user_id=user_id,
        workspace_id=workspace_id,
        decision_keys=keys,
    )
    st.markdown("### Persistent decision records")
    st.caption("Status, owner, due date, rationale, and activity are saved for this BOM.")
    if load_error:
        st.warning(f"Saved decision records could not be loaded: {load_error}")

    for index, action in enumerate(rows):
        decision_key = keys[index]
        part_number = str(action.get("part_number") or "Component").strip()
        title = str(action.get("title") or action.get("action") or "Engineering action").strip()
        record = saved.get(decision_key) or {}
        # This shared table uses the Milestone 13 decision-engine vocabulary.
        # Do not persist the separate presentation-only labels from the card.
        initial_status = str(record.get("status") or "New").strip()
        if initial_status not in DECISION_RECORD_STATUSES:
            initial_status = "New"
        initial_owner = str(record.get("owner") or action.get("owner") or "Component Engineering")
        initial_due_date = str(record.get("due_date") or "")

        with st.expander(f"{part_number} — {title}", expanded=(index == 0)):
            if not can_edit:
                st.info(f"Saved status: {initial_status} · Owner: {initial_owner}")
            else:
                with st.form(f"decision_record_form_{decision_key}"):
                    status = st.selectbox(
                        "Decision status",
                        DECISION_RECORD_STATUSES,
                        index=DECISION_RECORD_STATUSES.index(initial_status),
                        key=f"decision_record_status_{decision_key}",
                    )
                    owner = st.text_input(
                        "Owner",
                        value=initial_owner,
                        key=f"decision_record_owner_{decision_key}",
                    )
                    due_date_input = st.text_input(
                        "Due date (YYYY-MM-DD)",
                        value=initial_due_date,
                        key=f"decision_record_due_{decision_key}",
                    )
                    note = st.text_area(
                        "Rationale or audit note",
                        value="",
                        key=f"decision_record_note_{decision_key}",
                    )
                    submitted = st.form_submit_button("Save decision record", type="primary")

                if submitted:
                    due_date, date_error = normalize_due_date(due_date_input)
                    if date_error:
                        st.error(date_error)
                    elif not owner.strip():
                        st.error("Enter an owner before saving the decision record.")
                    else:
                        payload = recommendation_record_payload(
                            analysis_id,
                            action,
                            decision_key=decision_key,
                            status=status,
                            owner=owner.strip(),
                            due_date=due_date,
                        )
                        previous_status = record.get("status")
                        error = save_decision_workflow(
                            supabase,
                            user_id=user_id,
                            workspace_id=workspace_id,
                            decision=payload,
                            status=status,
                            assigned_owner=owner.strip(),
                            due_date=due_date,
                            actor_name=actor_name or "Engineer",
                            previous_status=str(previous_status) if previous_status else None,
                        )
                        if error:
                            st.error(f"Decision record was not saved: {error}")
                        elif note.strip():
                            note_error = add_decision_note(
                                supabase,
                                user_id=user_id,
                                workspace_id=workspace_id,
                                decision=payload,
                                author_name=actor_name or "Engineer",
                                note_text=note.strip(),
                            )
                            if note_error:
                                st.error(
                                    "Decision status was saved, but its rationale note was not saved: "
                                    f"{note_error}"
                                )
                            else:
                                st.success("Decision record and rationale saved.")
                                st.rerun()
                        else:
                            st.success("Decision record saved.")
                            st.rerun()

            notes = list(record.get("notes") or [])
            if notes:
                st.markdown("**Saved rationale and notes**")
                for saved_note in reversed(notes):
                    st.text(
                        f"{saved_note.get('author') or 'Engineer'} · "
                        f"{saved_note.get('time') or 'Saved'}\n"
                        f"{saved_note.get('text') or ''}"
                    )
            history = list(record.get("history") or [])
            if history:
                st.markdown("**Decision activity**")
                for event in reversed(history):
                    st.caption(
                        f"{event.get('time') or 'Saved'} · "
                        f"{event.get('event') or 'Decision updated'}"
                    )
