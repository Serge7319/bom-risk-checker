"""The signed-out BOM stress test, embedded by the real Cadivor homepage."""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from src.public_bom_stress_test import (
    StressTestError,
    capture_lead,
    enabled,
    run_audit,
    send_report_verification,
)


def render_public_bom_stress_test() -> None:
    """Render only the five public rows; the full result remains on the server."""
    st.markdown("""<style>
      header[data-testid="stHeader"], [data-testid="stToolbar"] {display:none!important}
      .block-container {padding:18px 22px 32px!important;max-width:1080px!important}
      .stApp {background:#f4f8ff!important;color:#10284b}
      .st-key-cv_public_stress_test {padding:20px 24px;border:1px solid #cfe0f5;
        border-radius:20px;background:#fff;box-shadow:0 12px 32px rgba(10,28,59,.06)}
      .st-key-cv_public_stress_test [data-testid="stFileUploaderDropzone"] {
        border:2px dashed #86acee;border-radius:14px;background:#f7faff;padding:18px}
      .cv-stress-locked {padding:18px;border:1px solid #b9cff1;border-radius:14px;
        background:#edf4ff;color:#163260;font-size:14px;line-height:1.6}
      .cv-stress-locked strong {display:block;font-size:17px;color:#0b2144}
      @media(max-width:700px){.block-container {padding:10px!important}
        .st-key-cv_public_stress_test {padding:16px}}
    </style>""", unsafe_allow_html=True)
    with st.container(key="cv_public_stress_test"):
        if not enabled():
            st.info("The free BOM stress test is being prepared. Please check back soon.")
            return
        report = st.session_state.get("cv_stress_report")
        if report:
            st.markdown("## Preliminary BOM audit")
            st.caption("First five checked components · verify your work email for the complete audit.")
            if st.button("Audit another BOM", key="cv_stress_new_audit"):
                for key in ("cv_stress_report", "cv_stress_error", "cv_stress_last_digest",
                            "cv_stress_upload", "cv_stress_email_pending"):
                    st.session_state.pop(key, None)
                st.rerun()
        else:
            st.markdown("## Free BOM stress test")
            st.write("Drop your BOM (.csv / .xlsx) here for an instant risk and obsolescence audit. No account is needed to see the first five components.")
            st.caption("Up to 30 rows and 1 MB. Supplier lookups may take several minutes. Do not upload regulated or export-controlled designs.")
            uploaded = st.file_uploader(
                "Drop your BOM here", type=["csv", "xlsx"], max_upload_size=1,
                key="cv_stress_upload",
            )
            if uploaded is not None:
                payload = uploaded.getvalue()
                digest = hashlib.sha256(payload + uploaded.name.encode()).hexdigest()
                if st.session_state.get("cv_stress_last_digest") != digest:
                    st.session_state["cv_stress_last_digest"] = digest
                    st.session_state.pop("cv_stress_error", None)
                    try:
                        headers = st.context.headers
                        signed = next((str(value) for name, value in (headers or {}).items()
                                       if name.lower() == "x-cadivor-visitor"), "")
                        with st.spinner("Checking lifecycle and supplier evidence…"):
                            st.session_state["cv_stress_report"] = run_audit(uploaded.name, payload, signed)
                        st.rerun()
                    except StressTestError as exc:
                        st.session_state["cv_stress_error"] = str(exc)
        if st.session_state.get("cv_stress_error"):
            st.error(st.session_state["cv_stress_error"])
            if st.button("Retry audit", key="cv_stress_retry"):
                st.session_state.pop("cv_stress_last_digest", None)
                st.session_state.pop("cv_stress_error", None)
                st.rerun()
        report = st.session_state.get("cv_stress_report")
        if not report:
            return
        st.success(f"Checked {report['row_count']} components. Here are the first {len(report['preview'])} results.")
        preview = pd.DataFrame([{
            "MPN": row["mpn"], "Qty": row["quantity"],
            "Lifecycle": row["lifecycle"], "Stock": row["stock"],
            "Lead time (weeks)": row["lead_time_weeks"],
            "Source": row.get("sources"), "Risk": row["risk"],
        } for row in report["preview"]])
        st.dataframe(preview, hide_index=True, use_container_width=True)
        remaining = int(report["remaining_count"])
        if remaining:
            high = int(report["remaining_high_risk"])
            unverified = int(report["remaining_unverified"])
            st.markdown(
                '<div class="cv-stress-locked"><strong>'
                f'{remaining} more components are locked · {high} verified high-risk dependencies'
                '</strong>Verify your work email to see the full report, including lifecycle, stock, lead time, and evidence.'
                + (f' {unverified} components still need supplier verification.' if unverified else '')
                + '</div>', unsafe_allow_html=True,
            )
        else:
            st.info("All components fit in the free preview. Verify a work email to save and download this audit.")
        pending = st.session_state.get("cv_stress_email_pending")
        if pending:
            st.success(f"Check {pending} for your secure sign-in link. After verification, continue to Reports for the complete audit.")
            return
        with st.form("cv_stress_work_email_form", clear_on_submit=False):
            email = st.text_input("Work email", placeholder="you@company.com", autocomplete="email")
            accepted = st.checkbox("I agree to the Terms of Service and Privacy Policy.")
            submit = st.form_submit_button("Email my full report", type="primary")
            st.caption("We'll send a secure sign-in link. Verify your work email to unlock the full audit in Reports.")
        st.markdown(
            "[Terms of Service](https://www.cadivor.com/#/terms) · "
            "[Privacy Policy](https://www.cadivor.com/#/privacy)"
        )
        if submit:
            if not accepted:
                st.error("Accept the Terms of Service and Privacy Policy to continue.")
            else:
                try:
                    address = capture_lead(report["id"], email)
                    send_report_verification(address)
                except StressTestError as exc:
                    st.error(str(exc))
                else:
                    st.session_state["cv_stress_email_pending"] = address
                    st.rerun()
