"""Priority 1: the BOM intake review UI keeps its safety contracts.

These are source-level contracts (like the repo's other web tests). The behaviour
behind them is covered end to end in tests/test_bom_intake.py.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web" / "src"
PAGE = (WEB / "app" / "bom-analyzer" / "page.tsx").read_text(encoding="utf-8")
REVIEW = (WEB / "components" / "BomIntakeReview.tsx").read_text(encoding="utf-8")
API = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
DRAFT = (WEB / "lib" / "bomDraft.ts").read_text(encoding="utf-8")
JOBS = (WEB / "lib" / "bomAnalyzeJobs.ts").read_text(encoding="utf-8")
CSS = (WEB / "app" / "globals.css").read_text(encoding="utf-8")


def test_upload_accepts_csv_and_xlsx_only():
    assert 'accept=".csv,.xlsx"' in PAGE
    assert "CSV or XLSX" in PAGE


def test_review_shows_raw_beside_normalized_values():
    assert "As uploaded" in REVIEW
    assert "Used" in REVIEW
    assert "row.raw[" in REVIEW and "row.normalized[" in REVIEW


def test_row_status_and_severity_are_text_not_color_only():
    for label in ("Fix needed", "Review", "Left out"):
        assert label in REVIEW
    for label in ("Error", "Warning", "Note"):
        assert f'"{label}"' in REVIEW
    # Color is reinforcement only: the status label is always rendered as text.
    assert "ROW_STATUS_LABEL[row.status]" in REVIEW
    assert "SEVERITY_LABEL[issue.severity]" in REVIEW


def test_user_can_change_column_roles_with_a_labelled_control():
    assert "aria-label={`Role for column ${column.source}`}" in REVIEW
    assert "Don’t use" in REVIEW
    # One column per role: choosing a role moves it instead of leaving duplicates.
    assert "One column per role" in REVIEW


def test_user_can_correct_row_values_and_original_stays_visible():
    assert "setCorrection(" in REVIEW
    assert "corrected value" in REVIEW
    assert "your original stays on record" in REVIEW


def test_required_recommended_and_supplier_specific_wording():
    assert "supplier-specific sourcing" in REVIEW
    assert "Supplier is optional by default" in REVIEW
    assert "REQUIREMENT_LABEL" in REVIEW
    assert "needed for supplier-specific sourcing" in REVIEW


def test_excluding_rows_is_an_explicit_user_choice_that_is_disclosed():
    assert "Leave out rows that still have errors" in REVIEW
    assert "listed, with the reason, in the saved report" in REVIEW
    assert "excludeInvalidRows: false" in API  # default is never exclude


def test_generic_header_needs_explicit_confirmation():
    assert "mapping_needs_confirmation" in REVIEW
    assert "Confirm column roles" in REVIEW


def test_analyze_is_gated_until_preview_matches_the_users_choices():
    assert "const intakeDirty = intakeSignature(intake) !== intakeSignature(appliedIntake)" in PAGE
    # onAnalyze, the primary button state, and canAnalyze all require a clean match.
    assert re.search(r"const matches =\s*!intakeDirty", PAGE)
    assert re.search(r"const canAnalyze = Boolean\(\s*file &&\s*!intakeDirty", PAGE)
    assert "Re-check with my changes" in PAGE and "Re-check with my changes" in REVIEW
    # The analysis uses the options the visible preview was built with.
    assert "intake: appliedIntake" in PAGE


def test_new_file_never_inherits_previous_mapping_or_corrections():
    chosen = PAGE[PAGE.index("async function onFileChosen"): PAGE.index("function onRecheck")]
    assert "setIntake(freshIntakeOptions())" in chosen
    assert "setAppliedIntake(freshIntakeOptions())" in chosen


def test_options_reach_validate_and_analyze_requests():
    assert "export async function validateBom(" in API
    assert "options?: BomIntakeOptions" in API
    for field in ("column_mapping", "row_corrections", "supplier_specific", "default_supplier", "exclude_invalid_rows"):
        assert f'"{field}"' in API
    assert "appendIntakeOptions(body, meta?.intake)" in API
    assert "intake?: BomIntakeOptions" in JOBS
    assert "intake?: BomIntakeOptions" in DRAFT


def test_only_explicit_choices_are_sent():
    # No mapping is sent unless the user made one; corrections only when present.
    assert "if (options.columnMapping)" in API
    assert "Object.keys(options.rowCorrections).length" in API
    assert "columnMapping: null" in API


def test_draft_storage_stays_small_and_restores_the_review():
    assert "rows: []" in PAGE  # row detail is rebuilt from the file, not stored
    assert "intake: appliedIntake" in PAGE
    assert "Rebuild the row-by-row review" in PAGE
    assert "Draft metadata is best-effort" in DRAFT


def test_review_tolerates_drafts_saved_before_intake_review_existed():
    assert "validation.columns?.length" in PAGE
    assert "validation.columns || []" in REVIEW
    assert "validation.rows || []" in REVIEW


def test_no_supplier_claims_in_the_intake_review():
    text = REVIEW.casefold()
    for claim in ("in stock", "lead time", "price", "availability", "verified supplier", "certified"):
        assert claim not in text
    # The distributor guess is labelled as coming from column names only.
    assert "from column names only" in REVIEW  # labelled as a guess


def test_styles_exist_for_the_review_and_stack_on_mobile():
    for selector in (".cv-intake-pair", ".cv-intake-row--error", ".cv-intake-apply", ".cv-intake-table"):
        assert selector in CSS
    assert "@media (max-width: 760px)" in CSS[CSS.index(".cv-intake {"):]
