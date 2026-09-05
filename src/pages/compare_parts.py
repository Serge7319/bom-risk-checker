"""Authenticated Compare Parts page — neutral engineering comparison workspace."""
from __future__ import annotations

import html
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from src.datasheet_comparison import user_may_view_comparison_diagnostics
from src.parts_compare import (
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
    run_compare_parts,
)
from src.ui.cadivor_design_system import (
    cadivor_button_wrap,
    cadivor_button_wrap_end,
    cadivor_comparison_matrix_dataframe,
    cadivor_section_header,
)


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _inject_compare_parts_styles() -> None:
    if st.session_state.get("_cadivor_compare_parts_styles"):
        return
    st.session_state["_cadivor_compare_parts_styles"] = True
    st.markdown(
        """
        <style id="cadivor-compare-parts-css">
        .cp-hero-note{margin:0 0 14px;padding:10px 14px;border:1px solid #DCE5F0;border-radius:12px;background:#F8FBFF;color:#334155;font-size:13px;line-height:1.45}
        .cp-compare-card{margin:0 0 18px;padding:18px 18px 14px;border:1px solid #E2E8F0;border-radius:16px;background:#FFFFFF;box-shadow:0 10px 24px rgba(15,23,42,.04)}
        .cp-finding{margin:8px 0 16px;padding:16px 18px;border:1px solid #E2E8F0;border-radius:16px;background:#FFFFFF}
        .cp-finding__label{font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#64748B}
        .cp-finding__title{margin-top:4px;font-size:20px;font-weight:900;color:#0F172A}
        .cp-finding__title.is-compatible{color:#166534}
        .cp-finding__title.is-material{color:#B45309}
        .cp-finding__title.is-needs{color:#1D4ED8}
        .cp-finding__body{margin-top:8px;color:#475569;font-size:13px;line-height:1.45}
        .cp-part-card{padding:14px 16px;border:1px solid #E2E8F0;border-radius:14px;background:#FFFFFF;min-height:148px}
        .cp-part-card__eyebrow{font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#64748B}
        .cp-part-card__mpn{margin-top:4px;font-size:18px;font-weight:900;color:#0F172A}
        .cp-part-card__meta{margin-top:8px;color:#475569;font-size:13px;line-height:1.45}
        .cp-badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:750}
        .cp-badge--ok{background:#DCFCE7;color:#166534}
        .cp-badge--diff{background:#FFEDD5;color:#9A3412}
        .cp-badge--need{background:#DBEAFE;color:#1E40AF}
        section[data-testid="stMain"] .cp-compare-card .stFormSubmitButton>button{
          min-width:160px!important;width:auto!important;max-width:220px!important
        }
        @media(max-width:760px){
          .cp-part-card{min-height:0}
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


def _render_part_card(title: str, card: Mapping[str, Any]) -> None:
    datasheet = str(card.get("datasheet_url") or "")
    supplier = str(card.get("supplier_url") or "")
    st.markdown(
        f"""
        <div class="cp-part-card">
          <div class="cp-part-card__eyebrow">{_esc(title)}</div>
          <div class="cp-part-card__mpn">{_esc(card.get("mpn") or "Not found")}</div>
          <div class="cp-part-card__meta">
            {_esc(card.get("manufacturer") or "—")}<br/>
            Family: {_esc(card.get("family_display_name") or "—")}<br/>
            Package: {_esc(card.get("package") or "—")} · Lifecycle: {_esc(card.get("lifecycle_status") or "—")}
          </div>
        </div>
        """,
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


def render_compare_parts_page(*, is_admin: bool = False, role: str | None = None) -> None:
    """Render the Compare Parts engineering workspace."""
    _inject_compare_parts_styles()
    st.markdown('<div class="cv64-page-shell">', unsafe_allow_html=True)
    cadivor_section_header(
        "Compare any two parts on shared engineering evidence",
        eyebrow="Compare Parts",
        description=(
            "Enter two manufacturer part numbers for a neutral, family-aware attribute "
            "comparison. This is not an Alternative Finder recommendation."
        ),
        icon="git-compare",
    )
    st.markdown(
        '<div class="cp-hero-note">'
        "Cadivor compares only available evidence. Missing attributes stay missing and "
        "are never inferred as a match. Validate package, pinout, and electrical limits "
        "before production use."
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="cp-compare-card">', unsafe_allow_html=True)
    with st.form("compare_parts_form", clear_on_submit=False, border=False):
        cols = st.columns(2)
        with cols[0]:
            part_a_form = st.text_input(
                "Part A",
                key=COMPARE_PARTS_PART_A_WIDGET_KEY,
                placeholder="Manufacturer part number",
            )
        with cols[1]:
            part_b_form = st.text_input(
                "Part B",
                key=COMPARE_PARTS_PART_B_WIDGET_KEY,
                placeholder="Manufacturer part number",
            )
        button_cols = st.columns([1, 2, 1])
        with button_cols[0]:
            cadivor_button_wrap("primary")
            submitted = st.form_submit_button(
                "Compare Parts",
                type="primary",
                use_container_width=False,
            )
            cadivor_button_wrap_end()
    st.markdown("</div>", unsafe_allow_html=True)

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
                with st.status("Retrieving both parts and comparing attributes…", expanded=True):
                    st.write("Looking up Part A and Part B from configured suppliers…")
                    result = run_compare_parts(part_a, part_b)
                    st.write("Building the family-aware comparison matrix…")
                st.session_state[COMPARE_PARTS_RESULT_KEY] = result
            except Exception:
                st.session_state[COMPARE_PARTS_RESULT_KEY] = {
                    "status": STATUS_FAILED,
                    "part_a": part_a,
                    "part_b": part_b,
                    "error": "Cadivor could not complete this comparison right now. Please try again.",
                }

    result = st.session_state.get(COMPARE_PARTS_RESULT_KEY)
    if not isinstance(result, dict):
        st.info("Enter Part A and Part B, then press Compare Parts or Enter.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    status = str(result.get("status") or "")
    if status == STATUS_RUNNING:
        st.info("Comparison in progress…")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    if status == STATUS_FAILED:
        st.error(str(result.get("error") or "Comparison could not be completed."))
    if status not in {STATUS_COMPLETED, STATUS_FAILED}:
        st.markdown("</div>", unsafe_allow_html=True)
        return

    comparison = result.get("comparison")
    if not isinstance(comparison, dict):
        st.markdown("</div>", unsafe_allow_html=True)
        return

    finding = str(comparison.get("finding") or FINDING_NEEDS_DATA)
    counts = dict(comparison.get("counts") or {})
    needs = int(counts.get("needs_data") or 0)
    validation_note = (
        f"{needs} attribute{'s' if needs != 1 else ''} still need engineering validation."
        if needs
        else "Required available attributes were compared without material differences."
    )
    st.markdown(
        f"""
        <div class="cp-finding">
          <div class="cp-finding__label">Overall assessment</div>
          <div class="cp-finding__title {_finding_class(finding)}">{_esc(finding)}</div>
          <div class="cp-finding__body">
            {_esc(comparison.get("engineering_evidence_summary") or "")}<br/>
            <strong>What needs validation:</strong> {_esc(validation_note)}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    identity_cols = st.columns(2)
    with identity_cols[0]:
        _render_part_card("Part A", comparison.get("part_a") or {})
    with identity_cols[1]:
        _render_part_card("Part B", comparison.get("part_b") or {})

    st.markdown(
        f"**Family profile:** {_esc(comparison.get('family_display_name') or comparison.get('family') or 'General')}"
    )
    st.caption(
        "Engineering compatibility is separate from any supplier substitute relationship. "
        "Cadivor never labels either part as a Direct substitute here."
    )

    rows = list(comparison.get("rows") or [])
    matrix = _decorate_assessment_column(
        pd.DataFrame(rows, columns=list(USER_FACING_COMPARE_COLUMNS))
    )
    st.subheader("Attribute comparison")
    if matrix is None or matrix.empty:
        st.info("No comparable attributes were available for these parts.")
    else:
        cadivor_comparison_matrix_dataframe(matrix, key="compare_parts_matrix")

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
                st.dataframe(pd.DataFrame(diagnostic_rows), use_container_width=True, hide_index=True)
            else:
                st.caption("No diagnostic rows available.")

    st.markdown("</div>", unsafe_allow_html=True)
