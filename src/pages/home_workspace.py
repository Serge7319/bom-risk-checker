"""Home identity from user-scoped saved analyses, not delayed secondary reads."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Mapping

import streamlit as st

from src.ui.navigation import navigate_to, open_saved_bom

HOME_NEW = "new"
HOME_ATTENTION = "attention"
HOME_CONTINUE = "continue"
HOME_UNKNOWN = "unknown"

SAVED_ANALYSES_CACHE_KEY = "cadivor_home_saved_analyses"
SECONDARY_CACHE_KEY = "cadivor_home_secondary_cache"
SECONDARY_REFRESH_REQUEST_KEY = "cadivor_secondary_refresh_requested"
SECONDARY_REFRESH_FAILED_KEY = "cadivor_secondary_refresh_failed"
SECONDARY_UPDATE_BANNER = (
    "We couldn’t refresh workspace updates. Your saved BOMs are still available."
)
SECONDARY_UNAVAILABLE_NOTICE = "Portfolio updates aren’t available right now."
SECONDARY_REFRESH_FAILURE = (
    "Couldn’t refresh portfolio updates. Your saved BOMs are unchanged."
)
RETRY_UPDATES_LABEL = "Refresh workspace updates"
NEW_USER_TITLE = "Start your first BOM review"
NEW_USER_BODY = (
    "Upload a BOM to identify component risk, review evidence, and document the next engineering action."
)
ATTENTION_TITLE = "What needs attention"
CONTINUE_TITLE = "Continue your engineering work"
ONBOARDING_MESSAGES = (
    "Upload my first BOM",
    "Your first decision in four steps",
)


def user_scoped_analyses(rows: Any, user_id: str) -> list[dict[str, Any]]:
    """Keep analyses for this user. Drop rows that belong to someone else."""
    uid = str(user_id or "").strip()
    kept: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if not str(row.get("id") or "").strip():
            continue
        row_user = str(row.get("user_id") or "").strip()
        if row_user and uid and row_user != uid:
            continue
        if not _looks_saved(row):
            continue
        kept.append(row)
    return kept


def apply_saved_analysis_result(
    session_state: dict,
    *,
    user_id: str,
    rows: Any,
    status: str,
) -> list[dict[str, Any]] | None:
    """Return saved BOMs for ``user_id``.

    A timeout or error must not overwrite a known cache, and must not look like
    a successful empty workspace. ``None`` means the identity is unknown.
    """
    uid = str(user_id or "").strip()
    cache = session_state.get(SAVED_ANALYSES_CACHE_KEY)
    cached_rows = None
    if isinstance(cache, dict) and str(cache.get("user_id") or "") == uid:
        cached_rows = list(cache.get("rows") or [])

    if status == "ok":
        scoped = user_scoped_analyses(rows, uid)
        session_state[SAVED_ANALYSES_CACHE_KEY] = {"user_id": uid, "rows": scoped}
        return scoped
    return cached_rows


def build_home_model(
    *,
    user_id: str,
    analyses: list[dict[str, Any]] | None,
    parts: list[dict[str, Any]] | None = None,
    secondary_failed: bool = False,
) -> dict[str, Any]:
    """Classify Home without treating a missing secondary read as a new account."""
    if analyses is None:
        return {
            "kind": HOME_UNKNOWN,
            "user_id": str(user_id or ""),
            "title": "",
            "analyses": [],
            "primary": None,
            "recent": [],
            "secondary_failed": True,
            "show_onboarding": False,
        }
    scoped = user_scoped_analyses(analyses, user_id)
    urgent = _has_urgent_risk(scoped, None if secondary_failed else parts)
    if not scoped:
        kind = HOME_NEW
        title = NEW_USER_TITLE
        primary = {"kind": "upload", "label": "Upload a BOM"}
    elif urgent:
        kind = HOME_ATTENTION
        title = ATTENTION_TITLE
        primary = _priority_action(scoped, None if secondary_failed else parts)
    else:
        kind = HOME_CONTINUE
        title = CONTINUE_TITLE
        primary = _continue_action(_most_recent(scoped))
    return {
        "kind": kind,
        "user_id": str(user_id or ""),
        "title": title,
        "analyses": scoped,
        "primary": primary,
        "recent": [_recent_card(row) for row in _sorted_recent(scoped)[:3]],
        "secondary_failed": bool(secondary_failed and scoped),
        "show_onboarding": kind == HOME_NEW,
    }


def apply_secondary_result(
    session_state: dict,
    *,
    user_id: str,
    payload: Mapping[str, Any] | None,
    status: str,
) -> dict[str, Any] | None:
    """Return last-known portfolio updates. A timeout must not wipe a cache."""
    uid = str(user_id or "").strip()
    cache = session_state.get(SECONDARY_CACHE_KEY)
    cached = None
    if isinstance(cache, dict) and str(cache.get("user_id") or "") == uid:
        cached = cache.get("payload")
    if status == "ok" and isinstance(payload, Mapping):
        stored = {
            "parts": list(payload.get("parts") or []),
            "alerts": list(payload.get("alerts") or []),
            "state": dict(payload.get("state") or {}),
        }
        session_state[SECONDARY_CACHE_KEY] = {"user_id": uid, "payload": stored}
        return stored
    if isinstance(cached, Mapping):
        return {
            "parts": list(cached.get("parts") or []),
            "alerts": list(cached.get("alerts") or []),
            "state": dict(cached.get("state") or {}),
        }
    return None


def render_secondary_update_banner(
    *,
    unavailable: bool = False,
    refresh_failed: bool = False,
) -> None:
    """One compact notice, only when a visible secondary section has no data.

    Ordinary Home with saved BOMs does not call this. A manual refresh replaces
    the same slot; it never appends another control.
    """
    if not unavailable and not refresh_failed:
        return
    slot = st.empty()
    slot.empty()
    message = SECONDARY_REFRESH_FAILURE if refresh_failed else SECONDARY_UNAVAILABLE_NOTICE
    with slot.container():
        st.markdown(
            f"""
            <div class="cv-home-notice cv-home-notice--inline" data-testid="cv-home-secondary" role="status">
              <p>{html.escape(message)}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(RETRY_UPDATES_LABEL, key="home_retry_updates"):
            slot.empty()
            st.session_state[SECONDARY_REFRESH_REQUEST_KEY] = True
            st.session_state.pop(SECONDARY_REFRESH_FAILED_KEY, None)
            st.rerun()


def render_saved_boms_unavailable() -> None:
    """Primary identity failed and nothing is cached. Do not show new-user onboarding."""
    slot = st.empty()
    slot.empty()
    with slot.container():
        st.warning("We couldn’t load your saved BOMs.")
        if st.button("Retry saved BOMs", key="home_retry_saved_boms"):
            slot.empty()
            st.rerun()


def render_returning_home(
    model: Mapping[str, Any],
    *,
    plan_notice: str = "",
    pause_new_analyses: bool = False,
) -> None:
    if plan_notice:
        st.markdown(
            f"""
            <div class="cv-home-notice cv-home-notice--account" role="status">
              <span class="cv-home-notice-icon" aria-hidden="true">i</span>
              <p>{html.escape(plan_notice)}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    if model.get("secondary_section_unavailable") or model.get("secondary_refresh_failed"):
        render_secondary_update_banner(
            unavailable=bool(model.get("secondary_section_unavailable")),
            refresh_failed=bool(model.get("secondary_refresh_failed")),
        )
    primary = model.get("primary") or {}
    with st.container(key="cv_home_next"):
        primary_label = html.escape(str(primary.get("label") or "Continue"))
        primary_bom = html.escape(str(primary.get("bom_name") or ""))
        primary_context = html.escape(
            str(primary.get("context") or "Open the saved BOM and continue the review.")
        )
        st.markdown(
            f'''<div class="cv-home-priority-copy">
              <p class="cv-home-kicker">Next engineering action</p>
              <h2>{primary_label}</h2>
              <p>{primary_context}{f" · {primary_bom}" if primary_bom else ""}</p>
            </div>''',
            unsafe_allow_html=True,
        )
        action_col, new_col = st.columns([1.6, 1])
        with action_col:
            if st.button(
                str(primary.get("label") or "Continue"),
                key="home_primary_action",
                type="primary",
            ):
                _run_primary(primary)
        with new_col:
            if pause_new_analyses:
                if st.button("Open reports", key="home_open_reports"):
                    navigate_to("Reports", arm_opening=False)
            elif st.button("New BOM", key="home_new_bom"):
                navigate_to("BOM Analyzer", new_analysis="1", arm_opening=False)

    recent = list(model.get("recent") or [])
    if recent:
        st.markdown(
            '<h2 class="cv-home-recent-title">Recent BOMs</h2>',
            unsafe_allow_html=True,
        )
        for card in recent:
            with st.container(key=f"cv_home_bom_{card['id']}"):
                left, right = st.columns([4, 1])
                with left:
                    st.markdown(
                        f"""
                        <div class="cv-home-bom">
                          <div class="cv-home-bom-name">{html.escape(card['name'])}</div>
                          <div class="cv-home-chips">{_recent_chips(card)}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with right:
                    if st.button(
                        "Continue",
                        key=f"home_continue_{card['id']}",
                    ):
                        open_saved_bom(card["id"], arm_opening=False, _rerun=True)


def _run_primary(primary: Mapping[str, Any]) -> None:
    kind = str(primary.get("kind") or "")
    analysis_id = str(primary.get("analysis_id") or "").strip()
    mpn = str(primary.get("mpn") or "").strip()
    if kind == "review" and analysis_id and mpn:
        st.session_state["cadivor_active_analysis_id"] = analysis_id
        st.session_state["analysis_id"] = analysis_id
        st.session_state["cadivor_pending_analysis_section"] = "Components"
        st.session_state["cadivor_pending_analysis_section_id"] = analysis_id
        navigate_to(
            "Analysis Details",
            analysis_id=analysis_id,
            tab="components",
            component=mpn,
            arm_opening=False,
        )
        return
    if analysis_id:
        open_saved_bom(analysis_id, arm_opening=False, _rerun=True)


def _looks_saved(row: Mapping[str, Any]) -> bool:
    return any(
        row.get(field) not in (None, "", 0, 0.0)
        for field in ("filename", "project_name", "total_parts", "health_score", "created_at")
    )


def _has_urgent_risk(analyses: list[dict[str, Any]], parts: list[dict[str, Any]] | None) -> bool:
    if any(_int(row.get("high_risk_count")) > 0 for row in analyses):
        return True
    if parts is None:
        return False
    return any(_is_high_part(part) for part in parts)


def _is_high_part(part: Mapping[str, Any]) -> bool:
    level = str(part.get("risk_level") or part.get("Risk Level") or "").strip().lower()
    return level == "high"


def _priority_action(
    analyses: list[dict[str, Any]],
    parts: list[dict[str, Any]] | None,
) -> dict[str, str]:
    mpn, analysis_id = _highest_risk_part(parts or [])
    if mpn and not analysis_id:
        urgent = [row for row in analyses if _int(row.get("high_risk_count")) > 0]
        analysis_id = str((_most_recent(urgent) or {}).get("id") or "").strip()
    if mpn:
        analysis = next(
            (row for row in analyses if str(row.get("id") or "").strip() == analysis_id),
            None,
        )
        return {
            "kind": "review",
            "label": f"Review {mpn}",
            "mpn": mpn,
            "analysis_id": analysis_id,
            "bom_name": _bom_name(analysis or {}),
            "context": "High-risk component requires engineering review",
        }
    return _continue_action(_most_recent(analyses))


def _highest_risk_part(parts: list[dict[str, Any]]) -> tuple[str, str]:
    ranked = []
    for part in parts:
        if not isinstance(part, dict) or not _is_high_part(part):
            continue
        mpn = str(
            part.get("mpn")
            or part.get("part_number")
            or part.get("manufacturer_part_number")
            or ""
        ).strip()
        if not mpn:
            continue
        ranked.append((
            _float(part.get("risk_score") or part.get("Risk Score")),
            mpn,
            str(part.get("analysis_id") or "").strip(),
        ))
    if not ranked:
        return "", ""
    ranked.sort(key=lambda item: item[0], reverse=True)
    _score, mpn, analysis_id = ranked[0]
    return mpn, analysis_id


def _continue_action(row: Mapping[str, Any] | None) -> dict[str, str]:
    if not row:
        return {"kind": "continue", "label": "Continue", "analysis_id": ""}
    return {
        "kind": "continue",
        "label": f"Continue {_bom_name(row)}",
        "analysis_id": str(row.get("id") or "").strip(),
        "bom_name": _bom_name(row),
        "context": "Resume the latest saved engineering review",
    }


def _recent_card(row: Mapping[str, Any]) -> dict[str, Any]:
    health = row.get("health_score")
    high = row.get("high_risk_count")
    return {
        "id": str(row.get("id") or "").strip(),
        "name": _bom_name(row),
        "health": int(health) if health is not None and str(health).strip() != "" else None,
        "high_risk_count": int(high) if high is not None and str(high).strip() != "" else None,
        "updated": _updated_label(row.get("created_at")),
    }


def _recent_chips(card: Mapping[str, Any]) -> str:
    """Status chips for a saved BOM. Tone follows the stored score; labels do not."""
    chips: list[str] = []
    health = card.get("health")
    if health is not None:
        score = int(health)
        if score >= 80:
            tone, mark, name = "healthy", "●", "Healthy"
        elif score >= 55:
            tone, mark, name = "caution", "▲", "Review"
        else:
            tone, mark, name = "risk", "!", "At risk"
        chips.append(
            f'<span class="cv-home-chip cv-home-chip--{tone}">'
            f'<span aria-hidden="true">{mark}</span> Health {score} · {name}</span>'
        )
    high = card.get("high_risk_count")
    if high is not None:
        count = int(high)
        if count > 0:
            chips.append(
                f'<span class="cv-home-chip cv-home-chip--risk">'
                f'<span aria-hidden="true">!</span> {count} high-risk</span>'
            )
        else:
            chips.append(
                '<span class="cv-home-chip cv-home-chip--quiet">'
                '<span aria-hidden="true">–</span> No high-risk</span>'
            )
    if card.get("updated"):
        chips.append(
            f'<span class="cv-home-chip cv-home-chip--quiet">'
            f'<span aria-hidden="true">◷</span> Updated {html.escape(str(card["updated"]))}</span>'
        )
    return "".join(chips)


def _recent_caption(card: Mapping[str, Any]) -> str:
    parts = []
    if card.get("health") is not None:
        parts.append(f"Health {card['health']}")
    if card.get("high_risk_count") is not None:
        count = int(card["high_risk_count"])
        parts.append(f"{count} high-risk")
    if card.get("updated"):
        parts.append(f"Updated {card['updated']}")
    return " · ".join(parts)


def _bom_name(row: Mapping[str, Any]) -> str:
    return str(row.get("project_name") or row.get("filename") or "Saved BOM").strip() or "Saved BOM"


def _most_recent(analyses: list[dict[str, Any]]) -> dict[str, Any] | None:
    ordered = _sorted_recent(analyses)
    return ordered[0] if ordered else None


def _sorted_recent(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(analyses, key=_sort_key, reverse=True)


def _sort_key(row: Mapping[str, Any]) -> str:
    return str(row.get("created_at") or "")


def _updated_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10]
    return parsed.strftime("%b %d, %Y")


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
