from pathlib import Path
import json


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


def test_approving_from_a_bom_returns_to_the_updated_engineering_report():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    renderer = source.split("def _render_bom_replacement_approvals", 1)[1].split(
        "def render_replacement_search", 1
    )[0]
    saved_notice = renderer.index('st.session_state["cadivor_approved_alternatives_flash"] = (')
    return_to_report = renderer.index("if _navigate_back_to_bom_review(context):", saved_notice)
    rerun = renderer.index("st.rerun()", return_to_report)
    assert saved_notice < return_to_report < rerun

    report_source = (Path(__file__).resolve().parents[1] / "src" / "ui" / "ei_bom_report.py").read_text(encoding="utf-8")
    assert 'st.session_state.pop("cadivor_approved_alternatives_flash", "")' in report_source
    assert 'f"View approved alternatives ({approved_count})"' in report_source
    assert 'st.session_state[tab_state_key] = "Alternatives"' in report_source


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
    assert "candidate_lifecycle_is_blocked(approval_candidate)" in approvals
    assert "datasheet_lifecycle_blocked" in approvals
    assert "not lifecycle_blocked" in approvals
    assert "not compatibility_blocked" in approvals


def test_physical_and_isa_mismatches_are_prominent_and_block_bom_approval():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    approvals = source.split("def _render_bom_replacement_approvals", 1)[1].split(
        "def render_replacement_search", 1
    )[0]
    compare = source.split("def render_compare_live", 1)[1].split(
        "def render_datasheet_live", 1
    )[0]

    assert "CRITICAL_PHYSICAL_WARNING" in source
    assert "CRITICAL_FIRMWARE_WARNING" in source
    assert "blocked_from_drop_in_approval" in approvals
    assert "requires_acknowledgement" in approvals
    assert "not compatibility_blocked" in approvals
    assert "disabled=not can_approve" in approvals
    assert "and lifecycle_verified" in approvals
    assert "Candidate lifecycle is not verified as Active or NRND" in approvals
    assert "cv-compat-banner critical" in source
    assert "cv-compare-compat-critical" in compare
    assert 'compatibility_by_slot["Part B"] = assess_part_compatibility(' in compare


def test_datasheet_review_is_connected_to_finder_and_compare_approval():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    finder = source.split("def render_replacement_search", 1)[1].split(
        "def render_compare_live", 1
    )[0]
    compare = source.split("def render_compare_live", 1)[1].split(
        "def render_datasheet_live", 1
    )[0]
    approvals = source.split("def _render_bom_replacement_approvals", 1)[1].split(
        "def render_replacement_search", 1
    )[0]

    assert "_render_datasheet_evidence_review(" in approvals
    assert '"Refresh datasheet analysis"' in source
    assert "Optional source PDF" in source
    assert "Optional candidate PDF" in source
    assert "review_references_complete" in approvals
    assert "linked_documents_reviewed" in approvals
    assert "comparison_evidence={\"comparison\": comparison, \"slot\": candidate_slot}" in compare
    assert "_render_bom_replacement_approvals(" in finder


def test_approval_explains_missing_citations_and_offers_pdf_review_at_the_gate():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    approvals = source.split("def _render_bom_replacement_approvals", 1)[1].split(
        "def render_replacement_search", 1
    )[0]
    datasheet_review = source.split("def _render_datasheet_evidence_review", 1)[1].split(
        "def _approval_evidence_for_comparison", 1
    )[0]

    assert "This checkbox records your review" in approvals
    assert "does not approve the part by itself" in approvals
    assert '"Analyze linked datasheets"' in approvals
    assert "on_click=_request_datasheet_review" in approvals
    assert "review_request_key = f\"cadivor_alt_datasheet_review_request_{key_suffix}\"" in datasheet_review
    assert "review_requested or review_clicked" in datasheet_review


def test_approval_review_is_easy_to_reach_and_disabled_action_looks_disabled():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    approvals = source.split("def _render_bom_replacement_approvals", 1)[1].split(
        "def render_replacement_search", 1
    )[0]
    datasheet_review = source.split("def _render_datasheet_evidence_review", 1)[1].split(
        "def _approval_evidence_for_comparison", 1
    )[0]

    assert "Skip the evidence details and go to review &amp; approval" in approvals
    assert "cadivor-approval-checklist-" in approvals
    assert approvals.index('st.markdown("#### Engineering approval")') < approvals.index(
        "st.checkbox("
    )
    assert "This checkbox records your review. It does not approve the part by itself." in approvals
    assert 'expanded=False' in datasheet_review
    assert 'button[kind="primary"]:disabled' in approvals
    assert '"Approval locked — resolve the items above"' in approvals
    assert "package_document_conflicts(recorded_value, extracted_value)" in approvals


def test_linked_datasheets_are_analyzed_automatically_and_upload_is_optional():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    datasheet_review = source.split("def _render_datasheet_evidence_review", 1)[1].split(
        "def _approval_evidence_for_comparison", 1
    )[0]

    assert "automatically retrieves and analyzes available supplier/manufacturer PDFs" in datasheet_review
    assert 'with st.expander("Optional: upload or replace a datasheet", expanded=False)' in datasheet_review
    assert "auto_review_requested = bool(" in datasheet_review
    assert "auto_review_requested or review_requested or review_clicked" in datasheet_review
    assert "Refresh datasheet analysis" in datasheet_review


def test_saved_approval_exposes_datasheet_citations_and_report_links():
    from src.approved_alternatives import report_alternative
    from src.ui.ei_bom_report import _tab_body

    review = {
        "source_url": "https://manufacturer.example/source.pdf",
        "candidate_url": "https://manufacturer.example/candidate.pdf",
        "review_complete": True,
        "reviewer_attestation": {
            "confirmed": True,
            "source_reference": "Manufacturer A Rev C pp. 10-11",
            "candidate_reference": "Manufacturer B Rev D pp. 12-13",
        },
        "source_dimensions": [
            {"document": "Manufacturer A Rev C", "page": "10", "excerpt": "Body length 10.0 mm"}
        ],
        "field_evidence": [{"attribute": "Package", "source_excerpt": "SOIC-16", "candidate_excerpt": "SOIC-16"}],
    }
    row = report_alternative(
        {
            "original_part": "SOURCE-1",
            "alternative_part": "CANDIDATE-1",
            "comparison_snapshot": json.dumps({"datasheet_review": review}),
        }
    )
    assert row["datasheet_review"]["review_complete"] is True
    assert row["datasheet_review"]["reviewer_attestation"]["candidate_reference"].endswith("pp. 12-13")

    report_source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "ei_bom_report.py"
    ).read_text(encoding="utf-8")
    assert '"source_url"' in report_source
    assert '"candidate_url"' in report_source
    assert 'rel="noopener noreferrer"' in report_source

    rendered = _tab_body(
        "Alternatives",
        [],
        [],
        approved_alternatives=[
            {
                "original_part": "SOURCE-1",
                "alternative_part": "CANDIDATE-1",
                "comparison_snapshot": json.dumps({"datasheet_review": review}),
            }
        ],
    )
    assert "Manufacturer A Rev C pp. 10-11" in rendered
    assert "Manufacturer B Rev D pp. 12-13" in rendered
    assert "Body length 10.0 mm" in rendered
    assert "manufacturer.example/source.pdf" in rendered
    assert "manufacturer.example/candidate.pdf" in rendered


def test_streamlit_stale_refresh_does_not_dim_current_page_or_duplicate_nav():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "unified_shell.py"
    ).read_text(encoding="utf-8")
    assert 'body [data-stale="true"]{' in source
    assert 'opacity:1!important;filter:none!important' in source
    assert 'body:has([class*="st-key-cv_foundation_navigation"]:not([data-stale="true"]))' in source
    assert '[data-stale="true"]:has([class*="st-key-cv_foundation_navigation"])' in source
