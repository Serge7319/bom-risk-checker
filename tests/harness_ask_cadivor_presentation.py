#!/usr/bin/env python3
"""Zero-credit Ask Cadivor presentation harness — Sprint 72.2.5.2.

Renders the PC817 production scenario through the canonical renderer without
calling EngineeringAI.ask() or any OpenAI provider. Also writes a browser-like
preview artifact containing the actual stylesheet and workspace HTML.
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


def _install_streamlit_stub():
    st = types.ModuleType("streamlit")
    st.session_state = {}
    markdown_calls: list[tuple[str, dict]] = []
    html_calls: list[str] = []

    st.markdown = lambda content, **kwargs: markdown_calls.append((str(content), dict(kwargs)))
    st.html = lambda content, **kwargs: html_calls.append(str(content))
    st.expander = lambda *args, **kwargs: _NullContext()
    st.columns = MagicMock(
        side_effect=lambda spec: [MagicMock() for _ in (spec if isinstance(spec, (list, tuple)) else range(int(spec)))]
    )
    st.container = lambda **kwargs: _NullContext()

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
    return markdown_calls, html_calls


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def render_pc817_harness() -> str:
    markdown_calls, _html_calls = _install_streamlit_stub()
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
    return "\n".join(content for content, _kwargs in markdown_calls)


def _workspace_markdown(markdown_calls: list[tuple[str, dict]]) -> tuple[str, dict] | None:
    for content, kwargs in markdown_calls:
        if "cv725-decision-workspace" in content:
            return content, kwargs
    return None


def write_pc817_preview_artifact(response_html: str) -> Path:
    PREVIEW_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    tokens_css = DESIGN_TOKENS_CSS.read_text(encoding="utf-8") if DESIGN_TOKENS_CSS.exists() else ""
    ask_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
    preview = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Ask Cadivor PC817 Preview — Sprint 72.2.5.2</title>
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
  </style>
</head>
<body>
  <div class="preview-shell">
    <p class="preview-note">Deterministic zero-credit preview for Ask Cadivor PC817. Stylesheets: cadivor_design_system_v2.css + ask_cadivor_v2.css.</p>
    {response_html}
  </div>
</body>
</html>
"""
    PREVIEW_ARTIFACT.write_text(preview, encoding="utf-8")
    return PREVIEW_ARTIFACT


def main() -> int:
    markdown_calls, html_calls = _install_streamlit_stub()
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

    html = "\n".join(content for content, _kwargs in markdown_calls)
    workspace = _workspace_markdown(markdown_calls)
    workspace_html = workspace[0] if workspace else ""
    workspace_kwargs = workspace[1] if workspace else {}
    preview_path = write_pc817_preview_artifact(html)

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
        "desktop_workspace": "cv725-decision-workspace" in html,
        "assessment_column": "cv725-decision-assessment" in html,
        "assessment_open_by_default": 'class="cv725-assessment-details" open' in html,
        "stylesheet_injection_separate": any("cadivor-ask-cadivor-v2-css" in call for call in html_calls),
        "workspace_has_no_style_tag": "<style" not in workspace_html.lower(),
        "workspace_css_available": ".cv725-decision-workspace" in ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8"),
        "impact_grid": "cv724-impact-grid" in html,
        "driver_grid": "cv724-driver-grid" in html,
        "evidence_cards": "cv46-evidence-board" in html,
        "kpi_block_labels": 'class="cv722-summary-label">Status</div>' in html,
        "no_escaped_section_literal": "&lt;section" not in html,
        "workspace_starts_column_zero": bool(workspace_html) and workspace_html.lstrip().startswith("<"),
        "workspace_unsafe_allow_html": workspace_kwargs.get("unsafe_allow_html") is True,
        "no_closed_details_desktop_default": 'class="cv725-assessment-details">' not in workspace_html.replace('class="cv725-assessment-details" open', ""),
        "preview_artifact_written": preview_path.exists(),
        "numeric_values_preserved": all(token in html for token in ("21.4", "2 suppliers", "93", "97", "56%")),
    }

    print("=== Ask Cadivor PC817 presentation harness ===")
    print(f"Question: {PC817_QUESTION}")
    print(f"Rendered HTML length: {len(html)} chars")
    print(f"Preview artifact: {preview_path}")
    if workspace_html:
        print(f"Workspace repr (first 500): {repr(workspace_html[:500])}")
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
