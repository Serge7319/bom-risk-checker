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

