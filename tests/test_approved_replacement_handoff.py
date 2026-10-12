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
