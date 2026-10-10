from src.bom_upload_flow import consume_approved_bom_submission


def test_approved_upload_hands_off_file_names_and_starts_analysis():
    upload = object()
    state = {
        "cadivor_bom_analysis_ready": True,
        "cadivor_pending_upload": upload,
        "cadivor_pending_project": "New project",
        "cadivor_pending_bom_name": "Prototype BOM",
        "bom8_project_name": "Old project",
        "bom8_bom_name": "Old BOM",
        "bom8_sample_mode": True,
    }

    submitted, consumed_upload, project, name = consume_approved_bom_submission(state)

    assert submitted is True
    assert consumed_upload is upload
    assert (project, name) == ("New project", "Prototype BOM")
    assert state["bom8_project_name"] == "New project"
    assert state["bom8_bom_name"] == "Prototype BOM"
    assert state["bom8_analysis_pending"] is True
    assert "bom8_sample_mode" not in state
    assert "cadivor_pending_upload" not in state
    assert "cadivor_bom_analysis_ready" not in state


def test_approved_upload_replaces_stale_names_even_when_fields_are_blank():
    state = {
        "cadivor_bom_analysis_ready": True,
        "cadivor_pending_upload": object(),
        "cadivor_pending_project": "",
        "cadivor_pending_bom_name": "",
        "bom8_project_name": "Old project",
        "bom8_bom_name": "Old BOM",
    }

    consume_approved_bom_submission(state)

    assert state["bom8_project_name"] == ""
    assert state["bom8_bom_name"] == ""


def test_missing_upload_does_not_queue_analysis():
    state = {
        "cadivor_bom_analysis_ready": True,
        "cadivor_pending_upload": None,
        "cadivor_pending_project": "New project",
        "cadivor_pending_bom_name": "Prototype BOM",
    }

    submitted, upload, _, _ = consume_approved_bom_submission(state)

    assert submitted is True
    assert upload is None
    assert "bom8_analysis_pending" not in state
