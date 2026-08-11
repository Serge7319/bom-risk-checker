#!/usr/bin/env python3
"""Zero-credit Ask Cadivor stylesheet-loading harness — Sprint 72.2.9.

Proves ask_cadivor_v2.css loads through the same authenticated app-shell path
as premium.css and cadivor_design_system_v2.css, and that the response renderer
does not inject its own <style> block.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
PREMIUM_CSS = REPO_ROOT / "src/assets/css/premium.css"
DS_V2_CSS = REPO_ROOT / "src/assets/css/cadivor_design_system_v2.css"

from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION


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


def _install_streamlit_stub(*, script_run_id: str = "stylesheet-harness-run"):
    st = types.ModuleType("streamlit")
    st.session_state = {}
    st._active_column = None
    st.markdown_calls: list[tuple[str, dict, str | None]] = []
    st.html_calls: list[str] = []
    st.columns_calls: list[list[float]] = []

    class _ScriptRunCtx:
        def __init__(self, run_id: str) -> None:
            self.script_run_id = run_id

    script_ctx = _ScriptRunCtx(script_run_id)

    def _markdown(content, **kwargs):
        side = st._active_column or "root"
        st.markdown_calls.append((str(content), dict(kwargs), side))

    st.markdown = _markdown
    st.html = lambda content, **kwargs: st.html_calls.append(str(content))
    st.columns = lambda spec, gap=None: (
        st.columns_calls.append(list(spec) if isinstance(spec, (list, tuple)) else [1] * int(spec)) or [
            _RecordingColumn("left", st),
            _RecordingColumn("right", st),
        ]
    )
    st.container = lambda **kwargs: _NullContext()
    st.error = lambda *args, **kwargs: None

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = lambda *args, **kwargs: script_ctx
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner
    components = types.ModuleType("streamlit.components.v1")
    components.html = lambda content, **kwargs: st.html_calls.append(str(content))

    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    st.script_ctx = script_ctx
    return st


def _stylesheet_markdown_calls(st) -> list[str]:
    return [content for content, _kwargs, _side in st.markdown_calls if "<style" in content.lower()]


def simulate_authenticated_app_css_stack(st) -> list[str]:
    """Mirror authenticated_runtime.py CSS order without auth or navigation."""
    for name in (
        "src.ui.framework",
        "src.ui.design_system_v1",
        "src.ui.design_system_v2",
    ):
        sys.modules.pop(name, None)

    from src.ui.framework import inject_premium_css
    from src.ui.design_system_v1 import inject_design_system_v1

    inject_premium_css()
    inject_design_system_v1()
    return _stylesheet_markdown_calls(st)


def render_pc817_response_without_stylesheet(st) -> tuple[str, list[tuple[str, dict, str | None]]]:
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    start = len(st.markdown_calls)
    with patch.object(assistant, "_render_response_scroll_anchor"):
        with patch.object(assistant, "_render_quick_actions"):
            assistant._render_response(
                question=PC817_QUESTION,
                answer=PC817_ANSWER,
                context=PC817_CONTEXT,
            )
    response_calls = st.markdown_calls[start:]
    return "\n".join(content for content, _kwargs, _side in response_calls), response_calls


def main() -> int:
    st = _install_streamlit_stub()
    stylesheet_calls = simulate_authenticated_app_css_stack(st)
    response_html, response_calls = render_pc817_response_without_stylesheet(st)

    premium_css = PREMIUM_CSS.read_text(encoding="utf-8")
    ds_v2_css = DS_V2_CSS.read_text(encoding="utf-8")
    ask_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")

    premium_call = next((call for call in stylesheet_calls if premium_css[:120] in call), "")
    ds_v2_call = next((call for call in stylesheet_calls if "cadivor-design-system-v2" in call), "")
    ask_call = next((call for call in stylesheet_calls if "cadivor-ask-cadivor-v2-css" in call), "")

    response_markdown = [content for content, _kwargs, _side in response_calls]
    response_stylesheet_calls = [content for content in response_markdown if "<style" in content.lower()]

    checks = {
        "premium_loaded_via_app_shell": bool(premium_call.startswith("<style>")),
        "ds_v2_loaded_via_app_shell": "cadivor-design-system-v2" in ds_v2_call,
        "ask_cadivor_loaded_via_app_shell": "cadivor-ask-cadivor-v2-css" in ask_call,
        "ask_css_matches_disk_file": ask_css.strip() in ask_call,
        "ask_css_contains_contract_selectors": all(
            selector in ask_css
            for selector in (
                ".cv49-answer-card",
                ".cv727-assessment-panel",
                ".cv724-impact-grid",
                ".cv46-evidence-board",
            )
        ),
        "response_renderer_emits_no_style_tag": len(response_stylesheet_calls) == 0,
        "response_markup_present": "cv49-answer-card" in response_html,
        "native_columns_ratio_preserved": any(call == [0.85, 1.15] for call in st.columns_calls),
        "no_st_html_stylesheet_path": all("cadivor-ask-cadivor-v2-css" not in call for call in st.html_calls),
        "engineering_assistant_has_no_runtime_injection": "_inject_ask_cadivor_v2_styles" not in (
            REPO_ROOT / "src/components/engineering_assistant.py"
        ).read_text(encoding="utf-8"),
    }

    print("=== Ask Cadivor stylesheet-loading harness (Sprint 72.2.9) ===")
    print(f"App-shell stylesheet blocks: {len(stylesheet_calls)}")
    print(f"Response HTML length: {len(response_html)} chars")
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
