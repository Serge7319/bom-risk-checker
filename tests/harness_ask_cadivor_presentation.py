#!/usr/bin/env python3
"""Zero-credit Ask Cadivor presentation harness — Sprint 72.2.7.

Renders the PC817 production scenario through the canonical renderer without
calling EngineeringAI.ask() or any OpenAI provider. Also writes a browser-like
preview artifact containing the actual stylesheet and column-based workspace HTML.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
DESIGN_TOKENS_CSS = REPO_ROOT / "src/assets/css/cadivor_design_system_v2.css"
PREVIEW_ARTIFACT = REPO_ROOT / "tests/artifacts/ask_cadivor_pc817_preview.html"

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


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _RecordingColumn:
    def __init__(self, side: str, st_module: types.ModuleType) -> None:
        self._side = side
        self._st = st_module

    def __enter__(self):
        self._st._active_column = self._side
        return self

    def __exit__(self, *args):
        self._st._active_column = None
        return False


def _install_streamlit_stub():
    st = types.ModuleType("streamlit")
    st.session_state = {}
    st._active_column = None
    st.columns_calls: list[tuple[list[float], str | None]] = []
    st.container_calls: list[str] = []
    markdown_calls: list[tuple[str, dict, str]] = []
    html_calls: list[str] = []

    def _markdown(content, **kwargs):
        side = st._active_column or "root"
        markdown_calls.append((str(content), dict(kwargs), side))

    def _columns(spec, gap=None):
        if isinstance(spec, (list, tuple)):
            ratio = list(spec)
        else:
            ratio = [1] * int(spec)
        st.columns_calls.append((ratio, gap))
        return [_RecordingColumn("left", st), _RecordingColumn("right", st)]

    def _container(**kwargs):
        key = str(kwargs.get("key") or "")
        if key:
            st.container_calls.append(key)
        return _NullContext()

    st.markdown = _markdown
    st.html = lambda content, **kwargs: html_calls.append(str(content))
    st.expander = lambda *args, **kwargs: _NullContext()
    st.columns = _columns
    st.container = _container

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = lambda *args, **kwargs: types.SimpleNamespace(script_run_id="harness-run")
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner
    components = types.ModuleType("streamlit.components.v1")
    components.html = lambda content, **kwargs: html_calls.append(str(content))

    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st, markdown_calls, html_calls


def render_pc817_harness() -> str:
    _st, markdown_calls, _html_calls = _install_streamlit_stub()
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    with patch.object(assistant, "_render_response_scroll_anchor"):
        with patch.object(assistant, "_render_quick_actions"):
            assistant._render_response(
                question=PC817_QUESTION,
                answer=PC817_ANSWER,
                context=PC817_CONTEXT,
            )
    return "\n".join(content for content, _kwargs, _side in markdown_calls)


def _column_html(markdown_calls: list[tuple[str, dict, str]], side: str) -> str:
    return "\n".join(content for content, _kwargs, column in markdown_calls if column == side)


def write_pc817_preview_artifact(
    *,
    exchange_html: str,
    left_html: str,
    right_html: str,
    trailing_html: str = "",
) -> Path:
    PREVIEW_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    tokens_css = DESIGN_TOKENS_CSS.read_text(encoding="utf-8") if DESIGN_TOKENS_CSS.exists() else ""
    ask_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
    preview = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Ask Cadivor PC817 Preview — Sprint 72.2.7</title>
  <style id="cadivor-design-system-v2-tokens">{tokens_css}</style>
  <style id="ask_cadivor_v2.css">{ask_css}</style>
  <style>
    body {{
      margin: 0;
      padding: 24px;
      font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      background: var(--cv-bg, #f6f8fc);
      color: var(--cv-text, #0f172a);
    }}
    .preview-shell {{
      max-width: 1480px;
      margin: 0 auto;
    }}
    .preview-note {{
      margin: 0 0 16px;
      padding: 12px 16px;
      border: 1px solid var(--cv-border, #e2e8f0);
      border-radius: 12px;
      background: #fff;
      color: var(--cv-text-secondary, #334155);
      font-size: 13px;
    }}
    .preview-workspace {{
      display: grid;
      grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr);
      gap: 16px;
      margin: 12px 0 16px;
    }}
    @media (max-width: 1024px) {{
      .preview-workspace {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="preview-shell">
    <p class="preview-note">Deterministic zero-credit preview for Ask Cadivor PC817. Native Streamlit column layout simulated for browser review.</p>
    {exchange_html}
    <div class="preview-workspace st-key-cv727_decision_workspace">
      <div class="preview-left">{left_html}</div>
      <div class="preview-right">{right_html}</div>
    </div>
    {trailing_html}
  </div>
</body>
</html>
"""
    PREVIEW_ARTIFACT.write_text(preview, encoding="utf-8")
    return PREVIEW_ARTIFACT


def main() -> int:
    st, markdown_calls, html_calls = _install_streamlit_stub()
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    with patch.object(assistant, "_render_response_scroll_anchor"):
        with patch.object(assistant, "_render_quick_actions"):
            assistant._render_response(
                question=PC817_QUESTION,
                answer=PC817_ANSWER,
                context=PC817_CONTEXT,
            )

    html = "\n".join(content for content, _kwargs, _side in markdown_calls)
    left_html = _column_html(markdown_calls, "left")
    right_html = _column_html(markdown_calls, "right")
    exchange_html = _column_html(markdown_calls, "root")
    preview_path = write_pc817_preview_artifact(
        exchange_html=exchange_html,
        left_html=left_html,
        right_html=right_html,
    )

    checks = {
        "question_label_separate": "cv50-you-asked-label" in html and PC817_QUESTION in html,
        "direct_answer": "cv722-direct-answer-title" in html and "Review PC817 first." in html,
        "no_duplicate_direct_answer": html.count("Review PC817 first.") == 1,
        "no_duplicate_direct_answer_paragraph": 'class="cv722-direct-answer-text"' not in html,
        "evidence_component_status_separated": all(
            token in html
            for token in ("cv46-evidence-component", "cv46-evidence-status", "cv46-evidence-label", "cv46-evidence-statement")
        ),
        "no_evidence_concatenation": all(
            bad not in html for bad in ("PC817Review", "BZX55C5V1Review", "DRV8825Review", ">Review</em>", "•EVIDENCE")
        ),
        "three_reasons": html.count('class="cv722-reason-row"') == 3,
        "three_actions": html.count('class="cv722-action-row"') == 3,
        "no_duplicate_numbering": "1. 1" not in html and not any(f"<p>{n}</p>" in html for n in ("1", "2", "3")),
        "native_columns_ratio": any(call[0] == [0.85, 1.15] for call in st.columns_calls),
        "decision_workspace_container": "cv727_decision_workspace" in st.container_calls,
        "left_answer_in_left_column": "cv722-concise-answer" in left_html,
        "left_kpi_in_left_column": "cv722-summary-strip" in left_html,
        "right_assessment_in_right_column": "cv727-assessment-panel" in right_html,
        "no_giant_cv725_grid": "cv725-decision-workspace" not in html,
        "no_details_wrapper": "<details" not in html.lower(),
        "stylesheet_injection_separate": any("cadivor-ask-cadivor-v2-css" in call for call in html_calls),
        "column_content_has_no_style_tag": "<style" not in (left_html + right_html).lower(),
        "native_workspace_css_available": ".cv727-assessment-panel" in ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8"),
        "impact_grid": "cv724-impact-grid" in html,
        "driver_grid": "cv724-driver-grid" in html,
        "evidence_cards": "cv46-evidence-board" in html,
        "kpi_block_labels": 'class="cv722-summary-label">Status</div>' in html,
        "no_escaped_section_literal": "&lt;section" not in html,
        "preview_artifact_written": preview_path.exists(),
        "numeric_values_preserved": all(token in html for token in ("21.4", "2 suppliers", "93", "97", "56%")),
    }

    print("=== Ask Cadivor PC817 presentation harness ===")
    print(f"Question: {PC817_QUESTION}")
    print(f"Rendered HTML length: {len(html)} chars")
    print(f"Preview artifact: {preview_path}")
    print(f"Left column length: {len(left_html)} chars")
    print(f"Right column length: {len(right_html)} chars")
    print()
    failed = False
    for name, ok in checks.items():
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        failed = failed or not ok
    print()
    if failed:
        print("Harness: FAILED")
        return 1
    print("Harness: PASS (zero OpenAI credits consumed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
