from pathlib import Path


RUNTIME_SOURCE = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")


def test_bom_workspace_uses_distinct_new_and_saved_work_panels():
    assert 'class="bom9-workspace-hero"' in RUNTIME_SOURCE
    assert 'key="bom9_upload_panel"' in RUNTIME_SOURCE
    assert 'key="bom9_saved_panel"' in RUNTIME_SOURCE
    assert "st.columns([0.42, 0.58], gap=\"large\")" in RUNTIME_SOURCE
    assert "Build or reopen an engineering BOM" in RUNTIME_SOURCE


def test_saved_bom_library_keeps_context_and_management_actions():
    assert 'class="bom81-result-count"' in RUNTIME_SOURCE
    assert "height=min(540, 88 + len(editor_df) * 40)" in RUNTIME_SOURCE
    assert "Open Selected Analysis" in RUNTIME_SOURCE
    assert 'key="bom81_save_project_names"' in RUNTIME_SOURCE
    assert 'key="bom81_request_bulk_delete"' in RUNTIME_SOURCE
    assert 'key="bom81_clear_selection"' in RUNTIME_SOURCE
    assert 'key="bom9_review_queue"' in RUNTIME_SOURCE


def test_bom_workspace_has_laptop_tablet_and_mobile_rules():
    assert "@media(max-width:1360px)" in RUNTIME_SOURCE
    assert "@media(max-width:1100px)" in RUNTIME_SOURCE
    assert "@media(max-width:820px)" in RUNTIME_SOURCE
    assert "@media(max-width:620px)" in RUNTIME_SOURCE
    assert (
        'div[data-testid="stHorizontalBlock"]:has(.st-key-bom9_upload_panel)'
        ":has(.st-key-bom9_saved_panel)"
    ) in RUNTIME_SOURCE
    assert (
        'div[data-testid="stHorizontalBlock"]:has(.st-key-bom81_save_project_names)'
        ":has(.st-key-bom81_open_selected)"
    ) in RUNTIME_SOURCE
