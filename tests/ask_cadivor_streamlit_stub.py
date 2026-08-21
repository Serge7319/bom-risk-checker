"""Shared Streamlit stub for Ask Cadivor native UI harnesses and tests."""
from __future__ import annotations

import importlib
import inspect
import sys
import types
from unittest.mock import MagicMock

try:
    import streamlit as _REAL_STREAMLIT

    _CONTAINER_PARAMS = set(inspect.signature(_REAL_STREAMLIT.container).parameters)
    _CONTAINER_PARAMS.add("key")
    _COLUMNS_PARAMS = set(inspect.signature(_REAL_STREAMLIT.columns).parameters)
except Exception:  # pragma: no cover - defensive fallback
    _REAL_STREAMLIT = None  # type: ignore[assignment]
    _CONTAINER_PARAMS = {"height", "border", "key"}
    _COLUMNS_PARAMS = {"spec", "gap", "vertical_alignment"}


def _reimport_module(module_name: str) -> None:
    sys.modules.pop(module_name, None)
    importlib.import_module(module_name)


def restore_ask_cadivor_streamlit_modules() -> None:
    """Restore real Streamlit and commonly stubbed Cadivor modules after Ask Cadivor tests."""
    if _REAL_STREAMLIT is not None:
        sys.modules["streamlit"] = _REAL_STREAMLIT

    secrets = sys.modules.get("src.secrets")
    if secrets is not None and not getattr(secrets, "__file__", None):
        _reimport_module("src.secrets")

    navigation = sys.modules.get("src.ui.navigation")
    if navigation is not None:
        if not getattr(navigation, "__file__", None):
            sys.modules.pop("src.ui.navigation", None)
            _reimport_module("src.ui.navigation")
        else:
            navigate = getattr(navigation, "navigate_to", None)
            if inspect.isfunction(navigate) and navigate.__module__ != "src.ui.navigation":
                _reimport_module("src.ui.navigation")
            elif _REAL_STREAMLIT is not None:
                sys.modules["src.ui.navigation"].st = _REAL_STREAMLIT

    for broken_module in ("src.pages.analysis_detail",):
        module = sys.modules.get(broken_module)
        if module is not None and not getattr(module, "__file__", None):
            sys.modules.pop(broken_module, None)

    for mod_name in list(sys.modules):
        if mod_name.startswith("src.ui.cadivor_design_system"):
            sys.modules.pop(mod_name, None)
        if mod_name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(mod_name, None)


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _StatusContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def update(self, **kwargs):
        return None


class _RecordingColumn:
    def __init__(self, side: str, st_module: types.ModuleType) -> None:
        self._side = side
        self._st = st_module

    def __enter__(self):
        self._st._active_column = self._side
        if hasattr(self._st, "render_sequence"):
            self._st.render_sequence.append(f"column_{self._side}_enter")
        return self

    def __exit__(self, *args):
        self._st._active_column = None
        return False

    def columns(self, spec, gap=None, **kwargs):
        ratio = list(spec) if isinstance(spec, (list, tuple)) else [1] * int(spec)
        self._st.columns_calls.append((ratio, gap))
        if hasattr(self._st, "render_sequence"):
            self._st.render_sequence.append("columns_created")
        return [_RecordingColumn(f"{self._side}_nested_{idx}", self._st) for idx in range(len(ratio))]

    def link_button(self, *args, **kwargs):
        if hasattr(self._st, "render_sequence"):
            self._st.render_sequence.append("link_button")
        return None

    def button(self, *args, **kwargs):
        return False

    def caption(self, *args, **kwargs):
        return None



def install_ask_cadivor_streamlit_stub(
    *,
    session_state: dict | None = None,
    script_run_id: str = "ask-cadivor-stub-run",
):
    restore_ask_cadivor_streamlit_modules()

    st = types.ModuleType("streamlit")
    st.__version__ = getattr(_REAL_STREAMLIT, "__version__", "stub")
    st.session_state = session_state if session_state is not None else {}
    st._active_column = None
    st.render_sequence: list[str] = []
    st.columns_calls: list[tuple[list[float], str | None]] = []
    st.container_calls: list[str] = []
    st.markdown_calls: list[tuple[str, dict, str | None]] = []
    st.caption_calls: list[str] = []
    st.metric_calls: list[tuple] = []
    st.progress_calls: list[float] = []
    st.html_calls: list[str] = []

    class _ScriptRunCtx:
        def __init__(self, run_id: str) -> None:
            self.script_run_id = run_id
            self.gather_usage_stats = False

    script_ctx = _ScriptRunCtx(script_run_id)

    def _markdown(content, **kwargs):
        text = str(content)
        side = st._active_column or "root"
        st.markdown_calls.append((text, dict(kwargs), side))
        st.render_sequence.append(f"markdown_{side}")
        if "Review PC817 first." in text:
            st.render_sequence.append("direct_answer")
        if "cv722-reason-row" in text or "cv722-reason-list" in text:
            st.render_sequence.append("reason_card")
        if "cv722-action-row" in text or "cv722-action-list" in text:
            st.render_sequence.append("action_card")
        if "cv46-evidence-card" in text:
            st.render_sequence.append("evidence_card")
        if "cv722-summary-strip" in text:
            st.render_sequence.append("decision_summary")
        if "cv724-impact-grid" in text:
            st.render_sequence.append("impact_grid")

    def _caption(text, **kwargs):
        st.caption_calls.append(str(text))
        st.render_sequence.append("caption")

    def _metric(label, value, **kwargs):
        st.metric_calls.append((label, value, dict(kwargs)))
        st.render_sequence.append("metric")

    def _progress(value, **kwargs):
        st.progress_calls.append(float(value))
        st.render_sequence.append("progress")

    def _columns(spec, gap=None, **kwargs):
        unsupported = sorted(set(kwargs) - _COLUMNS_PARAMS)
        if unsupported:
            raise TypeError(
                "LayoutsMixin.columns() got an unexpected keyword argument "
                + repr(unsupported[0])
            )
        ratio = list(spec) if isinstance(spec, (list, tuple)) else [1] * int(spec)
        st.columns_calls.append((ratio, gap))
        st.render_sequence.append("columns_created")
        if ratio == [0.85, 1.15]:
            return [_RecordingColumn("left", st), _RecordingColumn("right", st)]
        return [_RecordingColumn(f"col_{idx}", st) for idx in range(len(ratio))]

    def _container(*args, **kwargs):
        if args:
            raise TypeError("container() takes 0 positional arguments")
        unsupported = sorted(set(kwargs) - _CONTAINER_PARAMS)
        if unsupported:
            raise TypeError(
                "LayoutsMixin.container() got an unexpected keyword argument "
                + repr(unsupported[0])
            )
        if kwargs.get("border"):
            st.container_calls.append("border")
            st.render_sequence.append("container_border")
        else:
            st.container_calls.append("plain")
            st.render_sequence.append("container_plain")
        return _NullContext()

    st.markdown = _markdown
    st.caption = _caption
    st.metric = _metric
    st.progress = _progress
    st.html = lambda content, **kwargs: st.html_calls.append(str(content))
    st.columns = _columns
    st.container = _container
    st.expander = lambda *args, **kwargs: _NullContext()
    st.form = lambda *args, **kwargs: _NullContext()
    st.text_area = MagicMock(return_value="")
    st.form_submit_button = MagicMock(return_value=False)
    st.button = MagicMock(return_value=False)
    st.radio = MagicMock(return_value="Ask Cadivor")
    st.info = MagicMock()
    st.warning = MagicMock()
    st.success = MagicMock()
    st.status = lambda *args, **kwargs: _StatusContext()
    st.link_button = MagicMock()
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
    for mod_name in list(sys.modules):
        if mod_name.startswith("src.ui.cadivor_design_system"):
            sys.modules.pop(mod_name, None)
    return st
