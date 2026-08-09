"""Session-scoped conversation helpers for the Cadivor Engineering Copilot."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_TURNS = 8
PROMPT_HISTORY_ANSWER_MAX = 1200


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
    return str(analysis.get("analysis_id") or analysis.get("id") or "unsaved-analysis")


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
