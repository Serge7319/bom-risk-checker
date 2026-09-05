"""Authenticated Compare Parts page — neutral engineering comparison workspace."""
from __future__ import annotations

import html
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from src.datasheet_comparison import user_may_view_comparison_diagnostics
from src.parts_compare import (
    COMPARE_PARTS_RESULT_KEY,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    USER_FACING_COMPARE_COLUMNS,
    claim_compare_parts_submit,
    generate_parts_comparison_pdf,
    run_compare_parts,
)
from src.ui.cadivor_design_system import (
    cadivor_comparison_matrix_dataframe,
    cadivor_section_header,
)


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _render_part_card(title: str, card: Mapping[str, Any]) -> None:
    datasheet = str(card.get("datasheet_url") or "")
    supplier = str(card.get("supplier_url") or "")
    st.markdown(
        f"""
        <div class="cv64-card" style="padding:14px 16px;margin-bottom:8px;">
          <div style="font-size:12px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:#64748B;">{_esc(title)}</div>
          <div style="font-size:18px;font-weight:900;color:#0F172A;margin-top:4px;">{_esc(card.get("mpn") or "Not found")}</div>
          <div style="color:#475569;font-size:13px;margin-top:6px;line-height:1.45;">
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
            st.caption("Datasheet link unavailable")
    with link_cols[1]:
        if supplier:
            st.link_button("Supplier page", supplier, use_container_width=True)
        else:
            st.caption("Supplier link unavailable")


def render_compare_parts_page(*, is_admin: bool = False, role: str | None = None) -> None:
    """Render the Compare Parts engineering workspace."""
    st.markdown('<div class="cv64-page-shell">', unsafe_allow_html=True)
    cadivor_section_header(
        "Compare any two manufacturer part numbers on shared engineering evidence",
        eyebrow="Compare Parts",
        description=(
            "Neutral attribute comparison across Cadivor’s family profiles. "
            "This is not an Alternative Finder recommendation."
        ),
        icon="git-compare",
    )

    with st.form("compare_parts_form", clear_on_submit=False, border=False):
        cols = st.columns(2)
        with cols[0]:
            part_a = st.text_input(
                "Part A",
                key="compare_parts_part_a",
                placeholder="Manufacturer part number",
            )
        with cols[1]:
            part_b = st.text_input(
                "Part B",
                key="compare_parts_part_b",
                placeholder="Manufacturer part number",
            )
        submitted = st.form_submit_button("Compare Parts →", type="primary", use_container_width=True)

    if submitted:
        if claim_compare_parts_submit(st.session_state, part_a, part_b):
            st.session_state[COMPARE_PARTS_RESULT_KEY] = {
                "status": STATUS_RUNNING,
                "part_a": str(part_a or "").strip(),
                "part_b": str(part_b or "").strip(),
            }
            with st.spinner("Retrieving supplier evidence and comparing attributes…"):
                result = run_compare_parts(part_a, part_b)
            st.session_state[COMPARE_PARTS_RESULT_KEY] = result

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
        # Still show partial comparison if present.
    if status not in {STATUS_COMPLETED, STATUS_FAILED}:
        st.markdown("</div>", unsafe_allow_html=True)
        return

    comparison = result.get("comparison")
    if not isinstance(comparison, dict):
        st.markdown("</div>", unsafe_allow_html=True)
        return

    finding = str(comparison.get("finding") or "")
    st.markdown(
        f"""
        <div class="cv64-card" style="padding:16px 18px;margin:12px 0 18px;">
          <div style="font-size:12px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:#64748B;">Finding</div>
          <div style="font-size:20px;font-weight:900;color:#0F172A;margin-top:4px;">{_esc(finding)}</div>
          <div style="color:#475569;font-size:13px;margin-top:8px;">{_esc(comparison.get("engineering_evidence_summary") or "")}</div>
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
    for note in comparison.get("notes") or []:
        st.caption(str(note))

    rows = list(comparison.get("rows") or [])
    matrix = pd.DataFrame(rows, columns=list(USER_FACING_COMPARE_COLUMNS))
    st.subheader("Attribute comparison")
    cadivor_comparison_matrix_dataframe(matrix, key="compare_parts_matrix")

    try:
        pdf_bytes = generate_parts_comparison_pdf(comparison)
        st.download_button(
            "Download comparison PDF",
            data=pdf_bytes,
            file_name=(
                f"cadivor-compare-"
                f"{(comparison.get('part_a') or {}).get('mpn') or 'part-a'}-vs-"
                f"{(comparison.get('part_b') or {}).get('mpn') or 'part-b'}.pdf"
            ),
            mime="application/pdf",
            use_container_width=True,
            key="compare_parts_pdf_download",
        )
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
