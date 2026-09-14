"""Every saved-BOM section uses the same navigation markup and underline style."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from src.ui.bom_navigation import (
    MORE_MENU,
    PRIMARY_AREAS,
    SAVED_BOM_NAV_CLASS,
    SAVED_BOM_NAV_KEY,
    SAVED_BOM_NAV_MORE_KEY,
    SAVED_BOM_TAB_KEY_PREFIX,
    render_saved_bom_section_nav,
    saved_bom_nav_css,
)

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = (
    "Engineering Decision Brief",
    "Parts & Risk",
    "Replacement Intelligence",
    "Engineering Decisions",
    "Ask Cadivor",
    "More menu open",
)


class _FakeStreamlit:
    def __init__(self) -> None:
        self.markdowns: list[str] = []
        self.containers: list[str] = []
        self.buttons: list[dict] = []
        self.popovers: list[str] = []

    def markdown(self, body, **_kwargs) -> None:
        self.markdowns.append(str(body))

    @contextmanager
    def container(self, key=None, **_kwargs):
        self.containers.append(str(key or ""))
        yield None

    def button(self, label, **kwargs):
        self.buttons.append({"label": label, **kwargs})
        return False

    @contextmanager
    def popover(self, label, **_kwargs):
        self.popovers.append(str(label))
        yield None


def _render(area: str, more_choice: str = "More") -> _FakeStreamlit:
    import sys
    import types

    fake = _FakeStreamlit()
    module = types.ModuleType("streamlit")
    module.markdown = fake.markdown
    module.container = fake.container
    module.button = fake.button
    module.popover = fake.popover
    previous = sys.modules.get("streamlit")
    sys.modules["streamlit"] = module
    try:
        render_saved_bom_section_nav(
            analysis_id="bom-1",
            selected_area=area if area in PRIMARY_AREAS else "Parts & Risk",
            more_choice=more_choice,
            more_menu=MORE_MENU,
        )
    finally:
        if previous is not None:
            sys.modules["streamlit"] = previous
        else:
            sys.modules.pop("streamlit", None)
    return fake


def test_every_saved_bom_section_uses_the_shared_nav():
    for section in SECTIONS:
        more_choice = "Discussion" if section == "More menu open" else "More"
        area = section if section in PRIMARY_AREAS else "Parts & Risk"
        rendered = _render(area, more_choice)
        markup = "\n".join(rendered.markdowns)
        assert SAVED_BOM_NAV_CLASS in markup, section
        assert 'data-cv-saved-bom-nav="shared"' in markup, section
        if section == "More menu open":
            assert 'data-cv-saved-bom-active="more"' in markup, section
        else:
            assert 'data-cv-saved-bom-active="area"' in markup, section
        assert rendered.containers.count(SAVED_BOM_NAV_KEY) == 1, section
        assert SAVED_BOM_NAV_MORE_KEY in rendered.containers, section
        labels = [item["label"] for item in rendered.buttons]
        assert list(PRIMARY_AREAS) == [label for label in labels if label in PRIMARY_AREAS], section
        assert rendered.popovers == ["More ▾"], section
        if section == "More menu open":
            assert all(item["type"] == "secondary" for item in rendered.buttons if "type" in item), section
        else:
            active = [item for item in rendered.buttons if item["label"] == area]
            assert active and active[0]["type"] == "primary", section
        assert all(
            item["key"].startswith(SAVED_BOM_TAB_KEY_PREFIX)
            for item in rendered.buttons
            if item["label"] in PRIMARY_AREAS
        ), section


def test_shared_nav_style_is_underline_only():
    css = saved_bom_nav_css()
    assert "border-bottom: 2px solid transparent" in css
    assert "border-bottom: 2px solid #2563eb" in css
    assert "border-radius: 0 !important" in css
    assert "background: #fff !important" in css
    assert "border-bottom: 1px solid #e5e7eb !important" in css
    assert "#eff6ff" not in css
    assert "border-radius: 10px 10px 0 0" not in css
    assert "border-radius: 999" not in css
    assert "border-radius: 8px" not in css
    assert "border-radius: 10px" not in css
    assert ".st-key-cv_foundation_navigation" in css
    assert "html body section[data-testid=\"stMain\"] [class*=\"st-key-cadivor_bom_tab_\"] button" not in css
    assert "html body section[data-testid=\"stMain\"] .st-key-cv_analysis_section_nav .stButton:not(.st-key-cv_foundation_navigation .stButton)" in css
    assert "data-cv-saved-bom-active=\"more\"" in css
    pill_sources = (
        ROOT / "src/assets/css/core_premium_ui.css",
        ROOT / "src/assets/css/premium_interactions.css",
        ROOT / "src/css/premium.css",
    )
    for path in pill_sources:
        text = path.read_text(encoding="utf-8")
        assert ".st-key-cv_analysis_section_nav" in text, path.name
        assert ".st-key-cv_saved_bom_nav_more" in text, path.name
    geometry = (ROOT / "src/ui/core_premium_ui.py").read_text(encoding="utf-8")
    final = geometry.split("def inject_workspace_geometry_final", 1)[1].split(
        "def authenticated_surface_ready", 1
    )[0]
    assert final.rindex("inject_saved_bom_nav_css()") > final.rindex("inject_cadivor_design_system()")
    page = (ROOT / "src/pages/analysis_detail.py").read_text(encoding="utf-8")
    assert ".st-key-cv_analysis_section_nav [data-testid=\"stHorizontalBlock\"]" not in page
