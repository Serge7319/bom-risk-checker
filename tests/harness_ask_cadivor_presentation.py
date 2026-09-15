#!/usr/bin/env python3
"""Zero-credit Ask Cadivor native presentation harness — Sprint 72.3.1.

Exercises the production native Streamlit renderer for the PC817 scenario.
No EngineeringAI.ask() or OpenAI calls.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub, restore_ask_cadivor_streamlit_modules

ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"

PC817_QUESTION = "What should I review first in this BOM?"

PC817_ANSWER = (
    "### Intent\nGeneral Engineering Review\n\n"
    "### Direct Answer\nReview PC817 first.\n\n"
    "### Evidence\n"
    "- **PC817** — medium risk with a 21.4 week lead time and only 2 suppliers\n"
    "- **BZX55C5V1** — moderate lead-time exposure with MAX3232CPE\n"
    "- **DRV8825** — End of Life lifecycle status requires attention\n\n"
    "### Recommended Actions\n"
    "1. Investigate alternative suppliers or parts for PC817.\n"
    "2. Validate procurement plans for moderate-lead-time components.\n"
    "3. Assess replacement strategy for DRV8825."
)

PC817_CONTEXT = {
    "analysis": {"analysis_id": "harness-pc817", "health_score": 93},
    "summary": {"health_score": 93, "release_posture": "focused_review"},
    "components": [
        {"part_number": "PC817", "risk_score": 40, "supplier_count": 2, "lead_time_weeks": 21.4},
        {"part_number": "BZX55C5V1", "risk_score": 35, "lead_time_weeks": 12},
        {"part_number": "DRV8825", "risk_score": 55, "lifecycle": "End of Life"},
    ],
    "monitoring": [],
    "alternatives": [],
    "decisions": [],
    "coverage": {"score": 56},
}


def render_pc817_harness(*, expand_details: bool = False) -> tuple[str, object]:
    st = install_ask_cadivor_streamlit_stub()
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    with patch.object(assistant, "_render_response_scroll_anchor"):
        with patch.object(assistant, "_render_quick_actions"):
            with patch.object(assistant, "_disclosure_is_open", return_value=bool(expand_details)):
                assistant._render_response(
                    question=PC817_QUESTION,
                    answer=PC817_ANSWER,
                    context=PC817_CONTEXT,
                )
    html = "\n".join(content for content, _kwargs, _side in st.markdown_calls)
    return html, st


def _column_text(st, side: str) -> str:
    return "\n".join(content for content, _kwargs, column in st.markdown_calls if column == side)


def main() -> int:
    html, st = render_pc817_harness(expand_details=False)
    expanded_html, expanded_st = render_pc817_harness(expand_details=True)
    root = "\n".join(content for content, _kwargs, side in st.markdown_calls if side == "root")
    css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")

    checks = {
        "single_column_compact": st.columns_calls == [],
        "conversation_exchange_html": "cv50-exchange" in html,
        "three_reason_rows": html.count("cv722-reason-row") >= 3,
        "three_action_rows": html.count("cv722-action-row") >= 3,
        "evidence_deferred_by_default": html.count("cv46-evidence-card") == 0,
        "evidence_available_when_expanded": expanded_html.count("cv46-evidence-card") >= 3,
        "summary_deferred_by_default": len(re.findall(r'class="cv722-summary-item', html)) == 0,
        "summary_available_when_expanded": len(re.findall(r'class="cv722-summary-item', expanded_html)) == 3,
        "impact_deferred_by_default": html.count("cv724-impact-cell") == 0,
        "impact_available_when_expanded": expanded_html.count("cv724-impact-cell") == 4,
        "direct_answer_present": "Review PC817 first." in root or "Review PC817 first." in html,
        "question_in_exchange": PC817_QUESTION in html,
        "no_duplicate_direct_answer": html.count("Review PC817 first.") == 1,
        "no_concatenated_component_status": all(
            token not in html for token in ("PC817Review", "BZX55C5V1Review", "DRV8825Review")
        ),
        "exchange_badges_separate": "cv50-type" in html and "cv50-saved" in html,
        "no_giant_html_card_shell": "cv725-decision-workspace" not in html,
        "no_details_wrapper": "<details" not in html.lower(),
        "compact_answer_surface": "cv72-compact-answer" in html and "cv722-concise-answer" in html,
        "assessment_deferred_by_default": "cv727-assessment-panel" not in html,
        "assessment_available_when_expanded": "cv727-assessment-panel" in expanded_html,
        "no_runtime_style_injection": not any("<style" in content.lower() for content, _kwargs, _side in st.markdown_calls),
        "shell_independent_css_on_disk": ".cv50-exchange" in css and ".cv722-summary-strip" in css,
        "numeric_values_preserved": all(token in html for token in ("21.4", "2 suppliers")),
        "priority_part_in_compact_card": "PC817" in html,
        "no_keyed_container_calls_in_source": "st.container(key=" not in (
            REPO_ROOT / "src/components/engineering_assistant.py"
        ).read_text(encoding="utf-8"),
    }

    print("=== Ask Cadivor PC817 native presentation harness (Sprint 72.3.1) ===")
    print(f"Question: {PC817_QUESTION}")
    print(f"Rendered markdown length: {len(html)} chars")
    print(f"Container calls: {', '.join(st.container_calls)}")
    print()
    failed = False
    for name, ok in checks.items():
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        failed = failed or not ok
    print()
    restore_ask_cadivor_streamlit_modules()
    if failed:
        print("Harness: FAILED")
        return 1
    print("Harness: PASS (zero OpenAI credits consumed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
