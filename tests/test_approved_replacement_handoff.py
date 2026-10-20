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
    assert "get_alternative_finder_original_part_input_config" in renderer
    assert "input_widget_key, _input_default" in renderer
    assert 'key=input_widget_key' in renderer
    assert 'st.session_state.pop("alternative_prefill_search_pending", False)' in renderer
    assert 'on_click=_queue_replacement_search' in renderer
    assert 'st.session_state.pop("cadivor_replacement_search_pending", "")' in renderer
    search_call = renderer.index("run_alternative_finder_search(st.session_state, query)")
    page_heading = renderer.index('"<div class=\'cv-ap\'><h1>Find a replacement')
    reveal = renderer.index('reveal_authenticated_page_body("Alternative Finder")')
    input_mount = renderer.index("key=input_widget_key")
    assert page_heading < input_mount < reveal < search_call
    assert "st.rerun()" not in renderer[search_call:search_call + 180]
    guard = renderer.index("search_completed = has_durable_search_for_mpn(st.session_state, query)")
    assert "if not search_completed:" in renderer[guard:]
    assert guard < renderer.index('fit_filter, life_filter, stock_filter, risk_filter, sort_by = st.columns(5)')
    assert guard < renderer.index("Replacement candidates</h2>")
    assert "        return\n    supplier_candidate_count = len(candidates)" in renderer[guard:]
    assert 'original["manufacturer_part_number"] = context_mpn' in renderer


def test_datasheet_review_shows_document_status_and_avoids_empty_evidence_table():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    review = source.split("def _render_datasheet_evidence_review", 1)[1].split(
        "def _approval_evidence_for_comparison", 1
    )[0]
    assert "cv-ap-doc-status" in review
    assert "MANUAL REVIEW" in review
    assert "if fields and has_extractable_text:" in review
    assert "Datasheets linked; evidence needs direct review" in review
    assert "No text-based package or dimension excerpt was found." in review


def test_approved_search_and_datasheet_mockup_keep_existing_processing_paths():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    qna_styles = (
        Path(__file__).resolve().parents[1] / "src" / "pages" / "datasheet_qa.py"
    ).read_text(encoding="utf-8")
    home_renderer = source.split("def render_home(", 1)[1].split(
        "def render_bom_catalog", 1
    )[0]
    finder = source.split("def render_replacement_search", 1)[1].split(
        "def render_compare_live", 1
    )[0]
    datasheet = source.split("def render_datasheet_live", 1)[1].split(
        "def render_settings_workspace", 1
    )[0]

    assert '"Manufacturer part number"' in finder
    assert 'placeholder="e.g., LM7805ACT"' in finder
    assert 'key="approved_replacement_search"' in finder
    assert 'on_click=_queue_replacement_search' in finder
    assert "run_alternative_finder_search(st.session_state, query)" in finder
    assert 'key="datasheet_qa_uploader"' in datasheet
    assert "datasheet_upload_signature(payload, filename=filename)" in datasheet
    assert "store_document_in_session(st.session_state, extracted)" in datasheet
    assert 'key=DATASHEET_QA_QUESTION_WIDGET_KEY' in datasheet
    assert 'key="approved_datasheet_ask"' in datasheet
    assert 'key="approved_datasheet_follow_up"' in datasheet
    assert "ASK A FOLLOW-UP" in datasheet
    assert "cv-dq-current-question" in datasheet
    assert "show_question_reference=False" in datasheet
    assert "_execute_datasheet_question(" in datasheet
    assert "_render_thread_turn(" in datasheet
    assert "on_change=on_datasheet_upload_change" in datasheet
    assert "data:application/pdf;base64," in datasheet
    assert "Change document" in datasheet
    assert "Open PDF ↗" in datasheet
    assert "cv-dq-open-pdf-wrap" in datasheet
    assert 'st.columns([3.2, 1]' in datasheet
    assert 'st.columns([1.35, 1.45, 4]' in datasheet
    assert "render_datasheet_page_png(payload, source_page)" in datasheet
    assert "_render_ask_next_chips(" in datasheet
    assert "Earlier questions" in datasheet
    assert "max-width:1440px" in qna_styles
    assert "cv-dq-open-pdf-wrap{display:flex;width:100%;justify-content:flex-end}" in source
    assert "st-key-approved_datasheet_next_page button *{color:#2463e8!important" in qna_styles
    assert "max-width:136px!important" in qna_styles
    assert 'st.columns([3.1, 1]' in home_renderer
    assert '"approved_home_row_last" if index == min(len(rows), 3) - 1' in home_renderer
    assert ".st-key-approved_home_row_last{border-radius:0 0 15px 15px" in source


def test_completed_empty_supplier_search_shows_guidance_without_zero_count_table():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    renderer = source.split("def render_replacement_search", 1)[1].split(
        "def render_compare_live", 1
    )[0]

    assert '"Retry supplier search"' in renderer
    assert '"No replacement-ready candidates"' in renderer
    assert "replacement_search_empty_state" in renderer
    search_source = (
        Path(__file__).resolve().parents[1] / "src" / "alternative_finder_search.py"
    ).read_text(encoding="utf-8")
    assert '"Supplier search incomplete"' in search_source
    assert '"No replacement candidates confirmed"' in search_source
    assert 'if supplier_candidate_count:' in renderer
    assert 'st.session_state["approved_replacement_compare_candidates"] = []' in renderer
    assert '"Replacement options ({len(candidates)})"' not in renderer


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
    assert '"return_decision_id"' in navigation_source


def test_decision_packet_replacement_handoff_returns_to_the_same_review_packet():
    root = Path(__file__).resolve().parents[1]
    page_source = (root / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
    renderer = page_source.split("def render_replacement_search", 1)[1].split(
        "def render_compare_live", 1
    )[0]

    assert 'return_page == "Engineering Decisions" and return_decision_id' in renderer
    assert '"← Back to decision review"' in renderer
    assert 'navigate_to("Engineering Decisions", decision_id=return_decision_id)' in renderer
    assert "_navigate_back_to_bom_review(source_context)" in renderer


def test_compare_page_has_context_preserving_return_to_finder():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    compare = source.split("def render_compare_live", 1)[1].split(
        "def render_datasheet_live", 1
    )[0]

    assert '"← Back to replacement search"' in compare
    assert 'navigate_to("Alternative Finder", **return_params)' in compare
    assert '"return_decision_id"' in compare


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
    search_call = renderer.index("run_alternative_finder_search(st.session_state, query)")
    heading = renderer.index("<h1>Find a replacement</h1>")
    input_mount = renderer.index("key=input_widget_key")
    reveal = renderer.index('reveal_authenticated_page_body("Alternative Finder")')
    assert heading < input_mount < reveal < search_call


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


def test_approval_citations_require_a_real_document_identifier_and_pdf_page():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "ui" / "approved_pages.py"
    ).read_text(encoding="utf-8")
    approvals = source.split("def _render_bom_replacement_approvals", 1)[1].split(
        "def render_replacement_search", 1
    )[0]
    datasheet_review = source.split("def _render_datasheet_evidence_review", 1)[1].split(
        "def _approval_evidence_for_comparison", 1
    )[0]

    assert "has_document_page_citation(source_reference)" in datasheet_review
    assert "has_document_page_citation(candidate_reference)" in datasheet_review
    assert "has_document_page_citation(reviewer_attestation.get(\"source_reference\"))" in approvals
    assert "has_document_page_citation(reviewer_attestation.get(\"candidate_reference\"))" in approvals
    assert "“NA” does not count" in approvals
    assert "PDF page number" in approvals


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
