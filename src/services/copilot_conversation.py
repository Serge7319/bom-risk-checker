"""Session-scoped conversation helpers for the Cadivor Engineering Copilot."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.services.copilot_conversation_store import (
    delete_thread as delete_persisted_thread,
    load_thread as load_persisted_thread,
    save_thread as save_persisted_thread,
)

MAX_TURNS = 8
PROMPT_HISTORY_ANSWER_MAX = 1200
_HYDRATED_ANALYSES_KEY = "cv724_hydrated_analysis_ids"


@dataclass(frozen=True, slots=True)
class CopilotTurn:
    question: str
    answer: str
    provider_connected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "provider_connected": self.provider_connected,
        }


def _analysis_key(context: dict[str, Any]) -> str:
    analysis = context.get("analysis") or {}
    return str(
        context.get("analysis_id")
        or analysis.get("analysis_id")
        or analysis.get("id")
        or "unsaved-analysis"
    )


def _workspace_id_from_context(context: dict[str, Any]) -> str:
    analysis = context.get("analysis") or {}
    return str(context.get("workspace_id") or analysis.get("workspace_id") or "")


def _hydrated_analysis_ids(session_state: Any) -> dict[str, bool]:
    hydrated = session_state.get(_HYDRATED_ANALYSES_KEY)
    if not isinstance(hydrated, dict):
        hydrated = {}
        session_state[_HYDRATED_ANALYSES_KEY] = hydrated
    return hydrated


def _apply_latest_turn_to_session(session_state: Any, thread: list[dict[str, Any]]) -> None:
    if not thread:
        return
    latest = thread[-1]
    question = str(latest.get("question") or "").strip()
    answer = str(latest.get("answer") or "").strip()
    if not answer:
        return
    if not str(session_state.get("cv35_last_answer") or "").strip():
        session_state["cv35_last_answer"] = answer
        session_state["cv35_last_question"] = question
        session_state["cv35_provider_connected"] = bool(latest.get("provider_connected"))


def get_thread(session_state: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
    threads = session_state.setdefault("cv36_threads", {})
    thread = threads.setdefault(_analysis_key(context), [])
    return list(thread)


def append_turn(
    session_state: Any,
    context: dict[str, Any],
    *,
    question: str,
    answer: str,
    provider_connected: bool,
) -> list[dict[str, Any]]:
    threads = session_state.setdefault("cv36_threads", {})
    key = _analysis_key(context)
    thread = list(threads.get(key) or [])
    thread.append(
        CopilotTurn(
            question=str(question or "").strip(),
            answer=str(answer or "").strip(),
            provider_connected=bool(provider_connected),
        ).to_dict()
    )
    threads[key] = thread[-MAX_TURNS:]
    session_state["cv36_threads"] = threads
    return list(threads[key])


def clear_thread(session_state: Any, context: dict[str, Any]) -> None:
    threads = session_state.setdefault("cv36_threads", {})
    threads.pop(_analysis_key(context), None)
    session_state["cv36_threads"] = threads


def hydrate_thread_from_store(
    session_state: Any,
    context: dict[str, Any],
    *,
    user_id: str,
    supabase: Any = None,
) -> str | None:
    """Load a saved Ask Cadivor thread into session_state once per analysis."""
    analysis_key = _analysis_key(context)
    user_key = str(user_id or "").strip()
    if not user_key or not analysis_key or analysis_key == "unsaved-analysis":
        return None
    hydrated = _hydrated_analysis_ids(session_state)
    if hydrated.get(analysis_key):
        return None
    hydrated[analysis_key] = True

    threads = session_state.setdefault("cv36_threads", {})
    if threads.get(analysis_key):
        _apply_latest_turn_to_session(session_state, list(threads.get(analysis_key) or []))
        return None
    if not supabase:
        return None

    thread, error = load_persisted_thread(
        supabase,
        user_id=user_key,
        analysis_id=analysis_key,
        workspace_id=_workspace_id_from_context(context),
    )
    if error or not thread:
        return error
    threads[analysis_key] = thread
    session_state["cv36_threads"] = threads
    _apply_latest_turn_to_session(session_state, thread)
    return None


def persist_thread_to_store(
    context: dict[str, Any],
    *,
    user_id: str,
    supabase: Any = None,
    thread: list[dict[str, Any]] | None = None,
) -> str | None:
    """Persist the current Ask Cadivor thread for this analysis."""
    analysis_key = _analysis_key(context)
    user_key = str(user_id or "").strip()
    if not supabase or not user_key or not analysis_key or analysis_key == "unsaved-analysis":
        return None
    payload = list(thread or [])
    return save_persisted_thread(
        supabase,
        user_id=user_key,
        analysis_id=analysis_key,
        workspace_id=_workspace_id_from_context(context),
        thread=payload,
    )


def clear_persisted_thread(
    context: dict[str, Any],
    *,
    user_id: str,
    supabase: Any = None,
) -> str | None:
    """Remove the durable Ask Cadivor thread for this analysis."""
    analysis_key = _analysis_key(context)
    user_key = str(user_id or "").strip()
    if not supabase or not user_key or not analysis_key or analysis_key == "unsaved-analysis":
        return None
    return delete_persisted_thread(
        supabase,
        user_id=user_key,
        analysis_id=analysis_key,
        workspace_id=_workspace_id_from_context(context),
    )


def compact_history(thread: list[dict[str, Any]], max_turns: int = 4) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for turn in thread[-max_turns:]:
        question = str(turn.get("question") or "").strip()
        answer = str(turn.get("answer") or "").strip()
        if question and answer:
            compact.append({"question": question[:500], "answer": answer[:PROMPT_HISTORY_ANSWER_MAX]})
    return compact


def follow_up_suggestions(question: str, answer: str, context: dict[str, Any]) -> list[str]:
    """Use assessment-generated follow-ups, with evidence-aware fallback prompts."""
    lines=str(answer or "").splitlines(); active=False; generated=[]
    for raw in lines:
        line=raw.strip()
        if line.lower().startswith("### follow-up questions"):
            active=True; continue
        if active and line.startswith("### "):
            break
        if active and line.startswith(("-", "*")):
            item=line[1:].strip()
            if item: generated.append(item)
    if generated:
        return generated[:4]
    components=sorted(list(context.get("components") or []), key=lambda row:int(row.get("risk_score") or 0), reverse=True)
    top=str((components[0].get("part_number") or components[0].get("mpn")) if components else "the top-ranked component")
    return [f"Why is {top} ranked first?", "What evidence would change this recommendation?", "What should the engineering owner do next?"]
