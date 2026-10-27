from __future__ import annotations

import csv
import io
from io import StringIO
from pathlib import Path

from src.saved_bom_editor import normalize_saved_bom_rows, saved_bom_csv_bytes


def test_saved_bom_editor_validates_and_exports_updated_quantities():
    rows, error = normalize_saved_bom_rows(
        [
            {"MPN": " GRM188R71C104KA01D ", "Quantity": 12},
            {"MPN": "RC0603FR-0710KL", "Quantity": 8.0},
        ]
    )
    assert error == ""
    assert rows == [
        {"mpn": "GRM188R71C104KA01D", "quantity": 12},
        {"mpn": "RC0603FR-0710KL", "quantity": 8},
    ]
    parsed = list(csv.DictReader(StringIO(saved_bom_csv_bytes(rows).decode("utf-8"))))
    assert parsed == [
        {"mpn": "GRM188R71C104KA01D", "quantity": "12"},
        {"mpn": "RC0603FR-0710KL", "quantity": "8"},
    ]


def test_saved_bom_editor_rejects_empty_and_invalid_rows():
    assert normalize_saved_bom_rows([])[1] == "Add at least one component before rerunning this analysis."
    assert normalize_saved_bom_rows([{"MPN": "", "Quantity": 1}])[1]
    assert normalize_saved_bom_rows([{"MPN": "U1", "Quantity": 0}])[1]
    assert normalize_saved_bom_rows([{"MPN": "U1", "Quantity": 1.5}])[1]


def test_updated_rows_use_the_existing_bom_upload_pipeline():
    from src.bom_upload_flow import consume_approved_bom_submission, resume_approved_bom_submission

    rows, error = normalize_saved_bom_rows([{"MPN": "U1", "Quantity": 4}])
    assert not error
    upload = io.BytesIO(saved_bom_csv_bytes(rows))
    upload.name = "controller_updated.csv"
    state = {
        "cadivor_bom_analysis_ready": True,
        "cadivor_pending_upload": upload,
        "cadivor_pending_project": "Controller",
        "cadivor_pending_bom_name": "Main Board",
    }
    submitted, pending, project, bom_name = consume_approved_bom_submission(state)
    assert submitted and project == "Controller" and bom_name == "Main Board"
    assert pending.name == "controller_updated.csv"
    pending.seek(0)
    assert pending.read().decode("utf-8") == "mpn,quantity\nU1,4\n"
    resumed, resumed_project, resumed_bom = resume_approved_bom_submission(state)
    assert resumed is pending
    assert (resumed_project, resumed_bom) == ("Controller", "Main Board")


def test_saved_bom_action_routes_are_separate_and_editor_reruns_updated_rows():
    root = Path(__file__).resolve().parents[1]
    pages = (root / "src/ui/approved_pages.py").read_text(encoding="utf-8")
    runtime = (root / "src/authenticated_runtime.py").read_text(encoding="utf-8")
    action_menu = pages.split("def _render_saved_bom_actions", 1)[1].split("def _delete_saved_bom", 1)[0]
    assert 'saved_bom_action="open"' in action_menu
    assert '"BOM Risk"' in action_menu
    assert '"Detailed Risk Report"' in action_menu
    assert 'st.data_editor(' in pages
    assert '"Rerun analysis with updates"' in pages
    assert 'consume_approved_bom_submission(st.session_state)' in runtime
    editor = pages.split("def _render_saved_bom_open_page", 1)[1].split("def _render_saved_bom_delete_page", 1)[0]
    assert '"cadivor_saved_bom_rerun_pending"' in editor
    assert '"cadivor_bom_upload_open"] = False' in editor
    assert 'navigate_to("BOM Analyzer", arm_opening=False)' in editor
    assert 'navigate_to("BOM Analyzer", new_analysis="1", arm_opening=False)' not in editor
    route = runtime.split('if app_mode in {"BOM Analyzer", "High Risk Review"}:', 1)[1]
    consume_handoff = route.index('st.session_state.pop("cadivor_saved_bom_rerun_pending", False)')
    catalog_render = route.index("render_bom_catalog(")
    assert consume_handoff < catalog_render
    assert '"BOM Settings",\n                        saved_bom_id=str(analysis_id)' in runtime
