from pathlib import Path


def test_approved_finder_consumes_clicked_part_before_mounting_search_input():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    renderer = source.split("def render_replacement_search", 1)[1].split(
        "def render_compare_live", 1
    )[0]

    assert "consume_alternative_finder_context(_query_param)" in renderer
    assert "apply_alternative_finder_prefill(navigation_context)" in renderer
    assert renderer.index('st.session_state["approved_replacement_query"] = clicked_mpn') < renderer.index(
        'st.text_input("Search MPN", key="approved_replacement_query")'
    )
    assert 'st.session_state.pop("alternative_prefill_search_pending", False)' in renderer
    assert "if (run or prefilled_search_pending) and query:" in renderer
    assert 'original["manufacturer_part_number"] = context_mpn' in renderer


def test_approval_controls_are_inside_candidate_details_and_persist_per_bom():
    root = Path(__file__).resolve().parents[1]
    page_source = (root / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
    navigation_source = (root / "src" / "ui" / "navigation.py").read_text(encoding="utf-8")
    runtime_source = (root / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
    renderer = page_source.split("def render_replacement_search", 1)[1].split(
        "def render_compare_live", 1
    )[0]

    assert "Approve this alternative" in page_source
    assert "Update approval" in page_source
    assert "Remove approval" in page_source
    assert "len(approved_names) < 3" in page_source
    assert "Record approved alternatives" not in renderer
    assert "Save approved alternatives" not in renderer
    call = renderer.index("_render_bom_replacement_approvals(")
    loop = renderer.index("for index, row in enumerate(shown):")
    expanded = renderer.index("if is_open:", loop)
    assert call > expanded
    assert "candidate=row" in renderer[call:call + 400]
    assert '"context_key": context_key' in page_source
    assert '"analysis_id": str(context.get("analysis_id") or "")' in navigation_source
    assert "payload.get(\"context_key\")" in runtime_source


def test_contextual_replacement_has_direct_return_to_bom_risk():
    root = Path(__file__).resolve().parents[1]
    page_source = (root / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
    navigation_source = (root / "src" / "ui" / "navigation.py").read_text(encoding="utf-8")

    assert '"engineering_intelligence_review": "← Back to BOM Risk"' in page_source
    assert "_navigate_back_to_bom_review(source_context)" in page_source
    assert 'st.session_state["cadivor_ei_report_tab"] = "BOM Risk"' in page_source
    assert 'st.session_state["cadivor_approved_alternatives_flash"] =' in page_source
    assert "Saved approvals stay with this BOM across analysis reruns" in page_source
    assert 'for context_key in ("source_page", "project_name", "bom_name"):' in navigation_source


def test_finder_route_stops_after_the_approved_renderer_and_reveals_before_search():
    root = Path(__file__).resolve().parents[1]
    runtime = (root / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
    page_source = (root / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
    branch = runtime.split('    if app_mode == "Alternative Finder":', 1)[1].split(
        '    if app_mode in {"BOM Analyzer", "High Risk Review"}:', 1
    )[0]
    renderer = page_source.split("def render_replacement_search", 1)[1].split(
        "def render_compare_live", 1
    )[0]

    assert branch.index("render_replacement_search()") < branch.index(
        'reveal_authenticated_page_body("Alternative Finder")'
    ) < branch.index("stop_authenticated_page()")
    assert branch.index("stop_authenticated_page()") < branch.index(
        "from integrations.supplier_aggregator import get_best_part_data"
    )
    assert renderer.index("<h1>Find a replacement</h1>") < renderer.index(
        'reveal_authenticated_page_body("Alternative Finder")'
    ) < renderer.index("run_alternative_finder_search(st.session_state, query)")


def test_compare_handoff_is_staged_before_compare_widgets_and_can_save_approval():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    finder = source.split("def render_replacement_search", 1)[1].split(
        "def render_compare_live", 1
    )[0]
    compare = source.split("def render_compare_live", 1)[1].split(
        "def render_datasheet_live", 1
    )[0]

    assert 'st.session_state["cadivor_compare_pending_handoff"]' in finder
    assert 'st.session_state["approved_compare_a"]' not in finder
    assert 'st.session_state.pop("cadivor_compare_pending_handoff", None)' in compare
    assert compare.index('st.session_state["approved_compare_a"] = pending_parts[0]') < compare.index(
        'st.text_input("Part A", key="approved_compare_a"'
    )
    assert '_render_bom_replacement_approvals(' in compare
    assert 'recorded_from="Compare parts"' in compare
    assert "from src.approved_alternatives import part_key" in compare


def test_obsolete_candidates_are_excluded_and_add_controls_use_stable_callbacks():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    renderer = source.split("def render_replacement_search", 1)[1].split(
        "def render_compare_live", 1
    )[0]
    approvals = source.split("def _render_bom_replacement_approvals", 1)[1].split(
        "def render_replacement_search", 1
    )[0]

    assert "excluded_obsolete = [row for row in named if candidate_lifecycle_is_blocked(row)]" in renderer
    assert "row for row in named if not candidate_lifecycle_is_blocked(row)" in renderer
    assert "on_click=_toggle_compare_candidate" in renderer
    assert '"approved_replacement_compare_toggle_"' in renderer
    assert "lifecycle_blocked = candidate_lifecycle_is_blocked(candidate)" in approvals
    assert "can_approve = not lifecycle_blocked" in approvals


def test_streamlit_stale_refresh_does_not_dim_current_page_or_duplicate_nav():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "unified_shell.py"
    ).read_text(encoding="utf-8")
    assert 'body [data-stale="true"]{' in source
    assert 'opacity:1!important;filter:none!important' in source
    assert 'body:has([class*="st-key-cv_foundation_navigation"]:not([data-stale="true"]))' in source
    assert '[data-stale="true"]:has([class*="st-key-cv_foundation_navigation"])' in source
