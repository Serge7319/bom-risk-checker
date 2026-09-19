from pathlib import Path


RUNTIME_SOURCE = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")


def test_bom_workspace_uses_distinct_new_and_saved_work_panels():
    assert 'class="bom9-workspace-hero"' in RUNTIME_SOURCE
    assert 'key="bom9_upload_panel"' in RUNTIME_SOURCE
    assert 'key="bom9_saved_panel"' in RUNTIME_SOURCE
    assert "st.columns([0.38, 0.62], gap=\"large\")" in RUNTIME_SOURCE
    assert "Build or reopen an engineering BOM" in RUNTIME_SOURCE


def test_saved_bom_library_keeps_context_and_management_actions():
    assert 'class="bom81-result-count"' in RUNTIME_SOURCE
    assert 'class="bom81-table-intelligence"' in RUNTIME_SOURCE
    assert '"Needs attention first"' in RUNTIME_SOURCE
    assert '"Next step": manager_df["Next step"]' in RUNTIME_SOURCE
    assert "st.column_config.ProgressColumn" in RUNTIME_SOURCE
    assert '"Components": manager_df["Components"]' in RUNTIME_SOURCE
    assert "height=min(520, 76 + len(editor_df) * 44)" in RUNTIME_SOURCE
    assert '"Open BOM" if selected_count == 1' in RUNTIME_SOURCE
    assert 'key="bom81_save_project_names"' in RUNTIME_SOURCE
    assert 'key="bom81_request_bulk_delete"' in RUNTIME_SOURCE
    assert 'key="bom81_clear_selection"' in RUNTIME_SOURCE
    assert 'key="bom9_review_queue"' in RUNTIME_SOURCE
    assert '"Sort"' in RUNTIME_SOURCE


def test_bom_workspace_removes_passive_summary_tiles_and_compacts_review_action():
    assert 'class="bom9-workspace-stats"' not in RUNTIME_SOURCE
    assert 'class="bom9-workspace-stat"' not in RUNTIME_SOURCE
    assert "Review high-risk parts" in RUNTIME_SOURCE
    assert "use_container_width=False" in RUNTIME_SOURCE
    assert "Select one BOM to enable Open BOM." in RUNTIME_SOURCE


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
