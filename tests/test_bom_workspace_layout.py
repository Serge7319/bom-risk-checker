from pathlib import Path


RUNTIME_SOURCE = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
APPROVED_SOURCE = Path("src/ui/approved_pages.py").read_text(encoding="utf-8")


def test_bom_workspace_uses_distinct_new_and_saved_work_panels():
    assert 'class="bom9-workspace-hero"' in RUNTIME_SOURCE
    assert 'key="bom9_upload_panel"' in RUNTIME_SOURCE
    assert 'key="bom9_saved_panel"' in RUNTIME_SOURCE
    assert "st.columns([0.38, 0.62], gap=\"large\")" in RUNTIME_SOURCE
    assert "Build or reopen an engineering BOM" in RUNTIME_SOURCE


def test_approved_upload_does_not_render_the_legacy_duplicate_uploader():
    guard = "if should_render_legacy_bom_workspace(st.session_state):"
    start = RUNTIME_SOURCE.index(guard)
    end = RUNTIME_SOURCE.index('        sample_mode = bool(st.session_state.get("bom8_sample_mode"))', start)
    legacy_workspace = RUNTIME_SOURCE[start:end]

    assert 'key="bom_file_uploader"' in legacy_workspace
    assert "should_render_legacy_bom_workspace" in RUNTIME_SOURCE[:start]


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



def test_new_bom_project_name_is_free_text():
    start = APPROVED_SOURCE.index('with st.container(key="approved_bom_upload_panel")')
    end = APPROVED_SOURCE.index('    else:\n        from datetime import date', start)
    upload_form = APPROVED_SOURCE[start:end]

    assert 'typed_project = st.text_input(' in upload_form
    assert '"Project name"' in upload_form
    assert 'selected_project = st.selectbox(' not in upload_form
    assert 'resolve_project_choice(' in upload_form
    assert 'NEW_PROJECT_CHOICE' in upload_form


def test_new_bom_upload_submits_names_and_file_together():
    start = APPROVED_SOURCE.index('with st.container(key="approved_bom_upload_panel")')
    end = APPROVED_SOURCE.index('    else:\\n        from datetime import date', start)
    upload_form = APPROVED_SOURCE[start:end]

    assert 'with st.form(key="approved_bom_upload_form", clear_on_submit=False)' in upload_form
    assert 'st.form_submit_button(' in upload_form
    assert 'autocomplete="off"' in upload_form
    assert 'st.session_state["cadivor_pending_project"]' in upload_form
    assert 'st.session_state["cadivor_pending_bom_name"] = bom_name' in upload_form
    assert '[class*="st-key-approved_bom_analyze"] button{width:auto!important' in APPROVED_SOURCE


def test_analysis_workspace_hides_duplicate_legacy_hero_and_caps_actions():
    hero_start = RUNTIME_SOURCE.index('class="bom9-workspace-hero"')
    guard_start = RUNTIME_SOURCE.rfind('if should_render_legacy_bom_workspace(st.session_state):', 0, hero_start)
    assert guard_start >= 0
    assert 'st-key-bom8_analysis_progress_card{max-width:960px!important' in RUNTIME_SOURCE
    assert 'st-key-bom8_analysis_preview{max-width:1440px!important' in RUNTIME_SOURCE
    assert 'st-key-bom8_one_time_payment_action{max-width:760px!important' in RUNTIME_SOURCE
    payment_start = RUNTIME_SOURCE.index('key="bom8_one_time_payment_action"')
    payment_end = RUNTIME_SOURCE.index('except OneTimeBOMError as exc:', payment_start)
    payment_action = RUNTIME_SOURCE[payment_start:payment_end]
    assert 'use_container_width=False' in payment_action
    assert 'use_container_width=True' not in payment_action
