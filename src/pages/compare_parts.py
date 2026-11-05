"""Authenticated Compare Parts page — neutral engineering comparison workspace."""
from __future__ import annotations

import html
import time
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from src.datasheet_comparison import user_may_view_comparison_diagnostics
from src.parts_compare import (
    COMPARE_PARTS_FUTURE_KEY,
    COMPARE_PARTS_PART_A_WIDGET_KEY,
    COMPARE_PARTS_PART_B_WIDGET_KEY,
    COMPARE_PARTS_RESULT_KEY,
    FINDING_COMPATIBLE,
    FINDING_MATERIAL,
    FINDING_NEEDS_DATA,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    USER_FACING_COMPARE_COLUMNS,
    claim_compare_parts_submit,
    generate_parts_comparison_pdf,
    resolve_compare_parts_submitted_mpn,
    submit_compare_parts,
)
from src.ui.cadivor_design_system import (
    MetricCard,
    cadivor_button_wrap,
    cadivor_button_wrap_end,
    cadivor_comparison_matrix_dataframe,
    cadivor_empty_state,
    cadivor_engineering_dataframe,
    cadivor_meta_row,
    cadivor_panel,
    cadivor_panel_end,
    cadivor_section_header,
    inject_cadivor_design_system,
    render_kpi_row_safe,
    render_part_image,
    render_subsection_header,
)

COMPARE_PARTS_DATASHEET_A_KEY = "compare_parts_datasheet_a"
COMPARE_PARTS_DATASHEET_B_KEY = "compare_parts_datasheet_b"
COMPARE_PARTS_STARTED_AT_KEY = "compare_parts_started_at"


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _inject_compare_parts_styles() -> None:
    inject_cadivor_design_system()
    if st.session_state.get("_cadivor_compare_parts_styles_v2"):
        return
    st.session_state["_cadivor_compare_parts_styles_v2"] = True
    st.markdown(
        """
        <style id="cadivor-compare-parts-css-v2" data-cadivor-layout-style="true">
        .cp-workspace{max-width:min(1080px,var(--cv-canvas,1420px));margin:0 auto 28px;padding:0 4px}
        .cp-reading{max-width:var(--cv-reading-max,62ch);color:var(--cv64-text-secondary,#475569);font-size:13px;line-height:1.5;margin:0 0 16px}
        .cp-finding-title{margin:6px 0 8px;font-size:22px;font-weight:900;letter-spacing:-.02em;color:var(--cv64-text,#0F172A)}
        .cp-finding-title.is-compatible{color:var(--cv64-success,#166534)}
        .cp-finding-title.is-material{color:var(--cv64-warning,#B45309)}
        .cp-finding-title.is-needs{color:var(--cv64-info,#1D4ED8)}
        .cp-finding-body{color:var(--cv64-text-secondary,#475569);font-size:13px;line-height:1.5;margin:0 0 12px}
        .cp-part-mpn{margin:4px 0 8px;font-size:18px;font-weight:900;letter-spacing:-.02em;color:var(--cv64-text,#0F172A)}
        .cp-part-meta{color:var(--cv64-text-secondary,#475569);font-size:13px;line-height:1.5;margin:0 0 10px}
        .cp-matrix-note{margin:4px 0 10px;color:var(--cv64-text-muted,#64748B);font-size:12px;line-height:1.45}
        .cp-legend{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 12px}
        .cp-legend span{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;font-size:11px;font-weight:750;border:1px solid var(--cv64-border,#E2E8F0);background:#fff;color:var(--cv64-text-secondary,#475569)}
        .cp-legend .ok{border-color:#BBF7D0;background:#F0FDF4;color:#166534}
        .cp-legend .warn{border-color:#FDE68A;background:#FFFBEB;color:#B45309}
        .cp-legend .need{border-color:#BFDBFE;background:#EFF6FF;color:#1D4ED8}
        .cp-assessment-card{border:1px solid var(--cv64-border,#E2E8F0);border-radius:16px;background:linear-gradient(180deg,#FFFFFF 0%,#F8FAFC 100%);padding:18px 18px 14px;box-shadow:0 10px 28px rgba(15,23,42,.04);margin-bottom:14px}
        .cp-review-warnings{margin:10px 0 0;padding:10px 12px;border:1px solid #FDE68A;border-radius:12px;background:#FFFBEB;color:#92400E;font-size:12px;line-height:1.45}
        .cp-review-warnings ul{margin:6px 0 0;padding-left:18px}
        .cp-review-warnings li{margin:0 0 4px}
        .cp-evidence-note{margin:10px 0 0;padding:10px 12px;border:1px solid #BFDBFE;border-radius:12px;background:#EFF6FF;color:#1E3A8A;font-size:12px;line-height:1.45}
        .cp-fixture-note{margin:10px 0 0;padding:10px 12px;border:1px solid #E2E8F0;border-radius:12px;background:#F8FAFC;color:#475569;font-size:12px;line-height:1.45}
        section[data-testid="stMain"] .cp-workspace .stFormSubmitButton>button{
          min-width:160px!important;width:auto!important;max-width:220px!important
        }
        section[data-testid="stMain"] .cp-workspace [data-testid="stDataFrame"]{
          border:1px solid var(--cv64-border,#E2E8F0);border-radius:12px;overflow:hidden
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _finding_class(finding: str) -> str:
    if finding == FINDING_COMPATIBLE:
        return "is-compatible"
    if finding == FINDING_MATERIAL:
        return "is-material"
    return "is-needs"


def _finding_tone(finding: str) -> str:
    if finding == FINDING_COMPATIBLE:
        return "success"
    if finding == FINDING_MATERIAL:
        return "warning"
    return "info"


def _render_part_card(title: str, card: Mapping[str, Any]) -> None:
    datasheet = str(card.get("datasheet_url") or "")
    supplier = str(card.get("supplier_url") or "")
    component_type = str(card.get("family_display_name") or "—")
    cadivor_panel(title)
    image_col, details_col = st.columns([0.24, 0.76], gap="small", vertical_alignment="center")
    with image_col:
        render_part_image(card.get("image_url"), card.get("mpn"), size=88, part=card)
    with details_col:
        st.markdown(
            f'<div class="cp-part-mpn">{_esc(card.get("mpn") or "Not found")}</div>'
            f'<div class="cp-part-meta">'
            f"{_esc(card.get('manufacturer') or '—')}<br/>"
            f"Component type: {_esc(component_type)}<br/>"
            f"Package: {_esc(card.get('package') or '—')} · "
            f"Lifecycle: {_esc(card.get('lifecycle_status') or '—')}"
            f"</div>",
            unsafe_allow_html=True,
        )
    link_cols = st.columns(2)
    with link_cols[0]:
        if datasheet:
            st.link_button("Datasheet", datasheet, use_container_width=True)
        else:
            st.caption("Datasheet unavailable")
    with link_cols[1]:
        if supplier:
            st.link_button("Supplier page", supplier, use_container_width=True)
        else:
            st.caption("Supplier page unavailable")
    cadivor_panel_end()


def _decorate_assessment_column(matrix: pd.DataFrame) -> pd.DataFrame:
    if matrix is None or matrix.empty or "Assessment" not in matrix.columns:
        return matrix
    decorated = matrix.copy()

    def _badge(value: object) -> str:
        text = str(value or "")
        if text == FINDING_COMPATIBLE:
            return "Compatible"
        if text == FINDING_MATERIAL:
            return "Material difference"
        return "Needs validation"

    decorated["Assessment"] = decorated["Assessment"].map(_badge)
    return decorated


def _uploaded_file_payload(upload: Any) -> dict[str, Any] | None:
    """Copy a Streamlit upload into plain bytes before sending it to a worker."""
    if upload is None:
        return None
    getter = getattr(upload, "getvalue", None)
    if not callable(getter):
        return None
    payload = bytes(getter() or b"")
    if not payload:
        return None
    return {
        "bytes": payload,
        "filename": str(getattr(upload, "name", "") or "datasheet.pdf"),
    }


def _collect_compare_parts_job() -> bool:
    """Transfer a completed worker result to session state."""
    future = st.session_state.get(COMPARE_PARTS_FUTURE_KEY)
    if future is None or not future.done():
        return False
    try:
        result = future.result()
        if not isinstance(result, dict):
            raise TypeError("comparison worker returned an invalid result")
    except Exception:
        running = st.session_state.get(COMPARE_PARTS_RESULT_KEY)
        running = running if isinstance(running, dict) else {}
        result = {
            "status": STATUS_FAILED,
            "part_a": str(running.get("part_a") or ""),
            "part_b": str(running.get("part_b") or ""),
            "error": "Cadivor could not complete this comparison right now. Please try again.",
        }
    st.session_state[COMPARE_PARTS_RESULT_KEY] = result
    st.session_state.pop(COMPARE_PARTS_FUTURE_KEY, None)
    st.session_state.pop(COMPARE_PARTS_STARTED_AT_KEY, None)
    return True


@st.fragment(run_every="1s")
def _render_compare_parts_job_status() -> None:
    """Poll the evidence search while leaving the rest of the workspace rendered."""
    future = st.session_state.get(COMPARE_PARTS_FUTURE_KEY)
    if future is None:
        return
    if _collect_compare_parts_job():
        st.rerun()
        return
    st.info(
        "Comparing the parts using available supplier and datasheet evidence. "
        "The comparison will appear here when the evidence checks finish.",
        icon="🔎",
    )
    try:
        started_at = float(st.session_state.get(COMPARE_PARTS_STARTED_AT_KEY) or 0.0)
    except (TypeError, ValueError):
        started_at = 0.0
    if started_at:
        elapsed = max(0, int(time.monotonic() - started_at))
        if elapsed >= 30:
            st.caption(
                f"Search time: {elapsed}s. Some evidence sources are responding slowly; "
                "the search is still running."
            )


def render_compare_parts_page(*, is_admin: bool = False, role: str | None = None) -> None:
    """Render the Compare Parts engineering workspace."""
    _collect_compare_parts_job()
    compare_future = st.session_state.get(COMPARE_PARTS_FUTURE_KEY)
    compare_running = compare_future is not None and not compare_future.done()
    _inject_compare_parts_styles()
    st.markdown('<div class="cv64-page-shell"><div class="cp-workspace">', unsafe_allow_html=True)
    cadivor_section_header(
        "Compare two parts",
        eyebrow="Compare parts",
        description="Enter two manufacturer part numbers. Missing attributes stay missing.",
        icon="git-compare",
    )
    st.markdown(
        '<p class="cp-reading">'
        "Cadivor compares only available evidence. Missing attributes stay missing and "
        "are never inferred as a match. Validate package, pinout, and electrical limits "
        "before production use."
        "</p>",
        unsafe_allow_html=True,
    )

    cadivor_panel(
        "Compare parts",
        subtitle="Enter manufacturer part numbers for Part A and Part B",
    )
    with st.form("compare_parts_form", clear_on_submit=False, border=False):
        cols = st.columns(2)
        with cols[0]:
            part_a_form = st.text_input(
                "Part A",
                key=COMPARE_PARTS_PART_A_WIDGET_KEY,
                placeholder="Manufacturer part number",
                disabled=compare_running,
            )
        with cols[1]:
            part_b_form = st.text_input(
                "Part B",
                key=COMPARE_PARTS_PART_B_WIDGET_KEY,
                placeholder="Manufacturer part number",
                disabled=compare_running,
            )
        button_cols = st.columns([1, 3])
        with button_cols[0]:
            cadivor_button_wrap("primary")
            submitted = st.form_submit_button(
                "Compare Parts",
                type="primary",
                use_container_width=False,
                disabled=compare_running,
            )
            cadivor_button_wrap_end()
    with st.expander("Optional: upload exact-MPN datasheet", expanded=False):
        st.caption(
            "Use this when a manufacturer or authorized-distributor link is missing "
            "or blocked. Values are shown only after the uploaded PDF names the "
            "entered manufacturer and exact MPN."
        )
        upload_cols = st.columns(2)
        with upload_cols[0]:
            uploaded_a = st.file_uploader(
                "Optional Part A PDF",
                type=["pdf"],
                key=COMPARE_PARTS_DATASHEET_A_KEY,
                help="Exact-MPN datasheet for Part A when live sources are unavailable.",
                disabled=compare_running,
            )
        with upload_cols[1]:
            uploaded_b = st.file_uploader(
                "Optional Part B PDF",
                type=["pdf"],
                key=COMPARE_PARTS_DATASHEET_B_KEY,
                help="Exact-MPN datasheet for Part B when live sources are unavailable.",
                disabled=compare_running,
            )
    cadivor_panel_end()

    if submitted:
        part_a = resolve_compare_parts_submitted_mpn(
            part_a_form,
            st.session_state.get(COMPARE_PARTS_PART_A_WIDGET_KEY),
        )
        part_b = resolve_compare_parts_submitted_mpn(
            part_b_form,
            st.session_state.get(COMPARE_PARTS_PART_B_WIDGET_KEY),
        )
        if not part_a or not part_b:
            st.warning("Enter both Part A and Part B manufacturer part numbers.")
        elif claim_compare_parts_submit(st.session_state, part_a, part_b):
            st.session_state[COMPARE_PARTS_RESULT_KEY] = {
                "status": STATUS_RUNNING,
                "part_a": part_a,
                "part_b": part_b,
            }
            try:
                uploads: dict[str, Any] = {}
                file_a = uploaded_a or st.session_state.get(COMPARE_PARTS_DATASHEET_A_KEY)
                file_b = uploaded_b or st.session_state.get(COMPARE_PARTS_DATASHEET_B_KEY)
                payload_a = _uploaded_file_payload(file_a)
                payload_b = _uploaded_file_payload(file_b)
                if payload_a is not None:
                    uploads["a"] = payload_a
                if payload_b is not None:
                    uploads["b"] = payload_b
                st.session_state[COMPARE_PARTS_RESULT_KEY] = {
                    "status": STATUS_RUNNING,
                    "part_a": part_a,
                    "part_b": part_b,
                }
                try:
                    st.session_state[COMPARE_PARTS_FUTURE_KEY] = submit_compare_parts(
                        part_a,
                        part_b,
                        datasheet_uploads=uploads or None,
                    )
                    st.session_state[COMPARE_PARTS_STARTED_AT_KEY] = time.monotonic()
                except Exception:
                    st.session_state.pop(COMPARE_PARTS_FUTURE_KEY, None)
                    st.session_state[COMPARE_PARTS_RESULT_KEY] = {
                        "status": STATUS_FAILED,
                        "part_a": part_a,
                        "part_b": part_b,
                        "error": "Cadivor could not start this comparison right now. Please try again.",
                    }
            except Exception:
                st.session_state.pop(COMPARE_PARTS_FUTURE_KEY, None)
                st.session_state[COMPARE_PARTS_RESULT_KEY] = {
                    "status": STATUS_FAILED,
                    "part_a": part_a,
                    "part_b": part_b,
                    "error": "Cadivor could not complete this comparison right now. Please try again.",
                }

    result = st.session_state.get(COMPARE_PARTS_RESULT_KEY)
    if not isinstance(result, dict):
        cadivor_empty_state(
            "No comparison yet",
            "Enter Part A and Part B, then press Compare Parts or Enter.",
            icon="git-compare",
        )
        st.markdown("</div></div>", unsafe_allow_html=True)
        return

    status = str(result.get("status") or "")
    if status == STATUS_RUNNING:
        _render_compare_parts_job_status()
        st.markdown("</div></div>", unsafe_allow_html=True)
        return
    if status == STATUS_FAILED:
        st.error(str(result.get("error") or "Comparison could not be completed."))
    if status not in {STATUS_COMPLETED, STATUS_FAILED}:
        st.markdown("</div></div>", unsafe_allow_html=True)
        return

    comparison = result.get("comparison")
    if not isinstance(comparison, dict):
        st.markdown("</div></div>", unsafe_allow_html=True)
        return

    finding = str(comparison.get("finding") or FINDING_NEEDS_DATA)
    counts = dict(comparison.get("counts") or {})
    compatible = int(counts.get("compatible") or 0)
    material = int(counts.get("material_difference") or 0)
    needs = int(counts.get("needs_data") or 0)
    validation_note = (
        f"{needs} attribute{'s' if needs != 1 else ''} still need engineering validation."
        if needs
        else "Required available attributes were compared without material differences."
    )
    component_type = str(
        comparison.get("family_display_name") or comparison.get("family") or "General"
    )

    cadivor_panel("Overall assessment")
    st.markdown('<div class="cp-assessment-card">', unsafe_allow_html=True)
    cadivor_meta_row(
        [
            (finding, _finding_tone(finding)),
            (f"Component type · {component_type}", "neutral"),
        ]
    )
    st.markdown(
        f'<div class="cp-finding-title {_finding_class(finding)}">{_esc(finding)}</div>'
        f'<div class="cp-finding-body">'
        f"{_esc(comparison.get('engineering_evidence_summary') or '')}<br/>"
        f"<strong>What needs validation:</strong> {_esc(validation_note)}"
        f"</div>",
        unsafe_allow_html=True,
    )
    render_kpi_row_safe(
        [
            MetricCard(label="Compatible fields", value=str(compatible), tone="success", icon="check"),
            MetricCard(label="Material differences", value=str(material), tone="warning", icon="alert"),
            MetricCard(label="Needs validation", value=str(needs), tone="info", icon="search"),
        ],
        columns=3,
    )
    review_warnings = [
        str(item).strip()
        for item in (comparison.get("review_warnings") or [])
        if str(item).strip()
    ]
    if review_warnings:
        st.markdown(
            '<div class="cp-review-warnings" role="status">'
            "<strong>Review warnings</strong>"
            "<ul>"
            + "".join(f"<li>{_esc(item)}</li>" for item in review_warnings)
            + "</ul></div>",
            unsafe_allow_html=True,
        )
    asymmetry = str(comparison.get("evidence_asymmetry_note") or "").strip()
    if asymmetry:
        st.markdown(
            f'<div class="cp-evidence-note" role="status"><strong>Evidence coverage</strong><br/>{_esc(asymmetry)}</div>',
            unsafe_allow_html=True,
        )
    access_blockers = (
        comparison.get("access_blockers")
        if isinstance(comparison.get("access_blockers"), dict)
        else {}
    )
    blocker_rows = [
        row
        for row in (access_blockers.get("blockers") or [])
        if isinstance(row, Mapping) and str(row.get("detail") or "").strip()
    ]
    if blocker_rows:
        unique_details: list[str] = []
        seen_details: set[str] = set()
        for row in blocker_rows:
            detail = str(row.get("detail") or "").strip()
            if detail and detail not in seen_details:
                seen_details.add(detail)
                unique_details.append(detail)
        config_names = sorted(
            {
                str(name).strip()
                for row in blocker_rows
                for name in (row.get("required_configuration") or [])
                if str(name).strip()
            }
        )
        config_note = (
            f" Required product configuration (do not paste secrets into chat): "
            f"{', '.join(config_names)}."
            if config_names
            else ""
        )
        st.markdown(
            '<div class="cp-evidence-note" role="status">'
            "<strong>Exact-MPN access blockers</strong>"
            "<ul>"
            + "".join(f"<li>{_esc(item)}</li>" for item in unique_details)
            + "</ul>"
            + (_esc(config_note) if config_note else "")
            + "</div>",
            unsafe_allow_html=True,
        )
    fixture_kpi = comparison.get("fixture_kpi") if isinstance(comparison.get("fixture_kpi"), dict) else {}
    fixture_note = str(fixture_kpi.get("note") or "").strip()
    if fixture_note:
        isolation = (
            comparison.get("fixture_production_isolation")
            if isinstance(comparison.get("fixture_production_isolation"), dict)
            else {}
        )
        isolation_note = str(isolation.get("note") or "").strip()
        st.markdown(
            f'<div class="cp-fixture-note" role="status"><strong>Test fixtures and KPI totals</strong><br/>'
            f"{_esc(fixture_note)} "
            f"Visible rows: {compatible + material + needs}. "
            f"KPI sum Compatible ({compatible}) + Material ({material}) + Needs validation ({needs}) "
            f"= {compatible + material + needs}."
            + (f" {_esc(isolation_note)}" if isolation_note else "")
            + "</div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
    cadivor_panel_end()

    identity_cols = st.columns(2)
    with identity_cols[0]:
        _render_part_card("Part A", comparison.get("part_a") or {})
    with identity_cols[1]:
        _render_part_card("Part B", comparison.get("part_b") or {})

    st.markdown(
        f'<div class="cp-matrix-note">Component type: {_esc(component_type)}. '
        "Engineering compatibility is separate from any supplier substitute relationship. "
        "Cadivor never labels either part as a Direct substitute here. "
        "[Test fixture] values are stubs for this review, not live manufacturer evidence.</div>",
        unsafe_allow_html=True,
    )

    rows = list(comparison.get("rows") or [])
    matrix = _decorate_assessment_column(
        pd.DataFrame(rows, columns=list(USER_FACING_COMPARE_COLUMNS))
    )
    render_subsection_header(
        "Attribute comparison",
        description="Compact Compatible / Material difference / Needs validation matrix.",
    )
    st.markdown(
        '<div class="cp-legend">'
        '<span class="ok">Compatible</span>'
        '<span class="warn">Material difference</span>'
        '<span class="need">Needs validation</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    if matrix is None or matrix.empty:
        cadivor_empty_state(
            "No comparable attributes",
            "No comparable attributes were available for these parts.",
            icon="table",
        )
    else:
        cadivor_panel("Comparison matrix")
        cadivor_comparison_matrix_dataframe(matrix, key="compare_parts_matrix")
        cadivor_panel_end()

    try:
        pdf_bytes = generate_parts_comparison_pdf(comparison)
        cadivor_button_wrap("secondary")
        st.download_button(
            "Download comparison PDF",
            data=pdf_bytes,
            file_name=(
                f"cadivor-compare-"
                f"{(comparison.get('part_a') or {}).get('mpn') or 'part-a'}-vs-"
                f"{(comparison.get('part_b') or {}).get('mpn') or 'part-b'}.pdf"
            ),
            mime="application/pdf",
            use_container_width=False,
            key="compare_parts_pdf_download",
        )
        cadivor_button_wrap_end()
    except Exception:
        st.warning("PDF export is temporarily unavailable. The on-screen comparison remains valid.")

    if user_may_view_comparison_diagnostics(role=role, is_admin=is_admin):
        with st.expander("Developer comparison diagnostics (Admin)", expanded=False):
            diagnostic_rows = list(comparison.get("diagnostic_rows") or [])
            if diagnostic_rows:
                cadivor_engineering_dataframe(
                    pd.DataFrame(diagnostic_rows),
                    key="compare_parts_diagnostics",
                )
            else:
                st.caption("No diagnostic rows available.")

    st.markdown("</div></div>", unsafe_allow_html=True)
