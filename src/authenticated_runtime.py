"""Cadivor authenticated application runtime.

Loaded only after the auth bootstrap succeeds. Heavy imports, workspace
initialization, and authenticated page routing live here so the public login
shell can render without importing the full product surface.

Sprint 75.2A: route-specific engines/pages are imported inside their route
branches (or nested helpers) so Dashboard cold-start does not load the full
product graph.
"""
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from src.readability_system import readability_css
from src.living_workspace import (
    compute_dashboard_summary_metrics,
    render_dashboard_monitoring_workspace,
    render_engineering_overview_workspace,
)
from src.pages.dashboard_workspaces import (
    inject_dashboard_workspace_styles,
    load_portfolio_dashboard_context,
    render_dashboard_analytics_workspace,
    render_dashboard_page_heading,
    render_dashboard_workspace_navigation,
    render_portfolio_intelligence_workspace,
)
from src.decision_engine import build_decision_center, STATUSES
from src.decision_dashboard import decision_card_html, packet_header_html
from src.decision_repository import (
    load_decision_state,
    save_decision_workflow,
    add_decision_note,
)
from src.procurement_advisor import build_procurement_advisor
from src.engineering_overview import build_engineering_overview
from src.plans import PLANS, get_plan, validate_bom_against_plan, resolve_effective_plan, format_limit
from src.auth_bootstrap import get_supabase_client, log_startup_phase, qp_value as _qp_value
from src.supabase_read import SupabaseReadTransportError, execute_supabase_read
from src.auth_state import (
    AUTH_AUTHENTICATED,
    AUTH_SIGNED_OUT,
    AUTH_LOGGING_OUT,
    APP_AUTHENTICATED,
    APP_PUBLIC,
    begin_logout,
    finalize_logout_cookie,
)
import time
import html
import re
import json
import math
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

start_time = time.time()
from src.ui.milestone10a import apply_milestone10a_design_system
from src.ui.framework import (
    inject_premium_css,
    inject_v32_ux_css,
    render_topbar,
    render_navigation_loading_overlay,
    page_header,
    metric_card,
    light_plotly_layout,
    empty_state,
    action_card,
    dashboard_command_center,
    dashboard_insight_card,
)
from src.urls import app_checkout_url
from src.secrets import get_secret
from src.ui.navigation import (
    ALTERNATIVE_FINDER_PAGE,
    apply_alternative_finder_prefill,
    consume_alternative_finder_context,
    internal_nav_button,
    navigate_to,
    navigate_to_alternative_finder,
    render_command_nav_triggers,
    reset_alternative_finder_prefill,
)
from src.browser_navigation import consume_browser_navigation_event
from src.ui.unified_shell import render_unified_shell, inject_unified_shell_css
from src.ui.workspace_consistency import inject_workspace_consistency_css
from src.ui.premium_interaction_repair import inject_premium_interaction_css
from src.ui.premium_interactions import render_premium_interactions
from src.components.command_center import render_command_center
from src.core.workspace_search import build_workspace_commands
from src.ui.design_system_v1 import inject_design_system_v1
from src.ui.core_premium_ui import (
    inject_core_premium_ui,
    inject_workspace_geometry_final,
    mark_authenticated_surface_ready,
    stop_authenticated_page,
)
from src.ui.executive_workspace import inject_executive_workspace_css, render_page_context
from src.ui.executive_ux import inject_executive_ux_css, workflow_steps
from src.ui.enterprise_experience import inject_enterprise_experience_css, operation_status
from src.ui.cadivor_components import page_header as ds_page_header, kpi_grid as ds_kpi_grid, section_header as ds_section_header, empty_state as ds_empty_state
from src.ui.cadivor_design_system import (
    MetricCard,
    cadivor_button_wrap,
    cadivor_button_wrap_end,
    cadivor_engineering_dataframe,
    cadivor_metric_row,
    cadivor_panel,
    cadivor_panel_end,
    cadivor_section_header,
    cadivor_table,
    render_decision_card_actions,
    render_kpi_row_safe,
)
from src.components.onboarding import (
    render_analysis_success,
    render_upload_detected,
    render_first_run_dashboard,
    render_activation_strip,
)
from src.components.upgrade_prompt import render_upgrade_prompt
from src.components.first_analysis_brief import render_first_analysis_brief
from src.onboarding_service import (
    ensure_onboarding_progress,
    update_onboarding_progress,
    completion_count,
)
from src.customer_profile_service import (
    ensure_customer_profile,
    update_customer_profile,
    ensure_user_preferences,
    update_user_preferences,
)
from src.event_labels import (
    action_label,
    category_label,
    display_time,
    event_category,
    friendly_summary,
)
from src.collaboration_service import (
    touch_workspace_presence,
    list_workspace_presence,
    list_audit_log,
    mark_all_notifications_read,
)
from src.workspace_service import (
    ensure_personal_workspace,
    list_members,
    list_invites,
    create_invite,
    cancel_invite,
    update_member_role,
    remove_member,
    update_workspace,
    list_activity,
    list_notifications,
    mark_notification_read,
    list_user_workspaces,
    get_workspace_by_id,
    get_active_workspace_preference,
    set_active_workspace_preference,
    create_organization_workspace,
)
try:
    import extra_streamlit_components as stx
except Exception:
    stx = None

log_startup_phase("authenticated_runtime_imports_complete")

cookie_manager = None
supabase = None


def _init_runtime_clients() -> None:
    """Bind Supabase and CookieManager on the main thread after import completes."""
    global cookie_manager, supabase
    if cookie_manager is None:
        from src.auth_cookies import get_auth_cookie_manager

        cookie_manager = get_auth_cookie_manager()
    if supabase is None:
        supabase = get_supabase_client()


def load_user_data():
    user = st.session_state["user"]
    user_id = user.id
    from src.services.authenticated_profile_cache import (
        recent_verified_profile,
        remember_verified_profile,
    )

    try:
        response = execute_supabase_read(
            supabase.table("users")
            .select("*")
            .eq("id", user_id),
            operation="load_user_data",
        )
    except SupabaseReadTransportError:
        cached_profile = recent_verified_profile(st.session_state, user_id)
        if cached_profile:
            return cached_profile
        st.warning(
            "Cadivor could not reach the database right now. "
            "Please wait a moment and use **Rerun** or refresh the page."
        )
        stop_authenticated_page()

    if response.data:
        return remember_verified_profile(st.session_state, response.data[0]) or response.data[0]

    # A profile that was successfully loaded earlier in this authenticated
    # session must not be treated as missing because one later read is briefly
    # empty. Provisioning is only for a genuinely fresh session with no
    # verified profile yet.
    cached_profile = recent_verified_profile(st.session_state, user_id)
    if cached_profile:
        return cached_profile

    from src.services.user_provisioning import UserProvisioningError, ensure_user_profile

    try:
        profile, _created = ensure_user_profile(supabase, user, operation="load_user_data")
        return remember_verified_profile(st.session_state, profile) or profile
    except UserProvisioningError:
        st.error(
            "Cadivor could not initialize your workspace profile. "
            "Please try again in a moment or contact support if this continues."
        )
        stop_authenticated_page()



def _safe_text(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def render_maintenance_mode_surface(message):
    """Render the customer-facing maintenance screen for non-admin users."""
    customer_message = _safe_text(
        message,
        "Cadivor is undergoing scheduled maintenance. Please try again shortly.",
    )
    safe_message = html.escape(customer_message)
    st.markdown(
        f"""
        <style id="cadivor-maintenance-mode">
        html, body, .stApp, [data-testid="stAppViewContainer"] {{
            min-height: 100%;
            background: #071b3d !important;
        }}
        [data-testid="stAppViewContainer"] > .main {{
            min-height: 100vh;
            background:
                radial-gradient(circle at 84% 12%, rgba(51, 109, 232, .28), transparent 28rem),
                radial-gradient(circle at 8% 92%, rgba(20, 184, 166, .12), transparent 25rem),
                #071b3d;
        }}
        [data-testid="stAppViewContainer"] > .main .block-container {{
            max-width: 900px;
            min-height: 100vh;
            padding: 48px 24px;
            display: flex;
            align-items: center;
        }}
        #cadivor-maintenance-screen {{
            width: 100%;
            color: #f8fbff;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }}
        #cadivor-maintenance-screen .maintenance-card {{
            max-width: 680px;
            margin: 0 auto;
            padding: 42px;
            border: 1px solid rgba(166, 194, 244, .24);
            border-radius: 24px;
            background: rgba(10, 33, 74, .78);
            box-shadow: 0 28px 80px rgba(0, 0, 0, .28);
        }}
        #cadivor-maintenance-screen .maintenance-brand {{
            display: inline-flex;
            align-items: center;
            gap: 11px;
            margin-bottom: 42px;
            color: #ffffff;
            font-size: 20px;
            font-weight: 750;
            letter-spacing: -.03em;
        }}
        #cadivor-maintenance-screen .maintenance-mark {{
            display: grid;
            width: 34px;
            height: 34px;
            place-items: center;
            border-radius: 10px;
            background: linear-gradient(135deg, #4c8aff, #2857cb);
            color: #ffffff;
            font-size: 21px;
            font-weight: 800;
        }}
        #cadivor-maintenance-screen .maintenance-eyebrow {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: #a9c5ff;
            font-size: 12px;
            font-weight: 750;
            letter-spacing: .11em;
            text-transform: uppercase;
        }}
        #cadivor-maintenance-screen .maintenance-eyebrow::before {{
            content: "";
            width: 8px;
            height: 8px;
            border-radius: 999px;
            background: #72e1bd;
            box-shadow: 0 0 0 5px rgba(114, 225, 189, .12);
        }}
        #cadivor-maintenance-screen h1 {{
            max-width: 570px;
            margin: 18px 0 16px;
            color: #ffffff;
            font-size: clamp(34px, 5vw, 54px);
            line-height: 1.04;
            letter-spacing: -.055em;
        }}
        #cadivor-maintenance-screen .maintenance-message {{
            max-width: 590px;
            margin: 0;
            color: #d4e1f7;
            font-size: 18px;
            line-height: 1.6;
        }}
        #cadivor-maintenance-screen .maintenance-assurance {{
            display: flex;
            gap: 13px;
            margin-top: 34px;
            padding: 18px 20px;
            border: 1px solid rgba(115, 171, 255, .22);
            border-radius: 14px;
            background: rgba(54, 112, 218, .13);
            color: #dce9ff;
            line-height: 1.5;
        }}
        #cadivor-maintenance-screen .maintenance-assurance strong {{ color: #ffffff; }}
        #cadivor-maintenance-screen .maintenance-shield {{ color: #8eb6ff; font-size: 20px; }}
        #cadivor-maintenance-screen .maintenance-footer {{
            margin: 30px 0 0;
            color: #a8bbda;
            font-size: 14px;
            line-height: 1.55;
        }}
        #cadivor-maintenance-screen .maintenance-footer a {{ color: #b9d0ff; }}
        @media (max-width: 640px) {{
            [data-testid="stAppViewContainer"] > .main .block-container {{ padding: 24px 16px; }}
            #cadivor-maintenance-screen .maintenance-card {{ padding: 28px 24px; border-radius: 18px; }}
            #cadivor-maintenance-screen .maintenance-brand {{ margin-bottom: 30px; }}
            #cadivor-maintenance-screen .maintenance-message {{ font-size: 16px; }}
        }}
        </style>
        <main id="cadivor-maintenance-screen" aria-labelledby="cadivor-maintenance-heading">
          <section class="maintenance-card">
            <div class="maintenance-brand"><span class="maintenance-mark">C</span><span>Cadivor</span></div>
            <div class="maintenance-eyebrow">Scheduled maintenance</div>
            <h1 id="cadivor-maintenance-heading">We’re improving Cadivor.</h1>
            <p class="maintenance-message">{safe_message}</p>
            <div class="maintenance-assurance"><span class="maintenance-shield">&#9670;</span><span><strong>Your engineering data is safe.</strong><br/>Your workspace and saved analyses will be available again when service is restored.</span></div>
            <p class="maintenance-footer">Please check back shortly. For time-sensitive access support, contact <a href="mailto:beta@cadivor.com">beta@cadivor.com</a>.</p>
          </section>
        </main>
        """,
        unsafe_allow_html=True,
    )


def get_user_profile(current_user):
    """Return user-facing profile fields without assuming optional DB columns exist."""
    if not isinstance(current_user, dict):
        current_user = {}
    auth_user = st.session_state.get("user")
    metadata = getattr(auth_user, "user_metadata", {}) or {}

    email = _safe_text(current_user.get("email"), _safe_text(getattr(auth_user, "email", "")))
    full_name = _safe_text(
        current_user.get("full_name"),
        _safe_text(
            current_user.get("name"),
            _safe_text(metadata.get("full_name"), _safe_text(metadata.get("name"), "")),
        ),
    )
    first_name = _safe_text(current_user.get("first_name"), _safe_text(metadata.get("first_name"), ""))
    last_name = _safe_text(current_user.get("last_name"), _safe_text(metadata.get("last_name"), ""))
    if not full_name and (first_name or last_name):
        full_name = f"{first_name} {last_name}".strip()
    if not full_name and email:
        full_name = email.split("@")[0].replace(".", " ").replace("_", " ").title()

    company = _safe_text(
        current_user.get("company_name"),
        _safe_text(current_user.get("company"), _safe_text(metadata.get("company_name"), _safe_text(metadata.get("company"), ""))),
    )
    role_title = _safe_text(current_user.get("role_title"), _safe_text(current_user.get("job_title"), _safe_text(metadata.get("role_title"), "")))
    avatar_url = _safe_text(current_user.get("profile_image_url"), _safe_text(current_user.get("avatar_url"), _safe_text(metadata.get("avatar_url"), "")))
    phone = _safe_text(current_user.get("phone"), _safe_text(metadata.get("phone"), ""))
    country = _safe_text(current_user.get("country"), _safe_text(metadata.get("country"), ""))
    timezone = _safe_text(current_user.get("timezone"), _safe_text(metadata.get("timezone"), ""))
    workspace_name = _safe_text(current_user.get("workspace_name"), _safe_text(company, "Cadivor Workspace"))
    plan = _safe_text(current_user.get("plan"), "Starter")

    # Milestone 11A.1: overlay persistent customer profile fields when
    # the new profile migration is available.
    user_id = _safe_text(
        current_user.get("id"),
        _safe_text(getattr(auth_user, "id", "")),
    )
    if user_id:
        try:
            customer_profile, customer_profile_error = ensure_customer_profile(
                supabase,
                user_id,
                email,
                full_name,
            )
            if customer_profile and not customer_profile_error:
                full_name = _safe_text(
                    customer_profile.get("full_name"),
                    full_name,
                )
                company = _safe_text(
                    customer_profile.get("company_name"),
                    company,
                )
                role_title = _safe_text(
                    customer_profile.get("job_title"),
                    role_title,
                )
                avatar_url = _safe_text(
                    customer_profile.get("avatar_url"),
                    avatar_url,
                )
                phone = _safe_text(
                    customer_profile.get("phone"),
                    phone,
                )
                country = _safe_text(
                    customer_profile.get("country"),
                    country,
                )
                timezone = _safe_text(
                    customer_profile.get("timezone"),
                    timezone,
                )
        except Exception:
            pass

    initials_source = full_name or email or "Cadivor"
    initials = "".join([part[0] for part in initials_source.replace("@", " ").split()[:2]]).upper()[:2] or "C"
    return {
        "email": email,
        "full_name": full_name or "Cadivor user",
        "company": company,
        "role_title": role_title,
        "avatar_url": avatar_url,
        "phone": phone,
        "country": country,
        "timezone": timezone,
        "workspace_name": workspace_name,
        "plan": plan,
        "initials": initials,
    }


def update_user_profile_fields(user_id, updates):
    """Update only optional profile columns that already exist in the users table."""
    user_record = globals().get("current_user") or {}
    existing = set(user_record.keys()) if isinstance(user_record, dict) else set()
    allowed = {k: v for k, v in updates.items() if k in existing}
    skipped = [k for k in updates.keys() if k not in existing]
    if allowed:
        supabase.table("users").update(allowed).eq("id", user_id).execute()
    return allowed, skipped

def load_alternative_history(user_id):
    response = (
        _workspace_query(
            supabase.table("alternative_recommendations")
            .select("*")
        )
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data if response.data else []



def load_analysis_history(user_id):
    response = (
        _workspace_query(
            supabase.table("analyses")
            .select("*")
        )
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data if response.data else []


def _workspace_query(query):
    workspace_id = str(st.session_state.get("active_workspace_id") or "")
    if workspace_id:
        return query.eq("workspace_id", workspace_id)
    return query


def _workspace_payload(payload):
    result = dict(payload or {})
    workspace_id = str(st.session_state.get("active_workspace_id") or "")
    if workspace_id:
        result["workspace_id"] = workspace_id
    return result


def _decision_context_key(analysis_id=None):
    """Return a stable decision scope for saved analyses or standalone searches."""
    if analysis_id is None:
        return "standalone"

    analysis_value = str(analysis_id).strip()
    return analysis_value if analysis_value else "standalone"


def _make_json_safe(value, _seen=None):
    """Convert nested supplier and pandas values into JSON-safe data.

    Circular references are replaced with a readable marker so Supabase's
    JSON encoder cannot fail while saving source/comparison snapshots.
    """
    if _seen is None:
        _seen = set()

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    value_id = id(value)
    if value_id in _seen:
        return "[circular reference omitted]"

    if isinstance(value, dict):
        _seen.add(value_id)
        try:
            return {
                str(key): _make_json_safe(item, _seen)
                for key, item in value.items()
            }
        finally:
            _seen.discard(value_id)

    if isinstance(value, (list, tuple, set)):
        _seen.add(value_id)
        try:
            return [_make_json_safe(item, _seen) for item in value]
        finally:
            _seen.discard(value_id)

    if hasattr(value, "to_dict"):
        try:
            return _make_json_safe(value.to_dict(), _seen)
        except Exception:
            pass

    if hasattr(value, "item"):
        try:
            return _make_json_safe(value.item(), _seen)
        except Exception:
            pass

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass

    return str(value)


def save_analysis_decision(user_id, payload):
    """Insert or update a persistent Alternative Finder engineering decision."""
    if not user_id:
        raise ValueError("A signed-in user is required to save a decision.")

    original_part = str(payload.get("original_part", "")).strip()
    alternative_part = str(payload.get("alternative_part", "")).strip()
    analysis_id = payload.get("analysis_id")
    context_key = _decision_context_key(analysis_id)

    if not original_part or not alternative_part:
        raise ValueError("Original and alternative part numbers are required.")

    record = {
        "user_id": user_id,
        "workspace_id": st.session_state.get("active_workspace_id") or None,
        "analysis_id": str(analysis_id).strip() if analysis_id else None,
        "context_key": context_key,
        "project_name": str(payload.get("project_name", "")).strip(),
        "engineer_name": str(payload.get("engineer_name", "")).strip(),
        "original_part": original_part,
        "alternative_part": alternative_part,
        "decision": str(payload.get("decision", "Saved")).strip() or "Saved",
        "engineering_note": str(payload.get("engineering_note", "")).strip(),
        "recommendation_score": int(payload.get("recommendation_score", 0) or 0),
        "recommendation_rating": str(payload.get("recommendation_rating", "")),
        "compatibility_confidence": int(
            payload.get("compatibility_confidence", 0) or 0
        ),
        "compatibility_rating": str(payload.get("compatibility_rating", "")),
        "lifecycle": str(payload.get("lifecycle", "")),
        "risk": str(payload.get("risk", "")),
        "supplier": str(payload.get("supplier", "")),
        "stock": int(float(payload.get("stock", 0) or 0)),
        "unit_price": float(payload.get("unit_price", 0) or 0),
        "package": str(payload.get("package", "")),
        "stock_delta": str(payload.get("stock_delta", "")),
        "price_delta": str(payload.get("price_delta", "")),
        "source_snapshot": _make_json_safe(
            payload.get("source_snapshot", {}) or {}
        ),
        "comparison_snapshot": _make_json_safe(
            payload.get("comparison_snapshot", {}) or {}
        ),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    existing = (
        _workspace_query(
            supabase.table("analysis_decisions")
            .select("id")
        )
        .eq("user_id", user_id)
        .eq("context_key", context_key)
        .eq("original_part", original_part)
        .eq("alternative_part", alternative_part)
        .limit(1)
        .execute()
    )

    if existing.data:
        decision_id = existing.data[0]["id"]
        response = (
            supabase.table("analysis_decisions")
            .update(record)
            .eq("id", decision_id)
            .eq("user_id", user_id)
            .execute()
        )
    else:
        record["created_at"] = datetime.now(timezone.utc).isoformat()
        response = (
            supabase.table("analysis_decisions")
            .insert(record)
            .execute()
        )

    if not response.data:
        raise RuntimeError("Supabase did not return the saved decision.")

    return response.data[0]


def load_analysis_decisions(
    user_id,
    original_part=None,
    analysis_id=None,
    limit=25,
    include_all_contexts=False,
):
    """Load active engineering decisions, with optional cross-context history."""
    context_key = _decision_context_key(analysis_id)

    query = (
        _workspace_query(
            supabase.table("analysis_decisions")
            .select("*")
        )
        .eq("user_id", user_id)
        .is_("archived_at", "null")
    )

    if not include_all_contexts:
        query = query.eq("context_key", context_key)

    if original_part:
        query = query.eq("original_part", str(original_part).strip())

    response = (
        query.order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data if response.data else []


def archive_analysis_decision(user_id, decision_id):
    response = (
        _workspace_query(
            supabase.table("analysis_decisions")
            .update(
                {
                    "archived_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
        .eq("id", decision_id)
        .eq("user_id", user_id)
        .execute()
    )
    return response.data if response.data else []


def generate_engineering_change_package_pdf(
    *,
    original_part,
    alternative_part,
    decision,
    engineering_note,
    recommendation_score,
    compatibility_confidence,
    lifecycle,
    risk,
    supplier,
    stock,
    unit_price,
    package,
    stock_delta,
    price_delta,
    engineer_name,
    project_name,
    comparison_snapshot=None,
):
    """Generate a wrapped, ECO-ready engineering change package PDF."""
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    buffer = BytesIO()
    generated_at = datetime.now(timezone.utc)
    comparison_snapshot = comparison_snapshot or {}

    def _safe_list(value):
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        if value in (None, "", {}):
            return []
        return [str(value).strip()]

    matches = _safe_list(comparison_snapshot.get("engineering_matches", []))
    warnings = _safe_list(comparison_snapshot.get("warnings", []))
    advantages = _safe_list(comparison_snapshot.get("advantages", []))
    tradeoffs = _safe_list(comparison_snapshot.get("tradeoffs", []))

    combined_warnings = " ".join(warnings).lower()
    next_steps = []
    if any(word in combined_warnings for word in ("package", "mounting", "footprint")):
        next_steps.append("Verify PCB footprint, land pattern, and mounting constraints.")
    if "voltage" in combined_warnings:
        next_steps.append("Confirm voltage ratings against the circuit operating limits.")
    if any(word in combined_warnings for word in ("architecture", "channel")):
        next_steps.append("Validate the electrical architecture and functional behavior.")
    if "pin" in combined_warnings:
        next_steps.append("Confirm pin mapping before schematic or PCB release.")
    if any(word in combined_warnings for word in ("thermal", "power", "current")):
        next_steps.append("Review current, power dissipation, and thermal margins.")
    if compatibility_confidence < 70:
        next_steps.append("Complete bench validation before production approval.")
    if str(decision).lower() == "approved":
        next_steps.append("Update the BOM revision and retain this package with the change record.")
    elif str(decision).lower() == "rejected":
        next_steps.append("Document the rejection rationale and continue candidate review.")
    else:
        next_steps.append("Record an approval or rejection after engineering review.")

    unique_steps = []
    for step in next_steps:
        if step not in unique_steps:
            unique_steps.append(step)
    next_steps = unique_steps[:7]

    def _header_footer(canvas, doc):
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        canvas.saveState()
        width, height = letter
        canvas.setFillColor(colors.HexColor("#2563EB"))
        canvas.rect(0, height - 12, width, 12, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#0F172A"))
        # Keep the PDF independent of optional custom-font registration on\n        # production workers.\n        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(42, height - 28, "CADIVOR")
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(42, height - 38, "ENGINEERING INTELLIGENCE")
        canvas.setStrokeColor(colors.HexColor("#E2E8F0"))
        canvas.line(42, 31, width - 42, 31)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(
            42,
            19,
            f"{original_part} -> {alternative_part} - Engineering Change Package",
        )
        canvas.drawRightString(width - 42, 19, f"Page {doc.page}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=42,
        leftMargin=42,
        topMargin=52,
        bottomMargin=42,
        title=f"Cadivor Engineering Change Package: {original_part} to {alternative_part}",
        author=str(engineer_name or "Cadivor"),
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"].clone("cadivor_pdf_title")
    # ReportLab's paragraph parser cannot derive the bold/italic family from
    # this registered custom-font alias. Use the built-in mapped family for
    # all paragraph styles; the canvas header may still use the brand font.
    title_style.fontName = "Helvetica-Bold"
    title_style.fontSize = 22
    title_style.leading = 26
    title_style.textColor = colors.HexColor("#0B1220")
    title_style.alignment = 0

    subtitle_style = styles["BodyText"].clone("cadivor_pdf_subtitle")
    subtitle_style.fontName = "Helvetica"
    subtitle_style.fontSize = 9.5
    subtitle_style.leading = 14
    subtitle_style.textColor = colors.HexColor("#475569")

    section_style = styles["Heading2"].clone("cadivor_pdf_section")
    section_style.fontName = "Helvetica-Bold"
    section_style.fontSize = 12
    section_style.leading = 15
    section_style.textColor = colors.HexColor("#0F172A")
    section_style.spaceBefore = 14
    section_style.spaceAfter = 8

    body_style = styles["BodyText"].clone("cadivor_pdf_body")
    body_style.fontName = "Helvetica"
    body_style.fontSize = 8.2
    body_style.leading = 10.4
    body_style.textColor = colors.HexColor("#334155")
    body_style.wordWrap = "CJK"

    compact_style = styles["BodyText"].clone("cadivor_pdf_compact")
    compact_style.fontName = "Helvetica"
    compact_style.fontSize = 7.4
    compact_style.leading = 9.2
    compact_style.textColor = colors.HexColor("#334155")
    compact_style.wordWrap = "CJK"

    small_style = styles["BodyText"].clone("cadivor_pdf_small")
    small_style.fontName = "Helvetica"
    small_style.fontSize = 7.2
    small_style.leading = 9
    small_style.textColor = colors.HexColor("#475569")
    small_style.wordWrap = "CJK"

    label_style = styles["BodyText"].clone("cadivor_pdf_label")
    label_style.fontName = "Helvetica-Bold"
    label_style.fontSize = 7.2
    label_style.leading = 9
    label_style.textColor = colors.HexColor("#0F172A")
    label_style.wordWrap = "CJK"

    header_cell_style = styles["BodyText"].clone("cadivor_pdf_header_cell")
    header_cell_style.fontName = "Helvetica-Bold"
    header_cell_style.fontSize = 7.5
    header_cell_style.leading = 9
    header_cell_style.textColor = colors.white
    header_cell_style.wordWrap = "CJK"

    def _clean_text(value):
        text_value = str(value if value is not None else "-")
        replacements = {
            "✓": "",
            "⚠": "",
            "ℹ": "",
            "●": "",
            "🔴": "",
            "🟢": "",
            "🟡": "",
            "■": "",
            "▪": "",
            "□": "-",
            "→": "to",
            "•": "-",
        }
        for old, new in replacements.items():
            text_value = text_value.replace(old, new)

        text_value = re.sub(
            r"^\s*(warning|match|advantage|trade[- ]?off)\s*:\s*",
            "",
            text_value,
            flags=re.IGNORECASE,
        )
        text_value = re.sub(r"\s+", " ", text_value).strip()
        return html.escape(text_value)

    def _p(value, style=body_style, bold=False, color=None):
        from reportlab.platypus import Paragraph
        content = _clean_text(value)
        if bold:
            content = f"<b>{content}</b>"
        if color:
            content = f'<font color="{color}">{content}</font>'
        return Paragraph(content, style)

    def _bullet_block(items, prefix, empty_message, color, style=compact_style):
        from reportlab.platypus import Paragraph
        if not items:
            return _p(empty_message, style)

        lines = []
        for item in items:
            cleaned_item = re.sub(
                r"^\s*(warning|match|advantage|trade[- ]?off)\s*:\s*",
                "",
                str(item),
                flags=re.IGNORECASE,
            )
            cleaned_item = cleaned_item.replace("■", "").replace("▪", "").strip()

            if prefix == "ADVANTAGE:":
                stock_match = re.search(
                    r"([0-9]+(?:\.[0-9]+)?)\s*[x×]\s*more stock",
                    cleaned_item,
                    flags=re.IGNORECASE,
                )
                cost_match = re.search(
                    r"([0-9]+(?:\.[0-9]+)?)%\s*lower cost",
                    cleaned_item,
                    flags=re.IGNORECASE,
                )
                if stock_match:
                    cleaned_item = (
                        f"Approximately {stock_match.group(1)}x greater supplier inventory"
                    )
                elif cost_match:
                    cleaned_item = (
                        f"Estimated unit cost reduced by {cost_match.group(1)}%"
                    )

            lines.append(
                f'<font color="{color}"><b>{html.escape(prefix)}</b></font> '
                f'{_clean_text(cleaned_item)}'
            )

        return Paragraph("<br/><br/>".join(lines), style)

    decision_upper = str(decision or "Pending review").upper()
    decision_color = {
        "APPROVED": "#059669",
        "REJECTED": "#DC2626",
        "SAVED": "#2563EB",
    }.get(decision_upper, "#D97706")

    story = [
        Spacer(1, 4),
        Paragraph("Engineering Change Package", title_style),
        Spacer(1, 4),
        Paragraph(
            "Formal component replacement review for design, sourcing, quality, "
            "and change-control documentation.",
            subtitle_style,
        ),
        Spacer(1, 16),
    ]

    summary = Table(
        [
            [
                _p("PROJECT", label_style),
                _p("ENGINEER", label_style),
                _p("DECISION DATE", label_style),
                _p("STATUS", label_style),
            ],
            [
                _p(project_name or "Standalone Alternative Finder", compact_style),
                _p(engineer_name or "Cadivor user", compact_style),
                _p(generated_at.strftime("%b %d, %Y - %H:%M UTC"), compact_style),
                _p(decision_upper, compact_style, bold=True, color=decision_color),
            ],
        ],
        colWidths=[145, 125, 145, 85],
    )
    summary.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF6FF")),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(summary)

    story.append(Paragraph("Executive Decision Summary", section_style))
    decision_summary = Table(
        [
            [_p("Original Component", label_style), _p(original_part)],
            [_p("Selected Replacement", label_style), _p(alternative_part)],
            [_p("Recommendation Score", label_style), _p(f"{int(recommendation_score)}/100")],
            [_p("Compatibility Confidence", label_style), _p(f"{int(compatibility_confidence)}%")],
            [_p("Engineering Risk", label_style), _p(risk)],
            [_p("Lifecycle", label_style), _p(lifecycle)],
            [_p("Decision", label_style), _p(decision)],
        ],
        colWidths=[180, 320],
    )
    decision_summary.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")),
                ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(decision_summary)

    story.append(Paragraph("Sourcing and Package Impact", section_style))
    sourcing = Table(
        [
            [
                _p("Supplier", header_cell_style),
                _p("Available Stock", header_cell_style),
                _p("Unit Price", header_cell_style),
                _p("Package", header_cell_style),
            ],
            [
                _p(supplier, compact_style),
                _p(f"{int(stock):,}", compact_style),
                _p(f"${float(unit_price):.4g}", compact_style),
                _p(package, compact_style),
            ],
            [
                _p("Stock Impact", label_style),
                _p(stock_delta, compact_style),
                _p("Cost Impact", label_style),
                _p(price_delta, compact_style),
            ],
        ],
        colWidths=[120, 130, 120, 130],
    )
    sourcing.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563EB")),
                ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                    colors.white,
                    colors.HexColor("#F8FAFC"),
                ]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(sourcing)

    story.append(Paragraph("Engineering Evidence", section_style))
    evidence = Table(
        [
            [_p("ENGINEERING MATCHES", label_style), _p("WARNINGS", label_style)],
            [
                _bullet_block(
                    matches,
                    "MATCH:",
                    "No confirmed engineering matches were recorded.",
                    "#059669",
                ),
                _bullet_block(
                    warnings,
                    "WARNING:",
                    "No material warnings were recorded.",
                    "#D97706",
                ),
            ],
            [_p("SOURCING ADVANTAGES", label_style), _p("TRADE-OFFS", label_style)],
            [
                _bullet_block(
                    advantages,
                    "ADVANTAGE:",
                    "No sourcing advantage was calculated.",
                    "#059669",
                ),
                _bullet_block(
                    tradeoffs,
                    "TRADE-OFF:",
                    "No significant trade-offs identified.",
                    "#DC2626",
                ),
            ],
        ],
        colWidths=[250, 250],
    )
    evidence.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 1), colors.HexColor("#ECFDF5")),
                ("BACKGROUND", (1, 0), (1, 1), colors.HexColor("#FFFBEB")),
                ("BACKGROUND", (0, 2), (0, 3), colors.HexColor("#ECFDF5")),
                ("BACKGROUND", (1, 2), (1, 3), colors.HexColor("#FEF2F2")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(evidence)

    comparison_rows = comparison_snapshot.get("comparison_table", [])
    if isinstance(comparison_rows, list) and comparison_rows:
        clean_rows = [
            [
                _p("Attribute", header_cell_style),
                _p("Original", header_cell_style),
                _p("Selected Alternative", header_cell_style),
            ]
        ]
        for row in comparison_rows[:18]:
            if isinstance(row, dict):
                clean_rows.append(
                    [
                        _p(row.get("Attribute", row.get("attribute", "")), compact_style, bold=True),
                        _p(row.get("Original", row.get("original", "")), compact_style),
                        _p(
                            row.get(
                                "Selected Alternative",
                                row.get("selected_alternative", ""),
                            ),
                            compact_style,
                        ),
                    ]
                )
        if len(clean_rows) > 1:
            story.append(Paragraph("Side-by-Side Comparison", section_style))
            comparison = Table(clean_rows, colWidths=[160, 165, 175], repeatRows=1)
            comparison.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                            colors.white,
                            colors.HexColor("#F8FAFC"),
                        ]),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            story.append(comparison)

    story.append(Paragraph("Engineering Review Notes", section_style))
    note_box = Table(
        [[_p(engineering_note or "No engineering review notes were recorded.", body_style)]],
        colWidths=[500],
    )
    note_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(note_box)

    story.append(Paragraph("Recommended Next Actions", section_style))
    actions = Table(
        [[_p(f"- {step}", body_style)] for step in next_steps],
        colWidths=[500],
    )
    actions.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#BFDBFE")),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DBEAFE")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(actions)

    story.extend(
        [
            Spacer(1, 14),
            Paragraph(
                "This package documents the engineering review state at the time "
                "of generation. Final production release remains subject to the "
                "organization's approved change-control process.",
                small_style,
            ),
        ]
    )

    document.build(
        story,
        onFirstPage=_header_footer,
        onLaterPages=_header_footer,
    )
    buffer.seek(0)
    return buffer.getvalue()


def run_global_search(user_id, query, limit=8):
    """Search saved analyses, analysis parts, and alternative history for the dashboard command palette foundation."""
    query = (query or "").strip()
    if not query:
        return []

    q = query.lower()
    results = []

    try:
        analyses = load_analysis_history(user_id)
        for item in analyses:
            haystack = " ".join([
                str(item.get("project_name", "")),
                str(item.get("filename", "")),
                str(item.get("created_at", "")),
            ]).lower()
            if q in haystack:
                results.append({
                    "type": "BOM Analysis",
                    "title": item.get("project_name") or item.get("filename") or "Saved analysis",
                    "meta": f"{item.get('total_parts', 0)} parts • Health {item.get('health_score', '—')} • {item.get('created_at', '')}",
                    "page": "Dashboard",
                })
    except Exception:
        pass

    try:
        parts_response = (
            supabase.table("analysis_parts")
            .select("mpn,manufacturer,risk_level,lifecycle_status,analysis_id")
            .eq("user_id", user_id)
            .limit(100)
            .execute()
        )
        for part in parts_response.data or []:
            haystack = " ".join([
                str(part.get("mpn", "")),
                str(part.get("manufacturer", "")),
                str(part.get("risk_level", "")),
                str(part.get("lifecycle_status", "")),
            ]).lower()
            if q in haystack:
                results.append({
                    "type": "Component",
                    "title": part.get("mpn") or "Component",
                    "meta": f"{part.get('manufacturer', 'Unknown manufacturer')} • {part.get('risk_level', 'Unknown risk')} • {part.get('lifecycle_status', 'Unknown lifecycle')}",
                    "page": "BOM Analyzer",
                })
    except Exception:
        pass

    try:
        alternatives = load_alternative_history(user_id)
        for alt in alternatives:
            haystack = " ".join([
                str(alt.get("original_part", "")),
                str(alt.get("alternative_part", "")),
                str(alt.get("supplier", "")),
                str(alt.get("estimated_risk", "")),
            ]).lower()
            if q in haystack:
                results.append({
                    "type": "Alternative",
                    "title": f"{alt.get('original_part', '')} → {alt.get('alternative_part', '')}",
                    "meta": f"{alt.get('supplier', 'Unknown supplier')} • Score {alt.get('recommendation_score', '—')} • Stock {alt.get('stock', '—')}",
                    "page": "Alternative Finder",
                })
    except Exception:
        pass

    deduped = []
    seen = set()
    for result in results:
        key = (result.get("type"), result.get("title"), result.get("meta"))
        if key not in seen:
            deduped.append(result)
            seen.add(key)
    return deduped[:limit]


def render_global_search_panel(user_id):
    st.markdown(
        """
        <div class="cv-command-card cv-fade-in">
          <div class="cv-command-header">
            <div>
              <div class="cv-command-title">Global Search</div>
              <div class="cv-command-copy">Search BOMs, saved analyses, part numbers, suppliers, and alternatives. Command palette shortcut foundation: <span class="cv-kbd-inline">Ctrl</span> + <span class="cv-kbd-inline">K</span>.</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    search_query = st.text_input(
        "Search Cadivor workspace",
        value=st.session_state.get("global_search_query", ""),
        placeholder="Try a project name, part number, supplier, or risk level...",
        label_visibility="collapsed",
        key="global_search_query",
    )

    if search_query:
        results = run_global_search(user_id, search_query)
        if not results:
            empty_state(
                "No matching results",
                "Cadivor searched saved analyses, parts, alternatives, and suppliers but did not find a match.",
                "Analyze a BOM",
                "?page=BOM%20Analyzer",
                "⌕",
            )
        else:
            for result in results:
                page_href = str(result.get("page", "Dashboard")).replace(" ", "%20")
                st.markdown(
                    f"""
                    <div class="cv-result-card">
                      <div>
                        <div class="cv-result-title">{result.get('title', '')}</div>
                        <div class="cv-result-meta">{result.get('type', '')} • {result.get('meta', '')}</div>
                      </div>
                      <a class="cv-status-pill" href="?page={page_href}" target="_self">Open</a>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def generate_bom_pdf_report(project_name, selected_parts, attention_parts, bom_health_score, alternative_history=None):
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Executive BOM Risk Report", styles["Title"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"Project: {project_name}", styles["Heading2"]))
    risk_status = "Low Risk"

    if bom_health_score < 50:
        risk_status = "High Risk"
    elif bom_health_score < 80:
        risk_status = "Moderate Risk"

    story.append(
        Paragraph(
            f"BOM Health Score: {bom_health_score} / 100",
            styles["Heading2"]
        )
    )

    story.append(
        Paragraph(
            f"Overall Status: {risk_status}",
            styles["Normal"]
        )
    )

    story.append(Spacer(1, 12))

    executive_summary = (
    "This BOM shows moderate supply-chain risk due to obsolete "
    "components, replacement-suggested parts, and limited supplier "
    "availability. Priority should be given to obsolete and high-risk "
    "components before production release."
    )

    
    if risk_status == "High Risk":
        executive_summary = (
            "This BOM contains significant supply-chain and lifecycle risk. "
            "Immediate review of obsolete, high-risk, and low-availability "
            "components is strongly recommended before manufacturing."
        )

    elif risk_status == "Low Risk":
        executive_summary = (
            "This BOM currently demonstrates healthy lifecycle and sourcing "
            "status with relatively low supply-chain risk exposure."
        )

    story.append(
        Paragraph(
            f"<b>Executive Summary:</b> {executive_summary}",
            styles["BodyText"]
        )
    )

    story.append(
        Paragraph(
            (
                "<b>AI Recommendation Insight:</b> "
                "The strongest replacement path identified was ATMEGA328P-AU due to "
                "architecture compatibility, similar pin count, strong supplier availability, "
                "and minimal migration complexity."
            ),
            styles["BodyText"],
        )
    )

    story.append(Spacer(1, 16))

    story.append(
        Paragraph(
            f"Total Parts: {len(selected_parts)}",
            styles["Normal"]
        )
    )

    story.append(
        Paragraph(
            f"High-Risk Parts: {(selected_parts['risk_level'] == 'High').sum()}",
            styles["Normal"]
        )
    )

    story.append(Spacer(1, 16))

    story.append(
        Paragraph("Parts Requiring Attention", styles["Heading2"])
    )

    if attention_parts.empty:
        story.append(
            Paragraph("No critical parts detected.", styles["Normal"])
        )

    else:
        table_data = [
            [
                "Part Number",
                "Manufacturer",
                "Risk Level",
                "Lifecycle Status",
            ]
        ]

        for _, row in attention_parts.head(10).iterrows():
            table_data.append(
                [
                    str(row.get("mpn", "")),
                    str(row.get("manufacturer", "")),
                    str(row.get("risk_level", "")),
                    str(row.get("lifecycle_status", "")),
                ]
            )

        table = Table(table_data)

        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "CadivorVera-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                ]
            )
        )

        story.append(table)
    story.append(Spacer(1, 16))

    if alternative_history is None or alternative_history.empty:
        story.append(Paragraph("Supplier Verification", styles["Heading2"]))
        story.append(Paragraph("No saved supplier verification or alternative recommendations for this BOM.", styles["Normal"]))

    else:
        verification_history = alternative_history[
            alternative_history["original_part"] == alternative_history["alternative_part"]
        ]
        verification_history = verification_history.drop_duplicates(
            subset=["original_part", "supplier", "stock", "unit_price"]
        )

        true_alternative_history = alternative_history[
            alternative_history["original_part"] != alternative_history["alternative_part"]
        ]
        true_alternative_history = true_alternative_history.drop_duplicates(
            subset=["original_part", "alternative_part", "supplier", "stock", "unit_price"]
        )

        story.append(Paragraph("Supplier Verification", styles["Heading2"]))

        if verification_history.empty:
            story.append(Paragraph("No supplier verification records saved for this BOM.", styles["Normal"]))

        else:
            verification_table_data = [
                [
                    "Part Number",
                    "Supplier",
                    "Risk",
                    "Stock",
                    "Unit Price",
                ]
            ]

            for _, row in verification_history.head(10).iterrows():
                verification_table_data.append(
                    [
                        str(row.get("original_part", "")),
                        str(row.get("supplier", "")),
                        str(row.get("estimated_risk", "")),
                        str(row.get("stock", "")),
                        f"${float(row.get('unit_price', 0)):.2f}",
                    ]
                )

            verification_table = Table(verification_table_data)

            verification_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("FONTNAME", (0, 0), (-1, 0), "CadivorVera-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ]
                )
            )

            story.append(verification_table)

        story.append(Spacer(1, 16))
        story.append(Paragraph("Suggested Alternatives", styles["Heading2"]))

        if true_alternative_history.empty:
            story.append(Paragraph("No true alternative recommendations saved for this BOM.", styles["Normal"]))

        else:
            for original_part, group_df in true_alternative_history.groupby("original_part"):
                story.append(Paragraph(f"Alternatives for {original_part}", styles["Heading3"]))

                alt_table_data = [
                    [
                        "Alternative Part",
                        "Score",
                        "Risk",
                        "Supplier",
                        "Stock",
                        "Unit Price",
                    ]
                ]

                for _, row in group_df.head(5).iterrows():
                    alt_table_data.append(
                        [
                            str(row.get("alternative_part", "")),
                            str(row.get("recommendation_score", "")),
                            str(row.get("estimated_risk", "")),
                            str(row.get("supplier", "")),
                            str(row.get("stock", "")),
                            f"${float(row.get('unit_price', 0)):.2f}",

                        ]
                    )

                alt_table = Table(alt_table_data)

                alt_table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("FONTNAME", (0, 0), (-1, 0), "CadivorVera-Bold"),
                            ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ]
                    )
                )

                story.append(alt_table)
                story.append(Spacer(1, 10))

                for _, row in group_df.head(5).iterrows():
                    engineering_text = (
                        f"<b>{row.get('alternative_part', '')}</b><br/>"
                        f"Architecture: {row.get('architecture', '')}<br/>"
                        f"Package: {row.get('package', '')}<br/>"
                        f"Pin Count: {int(float(row.get('pin_count', 0) or 0))}<br/>"
                        f"Voltage Range: {row.get('voltage_range', '')}<br/>"
                        f"Compatibility Notes: {row.get('compatibility_notes', '')}<br/>"
                        f"Score Reasons: {row.get('score_reasons', '')}"
                    )

                    story.append(
                        Paragraph(
                            engineering_text,
                            styles["BodyText"],
                        )
                    )

                    story.append(Spacer(1, 8))

                best_engineering_row = group_df.loc[
                    group_df["recommendation_score"].astype(float).idxmax()
                ]

                story.append(
                    Paragraph(
                        (
                            f"<b>Best Engineering Recommendation:</b> "
                            f"{best_engineering_row['alternative_part']} "
                            f"with recommendation score of "
                            f"{best_engineering_row['recommendation_score']}."
                        ),
                        styles["BodyText"],
                    )
                )

                value_candidates = group_df[
                    group_df["stock"] > 0
                ]

                if not value_candidates.empty:
                    best_value_row = value_candidates.loc[
                        value_candidates["unit_price"].astype(float).idxmin()
                    ]

                    story.append(
                        Paragraph(
                            (
                                f"<b>Best Value Alternative:</b> "
                                f"{best_value_row['alternative_part']} "
                                f"— ${float(best_value_row['unit_price']):.2f} "
                                f"with available stock of {best_value_row['stock']} units."
                            ),
                            styles["BodyText"],
                        )
                    )

                story.append(Spacer(1, 14))

           
    doc.build(story)

    buffer.seek(0)

    return buffer



def run_authenticated_app() -> None:
    global current_user, is_admin, app_mode, saved_bom_count
    global active_workspace_id, active_workspace_name, active_workspace_role

    try:
        from src.auth_cookies import get_auth_cookie_manager
        from src.auth_diagnostics import log_auth_bounce, log_auth_correlation

        cookie_manager = get_auth_cookie_manager()
        log_auth_correlation(
            "authenticated_runtime_entry",
            cookie_manager=cookie_manager,
            transition_reason="runtime_entry",
        )
        log_auth_bounce(
            "authenticated_runtime",
            cookie_manager=cookie_manager,
            transition_reason="runtime_entry",
        )
    except Exception:
        pass

    from src.auth_state import explicit_logout_pending, handle_explicit_logout_if_pending

    if explicit_logout_pending() or st.session_state.get("cadivor_logout_in_progress"):
        if handle_explicit_logout_if_pending():
            st.stop()
        st.stop()

    _init_runtime_clients()

    st.markdown(
        """
        <style id="cadivor-root-surface">
        html, body, .stApp, [data-testid="stAppViewContainer"] {
            background: #F5F7FB !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    log_startup_phase("authenticated_runtime_begin")
    from src.performance_timing import emit_timing, timed_phase

    with timed_phase("runtime.load_user_data", operation="load_user_data"):
        current_user = load_user_data()

    is_admin = str(current_user.get("role", "")).lower() == "admin"
    # Admin Console v2.1 records only a timestamped authenticated heartbeat.
    # It deliberately stores no BOM content, page history, or client metadata.
    # A short throttle avoids adding a database write to every Streamlit rerun.
    heartbeat_key = "cadivor_last_activity_heartbeat"
    if time.time() - float(st.session_state.get(heartbeat_key, 0.0)) >= 60:
        try:
            supabase.rpc("cadivor_record_user_activity").execute()
            st.session_state[heartbeat_key] = time.time()
        except Exception:
            # The v2.1 migration is optional until approved; never block the app.
            pass

    def _record_support_activity(event_type, metadata=None):
        """Write a minimal support event without interrupting product work."""
        try:
            supabase.rpc("cadivor_record_support_activity", {
                "event_type": event_type,
                "event_metadata": metadata or {},
            }).execute()
        except Exception:
            pass

    if not st.session_state.get("cadivor_support_session_recorded"):
        _record_support_activity("session_started")
        st.session_state["cadivor_support_session_recorded"] = True
    # Admin Console v2 keeps maintenance and account suspension decisions in
    # server-enforced RPCs. If the migration is not present yet, normal product
    # access continues exactly as before.
    try:
        runtime_access_rows = supabase.rpc("cadivor_admin_runtime_access").execute().data or []
        runtime_access = runtime_access_rows[0] if runtime_access_rows else {}
        if str(runtime_access.get("account_status", "active")).lower() == "suspended":
            st.error("This Cadivor account has been suspended. Contact support if you need help.")
            st.stop()
        if bool(runtime_access.get("maintenance_mode")) and not is_admin:
            render_maintenance_mode_surface(runtime_access.get("maintenance_message"))
            st.stop()
    except Exception:
        pass
    with timed_phase("runtime.plan_resolve", operation="resolve"):
        effective_plan_name, trial_expired = resolve_effective_plan(current_user)
        if trial_expired:
            try:
                supabase.table("users").update({"plan": "Starter"}).eq("id", current_user["id"]).execute()
                current_user["plan"] = "Starter"
            except Exception:
                pass
            st.info("Your 14-day Cadivor trial has ended. Your workspace is now on Starter; saved analyses remain available.")


    @st.cache_data(ttl=3600, show_spinner=False)
    def get_part_data(row):
        from integrations.supplier_aggregator import get_best_part_data
        from src.alternative_engine import suggest_alternatives_v2
        part_number = row["mpn_normalized"]

        try:
            part_data = get_best_part_data(part_number)

        except Exception:
            part_data = {
                "mpn": part_number,
                "lifecycle_status": "Unknown",
                "stock_available": 0,
                "supplier_count": 0,
                "supplier_data_verified": False,
                "provider_health": {
                    "has_verified_data": False,
                    "summary_message": "Supplier data could not be verified during this analysis.",
                },
            }

        part_data["quantity"] = row.get("quantity", 0)

        try:
           alternative_part_numbers = suggest_alternatives_v2(part_number)

        except Exception:
            alternative_part_numbers = []

        part_data["has_alternates"] = len(alternative_part_numbers) > 0
        part_data["alternate_count"] = len(alternative_part_numbers)
        part_data["alternative_part_numbers"] = ", ".join(
            [
                alt.get("Alternative Part", str(alt))
                if isinstance(alt, dict)
                else str(alt)
                for alt in alternative_part_numbers
            ]
        )

        return part_data

    def send_monitor_alert_email(to_email: str, subject: str, message: str):
        import resend
        resend.api_key = get_secret("RESEND_API_KEY", required=True)
        from_email = get_secret(
            "ALERT_FROM_EMAIL",
            default="Cadivor <onboarding@resend.dev>",
        )

        if not resend.api_key:
            raise ValueError("Missing RESEND_API_KEY in configuration")

        return resend.Emails.send(
            {
                "from": from_email,
                "to": [to_email],
                "subject": subject,
                "html": f"<p>{message}</p>",
            }
        )
    def _json_safe_number(value, default=0):
        """Return a JSON-compliant finite number."""
        try:
            if value is None:
                return default
            number = float(value)
            return number if math.isfinite(number) else default
        except (TypeError, ValueError):
            return default


    def _json_safe_optional_number(value):
        """Return a finite number or None for optional database fields."""
        try:
            if value is None:
                return None
            number = float(value)
            return number if math.isfinite(number) else None
        except (TypeError, ValueError):
            return None


    def analyze_single_part(row):
        from src.risk_engine import calculate_risk
        from integrations.provider_health import unverified_supplier_reason_replacements
        part_data = get_part_data(row)
        risk_result = calculate_risk(part_data)
        risk_reasons = list(risk_result["risk_reasons"])
        supplier_verified = bool(part_data.get("supplier_data_verified", True))
        if not supplier_verified:
            replacements = unverified_supplier_reason_replacements()
            risk_reasons = [replacements.get(reason, reason) for reason in risk_reasons]
            if not any("could not be verified" in reason.lower() for reason in risk_reasons):
                risk_reasons.insert(
                    0,
                    "Some supplier data could not be verified during this analysis",
                )

        return {
            "MPN": row["mpn"],
            "Normalized MPN": row["mpn_normalized"],
            "Manufacturer": part_data.get("manufacturer", ""),
            "Manufacturer Part Number": part_data.get("manufacturer_part_number", ""),
            "Description": part_data.get("description", ""),
            "Quantity": row.get("quantity", 0),
            "Best Source": part_data.get("source", ""),
            "Supplier Count": part_data.get("supplier_count", 0),
            "Total Market Stock": part_data.get("total_market_stock", 0),
            "Sources Available": part_data.get("sources_available", ""),
            "Stock Available": part_data.get("stock_total", 0),
            "Unit Price": (
                part_data.get("unit_price")
                or part_data.get("price")
                or part_data.get("best_price")
                or part_data.get("minimum_price")
                or 0
            ),
            "Lead Time Weeks": part_data.get("lead_time_weeks", None),
            "Lifecycle Status": part_data.get("lifecycle_status", "Unknown"),
            "Product URL": part_data.get("product_detail_url", ""),
            "Has Alternates": part_data.get("has_alternates", False),
            "Alternate Count": part_data.get("alternate_count", 0),
            "Alternative Part Numbers": part_data.get("alternative_part_numbers", ""),
            "Supplier Data Verified": supplier_verified,
            "Risk Score": risk_result["risk_score"],
            "Risk Level": risk_result["risk_level"],
            "Risk Reasons": "; ".join(risk_reasons) or "No major risk found",
        }

    def analyze_bom(df, progress_status=None, progress_bar=None):
        from src.bom_parser import normalize_bom_columns, validate_bom, clean_bom_data
        from concurrent.futures import ThreadPoolExecutor, as_completed
        df = normalize_bom_columns(df)
        df = validate_bom(df)
        df = clean_bom_data(df)

        results = []
        total_parts = len(df)

        rows = [row for _, row in df.iterrows()]
        completed = 0

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_row = {
                executor.submit(analyze_single_part, row): row
                for row in rows
            }

            for future in as_completed(future_to_row):
                row = future_to_row[future]
                completed += 1

                if progress_status:
                    progress_status.info(
                        f"Completed {completed} of {total_parts}: {row.get('mpn', '')}"
                    )

                if progress_bar:
                    progress_bar.progress(completed / total_parts)

                try:
                    results.append(future.result(timeout=30))

                except Exception as e:
                    results.append(
                        {
                            "MPN": row.get("mpn", ""),
                            "Normalized MPN": row.get("mpn_normalized", ""),
                            "Manufacturer": "",
                            "Manufacturer Part Number": "",
                            "Description": "",
                            "Quantity": row.get("quantity", 0),
                            "Best Source": "",
                            "Supplier Count": 0,
                            "Total Market Stock": 0,
                            "Sources Available": "",
                            "Stock Available": 0,
                            "Lead Time Weeks": None,
                            "Lifecycle Status": "Unknown",
                            "Product URL": "",
                            "Has Alternates": False,
                            "Alternate Count": 0,
                            "Alternative Part Numbers": "",
                            "Risk Score": 100,
                            "Risk Level": "High",
                            "Risk Reasons": f"Part analysis failed: {e}",
                        }
                    )

        results_df = pd.DataFrame(results)
        if "Supplier Data Verified" in results_df.columns:
            degraded = not bool(results_df["Supplier Data Verified"].all())
        else:
            degraded = False
        st.session_state["cadivor_supplier_degraded"] = degraded
        st.session_state["cadivor_supplier_degraded_message"] = (
            "Some supplier data could not be verified during this analysis."
            if degraded
            else ""
        )
        return results_df

    def show_dashboard_summary(results_df):
        st.subheader("📊 BOM Risk Dashboard")

        total_parts = len(results_df)
        high_risk = (results_df["Risk Level"] == "High").sum()
        medium_risk = (results_df["Risk Level"] == "Medium").sum()
        low_risk = (results_df["Risk Level"] == "Low").sum()

        avg_risk_score = results_df["Risk Score"].mean()
        bom_health_score = max(0, round(100 - avg_risk_score))

        health_score = bom_health_score

        if health_score >= 90:
            health_status = "🟢 Excellent"
        elif health_score >= 75:
            health_status = "🟢 Healthy"
        elif health_score >= 60:
            health_status = "🟡 Moderate Risk"
        elif health_score >= 40:
            health_status = "🟠 High Risk"
        else:
            health_status = "🔴 Critical"

        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            "BOM Health Score",
            f"{health_score}/100",
            health_status,
        )
        col2.metric("Total Parts", total_parts)
        col3.metric("High Risk", high_risk)
        col4.metric("Medium Risk", medium_risk)

    

        st.divider()

        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("Risk Breakdown")
            risk_order = ["High", "Medium", "Low"]
            risk_counts = (
                results_df["Risk Level"]
                .value_counts()
                .reindex(risk_order, fill_value=0)
                .rename_axis("Risk Level")
                .reset_index(name="Components")
            )
            import plotly.express as px
            risk_fig = px.bar(
                risk_counts,
                x="Risk Level",
                y="Components",
                text="Components",
                height=245,
            )
            risk_fig.update_traces(marker_color="#2563EB", textposition="outside", cliponaxis=False)
            risk_fig.update_layout(
                margin=dict(l=8, r=8, t=8, b=8),
                showlegend=False,
                paper_bgcolor="white",
                plot_bgcolor="white",
                xaxis_title=None,
                yaxis_title=None,
                yaxis=dict(showgrid=True, gridcolor="#E8EEF6", zeroline=False),
            )
            st.plotly_chart(risk_fig, use_container_width=True, config={"displayModeBar": False})

        with col_b:
            st.subheader("Lifecycle Breakdown")
            lifecycle_counts = (
                results_df["Lifecycle Status"]
                .fillna("Unknown")
                .value_counts()
                .head(6)
                .rename_axis("Lifecycle Status")
                .reset_index(name="Components")
            )
            lifecycle_fig = px.bar(
                lifecycle_counts,
                x="Lifecycle Status",
                y="Components",
                text="Components",
                height=245,
            )
            lifecycle_fig.update_traces(marker_color="#2563EB", textposition="outside", cliponaxis=False)
            lifecycle_fig.update_layout(
                margin=dict(l=8, r=8, t=8, b=8),
                showlegend=False,
                paper_bgcolor="white",
                plot_bgcolor="white",
                xaxis_title=None,
                yaxis_title=None,
                xaxis=dict(tickangle=-18),
                yaxis=dict(showgrid=True, gridcolor="#E8EEF6", zeroline=False),
            )
            st.plotly_chart(lifecycle_fig, use_container_width=True, config={"displayModeBar": False})

        st.divider()

        st.subheader("🚨 Top Critical Parts")

        top_risks = results_df.sort_values(
            by="Risk Score",
            ascending=False
        ).head(5)

        cadivor_engineering_dataframe(
            top_risks[
                [
                    "MPN",
                    "Manufacturer",
                    "Risk Score",
                    "Risk Level",
                    "Stock Available",
                    "Supplier Count",
                    "Risk Reasons",
                ]
            ].reset_index(drop=True),
            column_config={
                "MPN": st.column_config.TextColumn(width="medium"),
                "Risk Score": st.column_config.NumberColumn(format="%d"),
                "Stock Available": st.column_config.NumberColumn(format="%,d"),
                "Supplier Count": st.column_config.NumberColumn(format="%d"),
            },
        )
        st.divider()

        st.subheader("✅ Recommended Actions")

        recommended_actions = []

        single_source_count = len(
            results_df[results_df["Supplier Count"] <= 1]
        )

        no_stock_count = len(
            results_df[results_df["Stock Available"] == 0]
        )

        unknown_lifecycle_count = len(
            results_df[
                results_df["Lifecycle Status"]
                .astype(str)
                .str.contains("unknown", case=False, na=False)
            ]
        )

        replacement_suggested_count = len(
            results_df[
                results_df["Lifecycle Status"]
                .astype(str)
                .str.contains("replacement", case=False, na=False)
            ]
        )

        if high_risk > 0:
            recommended_actions.append(
                f"🔴 Immediate review required for {high_risk} high-risk parts before production release."
            )

        if no_stock_count > 0:
            recommended_actions.append(
                f"📦 {no_stock_count} parts currently have no available stock. Procurement escalation recommended."
            )

        if single_source_count > 0:
            recommended_actions.append(
                f"⚠️ {single_source_count} parts rely on a single supplier. Evaluate secondary sourcing options."
            )

        if unknown_lifecycle_count > 0:
            recommended_actions.append(
                f"❓ {unknown_lifecycle_count} parts have unknown lifecycle status and require manufacturer verification."
            )

        if replacement_suggested_count > 0:
            recommended_actions.append(
                f"🔄 Replacement candidates were identified for {replacement_suggested_count} components."
            )

        if not recommended_actions:
            recommended_actions.append(
                "✅ No immediate sourcing risks detected. Continue periodic monitoring of lifecycle and stock availability."
            )

        st.markdown(
            '<div class="cv-action-list">'
            + "".join(f'<div class="cv-action-row">{html.escape(str(action))}</div>' for action in recommended_actions)
            + '</div>',
            unsafe_allow_html=True,
        )
    
        st.subheader("🧾 Executive Summary")

        summary_parts = []

        summary_parts.append(
            f"This BOM contains {total_parts} components with an overall health score of {health_score}/100, classified as {health_status}."
        )

        if high_risk > 0:
            summary_parts.append(
                f"{high_risk} high-risk components require immediate review before production release."
            )

        if no_stock_count > 0:
            summary_parts.append(
                f"{no_stock_count} components currently show no available stock, which may create procurement delays."
            )

        if single_source_count > 0:
            summary_parts.append(
                f"{single_source_count} components appear to rely on a single supplier, increasing sourcing risk."
            )

        if unknown_lifecycle_count > 0:
            summary_parts.append(
                f"{unknown_lifecycle_count} components have unknown lifecycle status and should be verified with the manufacturer or distributor."
            )

        if not recommended_actions:
            summary_parts.append(
                "No immediate sourcing risks were detected, but periodic monitoring is still recommended."
            )

        st.info(" ".join(summary_parts))


    def risk_badge(level):
        if level == "High":
            return "🔴 High"
        elif level == "Medium":
            return "🟡 Medium"
        elif level == "Low":
            return "🟢 Low"
        return "⚪ Unknown"


    def use_chart_dark_layout(fig, height=360):
        # Kept function name for compatibility, but use a premium light chart style.
        fig.update_layout(
            height=height,
            plot_bgcolor="#FFFFFF",
            paper_bgcolor="#FFFFFF",
            font=dict(color="#0F172A"),
            margin=dict(l=40, r=25, t=30, b=40),
        )
        fig.update_xaxes(gridcolor="#E5E7EB", zerolinecolor="#E5E7EB")
        fig.update_yaxes(gridcolor="#E5E7EB", zerolinecolor="#E5E7EB")
        return fig


    def brc_page_hero(title="Welcome back", subtitle="Monitor BOM risk, review recent analyses, and keep sourcing decisions moving from one executive dashboard."):
        st.markdown(
            f'<div class="brc-hero"><div class="brc-eyebrow">BOM Risk Intelligence</div><div class="brc-hero-title">{title}</div><p class="brc-hero-subtitle">{subtitle}</p></div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <style>
        :root {
            --brc-bg:#F5F7FB; --brc-surface:#FFFFFF; --brc-navy:#0F172A; --brc-muted:#64748B;
            --brc-border:#E2E8F0; --brc-blue:#2563EB; --brc-blue-soft:#EFF6FF;
            --brc-green:#2563EB; --brc-red:#EF4444; --brc-orange:#F59E0B;
            --brc-shadow:0 18px 45px rgba(15,23,42,.08);
        }
        html, body, [data-testid="stAppViewContainer"] { background:var(--brc-bg)!important; color:var(--brc-navy)!important; }
        [data-testid="stHeader"] { background:rgba(255,255,255,.88)!important; border-bottom:1px solid var(--brc-border)!important; }
        .block-container { max-width:100%!important; padding-top:1.25rem!important; padding-left:1.15rem!important; padding-right:1.15rem!important; }
        h1,h2,h3,h4,h5,h6 { color:var(--brc-navy)!important; letter-spacing:-.03em; }
        p,label,span,div,.stMarkdown,.stCaptionContainer { color:var(--brc-muted); }

        .brc-hero { background:linear-gradient(135deg,#fff 0%,#EEF6FF 100%); border:1px solid var(--brc-border); border-radius:18px; box-shadow:var(--brc-shadow); padding:26px 30px; margin:0 0 18px 0; }
        .brc-eyebrow { display:inline-flex; background:var(--brc-blue-soft); color:var(--brc-blue)!important; font-size:11px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; border-radius:999px; padding:7px 12px; margin-bottom:22px; }
        .brc-hero-title { color:var(--brc-navy)!important; font-size:34px; font-weight:850; line-height:1.05; margin:0 0 14px 0; }
        .brc-hero-subtitle { color:#52647A!important; font-size:17px; line-height:1.7; max-width:780px; margin:0; }

        .card,.kpi-card,.brc-card { background:#fff!important; border:1px solid var(--brc-border)!important; border-radius:16px!important; box-shadow:var(--brc-shadow)!important; padding:22px!important; margin-top:8px; margin-bottom:14px; }
        .card-title,.kpi-label { font-size:12px!important; font-weight:800!important; letter-spacing:.07em!important; text-transform:uppercase!important; color:#64748B!important; margin-bottom:12px!important; }
        .card-text,.kpi-note { font-size:13px!important; color:#334155!important; font-weight:700!important; }
        .kpi-value { font-size:32px!important; font-weight:850!important; color:var(--brc-navy)!important; margin-bottom:8px!important; line-height:1.05!important; }

        div.stButton > button, div.stDownloadButton > button { background:var(--brc-blue)!important; color:#FFFFFF!important; border:1px solid var(--brc-blue)!important; border-radius:10px!important; min-height:42px!important; padding:.55rem 1.05rem!important; font-weight:750!important; box-shadow:0 12px 24px rgba(37,99,235,.20)!important; width:auto!important; min-width:150px!important; }
        div.stButton > button:hover, div.stDownloadButton > button:hover { background:#1D4ED8!important; border-color:#1D4ED8!important; color:#FFFFFF!important; }
        div.stButton > button *, div.stDownloadButton > button * { color:#FFFFFF!important; }
        div.stButton > button:disabled,
        div.stDownloadButton > button:disabled {
            background:#E2E8F0!important;
            border-color:#CBD5E1!important;
            color:#94A3B8!important;
            box-shadow:none!important;
            cursor:not-allowed!important;
            opacity:1!important;
        }
        div.stButton > button:disabled *,
        div.stDownloadButton > button:disabled * {
            color:#94A3B8!important;
        }
        [data-testid="stSidebar"] div.stButton > button { width:100%!important; min-width:0!important; }

        div[data-testid="stTextInput"] input, div[data-testid="stSelectbox"] div[data-baseweb="select"], div[data-testid="stFileUploader"] section { background:#fff!important; border:1px solid #CBD5E1!important; border-radius:10px!important; color:var(--brc-navy)!important; }
    

        .stDataFrame,[data-testid="stDataFrame"] { border:1px solid var(--brc-border)!important; border-radius:8px!important; overflow:hidden!important; box-shadow:0 12px 30px rgba(15,23,42,.06)!important; background:#fff!important; }
        [data-testid="stDataFrame"] * { color:var(--brc-navy)!important; }
        [data-testid="stDataFrame"] [role="columnheader"], [data-testid="stDataFrame"] thead tr th { background:#F6F8FA!important; color:#475569!important; border-bottom:1px solid var(--brc-border)!important; font-weight:750!important; }
        [data-testid="stDataFrame"] [role="gridcell"], [data-testid="stDataFrame"] tbody tr td { background:#fff!important; color:var(--brc-navy)!important; border-bottom:1px solid #EEF2F7!important; }
        div[data-testid="stAlert"] { border-radius:12px!important; border:1px solid var(--brc-border)!important; }
        /* Cadivor v2.5 polished tables */
        [data-testid="stDataFrame"] { border-radius:14px!important; border:1px solid #E2E8F0!important; box-shadow:0 12px 30px rgba(15,23,42,.045)!important; }
        [data-testid="stDataFrame"] [role="row"]:hover [role="gridcell"] { background:#F8FAFC!important; }

        @media(max-width:900px){ .block-container{padding-left:1.1rem!important;padding-right:1.1rem!important;} .brc-hero-title{font-size:32px;} }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ---------- Cadivor App Navigation / Workspace Shell ----------
    NAV_OPTIONS = [
        "Dashboard",
        "BOM Analyzer",
        "Alternative Finder",
        "Monitoring",
        "Engineering Decisions",
        "Procurement Advisor",
        "Portfolio Intelligence",
        "Design Impact Analyzer",
        "Cost Optimization",
        "Supply Risk Scenario",
        "Reports",
        "Pricing",
        "Settings",
        "Workspace",
        "Notifications",
        "About",
    ]
    if is_admin:
        NAV_OPTIONS.insert(NAV_OPTIONS.index("Settings"), "Admin Console")
        NAV_OPTIONS.append("Help")

    if _qp_value("action") == "clear":
        st.session_state.pop("results_df", None)
        st.session_state.pop("uploaded_filename", None)
        try:
            st.query_params["page"] = _qp_value("page", "Dashboard")
            del st.query_params["action"]
        except Exception:
            pass

    # Default user plan
    selected_plan_name = effective_plan_name
    selected_plan = get_plan(selected_plan_name)
    monthly_upload_count = current_user["monthly_upload_count"]

    # Milestone 11B.2 — active organization data context.
    _context_user_id = _safe_text(current_user.get("id"), "")
    _context_email = _safe_text(current_user.get("email"), "")
    _context_name = _safe_text(
        current_user.get("full_name"),
        _context_email or "Cadivor user",
    )
    _context_company = (
        _safe_text(current_user.get("company"), "")
        or _safe_text(current_user.get("company_name"), "")
        or "Cadivor"
    )
    _context_workspace_name = (
        _context_company
        if _context_company.lower().endswith("workspace")
        else f"{_context_company} Workspace"
    )

    with timed_phase("runtime.workspace_init", operation="init"):
        _default_context_workspace, _default_context_error = ensure_personal_workspace(
            supabase,
            _context_user_id,
            _context_email,
            _context_name,
            _context_workspace_name,
            selected_plan_name,
        )

        _context_workspaces, _context_workspaces_error = list_user_workspaces(
            supabase,
            _context_user_id,
        )
        _preferred_context_workspace_id, _context_preference_error = (
            get_active_workspace_preference(
                supabase,
                _context_user_id,
            )
        )

        _context_available_ids = {
            str(item.get("id"))
            for item in (_context_workspaces or [])
            if item.get("id")
        }
        _context_requested_id = str(
            st.session_state.get("active_workspace_id")
            or _preferred_context_workspace_id
            or ""
        )

        if _context_requested_id in _context_available_ids:
            active_workspace, _active_workspace_error = get_workspace_by_id(
                supabase,
                _context_user_id,
                _context_requested_id,
            )
        else:
            active_workspace = _default_context_workspace or (
                _context_workspaces[0] if _context_workspaces else {}
            )

        active_workspace = active_workspace or {}
        active_workspace_id = str(active_workspace.get("id") or "")
        active_workspace_name = _safe_text(
            active_workspace.get("name"),
            "Cadivor Workspace",
        )
        active_workspace_role = _safe_text(
            active_workspace.get("current_role"),
            "owner",
        ).lower()

        if active_workspace_id:
            st.session_state["active_workspace_id"] = active_workspace_id
            st.session_state["active_workspace_name"] = active_workspace_name
            st.session_state["active_workspace_role"] = active_workspace_role

        try:
            saved_bom_count_response = execute_supabase_read(
                _workspace_query(supabase.table("analyses").select("id", count="exact")).eq(
                    "user_id", current_user["id"]
                ),
                operation="saved_bom_count",
            )
            saved_bom_count = saved_bom_count_response.count or 0
        except SupabaseReadTransportError:
            saved_bom_count = 0

    # Route state is mirrored to the address bar by navigate_to.  Treat a changed
    # URL page as an intentional route transition so browser Back/Forward restores
    # the visible Cadivor page instead of only changing an obsolete query string.
    _browser_navigation_event = consume_browser_navigation_event()
    _browser_navigation_params = {}
    _browser_navigation_event_id = ""
    if _browser_navigation_event:
        _browser_navigation_event_id = _safe_text(
            _browser_navigation_event.get("event_id"), ""
        )
        _browser_navigation_href = _safe_text(
            _browser_navigation_event.get("href"), ""
        )
        if (
            _browser_navigation_event_id
            and _browser_navigation_event_id
            != st.session_state.get("cadivor_last_browser_navigation_event_id")
            and _browser_navigation_href
        ):
            try:
                _browser_navigation_params = {
                    key: values[-1]
                    for key, values in parse_qs(
                        urlparse(_browser_navigation_href).query,
                        keep_blank_values=True,
                    ).items()
                    if values
                }
            except Exception:
                _browser_navigation_params = {}
            st.session_state["cadivor_last_browser_navigation_event_id"] = (
                _browser_navigation_event_id
            )

    try:
        _raw_external_page = st.query_params.get("page", "")
        if isinstance(_raw_external_page, list):
            _raw_external_page = _raw_external_page[0] if _raw_external_page else ""
    except Exception:
        _raw_external_page = ""
    _external_page = _safe_text(
        _browser_navigation_params.get("page", _raw_external_page), ""
    )

    app_mode = _safe_text(
        st.session_state.get("cadivor_route")
        or st.session_state.get("app_mode")
        or "Dashboard",
        "Dashboard",
    )
    _last_url_page = _safe_text(
        st.session_state.get("cadivor_last_url_page", ""),
        "",
    )
    if _external_page and _external_page != _last_url_page:
        app_mode = _external_page
    st.session_state["cadivor_last_url_page"] = _external_page or app_mode

    if app_mode not in NAV_OPTIONS and app_mode not in {"Analysis Details", "Onboarding"}:
        app_mode = "Dashboard"
    st.session_state["cadivor_route"] = app_mode
    st.session_state["app_mode"] = app_mode  # compatibility mirror
    if st.session_state.get("cadivor_support_last_page") != app_mode:
        _record_support_activity("page_viewed", {"page": app_mode})
        st.session_state["cadivor_support_last_page"] = app_mode

    # Sprint 50.1.2 — session-only analysis continuity across Cadivor pages.
    # Query values are treated only as navigation inputs; the durable browser-session
    # context lives in st.session_state and is never written to the database.
    _incoming_analysis_id = _safe_text(_qp_value("analysis_id", ""), "")
    _incoming_analysis_tab = _safe_text(_qp_value("analysis_tab", ""), "").replace("+", " ")
    _incoming_risk_filter = _safe_text(_qp_value("risk_filter", ""), "").strip().title()
    _incoming_high_risk_review = _safe_text(_qp_value("high_risk_review", ""), "").lower() in {
        "1", "true", "yes", "on"
    }
    if _incoming_analysis_id:
        st.session_state["cadivor_active_analysis_id"] = _incoming_analysis_id
        st.session_state["analysis_id"] = _incoming_analysis_id
    if _incoming_analysis_tab:
        st.session_state["cadivor_active_analysis_tab"] = _incoming_analysis_tab
    if _incoming_risk_filter in {"All", "High", "Medium", "Low"}:
        # KPI deep links should take the user directly to the corresponding
        # engineering review, while leaving the selectbox usable afterwards.
        st.session_state["bom81_detailed_risk_filter"] = _incoming_risk_filter
        try:
            st.query_params.pop("risk_filter", None)
        except Exception:
            pass
    if _incoming_high_risk_review:
        st.session_state["bom81_high_risk_review"] = True
        try:
            st.query_params.pop("high_risk_review", None)
        except Exception:
            pass

    _new_analysis_requested = _safe_text(_qp_value("new_analysis", ""), "").lower() in {
        "1", "true", "yes"
    }
    if _new_analysis_requested:
        for _state_key in (
            "cadivor_active_analysis_id",
            "cadivor_active_analysis_tab",
            "analysis_id",
            "results_df",
            "analysis_saved",
            "uploaded_filename",
        ):
            st.session_state.pop(_state_key, None)

    profile_for_shell = get_user_profile(current_user) if "get_user_profile" in globals() else current_user

    auth_user_for_onboarding = st.session_state.get("user")
    onboarding_user_id = _safe_text(
        getattr(auth_user_for_onboarding, "id", ""),
        _safe_text(current_user.get("id"), ""),
    )
    onboarding_progress = {}
    onboarding_error = None
    if onboarding_user_id:
        with timed_phase("runtime.onboarding_sync", operation="init"):
            onboarding_progress, onboarding_error = ensure_onboarding_progress(
                supabase,
                onboarding_user_id,
            )
            onboarding_progress = onboarding_progress or {}

        # Synchronize steps that can be inferred from existing Cadivor data.
        inferred_profile_complete = bool(
            profile_for_shell.get("full_name")
            and (
                profile_for_shell.get("company")
                or profile_for_shell.get("company_name")
                or profile_for_shell.get("role_title")
            )
        )
        inferred_workspace_complete = False
        try:
            inferred_workspace_complete = bool(
                supabase.table("workspace_members")
                .select("workspace_id")
                .eq("user_id", onboarding_user_id)
                .limit(1)
                .execute()
                .data
            )
        except Exception:
            pass

        inferred_alternative_complete = False
        try:
            inferred_alternative_complete = bool(
                _workspace_query(
                    supabase.table("analysis_decisions")
                    .select("id")
                )
                .eq("user_id", onboarding_user_id)
                .limit(1)
                .execute()
                .data
            )
        except Exception:
            pass

        sync_updates = {
            "profile_completed": inferred_profile_complete,
            "workspace_completed": inferred_workspace_complete,
            "first_bom_completed": saved_bom_count > 0,
            "first_alternative_completed": inferred_alternative_complete,
            "first_report_completed": bool(
                st.session_state.get("reports_session_history")
            ),
        }
        if any(
            bool(onboarding_progress.get(key)) != bool(value)
            for key, value in sync_updates.items()
        ):
            synced, sync_error = update_onboarding_progress(
                supabase,
                onboarding_user_id,
                sync_updates,
            )
            if synced and not sync_error:
                onboarding_progress = synced
    shell_name = profile_for_shell.get("full_name") or profile_for_shell.get("email", "Cadivor User").split("@")[0].title()
    shell_company = profile_for_shell.get("company_name") or profile_for_shell.get("company") or selected_plan_name
    shell_email = profile_for_shell.get("email") or current_user.get("email", "")
    shell_initials = "".join([part[0] for part in shell_name.split()[:2]]).upper()[:2] or "C"

    import urllib.parse as _urlparse


    # ---------- Cadivor Unified Application Shell ----------
    # One deterministic shell authority. Internal navigation uses session state and
    # the browser URL is not changed by ordinary sidebar interactions.
    inject_premium_css()
    st.markdown(readability_css(), unsafe_allow_html=True)


    def _s55_clear_analysis():
        for _key in (
            "cadivor_active_analysis_id", "cadivor_active_analysis_tab", "analysis_id",
            "results_df", "analysis_saved", "uploaded_filename",
        ):
            st.session_state.pop(_key, None)
        navigate_to("BOM Analyzer")


    def _s55_logout():
        """End the local session immediately; never route through page handling."""
        st.session_state.pop("cadivor_route_transition", None)
        st.session_state.pop("cadivor_nav_params", None)
        begin_logout(supabase, cookie_manager)


    render_unified_shell(
        current_page=app_mode,
        profile=profile_for_shell,
        workspace_name=shell_company,
        plan_name=selected_plan_name,
        usage_summary=f"{monthly_upload_count:,} / {format_limit(selected_plan['monthly_bom_limit'], 'BOM analysis', 'BOM analyses')} this month",
        saved_summary=f"{saved_bom_count:,} / {format_limit(selected_plan['max_saved_boms'], 'saved BOM')}",
        is_admin=is_admin,
        navigate=navigate_to,
        clear_analysis=_s55_clear_analysis,
        request_logout=_s55_logout,
    )

    # Design System v1 is deliberately injected after the application shell.
    with timed_phase("runtime.css_injection", operation="render"):
        inject_design_system_v1()
        inject_workspace_consistency_css()
        inject_premium_interaction_css()
        # Shell geometry loads before the final premium UI authority layer.
        inject_unified_shell_css()
        # Core premium UI is the last stylesheet: tokens, buttons, tables, KPIs, badges.
        inject_core_premium_ui()
        mark_authenticated_surface_ready()

    with timed_phase("runtime.workspace_commands", operation="workspace_commands") as cmd_meta:
        try:
            _workspace_command_records = build_workspace_commands(
                supabase, current_user["id"], limit_per_source=60,
            )
            cmd_meta["row_count"] = len(_workspace_command_records or [])
        except Exception:
            _workspace_command_records = []
    render_command_nav_triggers(_workspace_command_records)
    render_command_center(
        current_page=app_mode,
        user_name=shell_name.split()[0] if shell_name else "Engineer",
        workspace_commands=_workspace_command_records,
    )
    render_premium_interactions(current_page=app_mode)

    emit_timing(
        "runtime.route_enter",
        duration_ms=0.0,
        route=app_mode,
        outcome="success",
        event="route_enter",
    )

    if app_mode == "Onboarding":
        progress = onboarding_progress or {}
        completed_steps = completion_count(progress)
        total_steps = 5
        percent_complete = int((completed_steps / total_steps) * 100)

        st.markdown(
            """
            <style id="cadivor-onboarding-v11a2">
            .cv-onboard-hero{
                border:1px solid #BFDBFE;
                border-radius:26px;
                padding:30px 32px;
                background:
                    radial-gradient(circle at 92% 8%,rgba(37,99,235,.14),transparent 34%),
                    linear-gradient(135deg,#FFFFFF 0%,#F7FAFF 100%);
                box-shadow:0 22px 54px rgba(15,23,42,.07);
                margin-bottom:18px;
            }
            .cv-onboard-kicker{
                color:#2563EB;font-size:10px;font-weight:950;
                letter-spacing:.12em;text-transform:uppercase;margin-bottom:10px;
            }
            .cv-onboard-title{
                color:#0F172A;font-size:36px;line-height:1.06;font-weight:950;
                letter-spacing:-.045em;margin:0 0 10px;
            }
            .cv-onboard-copy{
                color:#52647A;font-size:14px;line-height:1.6;font-weight:690;
                max-width:860px;margin:0;
            }
            .cv-onboard-progress{
                height:10px;border-radius:999px;background:#E2E8F0;
                overflow:hidden;margin-top:20px;
            }
            .cv-onboard-progress i{
                display:block;height:100%;border-radius:999px;background:#2563EB;
            }
            .cv-onboard-progress-copy{
                color:#475569;font-size:11px;font-weight:850;margin-top:8px;
            }
            .cv-onboard-grid{
                display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
                gap:14px;margin:18px 0;
            }
            .cv-onboard-card{
                border:1px solid #E2E8F0;border-radius:19px;background:#FFFFFF;
                padding:18px;box-shadow:0 13px 34px rgba(15,23,42,.05);
            }
            .cv-onboard-card.done{border-color:#A7F3D0;background:#F0FDF4}
            .cv-onboard-step{
                color:#2563EB;font-size:9px;font-weight:950;letter-spacing:.1em;
                text-transform:uppercase;margin-bottom:7px;
            }
            .cv-onboard-card h3{
                color:#0F172A;font-size:16px;font-weight:950;margin:0 0 7px;
            }
            .cv-onboard-card p{
                color:#64748B;font-size:11px;line-height:1.5;font-weight:720;margin:0;
            }
            .cv-onboard-status{
                display:inline-flex;margin-top:12px;border-radius:999px;padding:5px 8px;
                font-size:9px;font-weight:950;background:#EFF6FF;color:#1D4ED8;
                border:1px solid #BFDBFE;
            }
            .cv-onboard-card.done .cv-onboard-status{
                background:#ECFDF5;color:#047857;border-color:#A7F3D0;
            }
            @media(max-width:760px){.cv-onboard-grid{grid-template-columns:1fr}}
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <section class="cv-onboard-hero">
              <div class="cv-onboard-kicker">Welcome to Cadivor</div>
              <h1 class="cv-onboard-title">Set up your engineering workspace.</h1>
              <p class="cv-onboard-copy">
                Complete these guided steps to personalize Cadivor, establish your
                workspace, analyze a BOM, review a replacement, and generate a report.
              </p>
              <div class="cv-onboard-progress"><i style="width:{percent_complete}%"></i></div>
              <div class="cv-onboard-progress-copy">
                {completed_steps} of {total_steps} steps complete · {percent_complete}%
              </div>
            </section>
            """,
            unsafe_allow_html=True,
        )

        steps = [
            (
                "1",
                "Complete your profile",
                "Add your company, title, time zone, and customer preferences.",
                bool(progress.get("profile_completed")),
            ),
            (
                "2",
                "Configure the workspace",
                "Confirm the workspace identity, settings, and collaboration foundation.",
                bool(progress.get("workspace_completed")),
            ),
            (
                "3",
                "Analyze your first BOM",
                "Upload a CSV or Excel BOM and save its engineering risk analysis.",
                bool(progress.get("first_bom_completed")),
            ),
            (
                "4",
                "Review a replacement",
                "Compare an alternative component and save an engineering decision.",
                bool(progress.get("first_alternative_completed")),
            ),
            (
                "5",
                "Generate a report",
                "Create an executive or engineering report for a saved BOM.",
                bool(progress.get("first_report_completed")),
            ),
        ]

        cards = []
        for number, title, copy, done in steps:
            cards.append(
                f'<div class="cv-onboard-card {"done" if done else ""}">'
                f'<div class="cv-onboard-step">Step {number}</div>'
                f'<h3>{html.escape(title)}</h3>'
                f'<p>{html.escape(copy)}</p>'
                f'<span class="cv-onboard-status">{"Complete" if done else "Next action"}</span>'
                f'</div>'
            )
        st.markdown(
            '<div class="cv-onboard-grid">' + "".join(cards) + "</div>",
            unsafe_allow_html=True,
        )

        next_incomplete_step = next(
            (
                index
                for index, key in enumerate(
                    (
                        "profile_completed",
                        "workspace_completed",
                        "first_bom_completed",
                        "first_alternative_completed",
                        "first_report_completed",
                    )
                )
                if not bool(progress.get(key))
            ),
            None,
        )

        onboarding_actions = [
            ("Edit Profile", "Settings", "onboarding_open_profile"),
            ("Open Workspace", "Workspace", "onboarding_open_workspace"),
            ("Analyze a BOM", "BOM Analyzer", "onboarding_open_bom"),
            ("Review Alternatives", "Alternative Finder", "onboarding_open_alternatives"),
            ("Generate a Report", "Reports", "onboarding_open_reports"),
        ]

        action_cols = st.columns(5)
        for index, (label, destination, key) in enumerate(onboarding_actions):
            with action_cols[index]:
                internal_nav_button(
                    label,
                    destination,
                    key=key,
                    use_container_width=True,
                    type="primary" if index == next_incomplete_step else "secondary",
                )

        finish_col, skip_col = st.columns(2)
        with finish_col:
            if st.button(
                "Mark Setup Complete",
                type="primary",
                use_container_width=True,
                disabled=completed_steps < total_steps,
                key="onboarding_complete",
            ):
                update_onboarding_progress(
                    supabase,
                    onboarding_user_id,
                    {
                        "welcome_seen": True,
                        "dismissed": False,
                        "completed_at": pd.Timestamp.utcnow().isoformat(),
                    },
                )
                st.success("Cadivor setup completed.")
                navigate_to("Dashboard")

        with skip_col:
            if st.button(
                "Skip for Now",
                type="secondary",
                use_container_width=True,
                key="onboarding_skip",
            ):
                update_onboarding_progress(
                    supabase,
                    onboarding_user_id,
                    {
                        "welcome_seen": True,
                        "dismissed": True,
                    },
                )
                navigate_to("Dashboard")

        stop_authenticated_page()


    # ---------- Dashboard ----------
    if app_mode == "Dashboard":
        inject_dashboard_workspace_styles()
        render_dashboard_page_heading()

        if (
            onboarding_progress
            and not onboarding_progress.get("dismissed")
            and completion_count(onboarding_progress) < 5
        ):
            onboarding_done = completion_count(onboarding_progress)
            onboarding_percent = int((onboarding_done / 5) * 100)
            st.markdown(
                f"""
                <style id="cadivor-dashboard-setup-v11a3">
                .cv-setup-reminder{{
                    border:1px solid #BFDBFE;border-radius:20px;background:#FFFFFF;
                    box-shadow:0 16px 38px rgba(15,23,42,.06);padding:18px 20px;
                    margin:0 0 18px;
                }}
                .cv-setup-reminder-top{{
                    display:flex;align-items:center;justify-content:space-between;
                    gap:14px;margin-bottom:10px;
                }}
                .cv-setup-reminder h3{{
                    color:#0F172A!important;font-size:16px;font-weight:950;margin:0;
                }}
                .cv-setup-reminder strong{{
                    color:#2563EB!important;font-size:12px;font-weight:950;
                }}
                .cv-setup-reminder p{{
                    color:#64748B!important;font-size:11px;line-height:1.5;
                    font-weight:720;margin:0 0 12px;
                }}
                .cv-setup-reminder-bar{{
                    height:8px;border-radius:999px;background:#E2E8F0;overflow:hidden;
                }}
                .cv-setup-reminder-bar i{{
                    display:block;height:100%;width:{onboarding_percent}%;
                    background:#2563EB;border-radius:999px;
                }}
                </style>
                <section class="cv-setup-reminder">
                  <div class="cv-setup-reminder-top">
                    <h3>Complete your Cadivor setup</h3>
                    <strong>{onboarding_done}/5 complete</strong>
                  </div>
                  <p>
                    Finish customer setup to complete your profile, workspace,
                    first BOM, replacement review, and first report.
                  </p>
                  <div class="cv-setup-reminder-bar"><i></i></div>
                </section>
                """,
                unsafe_allow_html=True,
            )
            # New accounts already receive the full setup experience on Dashboard.
            # Keep this reminder only after the user has made progress beyond account creation.
            if onboarding_done > 1 and st.button(
                "Setup Progress",
                key="dashboard_continue_onboarding",
            ):
                navigate_to("Onboarding")

        try:
            overview_analyses = load_analysis_history(current_user["id"]) or []
        except Exception:
            overview_analyses = []
        try:
            overview_parts_response = (
                _workspace_query(supabase.table("analysis_parts").select("*"))
                .eq("user_id", current_user["id"])
                .limit(5000)
                .execute()
            )
            overview_parts = overview_parts_response.data or []
        except Exception:
            overview_parts = []
        try:
            overview_alert_response = (
                _workspace_query(supabase.table("monitor_alerts").select("*"))
                .eq("user_id", current_user["id"])
                .order("created_at", desc=True)
                .limit(100)
                .execute()
            )
            overview_alerts = overview_alert_response.data or []
        except Exception:
            overview_alerts = []
        try:
            overview_state, _ = load_decision_state(
                supabase,
                user_id=current_user["id"],
                workspace_id=active_workspace_id or None,
            )
        except Exception:
            overview_state = {}

        overview_decisions = build_decision_center(
            alert_df=pd.DataFrame(overview_alerts),
            analyses=overview_analyses,
            saved_state=overview_state,
        )["decisions"]
        overview_procurement = build_procurement_advisor(
            analyses=overview_analyses,
            parts=overview_parts,
            alerts=overview_alerts,
        )
        overview = build_engineering_overview(
            analyses=overview_analyses,
            parts=overview_parts,
            alerts=overview_alerts,
            decisions=overview_decisions,
            procurement=overview_procurement,
        )

        # Launch Sprint 29.0D — new-account activation must be decided before
        # rendering the default Engineering Overview tab. Previously, onboarding
        # existed only inside Portfolio Dashboard, so brand-new users always saw
        # the empty overview because Streamlit opens the first tab by default.
        preview_onboarding = False
        try:
            preview_value = _qp_value("preview_onboarding", "")
            preview_onboarding = str(preview_value).strip().lower() in {
                "1", "true", "yes", "on"
            }
        except Exception:
            preview_onboarding = False

        real_overview_analyses = [
            row for row in overview_analyses
            if isinstance(row, dict)
            and row.get("id")
            and any(
                row.get(field) not in (None, "", 0, 0.0)
                for field in (
                    "filename",
                    "project_name",
                    "total_parts",
                    "health_score",
                    "created_at",
                )
            )
        ]

        if not real_overview_analyses or preview_onboarding:
            if preview_onboarding and real_overview_analyses:
                preview_notice, preview_exit = st.columns([4, 1])
                with preview_notice:
                    st.info(
                        "Onboarding preview is active. Your saved analyses are unchanged."
                    )
                with preview_exit:
                    if st.button(
                        "Exit preview",
                        key="dashboard_exit_onboarding_preview",
                        use_container_width=True,
                    ):
                        st.session_state.pop("preview_onboarding", None)
                        st.query_params.pop("preview_onboarding", None)
                        navigate_to("Dashboard")
            # Sprint 30.4: use the normalized, persistent customer profile so
            # onboarding and onboarding preview match the shell/dashboard identity.
            render_first_run_dashboard(
                current_user=profile_for_shell,
                workspace_name=active_workspace_name,
            )
            stop_authenticated_page()

        dashboard_nav_key = "cv672_dashboard_workspace_radio"
        if "dashboard_workspace_initialized" not in st.session_state:
            st.session_state["dashboard_workspace_initialized"] = True
            st.session_state["dashboard_workspace_tab"] = "Engineering Overview"
            st.session_state[dashboard_nav_key] = "Engineering Overview"

        workspace_category = render_dashboard_workspace_navigation(radio_key=dashboard_nav_key)
        st.session_state["dashboard_workspace_tab"] = workspace_category

        portfolio_cache_key = f"dashboard_portfolio_ctx_{current_user['id']}_{active_workspace_id or 'none'}"

        if workspace_category == "Engineering Overview":
            dashboard_metrics = compute_dashboard_summary_metrics(overview)
            profile = get_user_profile(current_user)

            def _render_engineering_activation() -> None:
                render_activation_strip(
                    analyses_count=len(real_overview_analyses),
                    has_review=False,
                    has_report=False,
                )
                if not is_admin:
                    render_upgrade_prompt(
                        plan_name=selected_plan_name,
                        monthly_used=len(real_overview_analyses),
                        monthly_limit=selected_plan.get("monthly_bom_limit"),
                    )

            render_engineering_overview_workspace(
                overview=overview,
                metrics=dashboard_metrics,
                activation_hook=_render_engineering_activation,
            )
        elif workspace_category == "Portfolio Intelligence":
            if portfolio_cache_key not in st.session_state:
                st.session_state[portfolio_cache_key] = load_portfolio_dashboard_context(
                    current_user=current_user,
                    load_alternative_history=load_alternative_history,
                    get_user_profile=get_user_profile,
                    preloaded_analyses=overview_analyses,
                    preloaded_alerts=overview_alerts,
                    fallback_analyses=real_overview_analyses,
                )
            render_portfolio_intelligence_workspace(
                ctx=st.session_state[portfolio_cache_key],
                overview=overview,
            )
        elif workspace_category == "Analytics":
            if portfolio_cache_key not in st.session_state:
                st.session_state[portfolio_cache_key] = load_portfolio_dashboard_context(
                    current_user=current_user,
                    load_alternative_history=load_alternative_history,
                    get_user_profile=get_user_profile,
                    preloaded_analyses=overview_analyses,
                    preloaded_alerts=overview_alerts,
                    fallback_analyses=real_overview_analyses,
                )
            render_dashboard_analytics_workspace(
                ctx=st.session_state[portfolio_cache_key],
                light_plotly_layout=light_plotly_layout,
            )
        elif workspace_category == "Monitoring":
            render_dashboard_monitoring_workspace(
                overview=overview,
                parts=overview_parts,
                alerts=overview_alerts,
            )

        # Existing customers can revisit the first-time experience without creating
        # a disposable account. This is a preview only and never changes saved data.
        st.html(
            """
            <p class="cv672-dashboard-preview-wrap">
              <a class="cv6723-quick-action cv672-dashboard-preview-link"
                 href="?page=Dashboard&amp;preview_onboarding=1"
                 target="_self">
                Preview onboarding
              </a>
            </p>
            """
        )

        inject_workspace_consistency_css()
        st.session_state.pop("cadivor_route_transition", None)
        stop_authenticated_page()

    if app_mode == "Analysis Details":
        # Sprint 30.2: make persistence explicit on every saved-analysis page.
        st.markdown(
            """
            <style id="cadivor-save-status-302">
            .cv302-savebar{display:flex;align-items:center;justify-content:space-between;gap:14px;
            border:1px solid #bbf7d0;background:linear-gradient(135deg,#ffffff,#f0fdf4);
            border-radius:13px;padding:10px 13px;margin:0 0 12px;box-shadow:0 8px 22px rgba(5,150,105,.055)}
            .cv302-saveleft{display:flex;align-items:center;gap:9px;min-width:0}
            .cv302-saveicon{width:26px;height:26px;border-radius:9px;background:#dcfce7;border:1px solid #bbf7d0;
            color:#15803d!important;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:950}
            .cv302-savetitle{font-size:11px;font-weight:900;color:#0f172a!important;line-height:1.25}
            .cv302-savecopy{font-size:9px;font-weight:650;color:#64748b!important;margin-top:2px}
            .cv302-savebadge{font-size:9px;font-weight:900;color:#047857!important;border:1px solid #a7f3d0;
            background:#ecfdf5;border-radius:999px;padding:5px 8px;white-space:nowrap}
            </style>
            <div class="cv302-savebar">
              <div class="cv302-saveleft">
                <div class="cv302-saveicon">✓</div>
                <div><div class="cv302-savetitle">Saved to your workspace</div>
                <div class="cv302-savecopy">This analysis and its engineering activity are preserved automatically.</div></div>
              </div>
              <div class="cv302-savebadge">Autosave on</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        from src.pages.analysis_detail import render_analysis_detail
        render_analysis_detail(
            current_user=current_user,
            supabase=supabase,
            load_analysis_history=load_analysis_history,
            light_plotly_layout=light_plotly_layout,
            _qp_value=_qp_value,
            workspace_id=active_workspace_id,
            workspace_role=active_workspace_role,
            workspace_members=(
                list_members(supabase, active_workspace_id)[0]
                if active_workspace_id
                else []
            ),
        )
        stop_authenticated_page()

    st.markdown(
        """
        <style>
          .cv130-hero{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#eef5ff);border-radius:24px;padding:21px;margin-bottom:14px;box-shadow:0 16px 42px rgba(37,99,235,.07)}
          .cv130-eyebrow{font-size:9px;font-weight:950;letter-spacing:.09em;text-transform:uppercase;color:#2563eb;margin-bottom:7px}.cv130-title{font-size:27px;font-weight:950;color:#0f172a;letter-spacing:-.04em;margin-bottom:7px}.cv130-copy{font-size:11px;font-weight:720;color:#52647a;line-height:1.6;max-width:920px}
          .cv130-decision-card,.cv130-packet{border:1px solid #dbe3ef;background:#fff;border-radius:20px;padding:16px;margin-bottom:11px;box-shadow:0 12px 30px rgba(15,23,42,.05)}.cv130-decision-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}.cv130-decision-title{font-size:16px;font-weight:950;color:#0f172a;letter-spacing:-.02em}.cv130-packet-title{font-size:23px;font-weight:950;color:#0f172a;letter-spacing:-.035em}.cv130-reason{font-size:10px;font-weight:720;color:#52647a;line-height:1.5;margin-top:5px}
          .cv130-badge{border-radius:999px;padding:7px 10px;font-size:9px;font-weight:950;white-space:nowrap;border:1px solid #bfdbfe;background:#eff6ff;color:#1d4ed8}.cv130-badge.good{border-color:#a7f3d0;background:#ecfdf5;color:#047857}.cv130-badge.warn{border-color:#fde68a;background:#fffbeb;color:#b45309}.cv130-badge.bad{border-color:#fecaca;background:#fef2f2;color:#b91c1c}
          .cv130-meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px}.cv130-meta span{border:1px solid #dbeafe;background:#eff6ff;border-radius:999px;padding:5px 8px;font-size:8px;font-weight:900;color:#1d4ed8}
          .cv130-impact{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;margin:12px 0}.cv130-impact div{border:1px solid #dbeafe;background:#f8fbff;border-radius:14px;padding:11px}.cv130-impact span{display:block;font-size:8px;font-weight:950;text-transform:uppercase;letter-spacing:.07em;color:#64748b;margin-bottom:5px}.cv130-impact strong{font-size:13px;font-weight:950;color:#0f172a}
          .cv131-compact{padding:13px 15px;margin-bottom:7px}.cv131-card-main{min-width:0}.cv131-card-badges{display:flex;gap:7px;align-items:flex-start;flex-wrap:wrap;justify-content:flex-end}.cv131-age{border-radius:999px;padding:6px 9px;font-size:8px;font-weight:950;border:1px solid #dbeafe;background:#eff6ff;color:#1d4ed8;white-space:nowrap}.cv131-age.watch{border-color:#fde68a;background:#fffbeb;color:#a16207}.cv131-age.warn{border-color:#fdba74;background:#fff7ed;color:#c2410c}.cv131-age.bad{border-color:#fecaca;background:#fef2f2;color:#b91c1c}
          .cv131-summary-grid{display:grid;grid-template-columns:1.2fr 1fr 1fr .7fr .8fr;gap:8px;margin-top:10px}.cv131-summary-grid div{border-left:2px solid #dbeafe;padding-left:8px}.cv131-summary-grid span{display:block;font-size:7px;font-weight:950;letter-spacing:.07em;text-transform:uppercase;color:#64748b}.cv131-summary-grid strong{font-size:10px;font-weight:900;color:#0f172a;line-height:1.3}.cv131-progress{height:6px;background:#e2e8f0;border-radius:999px;overflow:hidden;margin-top:10px}.cv131-progress div{height:100%;background:linear-gradient(90deg,#2563eb,#60a5fa);border-radius:999px}.cv131-progress.packet{height:8px;margin-top:14px}.cv131-next{font-size:9px;font-weight:750;color:#52647a;margin-top:6px}.cv131-breakdown{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.cv131-breakdown div{border:1px solid #e2e8f0;border-radius:12px;padding:10px;background:#fff}.cv131-breakdown span{display:block;font-size:8px;font-weight:950;color:#64748b;text-transform:uppercase}.cv131-breakdown strong{font-size:16px;font-weight:950;color:#0f172a}
          @media(max-width:900px){.cv130-decision-head{display:block}.cv130-impact,.cv131-breakdown{grid-template-columns:1fr 1fr}.cv131-summary-grid{grid-template-columns:1fr 1fr}.cv130-badge{display:inline-block;margin-top:10px}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <style>
          .cv123-monitor-hero{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#eef5ff);border-radius:24px;padding:20px;margin-bottom:14px;box-shadow:0 16px 42px rgba(37,99,235,.07)}
          .cv123-monitor-top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.cv123-monitor-eyebrow{font-size:9px;font-weight:950;letter-spacing:.09em;text-transform:uppercase;color:#2563eb;margin-bottom:7px}.cv123-monitor-title{font-size:25px;font-weight:950;color:#0f172a;letter-spacing:-.035em;margin-bottom:6px}.cv123-monitor-copy{font-size:11px;font-weight:720;color:#52647a;line-height:1.55;max-width:900px}
          .cv123-monitor-badge{border:1px solid #bfdbfe;border-radius:999px;padding:7px 10px;font-size:9px;font-weight:950;white-space:nowrap;background:#eff6ff;color:#1d4ed8}.cv123-monitor-badge.good{border-color:#a7f3d0;background:#ecfdf5;color:#047857}.cv123-monitor-badge.warn{border-color:#fde68a;background:#fffbeb;color:#b45309}.cv123-monitor-badge.bad{border-color:#fecaca;background:#fef2f2;color:#b91c1c}
          .cv123-alert-card{border:1px solid #dbe3ef;background:#fff;border-radius:18px;padding:15px;margin-bottom:10px;box-shadow:0 10px 28px rgba(15,23,42,.045)}.cv123-alert-head{display:flex;justify-content:space-between;gap:12px}.cv123-alert-part{font-size:14px;font-weight:950;color:#0f172a}.cv123-alert-type{font-size:9px;font-weight:950;color:#2563eb;text-transform:uppercase;letter-spacing:.07em}.cv123-alert-message{font-size:11px;font-weight:720;color:#475569;line-height:1.5;margin:8px 0}.cv123-alert-meta{display:flex;gap:7px;flex-wrap:wrap}.cv123-alert-pill{border:1px solid #dbeafe;background:#eff6ff;border-radius:999px;padding:5px 8px;font-size:8px;font-weight:900;color:#1d4ed8}.cv123-alert-action{border-top:1px solid #e2e8f0;margin-top:11px;padding-top:11px;font-size:11px;font-weight:780;color:#0f172a}
          @media(max-width:900px){.cv123-monitor-top{display:block}.cv123-monitor-badge{display:inline-block;margin-top:10px}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    if app_mode == "Monitoring":
        monitoring_allowed = is_admin or selected_plan_name in {"Trial", "Professional", "Business", "Enterprise"}
        monitoring_limit = selected_plan.get("monitored_parts_limit")
        if not monitoring_allowed:
            st.markdown(
                """
                <section class="cv123-monitor-hero">
                  <div class="cv123-monitor-top"><div>
                    <div class="cv123-monitor-eyebrow">Monitoring Intelligence Center</div>
                    <div class="cv123-monitor-title">Continuous component monitoring is not included in this plan</div>
                    <div class="cv123-monitor-copy">Upgrade to Professional to monitor up to 2,500 components, receive lifecycle and inventory alerts, and turn supplier changes into engineering actions.</div>
                  </div><span class="cv123-monitor-badge warn">Upgrade required</span></div>
                </section>
                """,
                unsafe_allow_html=True,
            )
            if st.button("View Professional plan", type="primary", key="monitoring_upgrade_plan"):
                navigate_to("Pricing")
            stop_authenticated_page()

        return_analysis_id = _qp_value("return_analysis_id")
        focused_monitor_part = _safe_text(
            _qp_value("mpn") or _qp_value("part"),
            "",
        )
        if return_analysis_id and st.button("← Back to Saved BOM", key="monitoring_back_to_saved_bom", type="secondary"):
            navigate_to("Analysis Details", analysis_id=return_analysis_id)

        def _monitor_query(table_name, columns="*"):
            return _workspace_query(supabase.table(table_name).select(columns)).eq("user_id", current_user["id"])

        try:
            alert_history = _monitor_query("monitor_alerts").order("created_at", desc=True).limit(500).execute()
            alert_df = pd.DataFrame(alert_history.data or [])
        except Exception as exc:
            st.error(f"Monitoring alerts could not be loaded: {exc}")
            alert_df = pd.DataFrame()

        try:
            monitor_history = _monitor_query("part_monitor_history").order("created_at", desc=True).limit(5000).execute()
            monitor_df = pd.DataFrame(monitor_history.data or [])
        except Exception as exc:
            st.error(f"Monitoring history could not be loaded: {exc}")
            monitor_df = pd.DataFrame()

        from src.monitoring_intelligence import build_monitoring_action_center
        monitoring_center = build_monitoring_action_center(alert_df, monitor_df)
        monitored_count = monitoring_center["monitored_components"]
        monitor_limit_label = "Unlimited" if monitoring_limit is None or is_admin else f"{int(monitoring_limit):,}"
        monitor_usage = 0 if monitoring_limit in (None, 0) or is_admin else min(100, round(monitored_count / int(monitoring_limit) * 100))

        cadivor_section_header(
            str(monitoring_center["posture"]),
            eyebrow="Monitoring Intelligence Center",
            description=str(monitoring_center["summary"]),
            icon="radar",
        )

        st.markdown(
            """
            <style>
            .cv320-kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;margin:14px 0 22px}.cv320-kpi{border:1px solid #e2e8f0;background:#fff;border-radius:16px;padding:15px 16px;box-shadow:0 10px 28px rgba(15,23,42,.045);transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}.cv320-kpi:hover{transform:translateY(-2px);border-color:#bfdbfe;box-shadow:0 16px 34px rgba(37,99,235,.09)}.cv320-kpi span{display:block;font-size:10px;font-weight:900;letter-spacing:.06em;text-transform:uppercase;color:#64748b!important;margin-bottom:7px}.cv320-kpi strong{font-size:25px;font-weight:950;color:#0f172a!important}.cv320-kpi small{display:block;font-size:10px;font-weight:700;color:#64748b!important;margin-top:5px}
            .cv320-card{--accent:#2563eb;border:1px solid #dbe3ef;border-left:5px solid var(--accent);background:#fff;border-radius:18px;padding:17px 18px;margin:11px 0;box-shadow:0 10px 28px rgba(15,23,42,.05);transition:transform .18s ease,box-shadow .18s ease}.cv320-card:hover{transform:translateY(-1px);box-shadow:0 16px 36px rgba(15,23,42,.075)}.cv320-card.critical{--accent:#dc2626}.cv320-card.high{--accent:#f97316}.cv320-card.medium{--accent:#eab308}.cv320-card.low{--accent:#16a34a}.cv320-cardhead{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.cv320-part{font-size:18px;font-weight:950;color:#0f172a!important}.cv320-type{font-size:10px;font-weight:950;letter-spacing:.07em;text-transform:uppercase;color:var(--accent)!important;margin-bottom:5px}.cv320-change{font-size:13px;font-weight:700;color:#475569!important;line-height:1.55;margin:10px 0}.cv320-pills{display:flex;flex-wrap:wrap;gap:7px}.cv320-pill{border:1px solid #dbeafe;background:#eff6ff;border-radius:999px;padding:6px 9px;font-size:10px;font-weight:850;color:#1d4ed8!important}.cv320-recommendation{display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:start;border:1px solid #bfdbfe;background:linear-gradient(135deg,#eff6ff,#f8fbff);border-radius:14px;margin-top:13px;padding:13px 14px}.cv320-recicon{width:31px;height:31px;border-radius:10px;background:#dbeafe;color:#1d4ed8!important;display:flex;align-items:center;justify-content:center;font-weight:950}.cv320-rectitle{font-size:10px;font-weight:950;letter-spacing:.06em;text-transform:uppercase;color:#1d4ed8!important}.cv320-reccopy{font-size:12px;font-weight:850;color:#0f172a!important;line-height:1.45;margin-top:3px}.cv320-impact{font-size:10px;font-weight:760;color:#52647a!important;line-height:1.4;margin-top:5px}.cv320-confidence{border-left:1px solid #bfdbfe;padding-left:12px;text-align:right;white-space:nowrap}.cv320-confidence span{display:block;font-size:8px;font-weight:900;text-transform:uppercase;color:#64748b!important}.cv320-confidence strong{font-size:15px;font-weight:950;color:#1d4ed8!important}.cv320-score{border-radius:999px;padding:8px 11px;font-size:10px;font-weight:950;white-space:nowrap}.cv320-score.bad{background:#fef2f2;border:1px solid #fecaca;color:#b91c1c!important}.cv320-score.warn{background:#fffbeb;border:1px solid #fde68a;color:#a16207!important}.cv320-score.good{background:#ecfdf5;border:1px solid #a7f3d0;color:#047857!important}
            .cv320-evidence{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:5px 0 13px}.cv320-evidence div{border:1px solid #e2e8f0;background:#f8fafc;border-radius:12px;padding:10px}.cv320-evidence span{display:block;font-size:8px;font-weight:950;text-transform:uppercase;letter-spacing:.06em;color:#64748b!important}.cv320-evidence strong{display:block;font-size:11px;font-weight:900;color:#0f172a!important;margin-top:4px}.cv320-section-title{font-size:12px;font-weight:950;color:#0f172a!important;margin:4px 0 10px}.cv320-limit{border:1px solid #dbeafe;background:#f8fbff;border-radius:15px;padding:13px 15px;margin:10px 0 18px}.cv320-limitrow{display:flex;justify-content:space-between;font-size:11px;font-weight:850;color:#475569!important;margin-bottom:8px}.cv320-bar{height:8px;border-radius:999px;background:#e2e8f0;overflow:hidden}.cv320-bar i{display:block;height:100%;background:linear-gradient(90deg,#2563eb,#60a5fa);border-radius:999px}.cv321-timeline{position:relative;margin:8px 0 10px;padding-left:22px}.cv321-timeline:before{content:"";position:absolute;left:7px;top:5px;bottom:5px;width:2px;background:#dbeafe}.cv321-event{position:relative;border:1px solid #e2e8f0;background:#fff;border-radius:14px;padding:12px 14px;margin:0 0 10px;box-shadow:0 8px 22px rgba(15,23,42,.04)}.cv321-event:before{content:"";position:absolute;left:-20px;top:17px;width:10px;height:10px;border-radius:50%;background:#2563eb;border:3px solid #eff6ff}.cv321-eventtime{font-size:9px;font-weight:850;color:#64748b!important}.cv321-eventtitle{font-size:13px;font-weight:950;color:#0f172a!important;margin-top:3px}.cv321-eventcopy{font-size:11px;font-weight:700;color:#52647a!important;margin-top:4px;line-height:1.45}
            [data-testid="stExpander"]{border-radius:14px!important;border-color:#dbe3ef!important;background:#fbfdff!important}[data-testid="stExpander"] summary{font-weight:850!important}.stButton>button,.stDownloadButton>button{min-height:42px!important;border-radius:10px!important;font-weight:850!important}
            @media(max-width:1200px){.cv320-kpis{grid-template-columns:repeat(3,1fr)}}@media(max-width:800px){.cv320-kpis{grid-template-columns:repeat(2,1fr)}.cv320-cardhead{display:block}.cv320-score{display:inline-block;margin-top:9px}.cv320-evidence{grid-template-columns:1fr 1fr}.cv320-recommendation{grid-template-columns:auto 1fr}.cv320-confidence{grid-column:2;text-align:left;border-left:0;padding-left:0}}
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div class="cv123-monitor-hero cv123-monitor-hero--compact">
              <span class="cv123-monitor-badge {html.escape(monitoring_center['posture_tone'])}">{monitoring_center['active_alerts']} active {'alert' if monitoring_center['active_alerts'] == 1 else 'alerts'}</span>
            </div>
            <div class="cv320-limit"><div class="cv320-limitrow"><span>{html.escape(str(selected_plan_name))} monitoring usage</span><span>{monitored_count:,} / {monitor_limit_label}</span></div><div class="cv320-bar"><i style="width:{monitor_usage}%"></i></div></div>
            """,
            unsafe_allow_html=True,
        )

        active_queue = monitoring_center.get("active_queue")
        price_alerts = 0
        if isinstance(active_queue, pd.DataFrame) and not active_queue.empty:
            price_alerts = int(
                active_queue["Alert Type"]
                .astype(str)
                .str.contains("price", case=False, regex=True)
                .sum()
            )

        render_kpi_row_safe(
            [
                MetricCard(label="Monitored", value=f"{monitored_count:,}", detail="components", tone="info", icon="radar"),
                MetricCard(label="Critical action", value=str(monitoring_center["immediate_actions"]), detail="priority ≥ 75", tone="danger", icon="octagon-alert"),
                MetricCard(label="Lifecycle", value=str(monitoring_center["lifecycle_alerts"]), detail="active changes", tone="warning", icon="clock-3"),
                MetricCard(label="Inventory", value=str(monitoring_center["inventory_alerts"]), detail="stock alerts", tone="monitoring", icon="boxes"),
                MetricCard(label="Stock", value=f"{monitored_count:,}", detail="tracked components", tone="info", icon="package-search"),
                MetricCard(label="Pricing", value=str(price_alerts), detail="price change alerts", tone="confidence", icon="dollar-sign"),
            ],
            columns=6,
            compact=True,
        )

        def _monitor_display(value, fallback="—"):
            if value is None:
                return fallback
            try:
                if pd.isna(value):
                    return fallback
            except Exception:
                pass
            cleaned = str(value).strip()
            return fallback if not cleaned or cleaned.lower() in {"nan", "none", "null", "nat"} else cleaned

        def _monitor_date(value):
            cleaned = _monitor_display(value, "")
            if not cleaned:
                return None
            try:
                return pd.to_datetime(cleaned).date()
            except Exception:
                return None

        def _monitor_confidence(score):
            return max(65, min(98, int(round(float(score or 0) * 0.92 + 8))))

        queue_tab, components_tab, timeline_tab, export_tab = st.tabs(["Action Queue", "Monitored Components", "Timeline", "Export"])

        with queue_tab:
            queue = monitoring_center["prioritized_alerts"]
            if queue.empty:
                st.success("No monitoring exception requires action. Continue scheduled supplier and lifecycle checks.")
            else:
                f1, f2, f3, f4 = st.columns([1.1, 1.1, 1.1, 1.8])
                severity_filter = f1.selectbox("Severity", ["All", "Critical", "High", "Medium", "Low"], key="m32_severity")
                status_filter = f2.selectbox("Status", ["Active", "All", "Open", "In Review", "Resolved", "Dismissed", "Reopened"], key="m32_status")
                type_filter = f3.selectbox("Change type", ["All", "Lifecycle", "Inventory", "Price", "Supplier"], key="m32_type")
                search_filter = f4.text_input(
                    "Search",
                    value=focused_monitor_part,
                    placeholder="Part number, owner, or alert text",
                    key="m32_search",
                )
                filtered = queue.copy()
                if severity_filter != "All": filtered = filtered[filtered["Severity"].str.lower() == severity_filter.lower()]
                if status_filter == "Active": filtered = filtered[~filtered["Status"].isin(["Resolved", "Dismissed"])]
                elif status_filter != "All": filtered = filtered[filtered["Status"] == status_filter]
                if type_filter != "All":
                    pattern = "stock|inventory" if type_filter == "Inventory" else type_filter.lower()
                    filtered = filtered[filtered["Alert Type"].str.contains(pattern, case=False, regex=True)]
                if search_filter.strip():
                    q = search_filter.strip().lower()
                    filtered = filtered[filtered.astype(str).apply(lambda c: c.str.lower().str.contains(q, regex=False)).any(axis=1)]
                st.caption(f"Showing {len(filtered)} of {len(queue)} monitoring records.")

                for idx, row in filtered.head(50).iterrows():
                    score = int(row["Priority Score"])
                    tone = "bad" if score >= 75 else "warn" if score >= 45 else "good"
                    severity = _monitor_display(row.get("Severity"), "Medium")
                    severity_class = severity.lower() if severity.lower() in {"critical", "high", "medium", "low"} else "medium"
                    part_number = _monitor_display(row.get("Part Number"), "Unknown component")
                    alert_type = _monitor_display(row.get("Alert Type"), "Monitoring change")
                    status = _monitor_display(row.get("Status"), "Open")
                    owner = _monitor_display(row.get("Owner"), "Unassigned")
                    due_label = _monitor_display(row.get("Due Date"), "No due date")
                    change = _monitor_display(row.get("Change"), "Monitoring evidence changed.")
                    recommended_action = _monitor_display(row.get("Recommended Action"), "Review this change and document the engineering response.")
                    expected_impact = _monitor_display(row.get("Expected Impact"), "Confirm whether redesign, sourcing, or qualification action is required.")
                    confidence = _monitor_confidence(score)
                    current_value = _monitor_display(row.get("Current Value", row.get("Current", row.get("New Value", ""))), "Latest evidence available")
                    previous_value = _monitor_display(row.get("Previous Value", row.get("Previous", row.get("Old Value", ""))), "Earlier baseline")
                    supplier = _monitor_display(row.get("Supplier", row.get("Primary Supplier", "")), "Supplier data pending")
                    checked = _monitor_display(row.get("Last Checked", row.get("Created At", row.get("created_at", ""))), "Recently")
                    st.markdown(f"""<section class="cv320-card {severity_class}"><div class="cv320-cardhead"><div><div class="cv320-type">{html.escape(alert_type)}</div><div class="cv320-part">{html.escape(part_number)}</div></div><span class="cv320-score {tone}">Priority {score}/100</span></div><div class="cv320-change">{html.escape(change)}</div><div class="cv320-pills"><span class="cv320-pill">Status: {html.escape(status)}</span><span class="cv320-pill">Owner: {html.escape(owner)}</span><span class="cv320-pill">Due: {html.escape(due_label)}</span><span class="cv320-pill">Severity: {html.escape(severity)}</span></div><div class="cv320-recommendation"><div class="cv320-recicon">i</div><div><div class="cv320-rectitle">Cadivor recommendation</div><div class="cv320-reccopy">{html.escape(recommended_action)}</div><div class="cv320-impact"><b>Why it matters:</b> {html.escape(expected_impact)}</div></div><div class="cv320-confidence"><span>Confidence</span><strong>{confidence}%</strong></div></div></section>""", unsafe_allow_html=True)

                    alert_id = str(row.get("Alert ID", ""))
                    with st.expander("Engineering evidence and workflow", expanded=False):
                        st.markdown(f"""<div class="cv320-section-title">Engineering evidence</div><div class="cv320-evidence"><div><span>Previous state</span><strong>{html.escape(previous_value)}</strong></div><div><span>Current state</span><strong>{html.escape(current_value)}</strong></div><div><span>Supplier</span><strong>{html.escape(supplier)}</strong></div><div><span>Last checked</span><strong>{html.escape(checked)}</strong></div></div><div class="cv320-section-title">Engineering workflow</div>""", unsafe_allow_html=True)
                        w1, w2, w3 = st.columns(3)
                        status_options = ["Open", "In Review", "Resolved", "Dismissed", "Reopened"]
                        priority_options = ["Low", "Normal", "High", "Urgent"]
                        row_status = status if status in status_options else "Open"
                        row_priority = _monitor_display(row.get("Priority"), "Normal")
                        row_priority = row_priority if row_priority in priority_options else "Normal"
                        new_status = w1.selectbox("Status", status_options, index=status_options.index(row_status), key=f"m32_status_{alert_id}_{idx}")
                        new_priority = w2.selectbox("Priority", priority_options, index=priority_options.index(row_priority), key=f"m32_priority_{alert_id}_{idx}")
                        existing_owner = "" if owner in {"Unassigned", "Engineering", "Procurement", "Supply Chain", "Component Engineering", "Engineering & Supply Chain"} else owner
                        new_owner = w3.text_input("Assigned to", value=existing_owner, placeholder="Name or team", key=f"m32_owner_{alert_id}_{idx}")
                        d1, d2 = st.columns([1, 2])
                        due_value = d1.date_input("Due date", value=_monitor_date(row.get("Due Date")), key=f"m32_due_{alert_id}_{idx}")
                        note_value = d2.text_area("Engineering note", value=_monitor_display(row.get("Note"), ""), placeholder="Document rationale, validation evidence, or next step...", key=f"m32_note_{alert_id}_{idx}")
                        a1, a2, a3, a4 = st.columns(4)
                        if a1.button("Save workflow", type="primary", use_container_width=True, key=f"m32_save_{alert_id}_{idx}"):
                            try:
                                payload = {"workflow_status": new_status, "priority": new_priority, "assigned_to": new_owner or None, "due_date": due_value.isoformat() if due_value else None, "review_note": note_value or None, "reviewed_at": datetime.now(timezone.utc).isoformat(), "resolved_at": datetime.now(timezone.utc).isoformat() if new_status == "Resolved" else None}
                                supabase.table("monitor_alerts").update(payload).eq("id", alert_id).eq("user_id", current_user["id"]).execute()
                                try:
                                    supabase.table("monitoring_events").insert({"user_id": current_user["id"], "workspace_id": active_workspace_id or None, "alert_id": alert_id or None, "analysis_id": str(row.get("Analysis ID", "") or "") or None, "part_number": str(row["Part Number"]), "event_type": "Workflow Updated", "event_summary": f"Alert moved to {new_status}; priority {new_priority}.", "previous_value": str(row["Status"]), "current_value": new_status, "metadata": {"assigned_to": new_owner, "due_date": payload["due_date"]}}).execute()
                                except Exception:
                                    pass
                                st.success("Monitoring workflow saved.")
                                st.rerun()
                            except Exception:
                                st.error(
                                    "Cadivor could not save this monitoring workflow. "
                                    "Please try again or contact support if the problem continues."
                                )
                        if a2.button("Find alternative", use_container_width=True, key=f"m32_alt_{alert_id}_{idx}"):
                            navigate_to_alternative_finder(
                                mpn=str(row["Part Number"]),
                                analysis_id=str(row.get("Analysis ID", "") or return_analysis_id or ""),
                                return_analysis_id=str(row.get("Analysis ID", "") or return_analysis_id or ""),
                                source_page="monitoring",
                            )
                        if a3.button("Open decisions", use_container_width=True, key=f"m32_decision_{alert_id}_{idx}"):
                            navigate_to("Engineering Decisions", focus_part=str(row["Part Number"]))
                        a4.download_button("Export evidence", data=pd.DataFrame([row]).to_csv(index=False).encode("utf-8"), file_name=f"{str(row['Part Number']).replace('/', '_')}_monitoring_evidence.csv", mime="text/csv", use_container_width=True, key=f"m32_export_{alert_id}_{idx}")

        with components_tab:
            components = monitoring_center["latest_components"]
            if components.empty:
                st.info("No monitored component snapshots are available yet.")
            else:
                component_search = st.text_input("Search monitored components", placeholder="Part number, supplier, lifecycle, or risk", key="m32_component_search")
                visible = components.copy()
                if component_search.strip():
                    q = component_search.strip().lower()
                    visible = visible[visible.astype(str).apply(lambda c: c.str.lower().str.contains(q, regex=False)).any(axis=1)]
                cadivor_engineering_dataframe(visible)
                if monitoring_limit is not None and not is_admin and monitored_count >= int(monitoring_limit):
                    st.warning(f"Your {selected_plan_name} workspace has reached its {int(monitoring_limit):,}-part monitoring limit. Existing monitoring remains active; upgrade to Business for unlimited monitoring.")

        with timeline_tab:
            try:
                events = _monitor_query("monitoring_events").order("created_at", desc=True).limit(250).execute()
                event_df = pd.DataFrame(events.data or [])
            except Exception:
                event_df = pd.DataFrame()
            timeline_source = event_df.copy()
            if timeline_source.empty:
                timeline_source = alert_df.copy()
                if not timeline_source.empty:
                    timeline_source = timeline_source.rename(columns={"alert_type": "event_type", "alert_message": "event_summary"})
            if timeline_source.empty:
                st.info("No monitoring timeline events are available yet.")
            else:
                st.markdown('<div class="cv321-timeline">', unsafe_allow_html=True)
                for _, event in timeline_source.head(100).iterrows():
                    event_time = _monitor_display(event.get("created_at"), "Recent")
                    try:
                        parsed = pd.to_datetime(event_time)
                        event_time = parsed.strftime("%b %d, %Y · %I:%M %p")
                    except Exception:
                        pass
                    event_part = _monitor_display(event.get("part_number"), "Workspace")
                    event_type = _monitor_display(event.get("event_type"), "Monitoring update")
                    event_summary = _monitor_display(event.get("event_summary"), "Monitoring evidence was updated.")
                    previous = _monitor_display(event.get("previous_value"), "")
                    current = _monitor_display(event.get("current_value"), "")
                    transition = f" · {previous} → {current}" if previous and current else ""
                    event_html = f'<div class="cv321-event"><div class="cv321-eventtime">{html.escape(event_time)}</div><div class="cv321-eventtitle">{html.escape(event_part)} · {html.escape(event_type)}</div><div class="cv321-eventcopy">{html.escape(event_summary + transition)}</div></div>'
                    st.markdown(event_html, unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

        with export_tab:
            queue = monitoring_center["prioritized_alerts"]
            components = monitoring_center["latest_components"]
            e1, e2 = st.columns(2)
            e1.download_button("Download monitoring action queue", data=queue.to_csv(index=False).encode("utf-8"), file_name="cadivor_monitoring_action_queue.csv", mime="text/csv", type="primary", use_container_width=True, key="m32_queue_export")
            e2.download_button("Download monitored component snapshot", data=components.to_csv(index=False).encode("utf-8"), file_name="cadivor_monitored_components.csv", mime="text/csv", use_container_width=True, key="m32_components_export")

        stop_authenticated_page()


    # ---------- Supply Risk Scenario ----------
    if app_mode == "Supply Risk Scenario":
        try:
            scenario_analyses = load_analysis_history(current_user["id"]) or []
        except Exception:
            scenario_analyses = []

        try:
            scenario_parts_response = (
                _workspace_query(supabase.table("analysis_parts").select("*"))
                .eq("user_id", current_user["id"])
                .limit(10000)
                .execute()
            )
            scenario_parts = scenario_parts_response.data or []
        except Exception:
            scenario_parts = []

        st.markdown("### Scenario assumptions")
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            scenario_build_quantity = st.number_input(
                "Planned builds",
                min_value=1,
                max_value=1_000_000,
                value=int(st.session_state.get("scenario_build_quantity", 100)),
                step=10,
                key="scenario_build_quantity",
            )
        with s2:
            stock_reduction_percent = st.slider(
                "Stock reduction",
                min_value=0,
                max_value=100,
                value=int(st.session_state.get("scenario_stock_reduction", 0)),
                step=5,
                key="scenario_stock_reduction",
                help="Models a percentage loss of currently recorded market stock.",
            )
        with s3:
            supplier_loss = st.number_input(
                "Suppliers lost",
                min_value=0,
                max_value=10,
                value=int(st.session_state.get("scenario_supplier_loss", 0)),
                step=1,
                key="scenario_supplier_loss",
            )
        with s4:
            demand_growth_percent = st.slider(
                "Demand growth",
                min_value=0,
                max_value=300,
                value=int(st.session_state.get("scenario_demand_growth", 0)),
                step=10,
                key="scenario_demand_growth",
            )

        include_lifecycle_event = st.checkbox(
            "Model a lifecycle disruption for components already showing moderate or higher risk",
            value=bool(st.session_state.get("scenario_lifecycle_event", False)),
            key="scenario_lifecycle_event",
        )

        from src.supply_risk_scenario import build_supply_scenario, render_supply_scenario
        scenario_intelligence = build_supply_scenario(
            scenario_analyses,
            scenario_parts,
            build_quantity=int(scenario_build_quantity),
            stock_reduction_percent=int(stock_reduction_percent),
            supplier_loss=int(supplier_loss),
            demand_growth_percent=int(demand_growth_percent),
            include_lifecycle_event=bool(include_lifecycle_event),
        )

        render_supply_scenario(
            intelligence=scenario_intelligence,
            internal_nav_button=internal_nav_button,
        )
        stop_authenticated_page()


    # ---------- Cost Optimization ----------
    if app_mode == "Cost Optimization":
        try:
            cost_analyses = load_analysis_history(current_user["id"]) or []
        except Exception:
            cost_analyses = []

        try:
            cost_parts_response = (
                _workspace_query(supabase.table("analysis_parts").select("*"))
                .eq("user_id", current_user["id"])
                .limit(10000)
                .execute()
            )
            cost_parts = cost_parts_response.data or []
        except Exception:
            cost_parts = []

        st.markdown(
            """
            <section class="cv21-hero">
              <div class="cv21-eyebrow">Engineering & Procurement Intelligence</div>
              <div class="cv21-title">Cost Optimization</div>
              <div class="cv21-copy">
                Model production cost using supplier pricing saved during BOM analysis.
                Change the build quantity to see total modeled spend and estimated savings update.
              </div>
            </section>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("### Production scenario")
        build_quantity = st.number_input(
            "Number of builds to model",
            min_value=1,
            max_value=1_000_000,
            value=int(st.session_state.get("cost_build_quantity", 100)),
            step=10,
            key="cost_build_quantity",
            help="Cadivor multiplies recorded BOM quantities and unit prices by this production quantity.",
        )

        from src.cost_optimization import build_cost_optimization, render_cost_optimization
        cost_intelligence = build_cost_optimization(
            cost_analyses,
            cost_parts,
            int(build_quantity),
        )
        render_cost_optimization(
            intelligence=cost_intelligence,
            internal_nav_button=internal_nav_button,
        )
        stop_authenticated_page()


    # ---------- Design Impact Analyzer ----------
    if app_mode == "Design Impact Analyzer":
        try:
            impact_analyses = load_analysis_history(current_user["id"]) or []
        except Exception:
            impact_analyses = []

        try:
            impact_parts_response = (
                _workspace_query(supabase.table("analysis_parts").select("*"))
                .eq("user_id", current_user["id"])
                .limit(10000)
                .execute()
            )
            impact_parts = impact_parts_response.data or []
        except Exception:
            impact_parts = []

        requested_impact_mpn = (
            st.session_state.get("design_impact_mpn")
            or _qp_value("part")
            or _qp_value("mpn")
            or ""
        )

        impact_return_analysis_id = _safe_text(_qp_value("analysis_id", ""), "")
        impact_return_section = _safe_text(_qp_value("return_section", "Components"), "Components")

        from src.design_impact_analyzer import build_design_impact, render_design_impact
        impact_intelligence = build_design_impact(
            impact_analyses,
            impact_parts,
            requested_impact_mpn,
        )
        impact_mpn = impact_intelligence.get("selected_mpn", "")
        impact_monitoring_rows = []
        try:
            impact_monitoring_rows = (
                _workspace_query(supabase.table("monitor_alerts").select("part_number,mpn"))
                .eq("user_id", current_user["id"])
                .limit(1000)
                .execute()
                .data
                or []
            )
        except Exception:
            pass
        has_impact_monitoring = any(
            _safe_text(row.get("part_number") or row.get("mpn"), "").upper() == str(impact_mpn).upper()
            for row in impact_monitoring_rows
        )
        impact_decision_rows = []
        try:
            impact_decision_rows = (
                _workspace_query(supabase.table("engineering_decisions").select("part_number"))
                .eq("user_id", current_user["id"])
                .eq("scope_key", active_workspace_id or "personal")
                .limit(1000)
                .execute()
                .data
                or []
            )
        except Exception:
            pass
        has_impact_decision = any(
            _safe_text(row.get("part_number"), "").upper() == str(impact_mpn).upper()
            for row in impact_decision_rows
        )
        render_design_impact(
            intelligence=impact_intelligence,
            internal_nav_button=internal_nav_button,
            return_analysis_id=impact_return_analysis_id,
            return_section=impact_return_section,
            has_monitoring=has_impact_monitoring,
            has_decision=has_impact_decision,
        )
        stop_authenticated_page()


    # ---------- Portfolio Intelligence ----------
    if app_mode == "Portfolio Intelligence":
        try:
            portfolio_analyses = load_analysis_history(current_user["id"]) or []
        except Exception:
            portfolio_analyses = []

        try:
            portfolio_parts_response = (
                _workspace_query(supabase.table("analysis_parts").select("*"))
                .eq("user_id", current_user["id"])
                .limit(10000)
                .execute()
            )
            portfolio_parts = portfolio_parts_response.data or []
        except Exception:
            portfolio_parts = []

        try:
            portfolio_alert_response = (
                _workspace_query(supabase.table("monitor_alerts").select("*"))
                .eq("user_id", current_user["id"])
                .order("created_at", desc=True)
                .limit(500)
                .execute()
            )
            portfolio_alerts = portfolio_alert_response.data or []
        except Exception:
            portfolio_alerts = []

        from src.portfolio_intelligence import build_portfolio_intelligence, render_portfolio_intelligence
        portfolio_intelligence = build_portfolio_intelligence(
            portfolio_analyses,
            portfolio_parts,
            portfolio_alerts,
        )
        render_portfolio_intelligence(
            intelligence=portfolio_intelligence,
            internal_nav_button=internal_nav_button,
        )
        stop_authenticated_page()


    # ---------- Procurement Advisor ----------
    if app_mode == "Procurement Advisor":
        try:
            pa_analyses = load_analysis_history(current_user["id"]) or []
            pa_parts_response = (
                _workspace_query(supabase.table("analysis_parts").select("*"))
                .eq("user_id", current_user["id"])
                .limit(5000)
                .execute()
            )
            pa_parts = pa_parts_response.data or []
        except Exception:
            pa_analyses, pa_parts = [], []

        advisor = build_procurement_advisor(
            analyses=pa_analyses,
            parts=pa_parts,
            alerts=[],
        )
        st.markdown('<div class="cv64-page-shell">', unsafe_allow_html=True)
        cadivor_section_header(
            "Procurement Advisor",
            eyebrow="Sourcing & Purchasing",
            description=advisor["summary"],
            icon="shopping-cart",
        )

        render_kpi_row_safe(
            [
                MetricCard(label="Action Needed", value=str(advisor["urgent_count"]), tone="danger", icon="shopping-cart"),
                MetricCard(label="Monitor", value=str(advisor["monitor_count"]), tone="monitoring", icon="radar"),
                MetricCard(label="Need Second Source", value=str(advisor["second_source_count"]), tone="warning", icon="git-branch"),
                MetricCard(label="Replacement Needed", value=str(advisor["replace_count"]), tone="info", icon="arrow-right-left"),
            ],
            columns=4,
        )

        priority_tab, details_tab = st.tabs(
            ["Action Needed", "All Components"]
        )
        with priority_tab:
            urgent_rows = [
                row for row in advisor["recommendations"]
                if row["Priority Score"] >= 75
            ][:10]
            if not urgent_rows:
                st.success("No immediate purchasing action is required.")
            else:
                st.caption(
                    f"Showing {len(urgent_rows)} component(s) with a priority score of 75 or higher."
                )
            for index, row in enumerate(urgent_rows):
                st.markdown(
                    f"""
                    <section class="cv151-card">
                      <div class="cv151-card-title">{html.escape(row['Part Number'])}</div>
                      <div class="cv151-card-copy">
                        <b>Recommended action: {html.escape(row['Recommendation'])}</b><br>
                        {html.escape(row['Next Step'])}
                      </div>
                      <div class="cv151-meta">
                        <span>Priority {row['Priority Score']}/100</span>
                        <span>Stock {row['Available Stock']:,}</span>
                        <span>{row['Supplier Sources']} supplier(s)</span>
                      </div>
                    </section>
                    """,
                    unsafe_allow_html=True,
                )
                cols = st.columns(2)
                with cols[0]:
                    internal_nav_button(
                        "Find Alternative",
                        "Alternative Finder",
                        key=f"pa_alt_{index}",
                        use_container_width=True,
                        original_part=row["Part Number"],
                        source_page="procurement_advisor",
                    )
                with cols[1]:
                    internal_nav_button(
                        "Open Monitoring",
                        "Monitoring",
                        key=f"pa_monitor_{index}",
                        use_container_width=True,
                        mpn=row["Part Number"],
                    )

        with details_tab:
            if advisor["recommendation_df"].empty:
                st.info("No component purchasing data is available.")
            else:
                cadivor_engineering_dataframe(
                    advisor["recommendation_df"],
                    column_config={
                        "Risk Level": st.column_config.TextColumn(width="small"),
                        "Recommended Action": st.column_config.TextColumn(width="medium"),
                    },
                )
                cadivor_button_wrap("secondary")
                st.download_button(
                    "Download Procurement Details",
                    advisor["recommendation_df"].to_csv(index=False).encode("utf-8"),
                    file_name="cadivor_procurement_details.csv",
                    mime="text/csv",
                    key="pa_export",
                )
                cadivor_button_wrap_end()

        st.markdown("</div>", unsafe_allow_html=True)
        stop_authenticated_page()


    # ---------- Engineering Decision Center ----------
    if app_mode == "Engineering Decisions":
        try:
            decision_alert_response = (
                _workspace_query(
                    supabase.table("monitor_alerts").select("*")
                )
                .eq("user_id", current_user["id"])
                .order("created_at", desc=True)
                .limit(150)
                .execute()
            )
            decision_alert_df = pd.DataFrame(decision_alert_response.data or [])
        except Exception:
            decision_alert_df = pd.DataFrame()

        try:
            decision_analyses = load_analysis_history(current_user["id"]) or []
        except Exception:
            decision_analyses = []

        decision_scope_key = active_workspace_id or "personal"
        decision_cache_key = (
            f"engineering_decision_state_{current_user['id']}_{decision_scope_key}"
        )

        if decision_cache_key not in st.session_state:
            persistent_decision_state, decision_load_error = load_decision_state(
                supabase,
                user_id=current_user["id"],
                workspace_id=active_workspace_id or None,
            )
            st.session_state[decision_cache_key] = persistent_decision_state
            st.session_state[
                f"{decision_cache_key}_load_error"
            ] = decision_load_error

        decision_state = st.session_state[decision_cache_key]

        decision_center = build_decision_center(
            alert_df=decision_alert_df,
            analyses=decision_analyses,
            saved_state=decision_state,
        )
        all_decisions = decision_center["decisions"]

        focus_decision_id = _qp_value("decision_id")
        focus_part = _qp_value("focus_part")
        selected_decision = None

        if focus_decision_id:
            selected_decision = next(
                (
                    decision
                    for decision in all_decisions
                    if decision["decision_id"] == focus_decision_id
                ),
                None,
            )
        elif focus_part:
            selected_decision = next(
                (
                    decision
                    for decision in all_decisions
                    if str(decision["part_number"]).upper() == str(focus_part).upper()
                ),
                None,
            )

        st.markdown('<div class="cv64-page-shell">', unsafe_allow_html=True)
        cadivor_section_header(
            "Turn component intelligence into approved engineering action",
            eyebrow="Cadivor Engineering Decision Center",
            description=(
                "Review prioritized decisions, assign ownership, simulate expected impact, "
                "document engineering notes, and move work from open review to production readiness."
            ),
            icon="clipboard-check",
        )

        decision_load_error = st.session_state.get(
            f"{decision_cache_key}_load_error"
        )
        if decision_load_error:
            st.warning(
                "Persistent decision storage is not available yet. "
                "Run the Milestone 13.2 SQL, then refresh this page."
            )
        else:
            st.caption(
                "Decision workflow, notes, and history are saved to your Cadivor account."
            )

        if selected_decision:
            if st.button(
                "← Back to Engineering Decisions",
                key="decision_packet_back",
                type="secondary",
            ):
                navigate_to("Engineering Decisions")

            st.markdown(
                packet_header_html(selected_decision),
                unsafe_allow_html=True,
            )

            summary_tab, evidence_tab, notes_tab, history_tab = st.tabs(
                ["Decision Summary", "Evidence", "Engineering Notes", "Decision History"]
            )

            decision_id = selected_decision["decision_id"]
            state_record = decision_state.setdefault(
                decision_id,
                {
                    "status": (
                        "New"
                        if selected_decision["status"] == "Open"
                        else selected_decision["status"]
                    ),
                    "owner": selected_decision["assigned_owner"],
                    "notes": selected_decision.get("notes", []),
                    "history": [
                        {
                            "event": "Decision created",
                            "time": selected_decision["detected_at"],
                        }
                    ],
                },
            )

            with summary_tab:
                render_kpi_row_safe(
                    [
                        MetricCard(label="Component / BOM", value=str(selected_decision["part_number"]), tone="info", icon="package"),
                        MetricCard(label="Priority", value=f"{selected_decision['priority_score']}/100", tone="warning", icon="triangle-alert"),
                        MetricCard(label="Confidence", value=f"{selected_decision['confidence']}%", tone="confidence", icon="gauge"),
                        MetricCard(label="Estimated Effort", value=f"{selected_decision['estimated_effort_hours']} hrs", tone="monitoring", icon="clock-3"),
                    ],
                    columns=4,
                )

                st.markdown("### Cadivor Recommendation")
                st.info(selected_decision["recommended_action"])
                st.caption(selected_decision["expected_impact"])

                st.markdown("### Decision Priority Matrix")
                priority_breakdown = selected_decision.get("priority_breakdown", {})
                st.markdown(
                    """
                    <div class="cv131-breakdown">
                    """
                    + "".join(
                        f"<div><span>{html.escape(str(label))}</span><strong>{int(value)}</strong></div>"
                        for label, value in priority_breakdown.items()
                    )
                    + "</div>",
                    unsafe_allow_html=True,
                )

                st.markdown("### AI Confidence")
                confidence_cols = st.columns([1, 3])
                confidence_cols[0].metric(
                    "Decision Confidence",
                    f"{selected_decision['confidence']}%",
                )
                with confidence_cols[1]:
                    for reason in selected_decision.get("confidence_reasons", []):
                        st.markdown(f"✓ {reason}")

                impact = selected_decision
                st.markdown(
                    f"""
                    <div class="cv130-impact">
                      <div><span>Current Health</span><strong>{impact['current_health']}/100</strong></div>
                      <div><span>Projected Health</span><strong>{impact['projected_health']}/100</strong></div>
                      <div><span>Health Improvement</span><strong>+{impact['health_gain']}</strong></div>
                      <div><span>Supply Risk Reduction</span><strong>-{impact['supply_risk_reduction']}</strong></div>
                      <div><span>Lifecycle Issues Removed</span><strong>{impact['lifecycle_exposure_reduction']}</strong></div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                workflow_cols = st.columns(3)
                with workflow_cols[0]:
                    current_workflow_status = state_record.get("status", "New")
                    if current_workflow_status == "Open":
                        current_workflow_status = "New"
                    elif current_workflow_status == "Awaiting Approval":
                        current_workflow_status = "Manager Approval"
                    elif current_workflow_status in ("Approved", "Production Ready"):
                        current_workflow_status = "Production Approved"
                    status_index = (
                        STATUSES.index(current_workflow_status)
                        if current_workflow_status in STATUSES
                        else 0
                    )
                    new_status = st.selectbox(
                        "Decision status",
                        STATUSES,
                        index=status_index,
                        key=f"decision_status_{decision_id}",
                    )
                with workflow_cols[1]:
                    new_owner = st.text_input(
                        "Assigned owner",
                        value=state_record.get("owner", selected_decision["owner"]),
                        key=f"decision_owner_{decision_id}",
                    )
                with workflow_cols[2]:
                    st.text_input(
                        "Target date",
                        value=selected_decision["due_date"],
                        key=f"decision_due_{decision_id}",
                        disabled=True,
                    )

                if st.button(
                    "Save Decision Workflow",
                    key=f"save_decision_{decision_id}",
                    type="primary",
                ):
                    previous_status = state_record.get("status", "New")
                    saved_owner = (
                        new_owner.strip()
                        or selected_decision["owner"]
                    )
                    save_error = save_decision_workflow(
                        supabase,
                        user_id=current_user["id"],
                        workspace_id=active_workspace_id or None,
                        decision=selected_decision,
                        status=new_status,
                        assigned_owner=saved_owner,
                        due_date=selected_decision.get("due_date"),
                        actor_name=(
                            profile_for_shell.get("full_name")
                            or shell_name
                        ),
                        previous_status=previous_status,
                    )

                    if save_error:
                        st.error(
                            "The decision could not be saved. "
                            "Confirm the Milestone 13.2 SQL was applied."
                        )
                    else:
                        refreshed_state, refresh_error = load_decision_state(
                            supabase,
                            user_id=current_user["id"],
                            workspace_id=active_workspace_id or None,
                        )
                        if refresh_error:
                            state_record["status"] = new_status
                            state_record["owner"] = saved_owner
                        else:
                            st.session_state[decision_cache_key] = refreshed_state
                        st.success("Decision workflow saved.")
                        st.rerun()

                navigation_cols = st.columns(4)
                with navigation_cols[0]:
                    internal_nav_button(
                        "Find Alternative",
                        "Alternative Finder",
                        key=f"decision_find_alt_{decision_id}",
                        use_container_width=True,
                        original_part=selected_decision["part_number"],
                        analysis_id=str(selected_decision.get("analysis_id") or ""),
                        source_page="engineering_decisions",
                    )
                with navigation_cols[1]:
                    internal_nav_button(
                        "Open Monitoring",
                        "Monitoring",
                        key=f"decision_monitor_{decision_id}",
                        use_container_width=True,
                    )
                with navigation_cols[2]:
                    internal_nav_button(
                        "Generate Report",
                        "Reports",
                        key=f"decision_report_{decision_id}",
                        use_container_width=True,
                    )
                with navigation_cols[3]:
                    if selected_decision.get("analysis_id"):
                        internal_nav_button(
                            "Open Saved BOM",
                            "Analysis Details",
                            key=f"decision_analysis_{decision_id}",
                            use_container_width=True,
                            analysis_id=selected_decision["analysis_id"],
                        )
                    else:
                        st.caption("No saved BOM is linked to this decision.")

            with evidence_tab:
                st.markdown("### Evidence used by Cadivor")
                for evidence in selected_decision.get("evidence", []):
                    st.markdown(f"- {evidence}")
                st.markdown("### Decision context")
                context_df = pd.DataFrame(
                    [
                        {
                            "Field": "Source",
                            "Value": selected_decision["source"],
                        },
                        {
                            "Field": "Decision Type",
                            "Value": selected_decision["decision_type"],
                        },
                        {
                            "Field": "Supporting Team",
                            "Value": selected_decision["supporting_team"],
                        },
                        {
                            "Field": "Estimated Cost Impact",
                            "Value": selected_decision["estimated_cost_impact"],
                        },
                    ]
                )
                cadivor_engineering_dataframe(context_df)

            with notes_tab:
                note = st.text_area(
                    "Add an engineering note",
                    placeholder="Record validation findings, supplier feedback, approval conditions, or next steps.",
                    key=f"decision_note_{decision_id}",
                )
                if st.button(
                    "Add Note",
                    key=f"decision_add_note_{decision_id}",
                    type="primary",
                ):
                    if not note.strip():
                        st.warning("Enter a note before saving.")
                    else:
                        note_author = (
                            profile_for_shell.get("full_name")
                            or shell_name
                        )
                        note_error = add_decision_note(
                            supabase,
                            user_id=current_user["id"],
                            workspace_id=active_workspace_id or None,
                            decision={
                                **selected_decision,
                                "status": state_record.get("status", "New"),
                                "assigned_owner": state_record.get(
                                    "owner",
                                    selected_decision["owner"],
                                ),
                            },
                            author_name=note_author,
                            note_text=note.strip(),
                        )

                        if note_error:
                            st.error(
                                "The note could not be saved. "
                                "Confirm the Milestone 13.2 SQL was applied."
                            )
                        else:
                            refreshed_state, refresh_error = load_decision_state(
                                supabase,
                                user_id=current_user["id"],
                                workspace_id=active_workspace_id or None,
                            )
                            if not refresh_error:
                                st.session_state[
                                    decision_cache_key
                                ] = refreshed_state
                            st.success("Engineering note saved.")
                            st.rerun()

                notes = state_record.get("notes", [])
                if not notes:
                    st.info("No engineering notes have been added yet.")
                else:
                    for item in reversed(notes):
                        with st.container(border=True):
                            st.markdown(f"**{item.get('author', 'Engineer')}**")
                            st.caption(item.get("time", ""))
                            st.write(item.get("text", ""))

            with history_tab:
                history = state_record.get("history", [])
                if not history:
                    st.info("No decision history is available.")
                else:
                    history_df = pd.DataFrame(history).rename(
                        columns={"event": "Event", "time": "Time"}
                    )
                    cadivor_table(
                        history_df.iloc[::-1],
                        caption="Decision history",
                    )

        else:
            rejected_count = sum(
                1 for decision in all_decisions if str(decision.get("status")) == "Rejected"
            )
            cadivor_metric_row(
                [
                    MetricCard(label="Pending", value=str(decision_center["open_count"]), tone="info", icon="clipboard-check"),
                    MetricCard(label="Critical", value=str(decision_center["critical_count"]), tone="danger", icon="triangle-alert"),
                    MetricCard(label="Rejected", value=str(rejected_count), tone="danger", icon="circle-x"),
                    MetricCard(label="Approved", value=str(decision_center["production_ready_count"]), tone="success", icon="badge-check"),
                    MetricCard(label="Engineering Hours", value=f"{decision_center['estimated_hours']} hrs", tone="monitoring", icon="clock-3"),
                    MetricCard(label="Average Age", value=f"{decision_center['average_age_days']} days", tone="confidence", icon="history"),
                ],
                columns=3,
            )

            refresh_decision_col, persistence_scope_col = st.columns([1, 3])
            with refresh_decision_col:
                cadivor_button_wrap("secondary")
                if st.button(
                    "Refresh Decisions",
                    key="refresh_persistent_decisions",
                    use_container_width=True,
                ):
                    st.session_state.pop(decision_cache_key, None)
                    st.session_state.pop(
                        f"{decision_cache_key}_load_error",
                        None,
                    )
                    st.rerun()
                cadivor_button_wrap_end()
            with persistence_scope_col:
                st.caption(
                    f"Persistent scope: {active_workspace_name or 'Personal workspace'}"
                )

            queue_tab, workload_tab, analytics_tab, archive_tab = st.tabs(
                [
                    "Needs Review",
                    "Team Workload",
                    "Decision Analytics",
                    "Completed",
                ]
            )

            with queue_tab:
                filter_cols = st.columns(3)
                with filter_cols[0]:
                    priority_filter = st.selectbox(
                        "Priority",
                        ["All", "Critical", "High", "Medium", "Routine"],
                        key="decision_priority_filter",
                    )
                with filter_cols[1]:
                    status_filter = st.selectbox(
                        "Status",
                        ["All"] + STATUSES,
                        key="decision_status_filter",
                    )
                with filter_cols[2]:
                    search_decisions = st.text_input(
                        "Search decisions",
                        placeholder="Component, project, owner, or action",
                        key="decision_search",
                    )

                visible = all_decisions
                if priority_filter != "All":
                    visible = [
                        decision
                        for decision in visible
                        if decision["priority"] == priority_filter
                    ]
                if status_filter != "All":
                    visible = [
                        decision
                        for decision in visible
                        if decision["status"] == status_filter
                    ]
                if search_decisions.strip():
                    query = search_decisions.strip().lower()
                    visible = [
                        decision
                        for decision in visible
                        if query
                        in " ".join(
                            [
                                str(decision["part_number"]),
                                str(decision["title"]),
                                str(decision["assigned_owner"]),
                                str(decision["reason"]),
                            ]
                        ).lower()
                    ]

                st.caption(f"Showing {len(visible)} of {len(all_decisions)} engineering decision(s).")

                if not visible:
                    st.info("No engineering decisions match the selected filters.")
                else:
                    for decision in visible[:40]:
                        st.markdown(
                            decision_card_html(decision),
                            unsafe_allow_html=True,
                        )
                        render_decision_card_actions(
                            decision,
                            navigate_to=navigate_to,
                            internal_nav_button=internal_nav_button,
                            key_prefix=f"queue_{decision['decision_id']}",
                        )

            with workload_tab:
                st.markdown("### Team Workload")
                active = [
                    decision
                    for decision in all_decisions
                    if decision["status"] not in ("Closed", "Rejected")
                ]
                if not active:
                    st.success("No open engineering workload remains.")
                else:
                    workload_rows = []
                    owners = sorted(set(decision["assigned_owner"] for decision in active))
                    for owner in owners:
                        owner_decisions = [
                            decision for decision in active if decision["assigned_owner"] == owner
                        ]
                        workload_rows.append(
                            {
                                "Owner": owner,
                                "Open Decisions": len(owner_decisions),
                                "Critical": sum(
                                    1 for decision in owner_decisions
                                    if decision["priority_score"] >= 85
                                ),
                                "Estimated Hours": sum(
                                    decision["estimated_effort_hours"]
                                    for decision in owner_decisions
                                ),
                                "Average Confidence": round(
                                    sum(decision["confidence"] for decision in owner_decisions)
                                    / len(owner_decisions)
                                ),
                            }
                        )
                    cadivor_table(
                        pd.DataFrame(workload_rows),
                        caption="Team workload by owner",
                        numeric_columns=["Open Decisions", "Critical", "Estimated Hours", "Average Confidence"],
                        align={
                            "Open Decisions": "right",
                            "Critical": "right",
                            "Estimated Hours": "right",
                            "Average Confidence": "right",
                        },
                    )

            with analytics_tab:
                cadivor_section_header(
                    "Decision Analytics",
                    description="Portfolio impact from open and closed engineering decisions.",
                    icon="chart-no-axes-combined",
                )
                cadivor_metric_row(
                    [
                        MetricCard(
                            label="Projected Health Gain",
                            value=f"+{decision_center['projected_health_gain']}",
                            tone="success",
                            icon="gauge",
                        ),
                        MetricCard(
                            label="Supply Risk Reduction",
                            value=f"-{decision_center['projected_risk_reduction']}",
                            tone="monitoring",
                            icon="radar",
                        ),
                        MetricCard(
                            label="Closed / Rejected",
                            value=str(decision_center["closed_count"]),
                            tone="neutral",
                            icon="circle-x",
                        ),
                        MetricCard(
                            label="Average Open Age",
                            value=f"{decision_center['average_age_days']} days",
                            tone="warning",
                            icon="clock",
                        ),
                    ],
                )

                if all_decisions:
                    status_counts = (
                        pd.DataFrame(all_decisions)["status"]
                        .value_counts()
                        .rename_axis("Workflow Stage")
                        .reset_index(name="Decisions")
                    )
                    owner_hours = (
                        pd.DataFrame(
                            [
                                {
                                    "Owner": decision["assigned_owner"],
                                    "Estimated Hours": decision["estimated_effort_hours"],
                                    "Priority Score": decision["priority_score"],
                                }
                                for decision in all_decisions
                                if decision["status"] not in ("Closed", "Rejected")
                            ]
                        )
                        .groupby("Owner", as_index=False)
                        .agg(
                            {
                                "Estimated Hours": "sum",
                                "Priority Score": "mean",
                            }
                        )
                        .rename(columns={"Priority Score": "Average Priority"})
                    )
                    analytics_left, analytics_right = st.columns(2)
                    with analytics_left:
                        st.markdown("#### Decisions by Workflow Stage")
                        cadivor_table(
                            status_counts,
                            badge_columns=["Workflow Stage"],
                            numeric_columns=["Decisions"],
                            align={"Decisions": "right"},
                        )
                    with analytics_right:
                        st.markdown("#### Open Workload Impact")
                        cadivor_table(
                            owner_hours,
                            numeric_columns=["Estimated Hours", "Average Priority"],
                            align={"Estimated Hours": "right", "Average Priority": "right"},
                        )

            with archive_tab:
                st.markdown("### Searchable Decision Archive")
                archive_search = st.text_input(
                    "Search archived decisions",
                    placeholder="Project, component, owner, type, or outcome",
                    key="decision_archive_search",
                )
                archived = [
                    decision
                    for decision in all_decisions
                    if decision["status"] in ("Closed", "Rejected", "Production Approved")
                ]
                if archive_search.strip():
                    archive_query = archive_search.strip().lower()
                    archived = [
                        decision
                        for decision in archived
                        if archive_query
                        in " ".join(
                            [
                                str(decision["title"]),
                                str(decision["part_number"]),
                                str(decision["assigned_owner"]),
                                str(decision["decision_type"]),
                                str(decision["status"]),
                            ]
                        ).lower()
                    ]

                if not archived:
                    st.info("No archived or production-approved decisions match the search.")
                else:
                    archive_df = pd.DataFrame(
                        [
                            {
                                "Updated": decision["updated_at"],
                                "Project / Component": decision["part_number"],
                                "Decision": decision["title"],
                                "Owner": decision["assigned_owner"],
                                "Decision Type": decision["decision_type"],
                                "Outcome": decision["status"],
                                "Confidence": f"{decision['confidence']}%",
                            }
                            for decision in archived
                        ]
                    )
                    cadivor_table(
                        archive_df,
                        caption="Archived and production-approved decisions",
                        monospace_columns=["Project / Component"],
                        badge_columns=["Outcome"],
                        align={"Confidence": "right"},
                    )
                    st.download_button(
                        "Export Decision Archive CSV",
                        data=archive_df.to_csv(index=False).encode("utf-8"),
                        file_name="cadivor_decision_archive.csv",
                        mime="text/csv",
                        key="decision_archive_csv",
                        type="primary",
                    )

        st.markdown("</div>", unsafe_allow_html=True)


    def _mark_first_report_complete() -> None:
        """Persist the first-report onboarding step as soon as a download is used."""
        if not onboarding_user_id:
            return
        updated, error = update_onboarding_progress(
            supabase,
            onboarding_user_id,
            {"first_report_completed": True, "welcome_seen": True},
        )
        if updated and not error:
            st.session_state["onboarding_report_completed"] = True


    # ---------- Reports ----------
    if app_mode == "Reports":
        # Milestone 5.5 — Functional Reports Center
        try:
            report_records = load_analysis_history(current_user["id"]) or []
        except Exception:
            report_records = []

        def _report_int(value, default=0):
            try:
                if value is None or (isinstance(value, float) and pd.isna(value)):
                    return default
                return int(float(value))
            except Exception:
                return default

        def _report_float(value, default=0.0):
            try:
                if value is None or (isinstance(value, float) and pd.isna(value)):
                    return default
                return float(value)
            except Exception:
                return default

        def _report_value(row, *keys, default=None):
            for key in keys:
                value = row.get(key)
                if value is not None and str(value).strip() not in ("", "nan", "None"):
                    return value
            return default

        def _analysis_label(row):
            project = _report_value(row, "project_name", "name", default="Saved BOM")
            created = str(_report_value(row, "created_at", "date", default=""))
            created_date = created.split("T")[0] if "T" in created else created[:10]
            return f"{project} — {created_date or 'undated'}"

        def _load_report_parts(analysis_id):
            if not analysis_id:
                return pd.DataFrame()
            try:
                response = (
                    _workspace_query(
                        supabase.table("analysis_parts")
                        .select("*")
                    )
                    .eq("analysis_id", analysis_id)
                    .eq("user_id", current_user["id"])
                    .execute()
                )
                return pd.DataFrame(response.data or [])
            except Exception:
                try:
                    response = (
                        _workspace_query(
                            supabase.table("analysis_parts")
                            .select("*")
                        )
                        .eq("analysis_id", analysis_id)
                        .execute()
                    )
                    return pd.DataFrame(response.data or [])
                except Exception:
                    return pd.DataFrame()

        def _build_executive_pdf(analysis_row, parts_df, decision_brief=None):
            from io import BytesIO
            from pathlib import Path
            import reportlab
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib import colors
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from src.engineering_decision_engine import (
                format_decision_brief_for_report,
            )
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=letter,
                rightMargin=42,
                leftMargin=42,
                topMargin=42,
                bottomMargin=42,
            )
            styles = getSampleStyleSheet()
            # Embed ReportLab's Vera fonts. The built-in PDF fonts can render
            # with visibly spread glyphs in common viewers, while an embedded
            # TrueType font keeps export typography consistent and legible.
            reportlab_fonts = Path(reportlab.__file__).resolve().parent / "fonts"
            if "CadivorVera" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("CadivorVera", str(reportlab_fonts / "Vera.ttf")))
            if "CadivorVera-Bold" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("CadivorVera-Bold", str(reportlab_fonts / "VeraBd.ttf")))
            styles.add(ParagraphStyle(
                name="CadivorReportTitle", parent=styles["Title"],
                fontName="CadivorVera-Bold", fontSize=22, leading=27,
                alignment=0, textColor=colors.HexColor("#0F172A"), spaceAfter=0,
            ))
            styles.add(ParagraphStyle(
                name="CadivorReportHeading", parent=styles["Heading2"],
                fontName="CadivorVera-Bold", fontSize=14, leading=18,
                alignment=0, textColor=colors.HexColor("#0F172A"), spaceBefore=0, spaceAfter=6,
            ))
            styles.add(ParagraphStyle(
                name="CadivorReportBody", parent=styles["BodyText"],
                fontName="CadivorVera", fontSize=10, leading=14,
                alignment=0, textColor=colors.HexColor("#334155"), spaceAfter=0,
            ))
            story = []

            project = _report_value(analysis_row, "project_name", "name", default="Saved BOM")
            filename = _report_value(analysis_row, "filename", "uploaded_file", "file_name", default="—")
            health = _report_int(_report_value(analysis_row, "health_score", default=0))
            high_risk = _report_int(_report_value(analysis_row, "high_risk_count", "high_risk_parts", default=0))
            medium_risk = _report_int(_report_value(analysis_row, "medium_risk_count", "medium_risk_parts", default=0))
            total_parts = _report_int(_report_value(analysis_row, "total_parts", "part_count", "parts_count", default=len(parts_df)))

            story.append(Paragraph("Cadivor Executive BOM Report", styles["CadivorReportTitle"]))
            story.append(Spacer(1, 12))
            story.append(Paragraph(f"Project: {html.escape(str(project))}", styles["CadivorReportHeading"]))
            story.append(Paragraph(f"Source file: {html.escape(str(filename))}", styles["CadivorReportBody"]))
            story.append(Spacer(1, 12))

            summary_table = Table(
                [
                    ["Health Score", "Total Parts", "High Risk", "Medium Risk"],
                    [str(health), str(total_parts), str(high_risk), str(medium_risk)],
                ],
                colWidths=[115, 115, 115, 115],
            )
            summary_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF6FF")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                        ("FONTNAME", (0, 0), (-1, 0), "CadivorVera-Bold"),
                        ("FONTNAME", (0, 1), (-1, 1), "CadivorVera-Bold"),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ]
                )
            )
            story.append(summary_table)
            story.append(Spacer(1, 16))

            if decision_brief:
                report_sections = format_decision_brief_for_report(decision_brief)
                story.append(Paragraph("Executive Engineering Summary", styles["CadivorReportHeading"]))
                story.append(Paragraph(report_sections["executive_summary"], styles["CadivorReportBody"]))
                story.append(Spacer(1, 12))
                story.append(Paragraph("Production Readiness", styles["CadivorReportHeading"]))
                story.append(Paragraph(report_sections["production_readiness"], styles["CadivorReportBody"]))
                story.append(Spacer(1, 12))
                story.append(Paragraph("Critical Findings", styles["CadivorReportHeading"]))
                story.append(Paragraph(report_sections["critical_findings"].replace("\n", "<br/>"), styles["CadivorReportBody"]))
                story.append(Spacer(1, 12))
                story.append(Paragraph("Recommended Actions", styles["CadivorReportHeading"]))
                story.append(Paragraph(report_sections["recommended_actions"].replace("\n", "<br/>"), styles["CadivorReportBody"]))
                story.append(Spacer(1, 12))
                story.append(Paragraph("Business Impact", styles["CadivorReportHeading"]))
                story.append(Paragraph(report_sections["business_impact"].replace("\n", "<br/>"), styles["CadivorReportBody"]))
                story.append(Spacer(1, 12))
                story.append(Paragraph("Engineering Confidence", styles["CadivorReportHeading"]))
                story.append(Paragraph(report_sections["confidence"], styles["CadivorReportBody"]))
                story.append(Spacer(1, 12))
                story.append(Paragraph("Supporting Evidence", styles["CadivorReportHeading"]))
                story.append(Paragraph(report_sections["supporting_evidence"].replace("\n", "<br/>"), styles["CadivorReportBody"]))
                story.append(Spacer(1, 16))
            else:
                if health >= 80:
                    recommendation = "Portfolio health is strong. Continue lifecycle and supplier monitoring."
                elif health >= 60:
                    recommendation = "Review elevated-risk parts and validate supplier coverage before release."
                else:
                    recommendation = "Immediate engineering and sourcing review is recommended before production release."

                story.append(Paragraph("Recommended action", styles["CadivorReportHeading"]))
                story.append(Paragraph(recommendation, styles["CadivorReportBody"]))
                story.append(Spacer(1, 16))

            story.append(Paragraph("Priority component review", styles["CadivorReportHeading"]))
            if parts_df.empty:
                story.append(Paragraph("No component-level records were available for this saved analysis.", styles["CadivorReportBody"]))
            else:
                work = parts_df.copy()
                risk_col = next((c for c in ["risk_level", "Risk Level", "risk"] if c in work.columns), None)
                score_col = next((c for c in ["risk_score", "Risk Score"] if c in work.columns), None)

                if score_col:
                    work["_sort_score"] = pd.to_numeric(work[score_col], errors="coerce").fillna(0)
                    work = work.sort_values("_sort_score", ascending=False)
                elif risk_col:
                    rank = {"High": 3, "Medium": 2, "Low": 1}
                    work["_risk_rank"] = work[risk_col].astype(str).map(rank).fillna(0)
                    work = work.sort_values("_risk_rank", ascending=False)

                def first_col(candidates):
                    return next((c for c in candidates if c in work.columns), None)

                mpn_col = first_col(["mpn", "MPN", "part_number", "manufacturer_part_number"])
                manufacturer_col = first_col(["manufacturer", "Manufacturer"])
                lifecycle_col = first_col(["lifecycle_status", "Lifecycle Status"])
                stock_col = first_col(["stock_available", "stock", "Stock Available", "total_market_stock"])

                table_data = [["Part", "Manufacturer", "Risk", "Lifecycle", "Stock"]]
                for _, row in work.head(12).iterrows():
                    table_data.append(
                        [
                            str(row.get(mpn_col, "—")) if mpn_col else "—",
                            str(row.get(manufacturer_col, "—")) if manufacturer_col else "—",
                            str(row.get(risk_col, "—")) if risk_col else "—",
                            str(row.get(lifecycle_col, "—")) if lifecycle_col else "—",
                            str(row.get(stock_col, "—")) if stock_col else "—",
                        ]
                    )

                parts_table = Table(table_data, repeatRows=1, colWidths=[105, 110, 65, 110, 70])
                parts_table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("FONTNAME", (0, 0), (-1, 0), "CadivorVera-Bold"),
                            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                            ("FONTSIZE", (0, 0), (-1, -1), 8),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ]
                    )
                )
                story.append(parts_table)

            doc.build(story)
            buffer.seek(0)
            return buffer.getvalue()

        total_reports = len(report_records)
        total_parts = sum(
            _report_int(
                _report_value(
                    row,
                    "total_parts",
                    "part_count",
                    "parts_count",
                    default=0,
                )
            )
            for row in report_records
        )
        total_high_risk = sum(
            _report_int(
                _report_value(
                    row,
                    "high_risk_count",
                    "high_risk_parts",
                    default=0,
                )
            )
            for row in report_records
        )
        health_values = [
            _report_int(_report_value(row, "health_score", default=0))
            for row in report_records
            if _report_value(row, "health_score", default=None) is not None
        ]
        average_health = (
            round(sum(health_values) / len(health_values))
            if health_values
            else 0
        )

        st.markdown(
            """
            <style id="cadivor-reports-professional-v9a">
            .cv-r9-hero{
                border:1px solid #BFDBFE;border-radius:26px;padding:30px 32px;
                background:
                    radial-gradient(circle at 88% 8%,rgba(37,99,235,.13),transparent 34%),
                    linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 62%,#EEF5FF 100%);
                box-shadow:0 22px 58px rgba(15,23,42,.07);margin-bottom:18px;
            }
            .cv-r9-eyebrow{
                display:inline-flex;align-items:center;gap:7px;padding:7px 11px;
                border:1px solid #BFDBFE;border-radius:999px;background:#EFF6FF;
                color:#2563EB!important;font-size:10px;font-weight:950;
                letter-spacing:.12em;text-transform:uppercase;margin-bottom:15px;
            }
            .cv-r9-title{
                color:#0F172A!important;font-size:38px;line-height:1.05;font-weight:980;
                letter-spacing:-.045em;margin:0 0 11px;
            }
            .cv-r9-copy{
                color:#52647A!important;font-size:15px;line-height:1.62;font-weight:680;
                max-width:880px;margin:0;
            }
            .cv-r9-metrics{
                display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
                gap:12px;margin:18px 0 24px;
            }
            .cv-r9-metric{
                border:1px solid #E2E8F0;background:#FFFFFF;border-radius:19px;padding:17px;
                box-shadow:0 14px 34px rgba(15,23,42,.05);
            }
            .cv-r9-metric span{
                display:block;color:#64748B!important;font-size:9px;font-weight:950;
                letter-spacing:.09em;text-transform:uppercase;margin-bottom:7px;
            }
            .cv-r9-metric strong{
                display:block;color:#0F172A!important;font-size:27px;font-weight:980;
                letter-spacing:-.03em;
            }
            .cv-r9-metric small{
                display:block;color:#64748B!important;font-size:10px;font-weight:760;
                margin-top:6px;line-height:1.4;
            }
            .cv-r9-section{
                color:#0F172A!important;font-size:22px;font-weight:980;
                letter-spacing:-.03em;margin:25px 0 5px;
            }
            .cv-r9-sub{
                color:#64748B!important;font-size:12px;font-weight:740;margin-bottom:12px;
            }
            .cv-r9-template-grid{
                display:grid;
                gap:16px;
                align-items:stretch;
                width:100%;
                margin:0 0 16px;
            }
            .cv-r9-template-grid.three{
                grid-template-columns:repeat(3,minmax(0,1fr));
            }
            .cv-r9-template-grid.two{
                grid-template-columns:repeat(2,minmax(0,1fr));
            }
            .cv-r9-template{
                box-sizing:border-box;
                width:100%;
                min-width:0;
                min-height:195px;
                height:100%;
                border:1px solid #E2E8F0;
                background:#FFFFFF;
                border-radius:21px;
                padding:19px;
                box-shadow:0 15px 38px rgba(15,23,42,.05);
            }
            .cv-r9-template-icon{
                width:42px;height:42px;border-radius:13px;display:flex;
                align-items:center;justify-content:center;background:#EFF6FF;
                border:1px solid #BFDBFE;color:#2563EB!important;font-size:19px;
                font-weight:950;margin-bottom:13px;
            }
            .cv-r9-template h4{
                margin:0 0 7px;color:#0F172A!important;font-size:15px;font-weight:970;
            }
            .cv-r9-template p{
                margin:0;color:#52647A!important;font-size:11px;font-weight:720;
                line-height:1.52;min-height:50px;
            }
            .cv-r9-formats{display:flex;gap:6px;flex-wrap:wrap;margin-top:13px}
            .cv-r9-format{
                display:inline-flex;border:1px solid #DBEAFE;background:#EFF6FF;
                color:#1D4ED8!important;border-radius:999px;padding:5px 8px;
                font-size:9px;font-weight:950;
            }
            .cv-r9-selected{
                border:1px solid #BFDBFE;background:linear-gradient(135deg,#FFFFFF,#EFF6FF);
                border-radius:22px;padding:20px;box-shadow:0 17px 42px rgba(37,99,235,.07);
                margin:12px 0 15px;
            }
            .cv-r9-selected-grid{
                display:grid;grid-template-columns:1.35fr repeat(4,minmax(0,1fr));
                gap:10px;
            }
            .cv-r9-selected-cell{
                border:1px solid #DCE5F1;background:rgba(255,255,255,.9);
                border-radius:14px;padding:12px;min-width:0;
            }
            .cv-r9-selected-cell span{
                display:block;color:#64748B!important;font-size:8px;font-weight:950;
                letter-spacing:.09em;text-transform:uppercase;margin-bottom:6px;
            }
            .cv-r9-selected-cell strong{
                display:block;color:#0F172A!important;font-size:13px;font-weight:950;
                overflow-wrap:anywhere;
            }
            .cv-r9-preview-card{
                border:1px solid #E2E8F0;background:#FFFFFF;border-radius:19px;
                padding:17px;box-shadow:0 14px 34px rgba(15,23,42,.04);margin-bottom:12px;
            }
            .cv-r9-preview-title{
                color:#0F172A!important;font-size:14px;font-weight:970;margin-bottom:7px;
            }
            .cv-r9-preview-copy{
                color:#52647A!important;font-size:11px;font-weight:720;line-height:1.55;
            }
            .cv-r9-history{
                border:1px solid #E2E8F0;background:#FFFFFF;border-radius:19px;padding:16px;
            }
            .cv-r9-empty{
                border:1px dashed #CBD5E1;background:#F8FAFC;border-radius:18px;
                padding:22px;text-align:center;color:#64748B!important;font-size:12px;
                font-weight:760;
            }
            @media(max-width:1050px){
                .cv-r9-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}
                .cv-r9-selected-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
                .cv-r9-template-grid.three{grid-template-columns:repeat(2,minmax(0,1fr))}
            }
            @media(max-width:760px){
                .cv-r9-template-grid.three,
                .cv-r9-template-grid.two{grid-template-columns:1fr}
            }
            @media(max-width:650px){
                .cv-r9-metrics,.cv-r9-selected-grid{grid-template-columns:1fr}
                .cv-r9-title{font-size:31px}
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        cadivor_section_header(
            "Turn BOM intelligence into decisions.",
            eyebrow="Cadivor Report Library",
            description=(
                "Select a saved BOM, preview the engineering story, and generate the right "
                "deliverable for leadership, design review, sourcing, lifecycle management, "
                "or replacement planning."
            ),
            icon="file-text",
        )

        render_kpi_row_safe(
            [
                MetricCard(
                    label="Reports",
                    value=str(total_reports),
                    detail="Saved analyses ready to export",
                    tone="info",
                    icon="file-text",
                ),
                MetricCard(
                    label="Formats",
                    value="PDF + CSV",
                    detail="Available for every report package",
                    tone="success",
                    icon="download",
                ),
                MetricCard(
                    label="Exports",
                    value=str(total_reports),
                    detail="Report packages available",
                    tone="monitoring",
                    icon="file-spreadsheet",
                ),
            ],
            columns=3,
        )
        st.markdown(
            """
            <style>
              .cv-resource-tour{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:8px 0 18px}
              .cv-resource-tour-card{border:1px solid #D9E3F2;border-radius:18px;background:#FFF;padding:16px;box-shadow:0 12px 30px rgba(15,35,70,.06)}
              .cv-resource-tour-card h4{margin:0 0 6px;color:#11284B;font-size:16px}.cv-resource-tour-card p{margin:0;color:#58708F;font-size:13px;line-height:1.55;min-height:40px}
              .cv-resource-demo{position:relative;overflow:hidden;margin-top:14px;height:138px;border:1px solid #DCE7F5;border-radius:13px;background:linear-gradient(145deg,#F7FAFF,#EFF5FF);padding:12px}
              .cv-resource-demo-top{height:13px;width:58%;border-radius:5px;background:#C8D8F2}.cv-resource-demo-row{height:14px;margin-top:10px;border-radius:5px;background:#E1EAF7}.cv-resource-demo-row.active{background:#D8E8FF;animation:cv-resource-focus 6s ease-in-out infinite}.cv-resource-demo-row.short{width:62%}.cv-resource-demo-risk{position:absolute;right:12px;bottom:12px;border-radius:999px;background:#FFF0F0;color:#C2414A;font-weight:800;font-size:10px;padding:6px 8px;animation:cv-resource-pulse 2.2s ease-in-out infinite}.cv-resource-demo-check{position:absolute;right:12px;bottom:12px;border-radius:999px;background:#E9FBF2;color:#16734D;font-weight:800;font-size:10px;padding:6px 8px;animation:cv-resource-rise 6s ease-in-out infinite}.cv-resource-demo-line{position:absolute;left:12px;right:12px;bottom:12px;height:5px;border-radius:999px;background:#D7E4F7;overflow:hidden}.cv-resource-demo-line:after{content:'';display:block;width:42%;height:100%;background:#2865EB;border-radius:999px;animation:cv-resource-progress 6s ease-in-out infinite}.cv-resource-demo-node{display:inline-flex;align-items:center;justify-content:center;width:23px;height:23px;border-radius:8px;background:#2865EB;color:#FFF;font-size:11px;font-weight:900;margin:12px 6px 0 0;animation:cv-resource-rise 6s ease-in-out infinite}.cv-resource-demo-node:nth-child(2){animation-delay:.45s}.cv-resource-demo-node:nth-child(3){animation-delay:.9s}
              @keyframes cv-resource-focus{0%,22%{transform:translateX(0);background:#E1EAF7}38%,67%{transform:translateX(4px);background:#CFE3FF;box-shadow:0 0 0 2px rgba(40,101,235,.14)}100%{transform:translateX(0);background:#E1EAF7}}@keyframes cv-resource-progress{0%{transform:translateX(-115%)}42%,70%{transform:translateX(72%)}100%{transform:translateX(225%)}}@keyframes cv-resource-pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.06);box-shadow:0 0 0 5px rgba(194,65,74,.08)}}@keyframes cv-resource-rise{0%,20%{opacity:.35;transform:translateY(6px)}35%,78%{opacity:1;transform:translateY(0)}100%{opacity:.35;transform:translateY(6px)}}
              @media(max-width:900px){.cv-resource-tour{grid-template-columns:1fr}}@media(prefers-reduced-motion:reduce){.cv-resource-tour *{animation:none!important}}
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="cv-r9-section">Professional report library</div>'
            '<div class="cv-r9-sub">Portfolio context above shows the scale and overall risk behind the available report packages.</div>',
            unsafe_allow_html=True,
        )

        first_template_data = [
            (
                "Executive BOM Summary",
                "Leadership-ready health, priority risks, decision brief, and recommended actions.",
                "▤",
                ["PDF", "CSV"],
            ),
            (
                "Engineering Risk Review",
                "Component-level lifecycle, stock, supplier diversity, lead-time, and risk evidence.",
                "△",
                ["PDF", "CSV"],
            ),
            (
                "Procurement & Sourcing",
                "Supplier concentration, market stock, cost exposure, and secondary-source priorities.",
                "⇄",
                ["PDF", "CSV"],
            ),
        ]

        first_template_cards = []
        for title, copy, icon, formats in first_template_data:
            format_html = "".join(
                f'<span class="cv-r9-format">{fmt}</span>'
                for fmt in formats
            )
            first_template_cards.append(
                (
                    f'<div class="cv-r9-template">'
                    f'<div class="cv-r9-template-icon">{icon}</div>'
                    f'<h4>{title}</h4>'
                    f'<p>{copy}</p>'
                    f'<div class="cv-r9-formats">{format_html}</div>'
                    f'</div>'
                )
            )

        st.markdown(
            '<div class="cv-r9-template-grid three">'
            + "".join(first_template_cards)
            + "</div>",
            unsafe_allow_html=True,
        )

        second_template_data = [
            (
                "Lifecycle Exposure Report",
                "Lifecycle states, obsolete or replacement-suggested components, and alert-oriented review data.",
                "◷",
                ["PDF", "CSV"],
            ),
            (
                "Alternative Replacement Report",
                "Components requiring alternatives, candidate availability, and saved replacement-readiness fields.",
                "↔",
                ["PDF", "CSV"],
            ),
        ]

        second_template_cards = []
        for title, copy, icon, formats in second_template_data:
            format_html = "".join(
                f'<span class="cv-r9-format">{fmt}</span>'
                for fmt in formats
            )
            second_template_cards.append(
                (
                    f'<div class="cv-r9-template">'
                    f'<div class="cv-r9-template-icon">{icon}</div>'
                    f'<h4>{title}</h4>'
                    f'<p>{copy}</p>'
                    f'<div class="cv-r9-formats">{format_html}</div>'
                    f'</div>'
                )
            )

        st.markdown(
            '<div class="cv-r9-template-grid two">'
            + "".join(second_template_cards)
            + "</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="cv-r9-section">Build a report package</div>'
            '<div class="cv-r9-sub">Search for a saved BOM, confirm the selected engineering record, preview the content, and download the required files.</div>',
            unsafe_allow_html=True,
        )

        if report_records:
            labels = [_analysis_label(row) for row in report_records]

            incoming_report_analysis_id = str(
                _qp_value("analysis_id", "")
                or st.session_state.get("cadivor_active_analysis_id", "")
                or ""
            ).strip()
            report_route_token = (
                f"reports::{incoming_report_analysis_id}"
                if incoming_report_analysis_id
                else ""
            )

            if (
                incoming_report_analysis_id
                and st.session_state.get("reports_route_token") != report_route_token
            ):
                matching_label = None
                for row, label in zip(report_records, labels):
                    row_id = str(
                        _report_value(
                            row,
                            "id",
                            "analysis_id",
                            default="",
                        )
                        or ""
                    ).strip()
                    if row_id == incoming_report_analysis_id:
                        matching_label = label
                        break

                if matching_label:
                    st.session_state["reports_selected_analysis"] = matching_label
                    st.session_state["reports_route_token"] = report_route_token

            search_col, select_col = st.columns([0.34, 0.66], gap="medium")
            with search_col:
                report_search = st.text_input(
                    "Search saved analyses",
                    placeholder="Project or source filename",
                    key="reports_analysis_search",
                )

            filtered_labels = labels
            if report_search.strip():
                needle = report_search.strip().lower()
                filtered_labels = [
                    label
                    for label in labels
                    if needle in label.lower()
                ]

            if not filtered_labels:
                st.warning("No saved analyses match that search.")
                filtered_labels = labels

            current_selected = st.session_state.get("reports_selected_analysis")
            if current_selected not in filtered_labels:
                st.session_state["reports_selected_analysis"] = filtered_labels[0]

            with select_col:
                selected_label = st.selectbox(
                    "Saved BOM analysis",
                    filtered_labels,
                    key="reports_selected_analysis",
                )

            selected_index = labels.index(selected_label)
            selected_analysis = report_records[selected_index]
            selected_analysis_id = _report_value(
                selected_analysis,
                "id",
                "analysis_id",
                default=None,
            )
            selected_parts_df = _load_report_parts(selected_analysis_id)

            project_name = str(
                _report_value(
                    selected_analysis,
                    "project_name",
                    "name",
                    default="Saved BOM",
                )
            )
            source_file = str(
                _report_value(
                    selected_analysis,
                    "filename",
                    "uploaded_file",
                    "file_name",
                    default="—",
                )
            )
            health_score = _report_int(
                _report_value(selected_analysis, "health_score", default=0)
            )
            high_risk = _report_int(
                _report_value(
                    selected_analysis,
                    "high_risk_count",
                    "high_risk_parts",
                    default=0,
                )
            )
            medium_risk = _report_int(
                _report_value(
                    selected_analysis,
                    "medium_risk_count",
                    "medium_risk_parts",
                    default=0,
                )
            )
            part_count = _report_int(
                _report_value(
                    selected_analysis,
                    "total_parts",
                    "part_count",
                    "parts_count",
                    default=len(selected_parts_df),
                )
            )
            created_at = str(
                _report_value(
                    selected_analysis,
                    "created_at",
                    "updated_at",
                    "date",
                    default="",
                )
            )
            created_date = (
                created_at.split("T")[0]
                if "T" in created_at
                else created_at[:10]
            ) or "—"

            safe_project = (
                re.sub(r"[^A-Za-z0-9_-]+", "_", project_name).strip("_")
                or "saved_bom"
            )

            st.markdown(
                f"""
                <div class="cv-r9-selected">
                  <div class="cv-r9-selected-grid">
                    <div class="cv-r9-selected-cell">
                      <span>Selected BOM</span>
                      <strong>{html.escape(project_name)}</strong>
                    </div>
                    <div class="cv-r9-selected-cell">
                      <span>Health</span>
                      <strong>{health_score}/100</strong>
                    </div>
                    <div class="cv-r9-selected-cell">
                      <span>Parts</span>
                      <strong>{part_count}</strong>
                    </div>
                    <div class="cv-r9-selected-cell">
                      <span>High / Medium Risk</span>
                      <strong>{high_risk} / {medium_risk}</strong>
                    </div>
                    <div class="cv-r9-selected-cell">
                      <span>Saved</span>
                      <strong>{html.escape(created_date)}</strong>
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            def _customer_report_table(
                frame: pd.DataFrame,
                preferred_columns: list[str] | None = None,
            ) -> pd.DataFrame:
                """Return a customer-facing report preview without database fields."""
                if frame is None or frame.empty:
                    return pd.DataFrame()

                cleaned = frame.copy()

                hidden_columns = {
                    "id",
                    "user_id",
                    "analysis_id",
                    "workspace_id",
                    "organization_id",
                    "created_at",
                    "updated_at",
                    "raw_data",
                    "metadata",
                }
                cleaned = cleaned[
                    [
                        column
                        for column in cleaned.columns
                        if str(column).strip().lower() not in hidden_columns
                    ]
                ]

                if preferred_columns:
                    existing = [
                        column
                        for column in preferred_columns
                        if column in cleaned.columns
                    ]
                    if existing:
                        cleaned = cleaned[existing]

                human_labels = {
                    "project": "Project",
                    "project_name": "Project",
                    "source_file": "Source File",
                    "filename": "Source File",
                    "mpn": "Manufacturer Part Number",
                    "MPN": "Manufacturer Part Number",
                    "part_number": "Part Number",
                    "manufacturer": "Manufacturer",
                    "risk_score": "Risk Score",
                    "risk_level": "Risk Level",
                    "risk_reasons": "Risk Explanation",
                    "lifecycle_status": "Lifecycle Status",
                    "stock_available": "Available Stock",
                    "stock": "Available Stock",
                    "supplier_count": "Supplier Sources",
                    "unit_price": "Unit Price",
                    "lead_time": "Lead Time",
                    "lead_time_weeks": "Lead Time (Weeks)",
                    "has_alternates": "Alternatives Available",
                    "alternate_count": "Alternative Count",
                    "alternate_part_numbers": "Alternative Part Numbers",
                    "health_score": "Health Score",
                    "high_risk_parts": "High-Risk Components",
                    "medium_risk_parts": "Medium-Risk Components",
                    "message": "Status",
                }

                cleaned = cleaned.rename(
                    columns={
                        column: human_labels.get(
                            column,
                            str(column).replace("_", " ").strip().title(),
                        )
                        for column in cleaned.columns
                    }
                )
                return cleaned

            def _first_existing(frame: pd.DataFrame, names: list[str], default=None):
                for name in names:
                    if name in frame.columns:
                        return frame[name]
                return pd.Series([default] * len(frame), index=frame.index)

            def _risk_action(row: pd.Series) -> str:
                lifecycle = str(row.get("lifecycle_status", "")).lower()
                stock = float(pd.to_numeric(row.get("stock_available", 0), errors="coerce") or 0)
                suppliers = float(pd.to_numeric(row.get("supplier_count", 0), errors="coerce") or 0)
                score = float(pd.to_numeric(row.get("risk_score", 0), errors="coerce") or 0)
                if any(term in lifecycle for term in ("obsolete", "eol", "replacement", "nrnd", "not recommended")):
                    return "Qualify a replacement before production"
                if stock <= 0:
                    return "Resolve supply gap or approve substitute"
                if suppliers <= 1:
                    return "Approve a second source"
                if score >= 60:
                    return "Complete engineering review before release"
                if score >= 30:
                    return "Review during current design revision"
                return "Continue controlled monitoring"

            def _procurement_status(row: pd.Series) -> str:
                stock = float(pd.to_numeric(row.get("stock_available", 0), errors="coerce") or 0)
                suppliers = float(pd.to_numeric(row.get("supplier_count", 0), errors="coerce") or 0)
                lead = float(pd.to_numeric(row.get("lead_time_weeks", 0), errors="coerce") or 0)
                if stock <= 0:
                    return "Immediate sourcing action"
                if suppliers <= 1:
                    return "Single-source exposure"
                if lead >= 16:
                    return "Long lead time"
                if stock < 500:
                    return "Low stock coverage"
                return "Purchasing ready"

            def _lifecycle_priority(status: str) -> str:
                value = str(status or "").lower()
                if any(term in value for term in ("obsolete", "eol", "end of life")):
                    return "Immediate replacement"
                if any(term in value for term in ("replacement", "nrnd", "not recommended")):
                    return "Qualification required"
                if value in ("active", "new at mouser", "new"):
                    return "Routine monitoring"
                return "Status verification required"

            lifecycle_columns = [
                column
                for column in [
                    "mpn",
                    "MPN",
                    "part_number",
                    "manufacturer",
                    "lifecycle_status",
                    "Lifecycle Status",
                    "risk_level",
                    "risk_score",
                    "stock_available",
                    "supplier_count",
                ]
                if column in selected_parts_df.columns
            ]
            lifecycle_df = (
                selected_parts_df[lifecycle_columns].copy()
                if lifecycle_columns
                else selected_parts_df.copy()
            )

            alternative_columns = [
                column
                for column in [
                    "mpn",
                    "MPN",
                    "part_number",
                    "manufacturer",
                    "risk_level",
                    "risk_score",
                    "has_alternates",
                    "alternate_count",
                    "alternate_part_numbers",
                    "lifecycle_status",
                    "stock_available",
                ]
                if column in selected_parts_df.columns
            ]
            alternative_df = (
                selected_parts_df[alternative_columns].copy()
                if alternative_columns
                else selected_parts_df.copy()
            )

            sourcing_candidates = [
                "mpn",
                "part_number",
                "manufacturer",
                "lifecycle_status",
                "stock_available",
                "stock",
                "supplier_count",
                "unit_price",
                "risk_level",
                "risk_score",
                "has_alternates",
                "alternate_count",
            ]
            if selected_parts_df.empty:
                engineering_df = pd.DataFrame()
                sourcing_df = pd.DataFrame()
                lifecycle_df = pd.DataFrame()
                alternative_df = pd.DataFrame()
            else:
                role_source = selected_parts_df.copy()

                role_source["mpn"] = _first_existing(
                    role_source,
                    ["mpn", "MPN", "part_number"],
                    "Unknown",
                )
                role_source["manufacturer"] = _first_existing(
                    role_source,
                    ["manufacturer", "Manufacturer"],
                    "Unknown",
                )
                role_source["risk_level"] = _first_existing(
                    role_source,
                    ["risk_level", "Risk Level"],
                    "Unknown",
                )
                role_source["risk_score"] = pd.to_numeric(
                    _first_existing(role_source, ["risk_score", "Risk Score"], 0),
                    errors="coerce",
                ).fillna(0)
                role_source["risk_reasons"] = _first_existing(
                    role_source,
                    ["risk_reasons", "Risk Explanation"],
                    "No specific exception recorded",
                )
                role_source["lifecycle_status"] = _first_existing(
                    role_source,
                    ["lifecycle_status", "Lifecycle Status"],
                    "Unknown",
                )
                role_source["stock_available"] = pd.to_numeric(
                    _first_existing(
                        role_source,
                        ["stock_available", "Stock Available", "stock"],
                        0,
                    ),
                    errors="coerce",
                ).fillna(0)
                role_source["supplier_count"] = pd.to_numeric(
                    _first_existing(
                        role_source,
                        ["supplier_count", "Supplier Count"],
                        0,
                    ),
                    errors="coerce",
                ).fillna(0)
                role_source["primary_supplier"] = _first_existing(
                    role_source,
                    ["supplier", "primary_supplier", "best_source", "Supplier"],
                    "Not recorded",
                )
                role_source["unit_price"] = pd.to_numeric(
                    _first_existing(
                        role_source,
                        ["unit_price", "Unit Price"],
                        0,
                    ),
                    errors="coerce",
                ).fillna(0)
                role_source["lead_time_weeks"] = pd.to_numeric(
                    _first_existing(
                        role_source,
                        ["lead_time_weeks", "Lead Time Weeks", "lead_time"],
                        0,
                    ),
                    errors="coerce",
                ).fillna(0)

                role_source["Engineering Priority"] = role_source["risk_score"].apply(
                    lambda value: (
                        "Immediate"
                        if value >= 75
                        else "High"
                        if value >= 50
                        else "Moderate"
                        if value >= 25
                        else "Routine"
                    )
                )
                role_source["Recommended Action"] = role_source.apply(
                    _risk_action,
                    axis=1,
                )

                engineering_df = pd.DataFrame(
                    {
                        "Manufacturer Part Number": role_source["mpn"],
                        "Manufacturer": role_source["manufacturer"],
                        "Risk Level": role_source["risk_level"],
                        "Risk Score": role_source["risk_score"],
                        "Risk Explanation": role_source["risk_reasons"],
                        "Engineering Priority": role_source["Engineering Priority"],
                        "Recommended Action": role_source["Recommended Action"],
                        "_sort_risk_score": role_source["risk_score"],
                    }
                ).sort_values(
                    by="_sort_risk_score",
                    ascending=False,
                    kind="stable",
                ).drop(columns=["_sort_risk_score"])

                role_source["Procurement Status"] = role_source.apply(
                    _procurement_status,
                    axis=1,
                )
                sourcing_df = pd.DataFrame(
                    {
                        "Manufacturer Part Number": role_source["mpn"],
                        "Manufacturer": role_source["manufacturer"],
                        "Primary Supplier": role_source["primary_supplier"],
                        "Available Stock": role_source["stock_available"],
                        "Unit Price": role_source["unit_price"],
                        "Lead Time (Weeks)": role_source["lead_time_weeks"],
                        "Supplier Sources": role_source["supplier_count"],
                        "Procurement Status": role_source["Procurement Status"],
                        "_sort_stock": role_source["stock_available"],
                        "_sort_sources": role_source["supplier_count"],
                    }
                ).sort_values(
                    by=["_sort_stock", "_sort_sources"],
                    ascending=[True, True],
                    kind="stable",
                ).drop(columns=["_sort_stock", "_sort_sources"])

                role_source["Future Availability"] = role_source[
                    "lifecycle_status"
                ].apply(
                    lambda status: (
                        "At risk"
                        if any(
                            term in str(status).lower()
                            for term in (
                                "obsolete",
                                "eol",
                                "end of life",
                                "replacement",
                                "nrnd",
                                "not recommended",
                            )
                        )
                        else "Expected to continue"
                        if str(status).lower() == "active"
                        else "Needs verification"
                    )
                )
                role_source["Replacement Readiness"] = role_source[
                    "lifecycle_status"
                ].apply(
                    lambda status: (
                        "Replacement required"
                        if any(
                            term in str(status).lower()
                            for term in ("obsolete", "eol", "end of life")
                        )
                        else "Successor qualification advised"
                        if any(
                            term in str(status).lower()
                            for term in ("replacement", "nrnd", "not recommended")
                        )
                        else "No immediate replacement"
                    )
                )
                role_source["Review Priority"] = role_source[
                    "lifecycle_status"
                ].apply(_lifecycle_priority)

                lifecycle_rank = {
                    "Immediate replacement": 0,
                    "Qualification required": 1,
                    "Status verification required": 2,
                    "Routine monitoring": 3,
                }
                role_source["_lifecycle_rank"] = role_source[
                    "Review Priority"
                ].map(lifecycle_rank).fillna(4)

                lifecycle_df = pd.DataFrame(
                    {
                        "Manufacturer Part Number": role_source["mpn"],
                        "Manufacturer": role_source["manufacturer"],
                        "Lifecycle Status": role_source["lifecycle_status"],
                        "Future Availability": role_source["Future Availability"],
                        "Replacement Readiness": role_source["Replacement Readiness"],
                        "Review Priority": role_source["Review Priority"],
                        "_sort_lifecycle_rank": role_source["_lifecycle_rank"],
                    }
                ).sort_values(
                    by="_sort_lifecycle_rank",
                    ascending=True,
                    kind="stable",
                ).drop(columns=["_sort_lifecycle_rank"])

                has_alternates = _first_existing(
                    role_source,
                    ["has_alternates", "alternatives_available"],
                    False,
                )
                alternate_count = pd.to_numeric(
                    _first_existing(
                        role_source,
                        ["alternate_count", "alternatives_count"],
                        0,
                    ),
                    errors="coerce",
                ).fillna(0)
                alternate_parts = _first_existing(
                    role_source,
                    [
                        "alternate_part_numbers",
                        "recommended_alternative",
                        "alternative_part",
                    ],
                    "Not yet qualified",
                )

                role_source["Replacement Status"] = [
                    (
                        "Candidates available"
                        if bool(available) or count > 0
                        else "Alternative search required"
                    )
                    for available, count in zip(has_alternates, alternate_count)
                ]
                role_source["Recommended Replacement"] = alternate_parts
                role_source["Alternative Count"] = alternate_count.astype(int)
                role_source["Next Engineering Step"] = role_source[
                    "Replacement Status"
                ].apply(
                    lambda status: (
                        "Review compatibility and approve candidate"
                        if status == "Candidates available"
                        else "Run Alternative Finder"
                    )
                )

                alternative_df = pd.DataFrame(
                    {
                        "Original Component": role_source["mpn"],
                        "Manufacturer": role_source["manufacturer"],
                        "Current Lifecycle": role_source["lifecycle_status"],
                        "Replacement Status": role_source["Replacement Status"],
                        "Recommended Replacement": role_source["Recommended Replacement"],
                        "Alternative Count": role_source["Alternative Count"],
                        "Next Engineering Step": role_source["Next Engineering Step"],
                        "_sort_alternative_count": role_source["Alternative Count"],
                        "_sort_risk_score": role_source["risk_score"],
                    }
                ).sort_values(
                    by=["_sort_alternative_count", "_sort_risk_score"],
                    ascending=[False, False],
                    kind="stable",
                )

                alternative_df = alternative_df.drop(
                    columns=["_sort_alternative_count", "_sort_risk_score"]
                )

            from src.engineering_decision_engine import (
                build_engineering_decision_brief,
                get_cached_decision_brief,
                decision_brief_cache_key,
                cache_decision_brief,
                format_decision_brief_for_report,
            )
            from src.ai_report_intelligence import (
                build_ai_report_intelligence,
                build_ai_executive_pdf,
                build_ai_procurement_pdf,
            )
            from src.role_report_generator import build_role_report_pdf
            from src.pdf_entitlements import add_student_edition_watermark
            # Every report derives from the same normalized, current evidence.
            # An analysis-only cache key can otherwise reuse a decision brief
            # generated before supplier inventory or the health score changed.
            report_evidence_df = (
                role_source.copy() if not selected_parts_df.empty else selected_parts_df.copy()
            )
            if not report_evidence_df.empty:
                report_evidence_df["Stock Available"] = report_evidence_df["stock_available"]
                report_evidence_df["Stock"] = report_evidence_df["stock_available"]
                report_evidence_df["Supplier Count"] = report_evidence_df["supplier_count"]
            report_health_score = _report_int(
                _report_value(selected_analysis, "health_score", default=0)
            )
            evidence_columns = [
                column for column in (
                    "mpn", "risk_level", "risk_score", "lifecycle_status",
                    "stock_available", "supplier_count",
                ) if column in report_evidence_df.columns
            ]
            evidence_payload = report_evidence_df[evidence_columns].to_json(
                orient="records", date_format="iso"
            ) if evidence_columns else "[]"
            evidence_fingerprint = hashlib.sha256(
                f"{report_health_score}:{evidence_payload}".encode("utf-8")
            ).hexdigest()[:16]
            report_brief_key = (
                f"{decision_brief_cache_key(analysis_id=_report_value(selected_analysis, 'id', 'analysis_id', default=''))}"
                f":reports:{evidence_fingerprint}"
            )
            decision_brief = get_cached_decision_brief(report_brief_key)
            if decision_brief is None:
                decision_brief = build_engineering_decision_brief(
                    results_df=report_evidence_df,
                    analysis=dict(selected_analysis),
                    health_score=report_health_score,
                )
                cache_decision_brief(report_brief_key, decision_brief)

            pdf_bytes = _build_executive_pdf(
                selected_analysis,
                selected_parts_df,
                decision_brief=decision_brief,
            )
            ai_report = build_ai_report_intelligence(
                selected_analysis,
                report_evidence_df,
            )
            ai_executive_pdf = build_ai_executive_pdf(ai_report, decision_brief=decision_brief)
            ai_procurement_pdf = build_ai_procurement_pdf(ai_report)
            risk_report_pdf = build_role_report_pdf(
                title="Cadivor Engineering Risk Review",
                subtitle="Components ranked by technical risk requiring engineering attention.",
                project_name=project_name,
                dataframe=engineering_df,
                summary_lines=[
                    f"High-risk components: {high_risk}",
                    f"Medium-risk components: {medium_risk}",
                ],
            )
            sourcing_report_pdf = build_role_report_pdf(
                title="Cadivor Procurement & Sourcing Review",
                subtitle="Components ranked by purchasing availability and sourcing difficulty.",
                project_name=project_name,
                dataframe=sourcing_df,
                summary_lines=[
                    ai_report["procurement_summary"],
                ],
            )
            lifecycle_report_pdf = build_role_report_pdf(
                title="Cadivor Lifecycle Readiness Review",
                subtitle="Manufacturer lifecycle status and future availability assessment.",
                project_name=project_name,
                dataframe=lifecycle_df,
                summary_lines=[
                    f"Lifecycle concerns identified: {ai_report['lifecycle_concerns']}",
                ],
            )
            alternatives_report_pdf = build_role_report_pdf(
                title="Cadivor Alternative Readiness Review",
                subtitle="Replacement readiness and next qualification actions.",
                project_name=project_name,
                dataframe=alternative_df,
                summary_lines=[
                    "Use this report to identify components requiring an Alternative Finder review.",
                ],
            )

            # Sprint 31.2: every PDF in the Reports workspace carries the
            # Student Edition watermark when the active entitlement requires it.
            student_pdf = bool(selected_plan.get("student_watermark"))
            pdf_bytes = add_student_edition_watermark(pdf_bytes, student_pdf)
            ai_executive_pdf = add_student_edition_watermark(ai_executive_pdf, student_pdf)
            ai_procurement_pdf = add_student_edition_watermark(ai_procurement_pdf, student_pdf)
            risk_report_pdf = add_student_edition_watermark(risk_report_pdf, student_pdf)
            sourcing_report_pdf = add_student_edition_watermark(sourcing_report_pdf, student_pdf)
            lifecycle_report_pdf = add_student_edition_watermark(lifecycle_report_pdf, student_pdf)
            alternatives_report_pdf = add_student_edition_watermark(alternatives_report_pdf, student_pdf)

            risk_report_csv = engineering_df.to_csv(index=False).encode("utf-8")
            sourcing_report_csv = sourcing_df.to_csv(index=False).encode("utf-8")
            lifecycle_report_csv = lifecycle_df.to_csv(index=False).encode("utf-8")
            alternatives_report_csv = alternative_df.to_csv(index=False).encode("utf-8")
            executive_csv = pd.DataFrame(
                [
                    {
                        "project": project_name,
                        "source_file": source_file,
                        "health_score": health_score,
                        "part_count": part_count,
                        "high_risk_parts": high_risk,
                        "medium_risk_parts": medium_risk,
                        "saved_date": created_date,
                        **(
                            format_decision_brief_for_report(decision_brief)
                            if decision_brief
                            else {}
                        ),
                    }
                ]
            ).to_csv(index=False).encode("utf-8")

            def _report_download_button(
                label: str,
                *,
                report_type: str,
                data,
                file_name: str,
                mime: str,
                key: str,
                primary: bool = False,
            ) -> None:
                """Deliver a report without a rerun that can interrupt the file response."""
                options = {
                    "data": data,
                    "file_name": file_name,
                    "mime": mime,
                    "key": key,
                    "use_container_width": True,
                    # The report controls must stay ordinary download buttons.
                    # Wrapping them in a fragment and running a server callback
                    # during the click can interrupt Streamlit's file response.
                    "on_click": "ignore",
                }
                if primary:
                    options["type"] = "primary"
                st.download_button(label, **options)

            preview_tabs = st.tabs(
                [
                    "AI Executive Brief",
                    "AI Procurement Brief",
                    "Engineering Risk Review",
                    "Procurement & Sourcing Review",
                    "Lifecycle Readiness Review",
                    "Alternative Readiness Review",
                ]
            )

            with preview_tabs[0]:
                st.markdown(
                    f"""
                    <div class="cv-r9-preview-card">
                      <div class="cv-r9-preview-title">AI Executive Decision Brief</div>
                      <div class="cv-r9-preview-copy">
                        <b>Production readiness:</b> {html.escape(ai_report['readiness'])}
                        <br><br>{html.escape(ai_report['executive_summary'])}
                        <br><br><b>Management decision:</b>
                        {html.escape(ai_report['executive_decision'])}
                        <br><br><b>Projected health:</b>
                        {ai_report['health']}/100 → {ai_report['projected_health']}/100
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with preview_tabs[1]:
                procurement_items = "".join(
                    f"<li>{html.escape(item)}</li>"
                    for item in ai_report["procurement_actions"]
                )
                st.markdown(
                    f"""
                    <div class="cv-r9-preview-card">
                      <div class="cv-r9-preview-title">AI Procurement Brief</div>
                      <div class="cv-r9-preview-copy">
                        {html.escape(ai_report['procurement_summary'])}
                        <br><br><b>Priority actions</b>
                        <ul>{procurement_items}</ul>
                        <b>Estimated procurement effort:</b>
                        {ai_report['procurement_hours']} hour(s)
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with preview_tabs[2]:
                st.markdown("### Engineering Risk Review")
                st.caption(
                    "For design and component engineers: components ranked by technical risk, "
                    "with the reason and recommended engineering action."
                )
                if engineering_df.empty:
                    st.info("No component-level risk data is available.")
                else:
                    cadivor_engineering_dataframe(
                        engineering_df,
                        column_config={
                            "MPN": st.column_config.TextColumn(width="medium"),
                            "Risk Score": st.column_config.NumberColumn(format="%d"),
                        },
                    )
                    risk_pdf_col, risk_csv_col = st.columns(2)
                    with risk_pdf_col:
                        _report_download_button(
                            "Download Risk Review PDF",
                            report_type="Engineering Risk Review",
                            data=risk_report_pdf,
                            key=f"tab_risk_pdf_{selected_analysis_id}",
                            file_name=f"{safe_project}_engineering_risk_review.pdf",
                            mime="application/pdf",
                        )
                    with risk_csv_col:
                        _report_download_button(
                            "Download Risk Review CSV",
                            report_type="Engineering Risk Review",
                            data=risk_report_csv,
                            key=f"tab_risk_csv_{selected_analysis_id}",
                            file_name=f"{safe_project}_engineering_risk_review.csv",
                            mime="text/csv",
                        )

            with preview_tabs[3]:
                st.markdown("### Procurement & Sourcing Review")
                st.caption(
                    "For procurement and supply chain: purchasing availability, supplier coverage, "
                    "lead time, pricing, and the required sourcing response."
                )
                if sourcing_df.empty:
                    st.info("No sourcing fields are available for this analysis.")
                else:
                    cadivor_engineering_dataframe(
                        sourcing_df,
                        column_config={
                            "MPN": st.column_config.TextColumn(width="medium"),
                            "Stock Available": st.column_config.NumberColumn(format="%,d"),
                        },
                    )
                    sourcing_pdf_col, sourcing_csv_col = st.columns(2)
                    with sourcing_pdf_col:
                        _report_download_button(
                            "Download Sourcing Review PDF",
                            report_type="Procurement & Sourcing",
                            data=sourcing_report_pdf,
                            key=f"tab_sourcing_pdf_{selected_analysis_id}",
                            file_name=f"{safe_project}_procurement_sourcing_review.pdf",
                            mime="application/pdf",
                        )
                    with sourcing_csv_col:
                        _report_download_button(
                            "Download Sourcing Review CSV",
                            report_type="Procurement & Sourcing",
                            data=sourcing_report_csv,
                            key=f"tab_sourcing_csv_{selected_analysis_id}",
                            file_name=f"{safe_project}_procurement_sourcing_review.csv",
                            mime="text/csv",
                        )

            with preview_tabs[4]:
                st.markdown("### Lifecycle Readiness Review")
                st.caption(
                    "For component engineering: lifecycle continuity, future availability, "
                    "replacement readiness, and review priority."
                )
                if lifecycle_df.empty:
                    st.info("No lifecycle fields are available for this analysis.")
                else:
                    cadivor_engineering_dataframe(lifecycle_df)
                    lifecycle_pdf_col, lifecycle_csv_col = st.columns(2)
                    with lifecycle_pdf_col:
                        _report_download_button(
                            "Download Lifecycle Review PDF",
                            report_type="Lifecycle Exposure Report",
                            data=lifecycle_report_pdf,
                            key=f"tab_lifecycle_pdf_{selected_analysis_id}",
                            file_name=f"{safe_project}_lifecycle_readiness_review.pdf",
                            mime="application/pdf",
                        )
                    with lifecycle_csv_col:
                        _report_download_button(
                            "Download Lifecycle Review CSV",
                            report_type="Lifecycle Exposure Report",
                            data=lifecycle_report_csv,
                            key=f"tab_lifecycle_csv_{selected_analysis_id}",
                            file_name=f"{safe_project}_lifecycle_readiness_review.csv",
                            mime="text/csv",
                        )

            with preview_tabs[5]:
                st.markdown("### Alternative Readiness Review")
                st.caption(
                    "For replacement qualification: which components already have candidates "
                    "and which require an Alternative Finder search."
                )
                if alternative_df.empty:
                    st.info("No alternative-readiness fields are available for this analysis.")
                else:
                    cadivor_engineering_dataframe(alternative_df)
                    alt_pdf_col, alt_csv_col = st.columns(2)
                    with alt_pdf_col:
                        _report_download_button(
                            "Download Alternatives Review PDF",
                            report_type="Alternative Replacement Report",
                            data=alternatives_report_pdf,
                            key=f"tab_alternatives_pdf_{selected_analysis_id}",
                            file_name=f"{safe_project}_alternative_readiness_review.pdf",
                            mime="application/pdf",
                        )
                    with alt_csv_col:
                        _report_download_button(
                            "Download Alternatives Review CSV",
                            report_type="Alternative Replacement Report",
                            data=alternatives_report_csv,
                            key=f"tab_alternatives_csv_{selected_analysis_id}",
                            file_name=f"{safe_project}_alternative_readiness_review.csv",
                            mime="text/csv",
                        )

            st.markdown(
                '<div class="cv-r9-section">Report packages</div>'
                '<div class="cv-r9-sub">Downloads are generated from the selected saved BOM analysis.</div>',
                unsafe_allow_html=True,
            )

            with st.expander("Executive reports", expanded=True):
                st.caption("Leadership-ready summaries for release, risk, and management review.")
                ai_exec_col, executive_pdf_col, executive_csv_col = st.columns(3)
                with ai_exec_col:
                    ai_exec_name = f"{safe_project}_ai_executive_brief.pdf"
                    _report_download_button(
                        "AI Executive Brief · PDF",
                        report_type="AI Executive Brief",
                        key=f"shared_ai_executive_pdf_{selected_analysis_id}",
                        data=ai_executive_pdf,
                        file_name=ai_exec_name,
                        mime="application/pdf",
                        primary=True,
                    )
                with executive_pdf_col:
                    executive_pdf_name = f"{safe_project}_executive_summary.pdf"
                    _report_download_button(
                        "Executive Summary · PDF",
                        report_type="Executive BOM Summary",
                        key=f"shared_executive_pdf_{selected_analysis_id}",
                        data=pdf_bytes,
                        file_name=executive_pdf_name,
                        mime="application/pdf",
                    )
                with executive_csv_col:
                    executive_csv_name = f"{safe_project}_executive_summary.csv"
                    _report_download_button(
                        "Executive Data · CSV",
                        report_type="Executive BOM Summary",
                        key=f"shared_executive_csv_{selected_analysis_id}",
                        data=executive_csv,
                        file_name=executive_csv_name,
                        mime="text/csv",
                    )

            with st.expander("Engineering reports", expanded=False):
                st.caption("Technical reviews for component risk, lifecycle readiness, and alternatives.")
                risk_col, lifecycle_col, alternatives_col = st.columns(3)
                with risk_col:
                    risk_csv_name = f"{safe_project}_engineering_risk_review.csv"
                    _report_download_button(
                        "Risk Review · CSV",
                        report_type="Engineering Risk Review",
                        key=f"shared_risk_csv_{selected_analysis_id}",
                        data=engineering_df.to_csv(index=False).encode("utf-8"),
                        file_name=risk_csv_name,
                        mime="text/csv",
                    )
                with lifecycle_col:
                    lifecycle_csv_name = f"{safe_project}_lifecycle_exposure.csv"
                    _report_download_button(
                        "Lifecycle Review · CSV",
                        report_type="Lifecycle Exposure Report",
                        key=f"shared_lifecycle_csv_{selected_analysis_id}",
                        data=lifecycle_df.to_csv(index=False).encode("utf-8"),
                        file_name=lifecycle_csv_name,
                        mime="text/csv",
                    )
                with alternatives_col:
                    alternatives_csv_name = f"{safe_project}_alternative_readiness.csv"
                    _report_download_button(
                        "Alternatives Review · CSV",
                        report_type="Alternative Replacement Report",
                        key=f"shared_alternatives_csv_{selected_analysis_id}",
                        data=alternative_df.to_csv(index=False).encode("utf-8"),
                        file_name=alternatives_csv_name,
                        mime="text/csv",
                    )

            with st.expander("Procurement reports", expanded=False):
                st.caption("Purchasing and sourcing packages for procurement and supplier review.")
                ai_proc_col, sourcing_col = st.columns(2)
                with ai_proc_col:
                    ai_proc_name = f"{safe_project}_ai_procurement_brief.pdf"
                    _report_download_button(
                        "AI Procurement Brief · PDF",
                        report_type="AI Procurement Brief",
                        key=f"shared_ai_procurement_pdf_{selected_analysis_id}",
                        data=ai_procurement_pdf,
                        file_name=ai_proc_name,
                        mime="application/pdf",
                        primary=True,
                    )
                with sourcing_col:
                    sourcing_csv_name = f"{safe_project}_sourcing_summary.csv"
                    _report_download_button(
                        "Sourcing Review · CSV",
                        report_type="Procurement & Sourcing",
                        key=f"shared_sourcing_csv_{selected_analysis_id}",
                        data=sourcing_df.to_csv(index=False).encode("utf-8"),
                        file_name=sourcing_csv_name,
                        mime="text/csv",
                    )

            action_cols = st.columns(3)
            with action_cols[0]:
                internal_nav_button(
                    "Open Analysis Details",
                    "Analysis Details",
                    key="reports_open_analysis_details",
                    use_container_width=True,
                    analysis_id=selected_analysis_id,
                )
            with action_cols[1]:
                internal_nav_button(
                    "Open in BOM Analyzer",
                    "BOM Analyzer",
                    key="reports_open_bom_analyzer",
                    use_container_width=True,
                    analysis_id=selected_analysis_id,
                )
            with action_cols[2]:
                internal_nav_button(
                    "Open Alternative Finder",
                    ALTERNATIVE_FINDER_PAGE,
                    key="reports_open_alternative_finder",
                    use_container_width=True,
                    analysis_id=selected_analysis_id,
                    return_analysis_id=selected_analysis_id,
                    source_page="reports_center",
                )

            with st.expander(
                f"Browse all {len(report_records)} report-ready analyses",
                expanded=False,
            ):
                display_rows = []
                for row in report_records:
                    row_created_at = str(
                        _report_value(
                            row,
                            "created_at",
                            "date",
                            default="",
                        )
                    )
                    row_created_date = (
                        row_created_at.split("T")[0]
                        if "T" in row_created_at
                        else row_created_at[:10]
                    )
                    display_rows.append(
                        {
                            "Project": _report_value(
                                row,
                                "project_name",
                                "name",
                                default="Saved BOM",
                            ),
                            "Source File": _report_value(
                                row,
                                "filename",
                                "uploaded_file",
                                "file_name",
                                default="—",
                            ),
                            "Date": row_created_date or "—",
                            "Health": _report_int(
                                _report_value(
                                    row,
                                    "health_score",
                                    default=0,
                                )
                            ),
                            "High Risk": _report_int(
                                _report_value(
                                    row,
                                    "high_risk_count",
                                    "high_risk_parts",
                                    default=0,
                                )
                            ),
                            "Medium Risk": _report_int(
                                _report_value(
                                    row,
                                    "medium_risk_count",
                                    "medium_risk_parts",
                                    default=0,
                                )
                            ),
                            "Parts": _report_int(
                                _report_value(
                                    row,
                                    "total_parts",
                                    "part_count",
                                    "parts_count",
                                    default=0,
                                )
                            ),
                        }
                    )
                cadivor_engineering_dataframe(pd.DataFrame(display_rows))
        else:
            st.markdown(
                '<div class="cv-r9-empty">No saved BOM analyses are available. Analyze and save a BOM before generating reports.</div>',
                unsafe_allow_html=True,
            )

        stop_authenticated_page()


    # ---------- Pricing ----------
    if app_mode == "Pricing":
        # Sprint 31.3.1 — launch pricing polish patch.
        current_plan_key = str(selected_plan_name or "Starter").strip().lower()
        plan_aliases = {
            "pro": "professional",
            "professional": "professional",
            "business": "business",
            "enterprise": "enterprise",
            "student": "student",
            "trial": "free trial",
            "free trial": "free trial",
            "starter": "starter",
            "free": "starter",
        }
        normalized_current_plan = plan_aliases.get(current_plan_key, current_plan_key)
        used_boms = int(monthly_upload_count or 0)
        included_boms = int(selected_plan.get("monthly_bom_limit", 0) or 0)
        usage_percent = min(100, round((used_boms / included_boms) * 100)) if included_boms else 0
        monitored_limit = selected_plan.get("monitored_parts_limit")
        monitored_limit_text = "Unlimited" if monitored_limit is None else f"{int(monitored_limit):,}"
        analysis_limit_text = "Unlimited" if not included_boms else f"{included_boms:,}"
        component_limit = selected_plan.get("max_parts_per_bom")
        component_limit_text = "Unlimited" if component_limit is None else f"{int(component_limit):,} per BOM"
        reports_text = "Student Edition watermark" if selected_plan.get("student_watermark") else "Included"
        checkout_state = str(_qp_value("checkout", "") or "").strip().lower()

        if checkout_state == "success":
            st.success(
                "Payment completed. Your plan will update automatically after Stripe confirms the subscription."
            )
            st.caption(
                "This normally happens within a few moments. Refresh Cadivor if the plan badge has not changed yet."
            )
        elif checkout_state == "cancel":
            st.info("Checkout was canceled. Your current plan and saved work are unchanged.")

        st.markdown(
            """
            <style id="cadivor-pricing-313">
            .cv311-hero{border:1px solid #bfdbfe;background:
            radial-gradient(circle at 91% 12%,rgba(37,99,235,.13),transparent 29%),
            linear-gradient(135deg,#fff 0%,#f8fbff 64%,#eef5ff 100%);
            border-radius:26px;padding:36px 40px;margin-bottom:26px;box-shadow:0 20px 52px rgba(37,99,235,.08)}
            .cv311-eyebrow{font-size:clamp(13px,.82vw,16px);font-weight:950;letter-spacing:.11em;text-transform:uppercase;color:#2563eb!important;margin-bottom:10px}
            .cv311-title{font-size:clamp(38px,2.55vw,54px);font-weight:950;letter-spacing:-.045em;color:#0f172a!important;line-height:1.06;margin-bottom:14px;max-width:1180px}
            .cv311-copy{font-size:clamp(17px,1.05vw,21px);font-weight:680;color:#52647a!important;line-height:1.62;max-width:1080px}
            .cv311-current{border:1px solid #dbeafe;background:linear-gradient(135deg,#fff 0%,#fbfdff 100%);border-radius:22px;padding:25px 28px;margin-bottom:26px;box-shadow:0 14px 38px rgba(15,23,42,.065)}
            .cv311-current-head{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;margin-bottom:20px}
            .cv311-current-title{font-size:clamp(22px,1.35vw,28px);font-weight:950;color:#0f172a!important;line-height:1.2}
            .cv311-current-copy{font-size:clamp(14px,.9vw,17px);font-weight:680;color:#64748b!important;margin-top:7px;line-height:1.5}
            .cv311-plan-badge{border:1px solid #93c5fd;background:#eff6ff;color:#1d4ed8!important;border-radius:999px;padding:9px 14px;font-size:clamp(12px,.75vw,15px);font-weight:950;white-space:nowrap}
            .cv311-usage-meta{display:flex;justify-content:space-between;gap:12px;font-size:clamp(13px,.82vw,16px);font-weight:850;color:#475569!important;margin:17px 0 9px}
            .cv311-bar{height:11px;border-radius:999px;background:#e2e8f0;overflow:hidden}.cv311-bar i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#2563eb,#60a5fa);transition:width .45s ease}
            .cv311-section-title{font-size:clamp(29px,1.75vw,38px);font-weight:950;color:#0f172a!important;margin:34px 0 8px;letter-spacing:-.025em;line-height:1.16}
            .cv311-section-copy{font-size:clamp(15px,.98vw,19px);font-weight:650;color:#64748b!important;line-height:1.55;margin:0 0 20px}
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv311-card){padding:0!important;border-radius:23px!important;overflow:hidden!important;box-shadow:0 14px 38px rgba(15,23,42,.075)!important;transition:transform .22s ease,box-shadow .22s ease,border-color .22s ease!important;align-self:start!important}
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv311-card):hover{transform:translateY(-4px);box-shadow:0 22px 52px rgba(15,23,42,.12)!important}
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv311-featured){border:2px solid #2563eb!important;background:linear-gradient(180deg,#f2f7ff 0%,#fff 42%)!important;box-shadow:0 22px 56px rgba(37,99,235,.20)!important}
            .cv311-card-inner{padding:29px 32px 22px}
            .cv311-card-top{display:flex;justify-content:space-between;align-items:center;gap:14px}
            .cv311-name{font-size:clamp(25px,1.55vw,33px);font-weight:950;color:#0f172a!important;line-height:1.15;letter-spacing:-.025em}
            .cv311-tag{border:1px solid #93c5fd;background:#eff6ff;color:#1d4ed8!important;border-radius:999px;padding:9px 14px;font-size:clamp(11px,.72vw,14px);font-weight:950;white-space:nowrap;box-shadow:0 5px 14px rgba(37,99,235,.10);transition:transform .2s ease,box-shadow .2s ease}
            .cv311-tag.green{border-color:#6ee7b7;background:#ecfdf5;color:#047857!important}
            .cv311-price{font-size:clamp(46px,3.2vw,68px);font-weight:950;letter-spacing:-.055em;color:#0f172a!important;margin:18px 0 4px;line-height:1}
            .cv311-period{font-size:clamp(14px,.9vw,18px);font-weight:750;color:#64748b!important;letter-spacing:0;margin-left:4px}
            .cv311-outcome{font-size:clamp(17px,1.05vw,21px);font-weight:850;color:#1e293b!important;line-height:1.42;margin:15px 0 6px}
            .cv311-for{font-size:clamp(14px,.9vw,18px);font-weight:680;color:#64748b!important;line-height:1.5;margin:0 0 15px}
            .cv311-features{border-top:1px solid #dbe4ef;padding-top:14px}
            .cv311-feature{display:flex;align-items:flex-start;gap:10px;font-size:clamp(14px,.88vw,17px);font-weight:720;color:#334155!important;line-height:1.44;margin:8px 0}
            .cv311-check{color:#059669!important;font-weight:950;font-size:1.08em;line-height:1.35}.cv311-muted{color:#94a3b8!important}
            .cv311-current-note{border:1px solid #86efac;background:#ecfdf5;color:#047857!important;border-radius:12px;padding:13px 14px;font-size:clamp(13px,.82vw,16px);font-weight:900;text-align:center;margin:12px 12px 14px}
            .cv311-info-note{border:1px solid #bfdbfe;background:#f8fbff;color:#475569!important;border-radius:12px;padding:12px 14px;font-size:clamp(13px,.82vw,16px);font-weight:720;line-height:1.45;margin-top:12px}
            .cv311-compare{border:1px solid #dbe4ef;background:#fff;border-radius:22px;padding:28px;margin-top:30px;box-shadow:0 12px 34px rgba(15,23,42,.045)}
            .cv311-compare h3{font-size:clamp(26px,1.6vw,34px)!important;line-height:1.2!important;margin:0 0 9px!important;color:#0f172a!important}.cv311-compare p{font-size:clamp(14px,.9vw,18px);line-height:1.55;color:#64748b!important;margin:0 0 18px}
            .cv311-table{display:grid;grid-template-columns:minmax(210px,1.55fr) repeat(5,minmax(145px,1fr));border:1px solid #dbe4ef;border-radius:16px;overflow:auto;background:#fff}
            .cv311-cell{padding:17px 14px;border-right:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;font-size:clamp(13px,.78vw,16px);font-weight:760;color:#334155!important;background:#fff;min-width:128px;line-height:1.35;text-align:center}
            .cv311-cell:nth-child(6n+1){text-align:left;font-weight:900;position:sticky;left:0;z-index:2;background:#fff}.cv311-cell.head{font-size:clamp(13px,.82vw,17px);font-weight:950;color:#0f172a!important;background:#f8fafc;position:sticky;top:0;z-index:3}.cv311-cell.head:nth-child(6n+1){z-index:4;background:#f8fafc}.cv311-cell.pro{background:#f4f8ff;color:#1d4ed8!important}.cv311-cell:last-child{border-right:0}
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv311-card) .stButton>button,
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv311-card) .stLinkButton>a{min-height:48px!important;font-size:16px!important;font-weight:850!important;border-radius:11px!important;padding:11px 18px!important;transition:transform .18s ease,box-shadow .18s ease!important}
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv311-card) .stButton>button:hover,
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv311-card) .stLinkButton>a:hover{transform:translateY(-2px);box-shadow:0 10px 24px rgba(37,99,235,.20)!important}
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv311-featured) .cv311-tag{background:#2563eb;color:#fff!important;border-color:#2563eb;box-shadow:0 7px 18px rgba(37,99,235,.24)}
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv311-card):hover .cv311-tag{transform:translateY(-1px)}
            .cv311-summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
            .cv311-summary-item{border:1px solid #e2e8f0;background:#f8fafc;border-radius:14px;padding:14px 16px}
            .cv311-summary-label{font-size:clamp(11px,.7vw,14px);font-weight:900;letter-spacing:.055em;text-transform:uppercase;color:#64748b!important;margin-bottom:6px}
            .cv311-summary-value{font-size:clamp(15px,.95vw,19px);font-weight:950;color:#0f172a!important;line-height:1.25}
            .cv311-active{display:inline-flex;align-items:center;gap:7px;color:#047857!important;font-weight:900;font-size:clamp(13px,.82vw,16px);margin-top:7px}
            .cv311-active-dot{width:9px;height:9px;border-radius:999px;background:#10b981;box-shadow:0 0 0 4px rgba(16,185,129,.12)}
            @media(max-width:1100px){.cv311-card-inner{padding:26px 25px 21px}.cv311-table{grid-template-columns:minmax(180px,1.4fr) repeat(5,minmax(130px,1fr))}}
            @media(max-width:900px){.cv311-hero{padding:28px 24px}.cv311-current-head{display:block}.cv311-plan-badge{display:inline-block;margin-top:10px}.cv311-summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.cv311-card-inner{padding:25px 22px}.cv311-compare{padding:20px 16px}.cv311-table{grid-template-columns:minmax(175px,1.4fr) repeat(5,minmax(125px,1fr))}}
            @media(max-width:560px){.cv311-summary-grid{grid-template-columns:1fr}.cv311-current{padding:22px 20px}}
            </style>
            <section class="cv311-hero">
              <div class="cv311-eyebrow">Cadivor plans</div>
              <div class="cv311-title">Choose the engineering workflow your team is ready for.</div>
              <div class="cv311-copy">Start with education or prototype work, unlock the full platform during a 14-day trial, then scale from individual engineering decisions to organization-wide lifecycle intelligence.</div>
            </section>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <section class="cv311-current">
              <div class="cv311-current-head">
                <div>
                  <div class="cv311-current-title">{html.escape(str(selected_plan_name))} Workspace</div>
                  <div class="cv311-active"><span class="cv311-active-dot"></span>Active plan</div>
                  <div class="cv311-current-copy">Your included Cadivor capabilities and current monthly usage.</div>
                </div>
                <div class="cv311-plan-badge">{html.escape(str(selected_plan_name))}</div>
              </div>
              <div class="cv311-summary-grid">
                <div class="cv311-summary-item"><div class="cv311-summary-label">BOM analyses</div><div class="cv311-summary-value">{used_boms:,} / {analysis_limit_text}</div></div>
                <div class="cv311-summary-item"><div class="cv311-summary-label">Components</div><div class="cv311-summary-value">{component_limit_text}</div></div>
                <div class="cv311-summary-item"><div class="cv311-summary-label">Monitoring</div><div class="cv311-summary-value">{monitored_limit_text} parts</div></div>
                <div class="cv311-summary-item"><div class="cv311-summary-label">PDF reports</div><div class="cv311-summary-value">{reports_text}</div></div>
              </div>
              <div class="cv311-usage-meta"><span>Monthly BOM usage</span><span>{usage_percent}%</span></div>
              <div class="cv311-bar"><i style="width:{usage_percent}%"></i></div>
            </section>
            """,
            unsafe_allow_html=True,
        )

        def _start_plan_checkout(plan_name: str, secret_key: str, button_key: str) -> None:
            state_key = f"pricing_checkout_url_{plan_name.lower().replace(' ', '_')}"
            if st.button(
                f"Upgrade to {plan_name}",
                key=button_key,
                type="primary",
                use_container_width=True,
            ):
                try:
                    price_id = get_secret(secret_key, required=True)
                    from src.stripe_helper import create_checkout_session
                    st.session_state[state_key] = create_checkout_session(
                        price_id,
                        current_user["email"],
                        current_user["id"],
                        success_url=app_checkout_url(page="Pricing", checkout="success"),
                        cancel_url=app_checkout_url(page="Pricing", checkout="cancel"),
                    )
                except KeyError:
                    st.error(f"{plan_name} checkout is not configured in Streamlit secrets.")
                except Exception:
                    st.error(
                        f"Secure {plan_name} checkout could not be started. "
                        "Please try again or contact support."
                    )

            checkout_url = st.session_state.get(state_key)
            if checkout_url:
                st.link_button(
                    "Continue to secure checkout →",
                    checkout_url,
                    use_container_width=True,
                )

        education_plans = [
            {
                "name": "Student",
                "price": "Free",
                "tag": "Education",
                "outcome": "Build better engineering habits before entering industry.",
                "audience": "University students, technical colleges, engineering clubs, and capstone teams.",
                "features": [
                    "5 BOM analyses per month",
                    "Up to 50 components per BOM",
                    "Basic risk analysis and health score",
                    "Limited alternative search",
                    'PDF reports with "Student Edition" watermark',
                    "Community support only",
                ],
                "note": "No monitoring, API access, or team administration.",
            },
            {
                "name": "Free Trial",
                "price": "14 days",
                "tag": "Full access",
                "outcome": "Experience the complete Cadivor workflow before choosing a paid plan.",
                "audience": "New professional and business customers evaluating Cadivor with real BOMs.",
                "features": [
                    "No feature restrictions during the trial",
                    "Professional analysis and AI capabilities",
                    "Monitoring, reports, and engineering decisions",
                    "Team workflow evaluation",
                    "Saved work remains available after trial",
                ],
                "note": "At trial end, upgrade or continue on Starter.",
            },
        ]

        st.markdown('<div class="cv311-section-title">Start with Cadivor</div><div class="cv311-section-copy">Education access and a full-platform evaluation path.</div>', unsafe_allow_html=True)
        education_columns = st.columns(2, gap="medium")
        for column, plan in zip(education_columns, education_plans):
            plan_key = plan["name"].lower()
            is_current = normalized_current_plan == plan_key
            with column:
                with st.container(border=True):
                    st.markdown(
                        '<span class="cv311-card"></span>'
                        '<div class="cv311-card-inner">'
                        '<div class="cv311-card-top">'
                        f'<div class="cv311-name">{plan["name"]}</div>'
                        f'<div class="cv311-tag green">{plan["tag"]}</div>'
                        '</div>'
                        f'<div class="cv311-price">{plan["price"]}</div>'
                        f'<div class="cv311-outcome">{plan["outcome"]}</div>'
                        f'<div class="cv311-for">{plan["audience"]}</div>'
                        '<div class="cv311-features">'
                        + "".join(
                            f'<div class="cv311-feature"><span class="cv311-check">✓</span><span>{feature}</span></div>'
                            for feature in plan["features"]
                        )
                        + '</div>'
                        f'<div class="cv311-info-note">{plan["note"]}</div>'
                        '</div>',
                        unsafe_allow_html=True,
                    )
                    if is_current:
                        st.markdown('<div class="cv311-current-note">Your active plan</div>', unsafe_allow_html=True)
                    elif plan_key == "student":
                        st.link_button(
                            "Request Student Access",
                            "mailto:info@cadivor.com?subject=Cadivor%20Student%20Plan%20Request",
                            use_container_width=True,
                        )
                    else:
                        st.markdown(
                            '<div class="cv311-info-note">The 14-day full-access trial is intended for new customer evaluations.</div>',
                            unsafe_allow_html=True,
                        )

        paid_plans = [
            {
                "name": "Starter",
                "price": "$29",
                "annual_price": "$296",
                "tag": "Individual",
                "outcome": "Analyze prototype BOMs before production.",
                "audience": "Hobbyists, freelancers, makers, and small prototype companies.",
                "features": [
                    "10 BOM analyses per month",
                    "100 components per BOM",
                    "Supplier intelligence and alternative search",
                    "PDF and CSV reports",
                    "Email support",
                ],
                "exclusions": "No monitoring, AI engineering assistant, team collaboration, or API.",
            },
            {
                "name": "Professional",
                "price": "$99",
                "annual_price": "$1,010",
                "tag": "Most popular",
                "outcome": "Make engineering decisions with confidence using AI-powered lifecycle intelligence.",
                "audience": "Professional hardware engineers, startups, and small engineering companies.",
                "features": [
                    "Everything in Starter",
                    "Unlimited BOM analyses and components",
                    "Advanced AI recommendations and assistant",
                    "Engineering Decision Records",
                    "Official datasheet comparison with cited PDF evidence",
                    "Advanced reports and custom branding",
                    "Component comparison and supplier intelligence",
                    "Alternative recommendations and risk scoring",
                    "Monitoring for 2,500 components",
                    "Priority email support",
                ],
                "exclusions": "",
            },
            {
                "name": "Business",
                "price": "$299",
                "annual_price": "$3,050",
                "tag": "Teams",
                "outcome": "Standardize engineering decisions across your organization.",
                "audience": "Growing companies, electronics manufacturers, and cross-functional teams.",
                "features": [
                    "Everything in Professional",
                    "10 users included",
                    "Role-based permissions and approval workflows",
                    "Unlimited monitoring",
                    "Organization workspace and shared BOM library",
                    "Audit logs, comments, and activity history",
                    "Advanced analytics and usage dashboard",
                    "API access and webhooks",
                    "Priority support",
                ],
                "exclusions": "",
            },
            {
                "name": "Enterprise",
                "price": "Contact Sales",
                "tag": "Custom",
                "outcome": "Integrate Cadivor into your engineering infrastructure.",
                "audience": "Larger deployments requiring security, integrations, support, and custom architecture.",
                "features": [
                    "Unlimited users, monitoring, and API",
                    "SSO with SAML or OAuth",
                    "Priority SLA and dedicated customer success",
                    "ERP and PLM integrations",
                    "Custom AI models and integrations",
                    "Training and migration assistance",
                    "Quarterly business reviews",
                    "Dedicated infrastructure where required",
                ],
                "exclusions": "On-premises deployment is planned as a future option.",
            },
        ]

        st.markdown('<div class="cv311-section-title">Plans for working engineering teams</div><div class="cv311-section-copy">Professional is the flagship plan; Business adds organization-wide collaboration and controls.</div>', unsafe_allow_html=True)
        paid_rows = [paid_plans[:2], paid_plans[2:]]
        for row_index, row_plans in enumerate(paid_rows):
            paid_columns = st.columns(2, gap="medium")
            for column, plan in zip(paid_columns, row_plans):
                plan_key = plan["name"].lower()
                is_current = normalized_current_plan == plan_key
                featured = plan_key == "professional"
                with column:
                    with st.container(border=True):
                        marker = " cv311-featured" if featured else ""
                        display_price = html.escape(plan["price"]).replace("$", "&#36;")
                        display_annual_price = html.escape(plan.get("annual_price", "")).replace("$", "&#36;")
                        st.markdown(
                            f'<span class="cv311-card{marker}"></span>'
                            '<div class="cv311-card-inner">'
                            '<div class="cv311-card-top">'
                            f'<div class="cv311-name">{plan["name"]}</div>'
                            f'<div class="cv311-tag">{plan["tag"]}</div>'
                            '</div>'
                            f'<div class="cv311-price">{display_price}'
                            + (f'<span class="cv311-period"> / month</span>' if plan["price"].startswith("$") else "")
                            + '</div>'
                            + (f'<div class="cv311-info-note">{display_annual_price} / year · Save 15%</div>' if display_annual_price else "")
                            + f'<div class="cv311-outcome">{plan["outcome"]}</div>'
                            f'<div class="cv311-for">{plan["audience"]}</div>'
                            '<div class="cv311-features">'
                            + "".join(
                                f'<div class="cv311-feature"><span class="cv311-check">✓</span><span>{feature}</span></div>'
                                for feature in plan["features"]
                            )
                            + '</div>'
                            + (f'<div class="cv311-info-note">{plan["exclusions"]}</div>' if plan["exclusions"] else "")
                            + '</div>',
                            unsafe_allow_html=True,
                        )

                        if is_current:
                            st.markdown('<div class="cv311-current-note">Your active plan</div>', unsafe_allow_html=True)
                        elif plan_key == "professional" and normalized_current_plan not in {"professional", "business", "enterprise"}:
                            _start_plan_checkout("Professional", "STRIPE_PRO_PRICE_ID", "pricing_311_upgrade_professional")
                        elif plan_key == "business" and normalized_current_plan not in {"business", "enterprise"}:
                            _start_plan_checkout("Business", "STRIPE_BUSINESS_PRICE_ID", "pricing_311_upgrade_business")
                        elif plan_key == "enterprise":
                            st.link_button(
                                "Contact Sales",
                                "mailto:info@cadivor.com?subject=Cadivor%20Enterprise%20Inquiry",
                                use_container_width=True,
                            )
                        elif plan_key == "starter" and normalized_current_plan != "starter":
                            st.markdown(
                                '<div class="cv311-info-note">Contact support to move an existing paid subscription to Starter.</div>',
                                unsafe_allow_html=True,
                            )

        feature_rows = [
            ("BOM Analysis", "✓", "✓", "Unlimited", "Unlimited", "Unlimited"),
            ("Alternative Search", "Limited", "✓", "Advanced", "Advanced", "Advanced"),
            ("AI Recommendations", "—", "—", "✓", "✓", "✓"),
            ("BOM Monitoring", "—", "—", "2,500 parts", "Unlimited", "Unlimited"),
            ("Engineering Decision Records", "—", "—", "✓", "✓", "✓"),
            ("Team Collaboration", "—", "—", "—", "✓", "✓"),
            ("API Access", "—", "—", "—", "✓", "Unlimited"),
            ("SSO", "—", "—", "—", "—", "✓"),
            ("Custom Integrations", "—", "—", "—", "Limited", "✓"),
            ("Dedicated Support", "Community", "Email", "Priority", "Priority", "Dedicated"),
        ]
        st.markdown(
            '<section class="cv311-compare"><h3>Feature comparison</h3>'
            '<p>Free Trial includes the complete platform for 14 days and is therefore not repeated in the long-term plan matrix.</p>'
            '<div class="cv311-table">'
            '<div class="cv311-cell head">Feature</div>'
            '<div class="cv311-cell head">Student</div>'
            '<div class="cv311-cell head">Starter</div>'
            '<div class="cv311-cell head pro">Professional</div>'
            '<div class="cv311-cell head">Business</div>'
            '<div class="cv311-cell head">Enterprise</div>'
            + "".join(
                f'<div class="cv311-cell">{feature}</div>'
                f'<div class="cv311-cell">{student}</div>'
                f'<div class="cv311-cell">{starter}</div>'
                f'<div class="cv311-cell pro">{professional}</div>'
                f'<div class="cv311-cell">{business}</div>'
                f'<div class="cv311-cell">{enterprise}</div>'
                for feature, student, starter, professional, business, enterprise in feature_rows
            )
            + '</div></section>',
            unsafe_allow_html=True,
        )

        st.caption(
            "Stripe handles Professional and Business payments securely. Plan activation is applied through the existing Cadivor subscription webhook."
        )
        stop_authenticated_page()


    # ---------- Admin Console v2 (admin-only; all controls are server-enforced and audited) ----------
    if app_mode == "Admin Console":
        if not is_admin:
            st.error("This page is available only to Cadivor administrators.")
            stop_authenticated_page()
        st.title("Admin Console")
        st.caption("Operational control for Cadivor administrators. Every account and maintenance change is recorded in the audit trail.")
        try:
            overview_rows = supabase.rpc("cadivor_admin_overview").execute().data or []
            user_rows = supabase.rpc("cadivor_admin_list_users_v2").execute().data or []
            audit_rows = supabase.rpc("cadivor_admin_audit_events").execute().data or []
            support_activity_rows = supabase.rpc("cadivor_admin_support_activity_events").execute().data or []
        except Exception:
            st.warning("Admin Console v2 is waiting for its approved Supabase migration. Existing customer workflows are unaffected.")
            stop_authenticated_page()
        overview = overview_rows[0] if overview_rows else {}
        metric_columns = st.columns(5)
        metric_columns[0].metric("Registered users", overview.get("registered_users", len(user_rows)))
        metric_columns[1].metric("Online now", overview.get("active_now", 0))
        metric_columns[2].metric("Active in 30 days", overview.get("active_last_30_days", 0))
        metric_columns[3].metric("Suspended", overview.get("suspended_users", 0))
        metric_columns[4].metric("Platform", "Maintenance" if overview.get("maintenance_mode") else "Operational")

        overview_tab, users_tab, maintenance_tab, support_tab, audit_tab = st.tabs(
            ["Overview", "Users", "Maintenance", "Support activity", "Audit trail"]
        )

        with overview_tab:
            st.subheader("Control center")
            if overview.get("maintenance_mode"):
                st.warning(overview.get("maintenance_message") or "Maintenance mode is enabled for non-admin users.")
            else:
                st.success("Cadivor is available to customers. Administrators retain access during maintenance.")
            st.info("Plan changes are intentionally Stripe-controlled. Use the billing workflow for paid-plan activation.")

        with users_tab:
            st.subheader("User directory")
            def _human_admin_timestamp(value):
                parsed = pd.to_datetime(value, utc=True, errors="coerce")
                if pd.isna(parsed):
                    return "Never"
                return parsed.strftime("%b %d, %Y · %I:%M %p UTC")

            search_column, status_column, presence_column, role_column = st.columns((2.2, 1, 1, 1))
            search_users = search_column.text_input("Search users", placeholder="Email, name, company, plan, or role")
            status_filter = status_column.selectbox("Account status", ["All", "active", "suspended"])
            presence_filter = presence_column.selectbox("Presence", ["All", "active", "idle", "offline"])
            role_filter = role_column.selectbox("Role", ["All", "user", "admin"])
            users_frame = pd.DataFrame(user_rows)
            if not users_frame.empty:
                if search_users.strip():
                    needle = search_users.strip().lower()
                    searchable_columns = [column for column in ("email", "full_name", "company_name", "plan", "role", "account_status") if column in users_frame]
                    users_frame = users_frame[users_frame[searchable_columns].fillna("").astype(str).apply(
                        lambda row: row.str.lower().str.contains(needle, regex=False).any(), axis=1
                    )]
                if status_filter != "All":
                    users_frame = users_frame[users_frame["account_status"].fillna("active").str.lower() == status_filter]
                if presence_filter != "All" and "activity_status" in users_frame:
                    users_frame = users_frame[users_frame["activity_status"].fillna("offline").str.lower() == presence_filter]
                if role_filter != "All":
                    users_frame = users_frame[users_frame["role"].fillna("user").str.lower() == role_filter]
                directory_columns = [
                    column for column in ("email", "full_name", "company_name", "role", "plan", "activity_status", "last_active_at", "account_status", "last_sign_in_at")
                    if column in users_frame
                ]
                directory_frame = users_frame[directory_columns].rename(columns={
                    "email": "Email", "full_name": "Name", "company_name": "Company",
                    "role": "Role", "plan": "Plan", "account_status": "Account status",
                    "activity_status": "Presence", "last_active_at": "Last active", "last_sign_in_at": "Last sign-in",
                })
                if "Presence" in directory_frame:
                    presence_labels = {
                        "active": "🟢 Active",
                        "idle": "🟠 Idle",
                        "offline": "⚪ Offline",
                    }
                    directory_frame["Presence"] = directory_frame["Presence"].fillna("offline").astype(str).str.lower().map(
                        presence_labels
                    ).fillna("⚪ Offline")
                for timestamp_column in ("Last active", "Last sign-in"):
                    if timestamp_column in directory_frame:
                        directory_frame[timestamp_column] = directory_frame[timestamp_column].apply(_human_admin_timestamp)
                st.dataframe(directory_frame, use_container_width=True, hide_index=True)
            else:
                st.info("No users match the selected filters.")

            st.divider()
            st.subheader("Manage a user")
            if not user_rows:
                st.caption("No user account is available to manage.")
            else:
                selected_user = st.selectbox(
                    "Choose a user",
                    user_rows,
                    format_func=lambda row: f"{row.get('email', 'Unknown user')} · {row.get('activity_status', 'offline')} · {row.get('account_status', 'active')} · {row.get('plan', 'Starter')}",
                )
                selected_user_id = selected_user.get("id")
                selected_role = str(selected_user.get("role", "user")).lower()
                selected_status = str(selected_user.get("account_status", "active")).lower()
                is_self = str(selected_user_id) == str(current_user.get("id"))
                is_target_admin = selected_role == "admin"
                details_column, actions_column = st.columns((1, 1.45))
                with details_column:
                    st.markdown("**Account details**")
                    account_details = (
                        ("Email", selected_user.get("email") or "—"),
                        ("Name", selected_user.get("full_name") or "—"),
                        ("Company", selected_user.get("company_name") or "—"),
                        ("Plan", selected_user.get("plan") or "Starter"),
                        ("Presence", {"active": "🟢 Active", "idle": "🟠 Idle", "offline": "⚪ Offline"}.get(str(selected_user.get("activity_status") or "offline").lower(), "⚪ Offline")),
                        ("Last active", _human_admin_timestamp(selected_user.get("last_active_at"))),
                        ("Role", selected_role),
                        ("Status", selected_status),
                        ("Last sign-in", _human_admin_timestamp(selected_user.get("last_sign_in_at"))),
                    )
                    for detail_label, detail_value in account_details:
                        st.caption(detail_label)
                        st.write(detail_value)
                    if selected_user.get("suspended_reason"):
                        st.caption(f"Suspension reason: {selected_user['suspended_reason']}")
                with actions_column:
                    if is_self:
                        st.info("For safety, you cannot modify your own administrator account from this console.")
                    elif is_target_admin:
                        st.info("Administrator accounts cannot be suspended. Role changes are protected server-side to retain at least one administrator.")
                    else:
                        with st.form("admin_account_status_form"):
                            next_status = st.selectbox("Account access", ["active", "suspended"], index=0 if selected_status == "active" else 1)
                            status_reason = st.text_area("Reason for this change", max_chars=500)
                            status_confirmed = st.checkbox("I understand this changes the user's access immediately.")
                            apply_status = st.form_submit_button("Apply account status", type="primary")
                            if apply_status:
                                if not status_confirmed:
                                    st.error("Confirm the access change before applying it.")
                                else:
                                    try:
                                        supabase.rpc("cadivor_admin_set_account_status", {
                                            "target_user_id": selected_user_id,
                                            "next_status": next_status,
                                            "reason": status_reason,
                                        }).execute()
                                        st.success("Account status updated and recorded in the audit trail.")
                                        st.rerun()
                                    except Exception:
                                        st.error("Cadivor could not update this account. No change was confirmed.")
                    if not is_self:
                        with st.form("admin_role_form"):
                            next_role = st.selectbox("Cadivor role", ["user", "admin"], index=0 if selected_role == "user" else 1)
                            role_reason = st.text_input("Reason for role change", max_chars=500)
                            role_confirmed = st.checkbox("I understand this changes administrator access.")
                            apply_role = st.form_submit_button("Apply role change")
                            if apply_role:
                                if not role_confirmed:
                                    st.error("Confirm the role change before applying it.")
                                else:
                                    try:
                                        supabase.rpc("cadivor_admin_set_role", {
                                            "target_user_id": selected_user_id,
                                            "next_role": next_role,
                                            "reason": role_reason,
                                        }).execute()
                                        st.success("Role updated and recorded in the audit trail.")
                                        st.rerun()
                                    except Exception:
                                        st.error("Cadivor could not update this role. No change was confirmed.")

        with maintenance_tab:
            st.subheader("Maintenance mode")
            st.caption("When enabled, non-admin users are blocked after authentication. Administrators retain access to restore service.")
            maintenance_enabled = bool(overview.get("maintenance_mode"))
            with st.form("admin_maintenance_form"):
                next_maintenance_enabled = st.checkbox("Enable maintenance mode", value=maintenance_enabled)
                next_maintenance_message = st.text_area(
                    "Customer message",
                    value=overview.get("maintenance_message") or "Cadivor is undergoing scheduled maintenance. Please try again shortly.",
                    max_chars=280,
                )
                confirmation_phrase = "ENABLE MAINTENANCE" if next_maintenance_enabled else "DISABLE MAINTENANCE"
                maintenance_confirmation = st.text_input(f"Type {confirmation_phrase} to confirm")
                apply_maintenance = st.form_submit_button("Apply maintenance setting", type="primary")
                if apply_maintenance:
                    if maintenance_confirmation.strip() != confirmation_phrase:
                        st.error(f"Type {confirmation_phrase} exactly to continue.")
                    else:
                        try:
                            supabase.rpc("cadivor_admin_set_maintenance", {
                                "next_enabled": next_maintenance_enabled,
                                "next_message": next_maintenance_message,
                            }).execute()
                            st.success("Maintenance setting updated and recorded in the audit trail.")
                            st.rerun()
                        except Exception:
                            st.error("Cadivor could not update maintenance mode. No change was confirmed.")

        with support_tab:
            st.subheader("Support activity")
            st.caption("Privacy-safe operational timeline. It records sign-in sessions and page transitions, not passwords, BOM contents, searches, chat messages, or form text.")
            if support_activity_rows:
                support_frame = pd.DataFrame(support_activity_rows)
                event_labels = {
                    "session_started": "Session started",
                    "page_viewed": "Page viewed",
                }
                if "event_type" in support_frame:
                    support_frame["Activity"] = support_frame["event_type"].map(event_labels).fillna("Other activity")
                if "metadata" in support_frame:
                    def _support_detail(metadata):
                        detail = metadata if isinstance(metadata, dict) else {}
                        page = _safe_text(detail.get("page"), "")
                        return f"Visited {page}" if page else "—"
                    support_frame["Safe details"] = support_frame["metadata"].apply(_support_detail)
                if "created_at" in support_frame:
                    support_frame["When"] = pd.to_datetime(
                        support_frame["created_at"], utc=True, errors="coerce"
                    ).dt.strftime("%b %d, %Y · %I:%M %p UTC").fillna("—")
                if "email" in support_frame:
                    support_frame["User"] = support_frame["email"].fillna("—")
                if "full_name" in support_frame:
                    support_frame["Name"] = support_frame["full_name"].fillna("—")
                support_columns = [column for column in ("When", "User", "Name", "Activity", "Safe details") if column in support_frame]
                st.dataframe(
                    support_frame[support_columns],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No support activity has been recorded yet.")

        with audit_tab:
            st.subheader("Recent administrator activity")
            if audit_rows:
                audit_frame = pd.DataFrame(audit_rows)
                visible_audit_columns = [column for column in ("created_at", "action", "actor_id", "target_user_id", "metadata") if column in audit_frame]
                st.dataframe(audit_frame[visible_audit_columns], use_container_width=True, hide_index=True)
            else:
                st.caption("No administrative actions have been recorded yet.")
        stop_authenticated_page()

    # ---------- Settings ----------
    if app_mode == "Settings":
        profile = get_user_profile(current_user)
        auth_user = st.session_state.get("user")
        user_id = _safe_text(
            getattr(auth_user, "id", ""),
            _safe_text(current_user.get("id"), ""),
        )
        auth_email = _safe_text(
            getattr(auth_user, "email", ""),
            profile.get("email", ""),
        )

        customer_profile, profile_error = ensure_customer_profile(
            supabase,
            user_id,
            auth_email,
            profile.get("full_name", ""),
        )
        preferences, preferences_error = ensure_user_preferences(
            supabase,
            user_id,
        )

        customer_profile = customer_profile or {}
        preferences = preferences or {}

        st.markdown(
            """
            <style id="cadivor-customer-settings-v11a1">
            .cv-customer-hero{
                border:1px solid #BFDBFE;
                border-radius:24px;
                padding:26px 28px;
                margin-bottom:18px;
                background:
                    radial-gradient(circle at 95% 5%,rgba(37,99,235,.13),transparent 34%),
                    linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 100%);
                box-shadow:0 18px 46px rgba(15,23,42,.065);
            }
            .cv-customer-kicker{
                color:#2563EB;
                font-size:10px;
                font-weight:950;
                letter-spacing:.11em;
                text-transform:uppercase;
                margin-bottom:9px;
            }
            .cv-customer-title{
                color:#0F172A;
                font-size:31px;
                line-height:1.08;
                font-weight:950;
                letter-spacing:-.04em;
                margin:0 0 8px;
            }
            .cv-customer-copy{
                color:#52647A;
                font-size:14px;
                line-height:1.55;
                font-weight:680;
                margin:0;
                max-width:900px;
            }
            .cv-profile-card{
                border:1px solid #E2E8F0;
                border-radius:20px;
                background:#FFFFFF;
                padding:20px;
                box-shadow:0 14px 36px rgba(15,23,42,.05);
            }
            .cv-profile-top{
                display:flex;
                align-items:center;
                gap:15px;
                margin-bottom:16px;
            }
            .cv-profile-avatar{
                width:72px;
                height:72px;
                flex:0 0 72px;
                border-radius:20px;
                display:flex;
                align-items:center;
                justify-content:center;
                overflow:hidden;
                border:1px solid #BFDBFE;
                background:#EFF6FF;
                color:#1D4ED8;
                font-size:22px;
                font-weight:950;
            }
            .cv-profile-avatar img{
                width:100%;
                height:100%;
                object-fit:cover;
            }
            .cv-profile-name{
                color:#0F172A;
                font-size:18px;
                font-weight:950;
                margin-bottom:4px;
            }
            .cv-profile-role{
                color:#64748B;
                font-size:12px;
                font-weight:720;
            }
            .cv-profile-facts{
                display:grid;
                grid-template-columns:1fr;
                gap:9px;
            }
            .cv-profile-fact{
                border:1px solid #E2E8F0;
                border-radius:13px;
                padding:11px 12px;
                background:#F8FAFC;
            }
            .cv-profile-fact span{
                display:block;
                color:#64748B;
                font-size:9px;
                font-weight:950;
                letter-spacing:.09em;
                text-transform:uppercase;
                margin-bottom:5px;
            }
            .cv-profile-fact strong{
                display:block;
                color:#0F172A;
                font-size:12px;
                font-weight:900;
                overflow-wrap:anywhere;
            }
            .cv-settings-note{
                border:1px solid #DBEAFE;
                border-radius:15px;
                padding:13px 15px;
                background:#EFF6FF;
                color:#1E3A8A;
                font-size:11px;
                line-height:1.5;
                font-weight:700;
            }
            .cv-security-row{
                border:1px solid #E2E8F0;
                border-radius:15px;
                padding:14px;
                background:#FFFFFF;
                margin-bottom:10px;
            }
            .cv-security-row strong{
                display:block;
                color:#0F172A;
                font-size:13px;
                margin-bottom:4px;
            }
            .cv-security-row span{
                display:block;
                color:#64748B;
                font-size:11px;
                line-height:1.45;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            """
            <section class="cv-customer-hero">
              <div class="cv-customer-kicker">Customer account</div>
              <h1 class="cv-customer-title">Profile & preferences</h1>
              <p class="cv-customer-copy">
                Manage the personal identity, display defaults, and notification
                preferences Cadivor uses across engineering workspaces and reports.
              </p>
            </section>
            """,
            unsafe_allow_html=True,
        )

        settings_setup_done = completion_count(onboarding_progress or {})
        settings_setup_percent = int((settings_setup_done / 5) * 100)
        st.markdown(
            f"""
            <style id="cadivor-settings-setup-v11a3">
            .cv-settings-setup{{
                display:grid;grid-template-columns:1fr auto;gap:16px;align-items:center;
                border:1px solid #DBEAFE;border-radius:17px;background:#FFFFFF;
                padding:15px 17px;margin:0 0 14px;
                box-shadow:0 12px 28px rgba(15,23,42,.05);
            }}
            .cv-settings-setup strong{{
                display:block;color:#0F172A!important;font-size:13px;font-weight:950;
                margin-bottom:4px;
            }}
            .cv-settings-setup span{{
                color:#64748B!important;font-size:10px;font-weight:750;
            }}
            .cv-settings-setup b{{
                color:#2563EB!important;font-size:12px;font-weight:950;
            }}
            .cv-settings-setup-bar{{
                grid-column:1/-1;height:7px;border-radius:999px;background:#E2E8F0;
                overflow:hidden;
            }}
            .cv-settings-setup-bar i{{
                display:block;height:100%;width:{settings_setup_percent}%;
                background:#2563EB;border-radius:999px;
            }}
            </style>
            <section class="cv-settings-setup">
              <div>
                <strong>Customer setup</strong>
                <span>Profile, workspace, BOM, replacement, and reporting readiness</span>
              </div>
              <b>{settings_setup_done}/5 complete</b>
              <div class="cv-settings-setup-bar"><i></i></div>
            </section>
            """,
            unsafe_allow_html=True,
        )
        internal_nav_button(
            "Continue Customer Setup",
            "Onboarding",
            key="settings_open_onboarding",
            type="secondary",
        )

        migration_required = (
            profile_error == "migration_required"
            or preferences_error == "migration_required"
        )
        if migration_required:
            st.warning(
                "Some profile settings are temporarily unavailable. "
                "Your saved engineering data is unaffected. Please try again later."
            )

        profile_tab, preferences_tab, workspace_tab, security_tab, billing_tab = st.tabs(
            ["Profile", "Preferences", "Workspace", "Security", "Billing"]
        )

        with profile_tab:
            summary_col, form_col = st.columns([0.36, 0.64], gap="large")

            with summary_col:
                avatar_url_value = _safe_text(
                    customer_profile.get("avatar_url"),
                    profile.get("avatar_url", ""),
                )
                initials_value = profile.get("initials", "C")
                avatar_markup = (
                    f'<img src="{html.escape(avatar_url_value, quote=True)}" alt="Profile photo">'
                    if avatar_url_value
                    else html.escape(initials_value)
                )
                display_name = _safe_text(
                    customer_profile.get("full_name"),
                    profile.get("full_name", "Cadivor user"),
                )
                display_job = _safe_text(
                    customer_profile.get("job_title"),
                    profile.get("role_title", "Cadivor workspace member"),
                )
                display_company = _safe_text(
                    customer_profile.get("company_name"),
                    profile.get("company", "Not set"),
                )

                st.markdown(
                    f"""
                    <div class="cv-profile-card">
                      <div class="cv-profile-top">
                        <div class="cv-profile-avatar">{avatar_markup}</div>
                        <div>
                          <div class="cv-profile-name">{html.escape(display_name)}</div>
                          <div class="cv-profile-role">{html.escape(display_job)}</div>
                        </div>
                      </div>
                      <div class="cv-profile-facts">
                        <div class="cv-profile-fact">
                          <span>Email</span>
                          <strong>{html.escape(auth_email)}</strong>
                        </div>
                        <div class="cv-profile-fact">
                          <span>Company</span>
                          <strong>{html.escape(display_company)}</strong>
                        </div>
                        <div class="cv-profile-fact">
                          <span>Plan</span>
                          <strong>{html.escape(profile.get("plan", "Starter"))}</strong>
                        </div>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with form_col:
                with st.container(border=True):
                    st.subheader("Profile information")
                    st.caption(
                        "This information personalizes your account, team presence, "
                        "workspace records, and future report attribution."
                    )

                    full_name_value = st.text_input(
                        "Full name",
                        value=_safe_text(
                            customer_profile.get("full_name"),
                            profile.get("full_name", ""),
                        ),
                        placeholder="Joshua Kashambala",
                        key="customer_profile_full_name",
                    )
                    company_value = st.text_input(
                        "Company / organization",
                        value=_safe_text(
                            customer_profile.get("company_name"),
                            profile.get("company", ""),
                        ),
                        placeholder="Egres Technologies",
                        key="customer_profile_company",
                    )
                    job_title_value = st.text_input(
                        "Job title",
                        value=_safe_text(
                            customer_profile.get("job_title"),
                            profile.get("role_title", ""),
                        ),
                        placeholder="Founder, Engineering Lead, Sourcing Manager",
                        key="customer_profile_job_title",
                    )

                    phone_col, country_col = st.columns(2)
                    with phone_col:
                        phone_value = st.text_input(
                            "Phone",
                            value=_safe_text(
                                customer_profile.get("phone"),
                                profile.get("phone", ""),
                            ),
                            placeholder="+1 555 000 0000",
                            key="customer_profile_phone",
                        )
                    with country_col:
                        country_value = st.text_input(
                            "Country",
                            value=_safe_text(
                                customer_profile.get("country"),
                                profile.get("country", ""),
                            ),
                            placeholder="United States",
                            key="customer_profile_country",
                        )

                    timezone_value = st.text_input(
                        "Time zone",
                        value=_safe_text(
                            customer_profile.get("timezone"),
                            profile.get("timezone", ""),
                        ),
                        placeholder="America/New_York",
                        key="customer_profile_timezone",
                    )
                    avatar_value = st.text_input(
                        "Profile image URL",
                        value=_safe_text(
                            customer_profile.get("avatar_url"),
                            profile.get("avatar_url", ""),
                        ),
                        placeholder="https://example.com/profile.jpg",
                        key="customer_profile_avatar",
                    )
                    bio_value = st.text_area(
                        "Professional bio",
                        value=_safe_text(customer_profile.get("bio"), ""),
                        placeholder=(
                            "Optional short description shown in future collaboration "
                            "and approval workflows."
                        ),
                        height=110,
                        key="customer_profile_bio",
                    )

                    cadivor_button_wrap("primary")
                    if st.button(
                        "Save Profile",
                        type="primary",
                        disabled=migration_required,
                        key="save_customer_profile",
                    ):
                        saved_profile, save_error = update_customer_profile(
                            supabase,
                            user_id,
                            {
                                "full_name": full_name_value.strip(),
                                "company_name": company_value.strip(),
                                "job_title": job_title_value.strip(),
                                "phone": phone_value.strip(),
                                "country": country_value.strip(),
                                "timezone": timezone_value.strip(),
                                "avatar_url": avatar_value.strip(),
                                "bio": bio_value.strip(),
                            },
                        )
                        if save_error:
                            st.error(f"Unable to save profile: {save_error}")
                        else:
                            st.success("Customer profile saved.")
                            st.rerun()
                    cadivor_button_wrap_end()

        with preferences_tab:
            with st.container(border=True):
                st.subheader("Application preferences")
                st.caption(
                    "Set the defaults Cadivor should use when presenting engineering "
                    "information and sending product notifications."
                )

                appearance_options = ["System", "Light", "Dark"]
                saved_appearance = _safe_text(
                    preferences.get("appearance"),
                    "system",
                ).title()
                if saved_appearance not in appearance_options:
                    saved_appearance = "System"

                density_options = ["Comfortable", "Compact"]
                saved_density = _safe_text(
                    preferences.get("density"),
                    "comfortable",
                ).title()
                if saved_density not in density_options:
                    saved_density = "Comfortable"

                units_options = ["Metric", "Imperial"]
                saved_units = _safe_text(
                    preferences.get("default_units"),
                    "metric",
                ).title()
                if saved_units not in units_options:
                    saved_units = "Metric"

                currency_options = ["USD", "EUR", "GBP", "CAD"]
                saved_currency = _safe_text(
                    preferences.get("default_currency"),
                    "USD",
                ).upper()
                if saved_currency not in currency_options:
                    saved_currency = "USD"

                display_col, default_col = st.columns(2, gap="large")
                with display_col:
                    appearance_value = st.selectbox(
                        "Appearance",
                        appearance_options,
                        index=appearance_options.index(saved_appearance),
                        key="customer_preference_appearance",
                        help="Theme selection is stored now; full dark-theme support arrives in a later UI milestone.",
                    )
                    density_value = st.selectbox(
                        "Interface density",
                        density_options,
                        index=density_options.index(saved_density),
                        key="customer_preference_density",
                    )

                with default_col:
                    units_value = st.selectbox(
                        "Default units",
                        units_options,
                        index=units_options.index(saved_units),
                        key="customer_preference_units",
                    )
                    currency_value = st.selectbox(
                        "Default currency",
                        currency_options,
                        index=currency_options.index(saved_currency),
                        key="customer_preference_currency",
                    )

                st.subheader("Notification preferences")
                email_notifications = st.toggle(
                    "Account and product email",
                    value=bool(preferences.get("email_notifications", True)),
                    key="customer_pref_email",
                )
                workspace_notifications = st.toggle(
                    "Workspace collaboration updates",
                    value=bool(preferences.get("workspace_notifications", True)),
                    key="customer_pref_workspace",
                )
                monitoring_notifications = st.toggle(
                    "Monitoring and lifecycle alerts",
                    value=bool(preferences.get("monitoring_notifications", True)),
                    key="customer_pref_monitoring",
                )
                report_notifications = st.toggle(
                    "Report generation updates",
                    value=bool(preferences.get("report_notifications", True)),
                    key="customer_pref_reports",
                )

                cadivor_button_wrap("primary")
                if st.button(
                    "Save Preferences",
                    type="primary",
                    disabled=migration_required,
                    key="save_customer_preferences",
                ):
                    saved_preferences, save_error = update_user_preferences(
                        supabase,
                        user_id,
                        {
                            "appearance": appearance_value.lower(),
                            "density": density_value.lower(),
                            "default_units": units_value.lower(),
                            "default_currency": currency_value,
                            "email_notifications": email_notifications,
                            "workspace_notifications": workspace_notifications,
                            "monitoring_notifications": monitoring_notifications,
                            "report_notifications": report_notifications,
                        },
                    )
                    if save_error:
                        st.error(f"Unable to save preferences: {save_error}")
                    else:
                        st.success("Preferences saved.")
                        st.rerun()
                cadivor_button_wrap_end()

            st.markdown(
                """
                <div class="cv-settings-note">
                  Appearance and density preferences are now stored persistently.
                  Their full application across every page will be introduced after
                  the customer-settings foundation is stable.
                </div>
                """,
                unsafe_allow_html=True,
            )

        with workspace_tab:
            st.subheader("Workspace settings")
            st.caption(
                "Workspace identity, members, invitations, and engineering defaults "
                "are managed from the collaboration workspace."
            )
            internal_nav_button(
                "Open Workspace",
                "Workspace",
                key="settings_open_workspace",
                use_container_width=True,
            )

        with security_tab:
            st.subheader("Security")
            st.markdown(
                f"""
                <div class="cv-security-row">
                  <strong>Authenticated email</strong>
                  <span>{html.escape(auth_email)}</span>
                </div>
                <div class="cv-security-row">
                  <strong>Password management</strong>
                  <span>Password reset and change-password controls will be connected
                  in Milestone 11C using Supabase Auth.</span>
                </div>
                <div class="cv-security-row">
                  <strong>Two-factor authentication</strong>
                  <span>Planned for the security and authentication phase.</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with billing_tab:
            st.subheader("Plan & billing")
            st.caption(
                "Review Cadivor plans and upgrade the current account when the team "
                "requires higher BOM, monitoring, report, or member limits."
            )
            st.markdown(
                f"""
                <div class="cv-profile-card">
                  <div class="cv-profile-fact">
                    <span>Current plan</span>
                    <strong>{html.escape(profile.get("plan", "Starter"))}</strong>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            internal_nav_button(
                "View Plans",
                "Pricing",
                key="settings_view_plans",
                use_container_width=True,
            )

        stop_authenticated_page()


    # ---------- Workspace ----------
    if app_mode == "Workspace":
        profile = get_user_profile(current_user)
        auth_user = st.session_state.get("user")
        user_id = str(getattr(auth_user, "id", current_user.get("id", "")))
        owner_email = profile.get("email") or _safe_text(current_user.get("email"), "")
        owner_name = profile.get("full_name") or "Cadivor user"
        proposed_workspace_name = profile.get("workspace_name") or profile.get("company") or "Cadivor Workspace"

        default_workspace, workspace_error = ensure_personal_workspace(
            supabase,
            user_id,
            owner_email,
            owner_name,
            proposed_workspace_name,
            selected_plan_name,
        )

        available_workspaces, organizations_error = list_user_workspaces(supabase, user_id)
        preferred_workspace_id, preference_error = get_active_workspace_preference(
            supabase,
            user_id,
        )

        session_workspace_id = str(st.session_state.get("active_workspace_id") or "")
        requested_workspace_id = session_workspace_id or str(preferred_workspace_id or "")
        available_ids = {str(item.get("id")) for item in available_workspaces}

        if requested_workspace_id and requested_workspace_id in available_ids:
            workspace, active_workspace_error = get_workspace_by_id(
                supabase,
                user_id,
                requested_workspace_id,
            )
            workspace_error = active_workspace_error
        else:
            workspace = default_workspace
            if workspace and workspace.get("id"):
                st.session_state["active_workspace_id"] = str(workspace.get("id"))

        if not available_workspaces and workspace:
            available_workspaces = [workspace]

        st.markdown(
            """
            <style>
            .cv-ws-hero{border:1px solid #BFDBFE;border-radius:24px;padding:26px 28px;background:linear-gradient(135deg,#FFFFFF 0%,#EFF6FF 100%);box-shadow:0 18px 45px rgba(15,23,42,.06);margin-bottom:18px}
            .cv-ws-kicker{font-size:11px;font-weight:800;letter-spacing:.13em;text-transform:uppercase;color:#2563EB;margin-bottom:9px}
            .cv-ws-hero h1{font-size:34px;line-height:1.05;margin:0 0 9px;color:#0F172A}
            .cv-ws-hero p{max-width:780px;margin:0;color:#52647D;font-weight:600}
            .cv-ws-metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin:0 0 20px}
            .cv-ws-metric,.cv-ws-card{box-sizing:border-box;border:1px solid #E2E8F0;border-radius:18px;background:#FFFFFF;box-shadow:0 12px 30px rgba(15,23,42,.045)}
            .cv-ws-metric{padding:16px 18px;min-height:112px}
            .cv-ws-label{font-size:10px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#64748B}
            .cv-ws-value{font-size:27px;font-weight:850;color:#0F172A;margin:7px 0 2px}
            .cv-ws-note{font-size:12px;color:#64748B;font-weight:600}
            .cv-ws-card{padding:20px;margin-bottom:14px}
            .cv-ws-card h3{margin:0 0 6px;font-size:18px;color:#0F172A}
            .cv-ws-card p{margin:0;color:#64748B}
            .cv-ws-member{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(100px,.6fr) minmax(110px,.6fr);gap:12px;align-items:center;border:1px solid #E2E8F0;border-radius:15px;padding:13px 15px;margin:9px 0;background:#FBFDFF}
            .cv-ws-member strong{display:block;color:#0F172A}.cv-ws-member span{display:block;color:#64748B;font-size:12px;margin-top:2px}
            .cv-ws-role{display:inline-flex!important;width:max-content;padding:5px 10px;border-radius:999px;background:#EFF6FF;color:#1D4ED8!important;font-weight:800;text-transform:capitalize}
            .cv-ws-status{display:inline-flex!important;width:max-content;padding:5px 10px;border-radius:999px;background:#ECFDF5;color:#047857!important;font-weight:800;text-transform:capitalize}
            .cv-ws-activity{border-left:3px solid #BFDBFE;padding:2px 0 16px 16px;margin-left:6px}
            .cv-ws-activity strong{color:#0F172A}.cv-ws-activity span{display:block;color:#64748B;font-size:12px;margin-top:4px}
            .cv-ws-warning{border:1px solid #FDE68A;background:#FFFBEB;border-radius:18px;padding:18px;color:#92400E;margin:16px 0}
            .cv-org-card{border:1px solid #DBEAFE;border-radius:18px;background:#FFFFFF;padding:18px;box-shadow:0 12px 28px rgba(15,23,42,.045);margin-bottom:12px}
            .cv-org-card strong{display:block;color:#0F172A;font-size:15px}.cv-org-card span{display:block;color:#64748B;font-size:11px;margin-top:4px}
            .cv-org-active{display:inline-flex!important;width:max-content!important;margin-top:10px!important;padding:5px 9px;border-radius:999px;background:#ECFDF5;color:#047857!important;font-weight:850}
            .cv-collab-grid{display:grid;grid-template-columns:1.15fr .85fr;gap:14px;margin-bottom:14px}
            .cv-presence-row{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid #E2E8F0;border-radius:14px;padding:12px 13px;margin:8px 0;background:#FBFDFF}
            .cv-presence-person{display:flex;align-items:center;gap:10px;min-width:0}
            .cv-presence-dot{width:10px;height:10px;border-radius:999px;background:#22C55E;box-shadow:0 0 0 4px #DCFCE7}
            .cv-presence-dot.idle{background:#F59E0B;box-shadow:0 0 0 4px #FEF3C7}
            .cv-presence-dot.offline{background:#94A3B8;box-shadow:0 0 0 4px #F1F5F9}
            .cv-presence-row strong{display:block;color:#0F172A;font-size:12px}.cv-presence-row span{display:block;color:#64748B;font-size:10px;margin-top:2px}
            .cv-audit-row{display:grid;grid-template-columns:150px minmax(120px,.7fr) minmax(160px,1fr) minmax(0,1.7fr);gap:12px;align-items:center;border-bottom:1px solid #EEF2F7;padding:11px 4px}
            .cv-audit-row.header{background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;padding:10px 12px;color:#64748B;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.06em}
            .cv-audit-row strong{color:#0F172A;font-size:11px}.cv-audit-row span{color:#64748B;font-size:10px;overflow-wrap:anywhere}
            @media(max-width:900px){.cv-collab-grid{grid-template-columns:1fr}.cv-audit-row{grid-template-columns:1fr 1fr}}
            @media(max-width:900px){.cv-ws-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
            @media(max-width:620px){.cv-ws-metrics{grid-template-columns:1fr}.cv-ws-member{grid-template-columns:1fr}}
            </style>
            """,
            unsafe_allow_html=True,
        )

        if workspace_error == "migration_required":
            st.markdown(
                f"""
                <div class="cv-ws-hero">
                  <div class="cv-ws-kicker">Workspace & Team Collaboration</div>
                  <h1>{html.escape(proposed_workspace_name)}</h1>
                  <p>The collaboration interface is installed. Apply the included Milestone 10B Supabase migration to activate persistent members, invitations, activity, and notifications.</p>
                </div>
                <div class="cv-ws-warning"><strong>Database setup required.</strong><br>Run <code>supabase_migrations/20260712_milestone_10b_workspace_collaboration.sql</code> in the Supabase SQL Editor, then reload this page.</div>
                """,
                unsafe_allow_html=True,
            )
            st.info("Your existing BOM analyses and engineering decisions are not changed by this migration.")
            stop_authenticated_page()
        if workspace_error or not workspace:
            st.error(f"Unable to load the workspace: {workspace_error or 'Unknown workspace error'}")
            stop_authenticated_page()

        workspace_id = str(workspace.get("id"))
        current_role = str(workspace.get("current_role") or "viewer").lower()

        presence_error = touch_workspace_presence(
            supabase,
            workspace_id,
            user_id,
            owner_name,
            owner_email,
            "Workspace",
            workspace.get("name") or proposed_workspace_name,
        )
        can_administer = current_role in {"owner", "admin"}
        is_owner = current_role == "owner"

        members, members_error = list_members(supabase, workspace_id)
        invites, invites_error = list_invites(supabase, workspace_id)
        activity_rows, activity_error = list_activity(supabase, workspace_id, 75)
        presence_rows, presence_list_error = list_workspace_presence(
            supabase,
            workspace_id,
            25,
        )
        audit_rows, audit_error = list_audit_log(
            supabase,
            workspace_id,
            limit=250,
        )
        active_members = [row for row in members if row.get("status") == "active"]
        pending_invites = [row for row in invites if row.get("status") == "pending"]

        workspace_name = _safe_text(workspace.get("name"), proposed_workspace_name)
        st.markdown(
            f"""
            <div class="cv-ws-hero">
              <div class="cv-ws-kicker">Team Engineering Workspace</div>
              <h1>{html.escape(workspace_name)}</h1>
              <p>Manage workspace identity, engineering access, team invitations, collaboration activity, and notification readiness from one controlled workspace.</p>
            </div>
            <div class="cv-ws-metrics">
              <div class="cv-ws-metric"><div class="cv-ws-label">Plan</div><div class="cv-ws-value">{html.escape(selected_plan_name)}</div><div class="cv-ws-note">Current subscription</div></div>
              <div class="cv-ws-metric"><div class="cv-ws-label">Members</div><div class="cv-ws-value">{len(active_members)}</div><div class="cv-ws-note">Active workspace users</div></div>
              <div class="cv-ws-metric"><div class="cv-ws-label">Pending Invites</div><div class="cv-ws-value">{len(pending_invites)}</div><div class="cv-ws-note">Awaiting acceptance</div></div>
              <div class="cv-ws-metric"><div class="cv-ws-label">Saved Analyses</div><div class="cv-ws-value">{saved_bom_count}</div><div class="cv-ws-note">Shared engineering records</div></div>
              <div class="cv-ws-metric"><div class="cv-ws-label">Organizations</div><div class="cv-ws-value">{len(available_workspaces)}</div><div class="cv-ws-note">Accessible workspaces</div></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        (
            overview_tab,
            collaboration_tab,
            organizations_tab,
            members_tab,
            invitations_tab,
            activity_tab,
            audit_tab,
            settings_tab,
        ) = st.tabs(
            [
                "Overview",
                "Team Activity",
                "Organizations",
                "Members",
                "Invitations",
                "Workspace History",
                "Audit Log",
                "Settings",
            ]
        )

        with overview_tab:
            left, right = st.columns([1.25, .75], gap="large")
            with left:
                st.markdown(
                    f"""
                    <div class="cv-ws-card">
                      <h3>Workspace information</h3>
                      <p>Persistent identity and collaboration boundaries for your engineering records.</p>
                      <div class="cv-snapshot-grid" style="grid-template-columns:1fr 1fr;margin-top:15px">
                        <div class="cv-snapshot-item"><span>Workspace</span><strong>{html.escape(workspace_name)}</strong></div>
                        <div class="cv-snapshot-item"><span>Your role</span><strong>{html.escape(current_role.title())}</strong></div>
                        <div class="cv-snapshot-item"><span>Owner</span><strong>{html.escape(owner_name)}</strong></div>
                        <div class="cv-snapshot-item"><span>Created</span><strong>{html.escape(str(workspace.get('created_at',''))[:10] or 'Today')}</strong></div>
                        <div class="cv-snapshot-item"><span>Time zone</span><strong>{html.escape(_safe_text(workspace.get('timezone'),'UTC'))}</strong></div>
                        <div class="cv-snapshot-item"><span>Units</span><strong>{html.escape(_safe_text(workspace.get('unit_system'),'metric').title())}</strong></div>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown(
                    '<div class="cv-ws-card"><h3>Recent workspace activity</h3><p>Activity is collapsed by default so the overview remains compact. The complete audit timeline remains available in the Activity tab.</p></div>',
                    unsafe_allow_html=True,
                )
                if activity_error:
                    st.warning(f"Activity could not be loaded: {activity_error}")
                elif not activity_rows:
                    st.info("No workspace activity has been recorded yet.")
                else:
                    latest_activity = activity_rows[0]
                    st.markdown(
                        f'<div class="cv-ws-activity"><strong>{html.escape(_safe_text(latest_activity.get("summary"), "Workspace activity"))}</strong><span>{html.escape(_safe_text(latest_activity.get("actor_name"), "Cadivor"))} · {html.escape(str(latest_activity.get("created_at", ""))[:19].replace("T", " "))} UTC</span></div>',
                        unsafe_allow_html=True,
                    )
                    with st.expander(f"View recent activity ({min(len(activity_rows), 6)} events)", expanded=False):
                        for item in activity_rows[:6]:
                            st.markdown(
                                f'<div class="cv-ws-activity"><strong>{html.escape(_safe_text(item.get("summary"), "Workspace activity"))}</strong><span>{html.escape(_safe_text(item.get("actor_name"), "Cadivor"))} · {html.escape(str(item.get("created_at", ""))[:19].replace("T", " "))} UTC</span></div>',
                                unsafe_allow_html=True,
                            )
                        st.caption("Open the Activity tab for the complete workspace audit timeline.")
            with right:
                st.markdown(
                    f"""
                    <div class="cv-ws-card">
                      <h3>Collaboration readiness</h3>
                      <p>Organization switching, member boundaries, invitations, and role controls are active.</p>
                      <div class="cv-snapshot-grid" style="grid-template-columns:1fr;margin-top:15px">
                        <div class="cv-snapshot-item"><span>Member directory</span><strong>Active</strong></div>
                        <div class="cv-snapshot-item"><span>Invitation records</span><strong>Active</strong></div>
                        <div class="cv-snapshot-item"><span>Role controls</span><strong>{'Owner enabled' if is_owner else 'Permission controlled'}</strong></div>
                        <div class="cv-snapshot-item"><span>Email delivery</span><strong>Not connected yet</strong></div>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.caption("Organization membership is persistent. Saved BOM scoping and invitation acceptance links arrive in Milestone 11B.2.")

        with collaboration_tab:
            st.subheader("Team collaboration")
            st.caption(
                "See who is active, what the engineering team changed, and the "
                "latest organization events without leaving the workspace."
            )

            if presence_error == "migration_required" or presence_list_error == "migration_required":
                st.info(
                    "Run the Milestone 11C.1 migration to activate team presence "
                    "and the searchable audit log."
                )
            elif presence_list_error:
                st.error(f"Team presence could not be loaded: {presence_list_error}")

            now_utc = pd.Timestamp.utcnow()
            online_members = []
            idle_members = []
            offline_members = []
            for row in presence_rows:
                seen = pd.to_datetime(row.get("last_seen_at"), utc=True, errors="coerce")
                age_minutes = (
                    (now_utc - seen).total_seconds() / 60
                    if not pd.isna(seen)
                    else 999999
                )
                if age_minutes <= 10:
                    online_members.append(row)
                elif age_minutes <= 60:
                    idle_members.append(row)
                else:
                    offline_members.append(row)

            collaboration_left, collaboration_right = st.columns([1.15, 0.85], gap="medium")
            with collaboration_left:
                st.markdown("#### Live team presence")
                presence_display = online_members + idle_members + offline_members
                if not presence_display:
                    st.markdown(
                        '<div class="cv-analysis-empty">No team presence has been recorded yet.</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    presence_html = []
                    online_ids = {str(row.get("id")) for row in online_members}
                    idle_ids = {str(row.get("id")) for row in idle_members}
                    for row in presence_display[:12]:
                        row_id = str(row.get("id"))
                        state_class = "" if row_id in online_ids else "idle" if row_id in idle_ids else "offline"
                        state_label = "Online" if row_id in online_ids else "Idle" if row_id in idle_ids else "Offline"
                        presence_html.append(
                            f'<div class="cv-presence-row">'
                            f'<div class="cv-presence-person">'
                            f'<i class="cv-presence-dot {state_class}"></i>'
                            f'<div><strong>{html.escape(_safe_text(row.get("display_name"), row.get("email") or "Member"))}</strong>'
                            f'<span>{html.escape(_safe_text(row.get("page_name"), "Cadivor"))}'
                            f'{" · " + html.escape(_safe_text(row.get("object_label"), "")) if row.get("object_label") else ""}</span></div>'
                            f'</div><span>{state_label}</span></div>'
                        )
                    st.markdown("".join(presence_html), unsafe_allow_html=True)

            with collaboration_right:
                st.markdown("#### Collaboration snapshot")
                render_kpi_row_safe(
                    [
                        MetricCard(label="Online now", value=str(len(online_members)), tone="success", icon="radar"),
                        MetricCard(label="Active this hour", value=str(len(online_members) + len(idle_members)), tone="info", icon="clock-3"),
                        MetricCard(label="Activity events", value=str(len(activity_rows)), tone="monitoring", icon="clipboard-check"),
                        MetricCard(label="Audit records", value=str(len(audit_rows)), tone="confidence", icon="file-text"),
                    ],
                    columns=4,
                )

                st.markdown("#### Latest team events")
                if not activity_rows:
                    st.caption("No collaboration activity has been recorded.")
                else:
                    for row in activity_rows[:5]:
                        st.markdown(
                            f"""
                            <div class="cv-ws-activity">
                              <strong>{html.escape(_safe_text(row.get('actor_name'), 'Cadivor'))}</strong>
                              <span>{html.escape(_safe_text(row.get('summary'), row.get('action_type') or 'Workspace event'))}</span>
                              <span>{html.escape(str(row.get('created_at',''))[:19].replace('T',' '))} UTC</span>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

        with organizations_tab:
            st.subheader("Organizations")
            st.caption(
                "Switch between engineering organizations without signing out. "
                "Each organization has its own members, invitations, activity, and settings."
            )

            if organizations_error:
                st.error(f"Organizations could not be loaded: {organizations_error}")
            else:
                organization_lookup = {
                    f"{_safe_text(item.get('name'), 'Cadivor Workspace')} — {_safe_text(item.get('current_role'), 'viewer').title()}": item
                    for item in available_workspaces
                }
                current_label = next(
                    (
                        label
                        for label, item in organization_lookup.items()
                        if str(item.get("id")) == workspace_id
                    ),
                    next(iter(organization_lookup), ""),
                )

                if organization_lookup:
                    selected_organization_label = st.selectbox(
                        "Active organization",
                        list(organization_lookup.keys()),
                        index=list(organization_lookup.keys()).index(current_label)
                        if current_label in organization_lookup
                        else 0,
                        key="workspace_organization_switcher",
                    )
                    selected_organization = organization_lookup[selected_organization_label]
                    selected_organization_id = str(selected_organization.get("id"))

                    switch_col, status_col = st.columns([0.35, 0.65])
                    with switch_col:
                        switch_disabled = selected_organization_id == workspace_id
                        if st.button(
                            "Switch Organization",
                            type="primary",
                            disabled=switch_disabled,
                            use_container_width=True,
                            key="switch_active_organization",
                        ):
                            preference_save_error = set_active_workspace_preference(
                                supabase,
                                user_id,
                                selected_organization_id,
                            )
                            if preference_save_error:
                                st.error(preference_save_error)
                            else:
                                st.session_state["active_workspace_id"] = selected_organization_id
                                st.success("Active organization changed.")
                                st.rerun()
                    with status_col:
                        if selected_organization_id == workspace_id:
                            st.success(f"{workspace_name} is currently active.")
                        else:
                            st.info(
                                "Switching changes the member directory, invitations, "
                                "activity, and organization settings shown on this page."
                            )

                st.markdown("#### Organization directory")
                org_columns = st.columns(2)
                for index, item in enumerate(available_workspaces):
                    with org_columns[index % 2]:
                        is_active_org = str(item.get("id")) == workspace_id
                        st.markdown(
                            f"""
                            <div class="cv-org-card">
                              <strong>{html.escape(_safe_text(item.get('name'), 'Cadivor Workspace'))}</strong>
                              <span>{html.escape(_safe_text(item.get('current_role'), 'viewer').title())} access · {html.escape(_safe_text(item.get('plan'), 'starter').title())} plan</span>
                              {'<span class="cv-org-active">Active organization</span>' if is_active_org else ''}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

            st.markdown("#### Create another organization")
            st.caption(
                "Use a separate organization for another company, business unit, "
                "client environment, or engineering team."
            )
            new_org_name = st.text_input(
                "Organization name",
                placeholder="Example: Egres Engineering",
                key="new_organization_name",
            )
            if st.button(
                "Create Organization",
                type="primary",
                key="create_organization_workspace",
            ):
                created_org, create_org_error = create_organization_workspace(
                    supabase,
                    user_id,
                    owner_email,
                    owner_name,
                    new_org_name,
                    selected_plan_name,
                )
                if create_org_error:
                    st.error(create_org_error)
                elif created_org:
                    created_id = str(created_org.get("id"))
                    set_active_workspace_preference(supabase, user_id, created_id)
                    st.session_state["active_workspace_id"] = created_id
                    st.success(f"{_safe_text(created_org.get('name'), 'Organization')} was created.")
                    st.rerun()

            st.info(
                "Milestone 11B.1 establishes organization switching and membership boundaries. "
                "Saved BOM records will be assigned to organizations in Milestone 11B.2."
            )

        with members_tab:
            st.subheader("Workspace members")
            st.caption("Owners and admins manage access. Only the owner can change member roles in this foundation release.")
            if members_error:
                st.error(f"Members could not be loaded: {members_error}")
            elif not active_members:
                st.info("No active workspace members were found.")
            else:
                for member in active_members:
                    member_name = _safe_text(member.get("display_name"), _safe_text(member.get("email"), "Workspace member"))
                    member_email = _safe_text(member.get("email"), "")
                    member_role = _safe_text(member.get("role"), "viewer").lower()
                    st.markdown(
                        f'<div class="cv-ws-member"><div><strong>{html.escape(member_name)}</strong><span>{html.escape(member_email)}</span></div><div><span class="cv-ws-role">{html.escape(member_role)}</span></div><div><span class="cv-ws-status">{html.escape(_safe_text(member.get("status"),"active"))}</span></div></div>',
                        unsafe_allow_html=True,
                    )
                    if is_owner and member_role != "owner":
                        c1, c2, c3 = st.columns([1.1, .7, 2.2])
                        role_options = ["admin", "engineer", "viewer"]
                        with c1:
                            selected_role = st.selectbox(
                                "Role",
                                role_options,
                                index=role_options.index(member_role) if member_role in role_options else 2,
                                key=f"member_role_{member.get('id')}",
                                label_visibility="collapsed",
                            )
                        with c2:
                            if st.button("Update role", key=f"update_member_{member.get('id')}", use_container_width=True):
                                error = update_member_role(supabase, workspace_id, str(member.get("id")), selected_role, user_id, owner_name, member_email)
                                if error:
                                    st.error(error)
                                else:
                                    st.success(f"{member_email} is now {selected_role}.")
                                    st.rerun()
                        with c3:
                            if st.button("Remove member", key=f"remove_member_{member.get('id')}"):
                                st.session_state["workspace_remove_member"] = str(member.get("id"))
                        if st.session_state.get("workspace_remove_member") == str(member.get("id")):
                            st.warning(f"Remove {member_email} from this workspace? Their account will not be deleted.")
                            yes_col, no_col = st.columns(2)
                            with yes_col:
                                if st.button("Yes, remove member", key=f"confirm_remove_{member.get('id')}", type="primary"):
                                    error = remove_member(supabase, workspace_id, str(member.get("id")), user_id, owner_name, member_email)
                                    st.session_state.pop("workspace_remove_member", None)
                                    if error:
                                        st.error(error)
                                    else:
                                        st.success("Member removed.")
                                        st.rerun()
                            with no_col:
                                if st.button("Cancel", key=f"cancel_remove_{member.get('id')}"):
                                    st.session_state.pop("workspace_remove_member", None)
                                    st.rerun()

        with invitations_tab:
            st.subheader("Invite team members")
            st.caption("Create persistent invitations for admins, engineers, or viewers. Email delivery is not connected in this release.")
            if can_administer:
                invite_email = st.text_input("Email address", placeholder="engineer@company.com", key="workspace_invite_email")
                invite_role = st.selectbox("Workspace role", ["Engineer", "Viewer", "Admin"], key="workspace_invite_role")
                if st.button("Create Invitation", type="primary", key="create_workspace_invite"):
                    created, error = create_invite(supabase, workspace_id, invite_email, invite_role.lower(), user_id, owner_name)
                    if error:
                        st.error(error)
                    else:
                        st.success("Workspace invitation created. Email delivery will be connected in a later capability.")
                        st.rerun()
            else:
                st.info("Only workspace owners and admins can create invitations.")

            st.markdown("#### Pending invitations")
            if invites_error:
                st.error(f"Invitations could not be loaded: {invites_error}")
            elif not pending_invites:
                st.info("No invitations are waiting for acceptance.")
            else:
                invite_df = pd.DataFrame(
                    [
                        {
                            "Email": row.get("email"),
                            "Role": _safe_text(row.get("role"), "engineer").title(),
                            "Status": _safe_text(row.get("status"), "pending").title(),
                            "Invited By": _safe_text(row.get("invited_by_name"), owner_name),
                            "Created": str(row.get("created_at", ""))[:10],
                            "Expires": str(row.get("expires_at", ""))[:10],
                        }
                        for row in pending_invites
                    ]
                )
                cadivor_engineering_dataframe(
                    invite_df,
                    column_config={
                        "Email": st.column_config.TextColumn(width="medium"),
                        "Role": st.column_config.TextColumn(width="small"),
                        "Status": st.column_config.TextColumn(width="small"),
                    },
                )
                if can_administer:
                    invite_lookup = {f"{row.get('email')} — {str(row.get('created_at',''))[:10]}": row for row in pending_invites}
                    selected_invite_label = st.selectbox("Select an invitation to cancel", list(invite_lookup.keys()))
                    if st.button(
                        "Cancel Selected Invitation",
                        type="primary",
                        use_container_width=False,
                        key="cancel_selected_workspace_invitation",
                    ):
                        selected_invite = invite_lookup[selected_invite_label]
                        error = cancel_invite(supabase, workspace_id, str(selected_invite.get("id")), user_id, owner_name, _safe_text(selected_invite.get("email"), ""))
                        if error:
                            st.error(error)
                        else:
                            st.success("Invitation cancelled.")
                            st.rerun()

        with activity_tab:
            st.subheader("Workspace history")
            st.caption(
                "Review human-readable team and workspace administration events. "
                "Technical database action names are intentionally hidden from this view."
            )
            if activity_error:
                st.error(f"Workspace history could not be loaded: {activity_error}")
            elif not activity_rows:
                st.info("No workspace history has been recorded yet.")
            else:
                history_categories = sorted(
                    {category_label(event_category(row.get("action"), row.get("object_type"))) for row in activity_rows}
                )
                hist_a, hist_b, hist_c = st.columns([0.28, 0.52, 0.20])
                with hist_a:
                    selected_history_category = st.selectbox(
                        "Event category",
                        ["All categories"] + history_categories,
                        key="workspace_history_category",
                    )
                with hist_b:
                    history_search = st.text_input(
                        "Search workspace history",
                        placeholder="Search person, action, or summary",
                        key="workspace_history_search",
                    ).strip().lower()
                with hist_c:
                    history_limit = st.selectbox(
                        "Rows",
                        [25, 50, 75],
                        index=1,
                        key="workspace_history_limit",
                    )

                filtered_history = []
                for row in activity_rows:
                    category = category_label(event_category(row.get("action"), row.get("object_type")))
                    title = action_label(row.get("action"))
                    summary = friendly_summary(row)
                    actor = _safe_text(row.get("actor_name"), "Cadivor user")
                    if selected_history_category != "All categories" and category != selected_history_category:
                        continue
                    if history_search and history_search not in " ".join([category, title, summary, actor]).lower():
                        continue
                    filtered_history.append(
                        {
                            "Date": display_time(row.get("created_at")),
                            "Actor": actor,
                            "Category": category,
                            "Action": title,
                            "Summary": summary,
                        }
                    )

                st.caption(f"Showing {min(len(filtered_history), history_limit)} of {len(filtered_history)} matching events.")
                if not filtered_history:
                    st.info("No workspace events match the current filters.")
                else:
                    cadivor_engineering_dataframe(
                        pd.DataFrame(filtered_history[:history_limit]),
                        height=min(520, 75 + 36 * min(len(filtered_history), history_limit)),
                    )

        with audit_tab:
            st.subheader("Engineering audit log")
            st.caption(
                "Search customer-friendly engineering events. Raw backend actions remain "
                "available only inside the technical-details expander and CSV export."
            )

            if audit_error == "migration_required":
                st.info("Run the Milestone 11C.1 migration to activate the audit log.")
            elif audit_error:
                st.error(f"Audit log could not be loaded: {audit_error}")
            else:
                categories = sorted(
                    {category_label(event_category(row.get("action_type"), row.get("object_type"))) for row in audit_rows}
                )
                actor_names = sorted(
                    {
                        _safe_text(row.get("actor_name"), row.get("actor_email") or "System")
                        for row in audit_rows
                    }
                )
                filter_a, filter_b, filter_c, filter_d = st.columns([0.22, 0.22, 0.36, 0.20])
                with filter_a:
                    selected_category = st.selectbox(
                        "Category",
                        ["All categories"] + categories,
                        key="audit_category_filter",
                    )
                with filter_b:
                    selected_actor_label = st.selectbox(
                        "Actor",
                        ["All people"] + actor_names,
                        key="audit_actor_filter_friendly",
                    )
                with filter_c:
                    audit_search = st.text_input(
                        "Search audit records",
                        placeholder="BOM, component, report, teammate, or action",
                        key="audit_search_filter_friendly",
                    ).strip().lower()
                with filter_d:
                    audit_limit = st.selectbox(
                        "Rows",
                        [25, 50, 100],
                        index=1,
                        key="audit_display_limit",
                    )

                friendly_audit = []
                for row in audit_rows:
                    category = category_label(event_category(row.get("action_type"), row.get("object_type")))
                    actor = _safe_text(row.get("actor_name"), row.get("actor_email") or "System")
                    action_title = action_label(row.get("action_type"))
                    summary = friendly_summary(row)
                    searchable = " ".join(
                        [category, actor, action_title, summary, _safe_text(row.get("object_label"), "")]
                    ).lower()
                    if selected_category != "All categories" and category != selected_category:
                        continue
                    if selected_actor_label != "All people" and actor != selected_actor_label:
                        continue
                    if audit_search and audit_search not in searchable:
                        continue
                    friendly_audit.append(
                        {
                            "Time": display_time(row.get("created_at")),
                            "Actor": actor,
                            "Category": category,
                            "Action": action_title,
                            "Details": summary,
                            "Raw Action": _safe_text(row.get("action_type"), ""),
                            "Object Type": _safe_text(row.get("object_type"), ""),
                            "Object ID": _safe_text(row.get("object_id"), ""),
                            "Object Label": _safe_text(row.get("object_label"), ""),
                            "Raw Summary": _safe_text(row.get("summary"), ""),
                        }
                    )

                st.caption(f"Showing {min(len(friendly_audit), audit_limit)} of {len(friendly_audit)} matching audit records.")
                if not friendly_audit:
                    st.info("No audit records match the current filters.")
                else:
                    display_columns = ["Time", "Actor", "Category", "Action", "Details"]
                    cadivor_engineering_dataframe(
                        pd.DataFrame(friendly_audit[:audit_limit])[display_columns],
                        height=min(560, 75 + 36 * min(len(friendly_audit), audit_limit)),
                    )

                    record_options = {
                        f"{row['Time']} — {row['Action']} — {row['Actor']}": row
                        for row in friendly_audit[:audit_limit]
                    }
                    with st.expander("View technical details", expanded=False):
                        selected_record_label = st.selectbox(
                            "Audit record",
                            list(record_options.keys()),
                            key="audit_technical_record",
                        )
                        selected_record = record_options[selected_record_label]
                        st.caption(
                            "These identifiers are intended for support, troubleshooting, and API integrations."
                        )
                        technical_cols = st.columns(2)
                        technical_cols[0].code(
                            f"Raw action: {selected_record['Raw Action']}\n"
                            f"Object type: {selected_record['Object Type']}"
                        )
                        technical_cols[1].code(
                            f"Object ID: {selected_record['Object ID']}\n"
                            f"Object label: {selected_record['Object Label']}"
                        )

                    audit_export = pd.DataFrame(friendly_audit).to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "Export Audit Log CSV",
                        data=audit_export,
                        file_name=f"{re.sub(r'[^A-Za-z0-9_-]+', '_', workspace_name)}_audit_log.csv",
                        mime="text/csv",
                        type="primary",
                    )

        with settings_tab:
            st.subheader("Workspace settings")
            st.caption("Workspace owners and admins control the shared identity and engineering defaults.")
            if can_administer:
                settings_name = st.text_input("Workspace name", value=workspace_name, key="workspace_settings_name")
                settings_timezone = st.text_input("Time zone", value=_safe_text(workspace.get("timezone"), profile.get("timezone") or "UTC"), key="workspace_settings_timezone")
                settings_units = st.selectbox("Default unit system", ["metric", "imperial"], index=0 if _safe_text(workspace.get("unit_system"), "metric") == "metric" else 1, key="workspace_settings_units")
                if st.button("Save Workspace Settings", type="primary"):
                    error = update_workspace(supabase, workspace_id, settings_name, settings_timezone, settings_units, user_id, owner_name)
                    if error:
                        st.error(error)
                    else:
                        st.success("Workspace settings saved.")
                        st.rerun()
            else:
                st.info("Only workspace owners and admins can update workspace settings.")
            st.markdown(
                f"""
                <div class="cv-ws-card">
                  <h3>Workspace identifiers</h3>
                  <p>Use these values when support or future API integrations need to identify this workspace.</p>
                  <div class="cv-snapshot-grid" style="grid-template-columns:1fr;margin-top:15px">
                    <div class="cv-snapshot-item"><span>Workspace ID</span><strong>{html.escape(workspace_id)}</strong></div>
                    <div class="cv-snapshot-item"><span>Owner ID</span><strong>{html.escape(_safe_text(workspace.get('owner_id'), user_id))}</strong></div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        stop_authenticated_page()

    # ---------- Notifications ----------
    if app_mode == "Notifications":
        profile = get_user_profile(current_user)
        auth_user = st.session_state.get("user")
        user_id = str(getattr(auth_user, "id", current_user.get("id", "")))
        workspace = active_workspace
        workspace_error = None if workspace else "Workspace unavailable"
        st.markdown(
            """
            <div class="cv-dashboard-header">
              <div>
                <div class="cv-eyebrow">Notification Center</div>
                <h1 class="cv-title">Workspace updates</h1>
                <p class="cv-subtitle">Review collaboration events and workspace notifications alongside Cadivor monitoring alerts.</p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if workspace_error == "migration_required":
            st.info("Apply the Milestone 10B Supabase migration to activate workspace notifications.")
            stop_authenticated_page()
        if workspace_error or not workspace:
            st.error(f"Unable to load notifications: {workspace_error or 'Workspace unavailable'}")
            stop_authenticated_page()

        notification_rows, notification_error = list_notifications(supabase, str(workspace.get("id")), user_id, 75)
        unread_rows = [row for row in notification_rows if not row.get("is_read")]
        n1, n2, n3 = st.columns(3)
        n1.metric("Unread", len(unread_rows))
        n2.metric("Workspace Updates", len(notification_rows))
        n3.metric("Monitoring Alerts", int(active_alert_count if 'active_alert_count' in globals() else 0))

        if unread_rows:
            if st.button(
                "Mark All Workspace Notifications Read",
                type="primary",
                key="mark_all_workspace_notifications_read",
            ):
                mark_all_error = mark_all_notifications_read(
                    supabase,
                    str(workspace.get("id")),
                    user_id,
                )
                if mark_all_error:
                    st.error(mark_all_error)
                else:
                    st.success("All workspace notifications were marked as read.")
                    st.rerun()

        workspace_updates_tab, monitoring_tab = st.tabs(["Workspace Updates", "Monitoring Alerts"])
        with workspace_updates_tab:
            if notification_error:
                st.error(f"Notifications could not be loaded: {notification_error}")
            elif not notification_rows:
                empty_state("No workspace notifications", "Invitations, role changes, generated reports, and collaboration updates will appear here.", "Open Workspace", "?page=Workspace", "●")
            else:
                for row in notification_rows:
                    state = "Unread" if not row.get("is_read") else "Read"
                    st.markdown(
                        f"""
                        <div class="cv-panel" style="margin-bottom:10px">
                          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
                            <div><div class="cv-panel-title">{html.escape(_safe_text(row.get('title'),'Workspace update'))}</div><div class="cv-panel-copy">{html.escape(_safe_text(row.get('message'),''))}</div></div>
                            <span class="cv-status-pill {'success' if state == 'Read' else 'warning'}">{state}</span>
                          </div>
                          <div class="cv-panel-copy" style="margin-top:8px">{html.escape(str(row.get('created_at',''))[:19].replace('T',' '))} UTC</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if not row.get("is_read") and st.button("Mark as read", key=f"read_notification_{row.get('id')}"):
                        error = mark_notification_read(supabase, str(row.get("id")))
                        if error:
                            st.error(error)
                        else:
                            st.rerun()
        with monitoring_tab:
            st.info("Lifecycle, stock, and supplier events remain available in the Monitoring dashboard. Milestone 10B keeps them separate from team collaboration notifications to avoid duplicate records.")
            if st.button("Open Monitoring Dashboard", type="primary"):
                navigate_to("Monitoring")
        stop_authenticated_page()

    # ---------- Resources / Help ----------
    if app_mode == "Help":
        st.markdown('<div class="cv-help-shell cv64-page-shell">', unsafe_allow_html=True)
        cadivor_section_header("Cadivor Resources", eyebrow="Training library", description="Choose a topic to open a practical, step-by-step Cadivor guide.", icon="clipboard")
        st.markdown(
            """
            <style>
              .cv-resource-category{margin:22px 0 10px;color:#3B5880;font-size:12px;font-weight:900;letter-spacing:.09em;text-transform:uppercase}.cv-resource-detail-head{padding:22px;border:1px solid #D9E5F5;border-radius:18px;background:linear-gradient(135deg,#F7FAFF,#FFF);margin:8px 0 18px}.cv-resource-detail-head h2{margin:5px 0;color:#11284B}.cv-resource-detail-head p{margin:0;color:#58708F;line-height:1.55}.cv-resource-steps{border:1px solid #D9E5F5;border-radius:16px;background:#fff;padding:20px}.cv-resource-steps h3{margin:0 0 12px;color:#11284B}.cv-resource-step{display:flex;gap:12px;margin:14px 0;color:#395574;line-height:1.55}.cv-resource-step b{display:inline-flex;align-items:center;justify-content:center;min-width:28px;height:28px;border-radius:50%;background:#2865EB;color:#fff;font-size:12px}.cv-resource-screen-caption{border:1px solid #D8EADF;background:#F6FFFA;border-radius:12px;padding:12px 14px;color:#276047;line-height:1.55;margin-top:10px}.cv-resource-note{border:1px solid #D8EADF;background:#F6FFFA;border-radius:14px;padding:14px 16px;color:#276047;line-height:1.55;margin:16px 0}
            </style>
            """,
            unsafe_allow_html=True,
        )
        tutorials = [
            ("profile", "Set up your profile & workspace", "Settings", "Configure your profile, workspace details, security, and billing.", ["Open Settings from the sidebar.", "Choose the Profile, Preferences, Workspace, Security, or Billing area.", "Save only the changes you want to apply."]),
            ("dashboard", "Use the Dashboard", "Dashboard", "Understand the workspace summary and continue an active review.", ["Open Dashboard.", "Review the health, priority risk, and saved-analysis summaries.", "Use a shortcut or open a saved analysis to continue work."]),
            ("bom", "Upload and analyze a BOM", "BOM Analyzer", "Create a saved engineering review from a CSV or Excel BOM.", ["Open BOM Analyzer and start a new analysis.", "Download the 10-part sample BOM or upload your own CSV/XLSX file.", "Review validation, name the project, and save the analysis."]),
            ("ask", "Ask Cadivor about a BOM", "BOM Analyzer", "Ask an evidence-backed engineering question about a saved analysis.", ["Open a saved analysis in BOM Analyzer.", "Enter one focused question in Ask Cadivor.", "Select Ask Cadivor once, then read the direct answer and evidence."]),
            ("alternatives", "Find and compare alternatives", "Alternative Finder", "Evaluate potential alternates without treating them as automatic replacements.", ["Open Alternative Finder from the sidebar.", "Search for the affected manufacturer part number.", "Compare compatibility, sourcing evidence, and required engineering checks."]),
            ("impact", "Use Design Impact", "Design Impact Analyzer", "Understand how component choices can affect the engineering review.", ["Open Design Impact Analyzer.", "Select the relevant part or saved analysis context.", "Use the result to identify what needs engineering attention."]),
            ("decisions", "Record an engineering decision", "Engineering Decisions", "Capture approval, rejection, or risk acceptance with supporting evidence.", ["Open Engineering Decisions.", "Review the evidence and required checks before choosing a disposition.", "Save the decision record and export it when needed."]),
            ("procurement", "Use Procurement Advisor", "Procurement Advisor", "Prioritize the sourcing actions that deserve procurement attention.", ["Open Procurement Advisor.", "Review supplier coverage, availability, and risk signals.", "Use the recommended actions as a procurement review plan."]),
            ("cost", "Use Cost Optimization", "Cost Optimization", "Identify defensible cost-review opportunities without compromising engineering approval.", ["Open Cost Optimization.", "Review the candidate parts and stated assumptions.", "Validate impact with engineering and procurement before acting."]),
            ("supply", "Build a Supply Scenario", "Supply Risk Scenario", "Explore how supply conditions may affect the parts in a BOM.", ["Open Supply Risk Scenario from the sidebar.", "Choose the saved BOM or component context you want to review.", "Compare the scenario results and identify mitigation actions."]),
            ("monitoring", "Monitor a component", "Monitoring", "Track saved component and supply signals after the initial review.", ["Open Monitoring.", "Select the component or BOM you want to follow.", "Review changes and return to the engineering decision when evidence changes."]),
            ("portfolio", "Use Portfolio Intelligence", "Portfolio Intelligence", "Review risk and readiness across saved engineering work.", ["Open Portfolio Intelligence.", "Review portfolio-level health and priority items.", "Open the underlying BOM when an item needs action."]),
            ("reports", "Create and export reports", "Reports", "Generate decision-ready summaries from saved analyses.", ["Open Reports.", "Select the saved BOM and report type.", "Preview the scope, then export the report package."]),
            ("admin", "Use the Admin Console", "Admin Console", "Manage operational controls and understand live account activity (administrators only).", ["Open Admin Console if your account has administrator access.", "Review users, support activity, maintenance controls, and the audit trail.", "Use operational controls carefully; they can affect other users."]),
        ]
        tutorial_image_root = Path(__file__).resolve().parent / "assets" / "resources" / "tutorials"
        tutorial_screens = {
            "alternatives": [
                {
                    "image": "alternative-finder-01-enter-part.jpg",
                    "caption": "Step 1: Enter the complete manufacturer part number used in the BOM.",
                },
                {
                    "image": "alternative-finder-02-run-search.jpg",
                    "caption": "Step 2: Select Find Alternatives once to start the comparison.",
                },
                {
                    "image": "alternative-finder-03-review-baseline.jpg",
                    "caption": "Step 3: Review Cadivor's baseline before comparing candidates and recording a decision.",
                },
            ],
        }
        selected_id = st.session_state.get("cadivor_resources_tutorial")
        selected = next((tutorial for tutorial in tutorials if tutorial[0] == selected_id), None)
        if not selected:
            st.markdown("### Browse tutorials")
            st.caption("Choose a feature to open its training page. Each guide includes steps, a screen example, and a direct link to the feature.")
            for category, ids in (("Getting started", {"profile", "dashboard", "bom", "ask"}), ("Engineering & supply decisions", {"alternatives", "impact", "decisions", "procurement", "cost", "supply", "monitoring", "portfolio"}), ("Operations", {"reports", "admin"})):
                st.markdown(f"<div class='cv-resource-category'>{category}</div>", unsafe_allow_html=True)
                for row in range(0, len([tutorial for tutorial in tutorials if tutorial[0] in ids]), 2):
                    row_tutorials = [tutorial for tutorial in tutorials if tutorial[0] in ids][row:row + 2]
                    for column, tutorial in zip(st.columns(2), row_tutorials):
                        with column:
                            with st.container(border=True):
                                st.markdown(f"#### {tutorial[1]}")
                                st.caption(tutorial[3])
                                if st.button("Open tutorial →", key=f"resources_open_{tutorial[0]}", use_container_width=True):
                                    st.session_state["cadivor_resources_tutorial"] = tutorial[0]
                                    st.rerun()
        else:
            tutorial_index = tutorials.index(selected)
            tutorial_id, title, destination, summary, steps = selected
            if st.button("← Back to all tutorials", key="resources_back_library"):
                st.session_state.pop("cadivor_resources_tutorial", None)
                st.rerun()
            st.markdown(f"<section class='cv-resource-detail-head'><div class='cv-resource-category'>Cadivor training</div><h2>{title}</h2><p>{summary}</p></section>", unsafe_allow_html=True)
            steps_column, image_column = st.columns([1, 1.25])
            with steps_column:
                st.markdown("<div class='cv-resource-steps'><h3>Steps</h3>", unsafe_allow_html=True)
                for number, step in enumerate(steps, start=1):
                    st.markdown(f"<div class='cv-resource-step'><b>{number}</b><span>{step}</span></div>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
            with image_column:
                step_key = f"cadivor_resources_step_{tutorial_id}"
                current_step = int(st.session_state.get(step_key, 0) or 0)
                current_step = max(0, min(current_step, len(steps) - 1))
                st.session_state[step_key] = current_step
                step_tabs = st.columns(len(steps))
                for number, column in enumerate(step_tabs, start=1):
                    with column:
                        if st.button(f"Step {number}", key=f"resources_step_{tutorial_id}_{number}", use_container_width=True):
                            st.session_state[step_key] = number - 1
                            st.rerun()
                screens = tutorial_screens.get(tutorial_id, [])
                if len(screens) == len(steps):
                    screen = screens[current_step]
                    screen_path = tutorial_image_root / screen["image"]
                    st.image(
                        str(screen_path),
                        caption=f"Screen {current_step + 1} of {len(screens)} — {screen['caption']}",
                        use_container_width=True,
                    )
                    st.markdown(
                        f"<div class='cv-resource-screen-caption'><strong>What to do now:</strong> {html.escape(steps[current_step])}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.info(
                        "This lesson's action-specific screenshot sequence is being prepared. "
                        "The written steps remain available, but Cadivor will not show a generic or unrelated image in its place."
                    )
            st.markdown("<div class='cv-resource-note'><strong>Training note:</strong> Cadivor recommendations and scenarios support engineering judgment. Review evidence and complete the required checks before approving a replacement, procurement action, or release decision.</div>", unsafe_allow_html=True)
            previous_col, open_col, next_col = st.columns(3)
            with previous_col:
                if tutorial_index > 0 and st.button("← Previous tutorial", key="resources_previous", use_container_width=True):
                    st.session_state["cadivor_resources_tutorial"] = tutorials[tutorial_index - 1][0]
                    st.rerun()
            with open_col:
                if st.button(f"Open {destination}", key="resources_open_destination", type="primary", use_container_width=True):
                    navigate_to(destination)
            with next_col:
                if tutorial_index < len(tutorials) - 1 and st.button("Next tutorial →", key="resources_next", use_container_width=True):
                    st.session_state["cadivor_resources_tutorial"] = tutorials[tutorial_index + 1][0]
                    st.rerun()
        st.markdown("<div class='cv-resource-note'><strong>Need help with a real BOM?</strong> Email support@cadivor.com with the workflow step where you are blocked. Do not include confidential BOM details in email.</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        stop_authenticated_page()

    # ---------- About ----------
    if app_mode == "About":
        st.subheader("About Cadivor")
        st.caption("Engineering intelligence for electronics teams.")

        col1, col2 = st.columns([2, 1])

        with col1:
            st.markdown(
                """
                <div class="card">
                    <div class="card-title">What We Do</div>
                    <div class="card-text">
                        Cadivor helps engineering and supply chain teams identify obsolete,
                        unavailable, single-source, and high-risk components before they create production delays.
                        <br><br>
                        The platform combines supplier data, lifecycle signals, sourcing risk, and alternative
                        component recommendations into one workflow.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown(
                """
                <div class="card">
                    <div class="card-title">Core Capabilities</div>
                    <div class="card-text">
                        ✓ BOM risk analysis<br>
                        ✓ Multi-supplier availability checks<br>
                        ✓ Alternative component ranking<br>
                        ✓ Executive-ready reports<br>
                        ✓ Subscription-based usage controls
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with col2:
            st.markdown(
                """
                <div class="card">
                    <div class="card-title">Built For</div>
                    <div class="card-text">
                        • Electrical engineers<br>
                        • Manufacturing engineers<br>
                        • Supply chain teams<br>
                        • Hardware startups<br>
                        • Engineering managers
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        stop_authenticated_page()

    if app_mode == "Admin":
        st.subheader("Admin Dashboard")
        st.caption("Platform usage, customer activity, and subscription oversight.")

        users_response = (
            supabase.table("users")
            .select("*")
            .execute()
        )

        users_data = users_response.data
        total_users = len(users_data)

        active_subscriptions = len(
            [user for user in users_data if user.get("plan") != "Starter"]
        )

        analyses_response = (
            supabase.table("analyses")
            .select("*")
            .execute()
        )

        analyses_data = analyses_response.data
        total_boms_analyzed = len(analyses_data)

        starter_count = len(
            [user for user in users_data if user.get("plan") == "Starter"]
        )
        pro_count = len(
            [user for user in users_data if user.get("plan") == "Pro"]
        )
        business_count = len(
            [user for user in users_data if user.get("plan") == "Business"]
        )

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-label">Total Users</div>
                    <div class="kpi-value">{total_users}</div>
                    <div class="kpi-note">+12 this month</div>
                </div>
                """,
                unsafe_allow_html=True,
        )

        with col2:
            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-label">Active Subscriptions</div>
                    <div class="kpi-value">{active_subscriptions}</div>
                    <div class="kpi-note">82% retention</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with col3:
            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-label">BOMs Analyzed</div>
                    <div class="kpi-value">{total_boms_analyzed}</div>
                    <div class="kpi-note">↑ 18% growth</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with col4:
            st.markdown(
                """
                <div class="kpi-card">
                    <div class="kpi-label">Revenue</div>
                    <div class="kpi-value">$4,920</div>
                    <div class="kpi-note">Monthly recurring revenue</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.divider()

        st.subheader("Plan Distribution")

        plan_df = pd.DataFrame(
            {
                "Plan": ["Starter", "Pro", "Business"],
                "Users": [starter_count, pro_count, business_count],
            }
        )

        st.bar_chart(plan_df, x="Plan", y="Users")

        st.subheader("Recent User Activity")

        activity_df = pd.DataFrame(users_data)

        if not activity_df.empty:
            activity_df = activity_df.rename(
                columns={
                    "email": "User",
                    "plan": "Plan",
                    "monthly_upload_count": "BOMs Used",
                    "created_at": "Created At",
                }
            )

            display_cols = [
                "User",
                "Plan",
                "BOMs Used",
                "Created At",
            ]

            activity_display_df = activity_df[display_cols]

            cadivor_engineering_dataframe(activity_display_df)

        else:
            st.info("No users found.")

        stop_authenticated_page()

    if app_mode == "Alternative Finder":

        from integrations.supplier_aggregator import get_best_part_data
        from src.alternative_engine import suggest_alternatives_v2, compare_parts, rank_alternatives
        from src.datasheet_comparison import (
            build_datasheet_comparison,
            build_pdf_field_evidence,
            extract_datasheet_text,
        )
        from src.alternative_reasoning import build_alternative_reasoning
        from src.risk_engine import calculate_risk
        return_analysis_id = str(
            _qp_value("return_analysis_id")
            or st.session_state.get("cadivor_alt_finder_return_analysis_id", "")
            or ""
        ).strip()
        return_page = str(
            _qp_value("return_page")
            or st.session_state.get("cadivor_alt_finder_return_page", "")
            or ""
        ).strip()
        return_mpn = str(
            _qp_value("return_mpn")
            or st.session_state.get("cadivor_alt_finder_return_mpn", "")
            or ""
        ).strip()
        if return_page == "Design Impact Analyzer":
            def _return_to_design_impact() -> None:
                st.session_state["design_impact_mpn"] = return_mpn
                st.session_state.pop("cadivor_alt_finder_return_page", None)
                st.session_state.pop("cadivor_alt_finder_return_mpn", None)
                navigate_to("Design Impact Analyzer", _rerun=False, mpn=return_mpn)

            st.button(
                "← Back to Design Impact",
                key="alternative_back_to_design_impact",
                type="secondary",
                on_click=_return_to_design_impact,
            )
        elif return_analysis_id:
            def _return_to_saved_bom() -> None:
                return_section = str(
                    st.session_state.get("cadivor_alt_finder_return_analysis_section", "")
                    or "Components"
                ).strip()
                st.session_state["cadivor_active_analysis_id"] = return_analysis_id
                st.session_state["cadivor_pending_analysis_section"] = return_section
                st.session_state["cadivor_pending_analysis_section_id"] = return_analysis_id
                st.session_state.pop("cadivor_alt_finder_return_analysis_id", None)
                st.session_state.pop("cadivor_alt_finder_return_analysis_section", None)
                navigate_to(
                    "Analysis Details",
                    _rerun=False,
                    analysis_id=return_analysis_id,
                    analysis_tab=return_section,
                )

            st.button(
                "← Back to Saved BOM",
                key="alternative_back_to_saved_bom",
                type="secondary",
                on_click=_return_to_saved_bom,
            )

        st.markdown(
            """
            <style id="cadivor-alternative-finder-62a1">
            /* Milestone 6.2C.3 — safe Supabase snapshot serialization */
            .st-key-af62_hero,
            .st-key-af62_search,
            .st-key-af62_summary,
            .st-key-af62_tips {
                background:#FFFFFF!important;
                border:1px solid #E2E8F0!important;
                border-radius:22px!important;
                box-shadow:0 18px 46px rgba(15,23,42,.055)!important;
            }

            .st-key-af62_hero {
                padding:28px 30px!important;
                margin-bottom:18px!important;
                background:
                    radial-gradient(circle at 92% 10%,rgba(37,99,235,.10),transparent 30%),
                    linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 65%,#EEF5FF 100%)!important;
                border-color:#BFDBFE!important;
            }

            .st-key-af62_search,
            .st-key-af62_summary,
            .st-key-af62_tips {
                padding:22px!important;
            }

            .st-key-af62_search {
                margin-bottom:18px!important;
            }

            .af62-eyebrow {
                display:inline-flex;
                align-items:center;
                gap:8px;
                padding:7px 11px;
                border-radius:999px;
                background:#EFF6FF;
                border:1px solid #BFDBFE;
                color:#2563EB!important;
                font-size:10px;
                font-weight:950;
                letter-spacing:.11em;
                text-transform:uppercase;
                margin-bottom:16px;
            }

            .af62-title {
                color:#0B1220!important;
                font-size:36px;
                line-height:1.05;
                font-weight:980;
                letter-spacing:-.045em;
                margin:0 0 10px;
            }

            .af62-copy {
                color:#52647A!important;
                font-size:15px;
                line-height:1.65;
                font-weight:680;
                max-width:850px;
                margin:0;
            }

            .af62-card-head {
                display:flex;
                align-items:flex-start;
                justify-content:space-between;
                gap:14px;
                margin-bottom:16px;
            }

            .af62-card-title {
                color:#0B1220!important;
                font-size:19px;
                line-height:1.15;
                font-weight:960;
                letter-spacing:-.035em;
                margin:0;
            }

            .af62-card-subtitle {
                color:#64748B!important;
                font-size:12px;
                line-height:1.45;
                font-weight:720;
                margin-top:5px;
            }

            .af62-icon {
                width:42px;
                height:42px;
                border-radius:14px;
                display:flex;
                align-items:center;
                justify-content:center;
                flex:0 0 auto;
                background:#EFF6FF;
                border:1px solid #BFDBFE;
                color:#2563EB!important;
            }

            .af62-icon.green {
                background:#ECFDF5;
                border-color:#A7F3D0;
                color:#059669!important;
            }

            .af62-icon.amber {
                background:#FFFBEB;
                border-color:#FDE68A;
                color:#D97706!important;
            }

            .af62-search-label {
                color:#334155!important;
                font-size:12px;
                font-weight:850;
                margin-bottom:7px;
            }

            .st-key-af62_search [data-testid="stTextInput"] input {
                min-height:50px!important;
                border-radius:13px!important;
                border:1px solid #CBD5E1!important;
                background:#FFFFFF!important;
                color:#0F172A!important;
                font-size:14px!important;
                font-weight:720!important;
                padding-left:15px!important;
            }

            .st-key-af62_search [data-testid="stTextInput"] input:focus {
                border-color:#60A5FA!important;
                box-shadow:0 0 0 4px rgba(37,99,235,.12)!important;
            }

            .st-key-af62_search div.stButton > button {
                width:100%!important;
                min-height:50px!important;
                border-radius:13px!important;
                font-size:13px!important;
                font-weight:900!important;
            }

            .af62-summary-grid {
                display:grid;
                grid-template-columns:repeat(2,minmax(0,1fr));
                gap:10px;
                margin-top:4px;
            }

            .af62-field {
                padding:12px;
                border-radius:14px;
                background:#F8FAFC;
                border:1px solid #E2E8F0;
                min-height:72px;
            }

            .af62-field span {
                display:block;
                color:#64748B!important;
                font-size:9px;
                font-weight:950;
                text-transform:uppercase;
                letter-spacing:.09em;
                margin-bottom:7px;
            }

            .af62-field strong {
                display:block;
                color:#0B1220!important;
                font-size:13px;
                font-weight:900;
                line-height:1.35;
                overflow-wrap:anywhere;
            }

            .af62-search-status {
                display:inline-flex;
                align-items:center;
                gap:7px;
                margin-top:14px;
                padding:7px 10px;
                border-radius:999px;
                background:#EFF6FF;
                border:1px solid #BFDBFE;
                color:#2563EB!important;
                font-size:10px;
                font-weight:900;
            }

            .af62-search-status:before {
                content:"";
                width:7px;
                height:7px;
                border-radius:50%;
                background:#2563EB;
                box-shadow:0 0 0 3px rgba(37,99,235,.12);
            }

            .af62-search-status.success {
                background:#ECFDF5;
                border-color:#A7F3D0;
                color:#047857!important;
            }

            .af62-search-status.success:before {
                background:#10B981;
                box-shadow:0 0 0 3px rgba(16,185,129,.12);
            }

            .af62-search-status.warning {
                background:#FFFBEB;
                border-color:#FDE68A;
                color:#B45309!important;
            }

            .af62-search-status.warning:before {
                background:#F59E0B;
                box-shadow:0 0 0 3px rgba(245,158,11,.12);
            }

            .af62-data-link {
                color:#2563EB!important;
                text-decoration:none!important;
                font-weight:900!important;
            }

            .af62-data-link:hover {
                text-decoration:underline!important;
            }

            .af62-field.risk-low {
                background:#F0FDF4;
                border-color:#BBF7D0;
            }

            .af62-field.risk-medium {
                background:#FFFBEB;
                border-color:#FDE68A;
            }

            .af62-field.risk-high {
                background:#FEF2F2;
                border-color:#FECACA;
            }

            .af62-tips {
                display:grid;
                gap:11px;
            }

            .af62-tip {
                display:grid;
                grid-template-columns:28px minmax(0,1fr);
                gap:10px;
                align-items:start;
                color:#52647A!important;
                font-size:12px;
                line-height:1.5;
                font-weight:720;
            }

            .af62-tip-num {
                width:26px;
                height:26px;
                display:flex;
                align-items:center;
                justify-content:center;
                border-radius:9px;
                background:#EFF6FF;
                border:1px solid #BFDBFE;
                color:#2563EB!important;
                font-size:10px;
                font-weight:950;
            }

            .af62-examples {
                display:flex;
                flex-wrap:wrap;
                gap:8px;
                margin-top:14px;
            }

            .af62-chip {
                display:inline-flex;
                align-items:center;
                padding:7px 9px;
                border-radius:999px;
                background:#F8FAFC;
                border:1px solid #E2E8F0;
                color:#334155!important;
                font-size:10px;
                font-weight:850;
            }

            @media(max-width:900px){
                .af62-title{font-size:30px;}
                .af62-summary-grid{grid-template-columns:1fr;}
            }

            /* Milestone 6.2B — Best Recommendation Experience */
            .af62b-section-head{
                display:flex;
                align-items:flex-start;
                justify-content:space-between;
                gap:16px;
                margin:28px 0 12px;
            }

            .af62b-section-title{
                color:#0B1220!important;
                font-size:22px;
                font-weight:980;
                letter-spacing:-.04em;
                line-height:1.1;
            }

            .af62b-section-meta{
                color:#64748B!important;
                font-size:12px;
                font-weight:760;
                line-height:1.45;
                margin-top:5px;
            }

            .af62b-found-pill{
                display:inline-flex;
                align-items:center;
                gap:7px;
                padding:7px 10px;
                border-radius:999px;
                background:#ECFDF5;
                border:1px solid #A7F3D0;
                color:#047857!important;
                font-size:10px;
                font-weight:950;
                white-space:nowrap;
            }

            .af62b-found-pill:before{
                content:"";
                width:7px;
                height:7px;
                border-radius:50%;
                background:#10B981;
                box-shadow:0 0 0 3px rgba(16,185,129,.12);
            }

            .st-key-af62b_best_card{
                padding:22px!important;
                border:1px solid #BFDBFE!important;
                border-radius:22px!important;
                background:
                    radial-gradient(circle at 95% 0%, rgba(37,99,235,.12), transparent 32%),
                    linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 100%)!important;
                box-shadow:0 20px 52px rgba(37,99,235,.10)!important;
            }

            .af62b-best-top{
                display:flex;
                align-items:flex-start;
                justify-content:space-between;
                gap:18px;
                margin-bottom:18px;
            }

            .af62b-eyebrow{
                display:inline-flex;
                align-items:center;
                gap:7px;
                padding:7px 10px;
                border-radius:999px;
                background:#EFF6FF;
                border:1px solid #BFDBFE;
                color:#2563EB!important;
                font-size:10px;
                font-weight:950;
                letter-spacing:.08em;
                text-transform:uppercase;
                margin-bottom:11px;
            }

            .af62b-best-part{
                color:#0B1220!important;
                font-size:30px;
                font-weight:980;
                line-height:1;
                letter-spacing:-.05em;
                margin-bottom:9px;
            }

            .af62b-best-copy{
                color:#52647A!important;
                font-size:13px;
                line-height:1.55;
                font-weight:750;
                max-width:720px;
            }

            .af62b-score{
                width:112px;
                min-width:112px;
                height:112px;
                border-radius:24px;
                display:flex;
                flex-direction:column;
                align-items:center;
                justify-content:center;
                background:#FFFFFF;
                border:1px solid #BFDBFE;
                box-shadow:0 14px 34px rgba(37,99,235,.10);
            }

            .af62b-score strong{
                color:#2563EB!important;
                font-size:31px;
                line-height:1;
                font-weight:980;
            }

            .af62b-score span{
                color:#64748B!important;
                font-size:9px;
                font-weight:950;
                text-transform:uppercase;
                letter-spacing:.08em;
                margin-top:7px;
                text-align:center;
            }

            .af62b-metrics{
                display:grid;
                grid-template-columns:repeat(5,minmax(0,1fr));
                gap:10px;
                margin-top:4px;
            }

            .af62b-metric{
                min-width:0;
                padding:14px;
                border-radius:16px;
                background:#FFFFFF;
                border:1px solid #E2E8F0;
            }

            .af62b-metric span{
                display:block;
                color:#64748B!important;
                font-size:9px;
                font-weight:950;
                letter-spacing:.08em;
                text-transform:uppercase;
                margin-bottom:7px;
            }

            .af62b-metric strong{
                display:block;
                color:#0B1220!important;
                font-size:16px;
                line-height:1.25;
                font-weight:950;
                overflow-wrap:anywhere;
            }

            .af62b-metric.good{
                background:#F0FDF4;
                border-color:#BBF7D0;
            }

            .af62b-metric.warn{
                background:#FFFBEB;
                border-color:#FDE68A;
            }

            .af7-intelligence-card{
                border:1px solid #cbdcfb;
                border-radius:22px;
                padding:22px 24px;
                margin:18px 0 16px;
                background:
                    radial-gradient(circle at 100% 0%, rgba(37,99,235,.12), transparent 35%),
                    linear-gradient(135deg,#ffffff 0%,#f8fbff 100%);
                box-shadow:0 18px 42px rgba(15,23,42,.07);
            }
            .af7-intelligence-top{
                display:flex;
                justify-content:space-between;
                gap:18px;
                align-items:flex-start;
                margin-bottom:14px;
            }
            .af7-intelligence-eyebrow{
                color:#2563eb;
                font-size:11px;
                font-weight:900;
                letter-spacing:.11em;
                text-transform:uppercase;
                margin-bottom:7px;
            }
            .af7-intelligence-title{
                color:#0f172a;
                font-size:22px;
                line-height:1.15;
                font-weight:900;
                margin-bottom:6px;
            }
            .af7-intelligence-summary{
                color:#475569;
                font-size:14px;
                line-height:1.55;
                max-width:980px;
            }
            .af7-confidence-badge{
                flex:0 0 auto;
                border:1px solid #bfdbfe;
                border-radius:999px;
                background:#eff6ff;
                color:#1d4ed8;
                padding:8px 12px;
                font-size:12px;
                font-weight:850;
                white-space:nowrap;
            }
            .af7-factor-grid{
                display:grid;
                grid-template-columns:repeat(5,minmax(0,1fr));
                gap:10px;
                margin-top:16px;
            }
            .af7-factor{
                border:1px solid #dbe3ef;
                border-radius:16px;
                background:rgba(255,255,255,.88);
                padding:13px 14px;
                min-height:104px;
            }
            .af7-factor span{
                display:block;
                color:#64748b;
                font-size:9px;
                font-weight:900;
                letter-spacing:.10em;
                text-transform:uppercase;
                margin-bottom:7px;
            }
            .af7-factor strong{
                display:block;
                color:#0f172a;
                font-size:16px;
                line-height:1.25;
                margin-bottom:8px;
            }
            .af7-factor p{
                color:#64748b;
                font-size:11px;
                line-height:1.38;
                margin:0;
            }
            .af7-meter{
                height:6px;
                border-radius:999px;
                background:#e2e8f0;
                overflow:hidden;
                margin-top:10px;
            }
            .af7-meter > i{
                display:block;
                height:100%;
                border-radius:999px;
                background:#2563eb;
            }
            .af7-meter.good > i{background:#10b981;}
            .af7-meter.warn > i{background:#f59e0b;}
            .af7-meter.bad > i{background:#ef4444;}
            .af122-decision{border:1px solid #bfdbfe;background:linear-gradient(135deg,#ffffff,#eff6ff);border-radius:22px;padding:18px;margin:14px 0;box-shadow:0 14px 36px rgba(37,99,235,.07)}
            .af122-decision-top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.af122-eyebrow{font-size:9px;font-weight:950;letter-spacing:.09em;text-transform:uppercase;color:#2563eb;margin-bottom:6px}.af122-title{font-size:20px;font-weight:950;color:#0f172a;letter-spacing:-.025em}.af122-copy{font-size:11px;font-weight:700;color:#52647a;line-height:1.55;margin-top:5px}
            .af122-badge{border-radius:999px;padding:7px 10px;font-size:9px;font-weight:950;white-space:nowrap;border:1px solid #bfdbfe;background:#eff6ff;color:#1d4ed8}.af122-badge.good{border-color:#a7f3d0;background:#ecfdf5;color:#047857}.af122-badge.warn{border-color:#fde68a;background:#fffbeb;color:#b45309}.af122-badge.bad{border-color:#fecaca;background:#fef2f2;color:#b91c1c}
            .af122-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:14px}.af122-metric{border:1px solid #dbe3ef;background:#fff;border-radius:14px;padding:11px}.af122-metric span{display:block;font-size:8px;font-weight:950;text-transform:uppercase;letter-spacing:.07em;color:#64748b;margin-bottom:5px}.af122-metric strong{font-size:12px;font-weight:900;color:#0f172a;line-height:1.35}
            .af122-lists{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}.af122-list{border:1px solid #e2e8f0;background:#fff;border-radius:16px;padding:13px}.af122-list.good{border-color:#bbf7d0;background:#f0fdf4}.af122-list.warn{border-color:#fde68a;background:#fffbeb}.af122-list.bad{border-color:#fecaca;background:#fef2f2}.af122-list h4{font-size:10px;font-weight:950;text-transform:uppercase;letter-spacing:.07em;color:#0f172a;margin:0 0 8px}.af122-list div{font-size:10px;font-weight:700;color:#475569;line-height:1.5;margin:5px 0;padding-left:12px;position:relative}.af122-list div:before{content:"•";position:absolute;left:0;color:#2563eb}
            @media(max-width:900px){.af122-grid,.af122-lists{grid-template-columns:1fr}.af122-decision-top{display:block}.af122-badge{display:inline-block;margin-top:10px}}
            .af7-explain-note{
                color:#64748b;
                font-size:11px;
                line-height:1.45;
                margin-top:12px;
            }

            .af62b-analysis-grid{
                display:grid;
                grid-template-columns:repeat(4,minmax(0,1fr));
                gap:12px;
                margin:16px 0 6px;
            }

            .af62b-analysis-card{
                min-height:126px;
                padding:15px;
                border-radius:17px;
                background:#FFFFFF;
                border:1px solid #E2E8F0;
                box-shadow:0 10px 26px rgba(15,23,42,.035);
            }

            .af62b-analysis-card.good{
                background:#F0FDF4;
                border-color:#BBF7D0;
            }

            .af62b-analysis-card.warning{
                background:#FFFBEB;
                border-color:#FDE68A;
            }

            .af62b-analysis-card.tradeoff{
                background:#FEF2F2;
                border-color:#FECACA;
            }

            .af62b-analysis-title{
                color:#0B1220!important;
                font-size:12px;
                font-weight:950;
                margin-bottom:10px;
            }

            .af62b-analysis-list{
                display:grid;
                gap:7px;
            }

            .af62b-analysis-item{
                color:#52647A!important;
                font-size:11px;
                font-weight:740;
                line-height:1.4;
            }

            .af62b-analysis-empty{
                color:#94A3B8!important;
                font-size:11px;
                font-weight:740;
            }

            .af62b-compare-head{
                display:flex;
                align-items:center;
                justify-content:space-between;
                gap:14px;
                margin:18px 0 10px;
            }

            .af62b-compare-title{
                color:#0B1220!important;
                font-size:17px;
                font-weight:970;
                letter-spacing:-.025em;
            }

            .af62b-compare-sub{
                color:#64748B!important;
                font-size:11px;
                font-weight:740;
                margin-top:3px;
            }

            .af62b-compact-table [data-testid="stDataFrame"]{
                border:1px solid #E2E8F0;
                border-radius:16px;
                overflow:hidden;
            }

            .af62b-reset-note{
                color:#64748B!important;
                font-size:11px;
                font-weight:740;
                margin-top:8px;
            }

            @media(max-width:1100px){
                .af62b-metrics{grid-template-columns:repeat(2,minmax(0,1fr));}
                .af62b-analysis-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
                .af7-factor-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
            }

            @media(max-width:760px){
                .af62b-best-top{flex-direction:column;}
                .af62b-score{width:100%;height:auto;min-height:88px;}
                .af62b-metrics{grid-template-columns:1fr;}
                .af62b-analysis-grid{grid-template-columns:1fr;}
                .af7-factor-grid{grid-template-columns:1fr;}
            }

            /* Milestone 6.2B.1 — results cleanup and focused actions */
            .af62b-action-note{
                color:#64748B!important;
                font-size:11px;
                font-weight:760;
                line-height:1.45;
                padding-top:8px;
            }
            .af62b-shortlist-pill{
                display:inline-flex;
                align-items:center;
                gap:7px;
                padding:7px 10px;
                border-radius:999px;
                background:#ECFDF5;
                border:1px solid #A7F3D0;
                color:#047857!important;
                font-size:10px;
                font-weight:950;
            }
            .af62b-shortlist-pill:before{
                content:"";
                width:7px;
                height:7px;
                border-radius:50%;
                background:#10B981;
            }
            .af62b-advanced-copy{
                color:#64748B!important;
                font-size:12px;
                font-weight:740;
                line-height:1.5;
                margin:0 0 12px;
            }
            .st-key-af62b_compact_table [data-testid="stDataFrame"]{
                max-height:430px!important;
                overflow:auto!important;
            }
            .st-key-af62b_save_candidate button,
            .st-key-af62b_advanced_compare button{
                border-radius:12px!important;
                font-weight:900!important;
            }
            @media(max-width:760px){
                .af62b-action-note{padding-top:0;}
            }

            /* Milestone 6.3A — Engineering Decision Workspace */
            .af63-score-label{
                display:inline-flex;
                align-items:center;
                gap:6px;
                margin-top:8px;
                padding:5px 8px;
                border-radius:999px;
                background:#ECFDF5;
                border:1px solid #A7F3D0;
                color:#047857!important;
                font-size:9px;
                font-weight:950;
                text-transform:uppercase;
                letter-spacing:.06em;
            }

            .af63-score-label.medium{
                background:#FFFBEB;
                border-color:#FDE68A;
                color:#B45309!important;
            }

            .af63-score-label.low{
                background:#FEF2F2;
                border-color:#FECACA;
                color:#B91C1C!important;
            }

            .af63-decision-shell{
                margin:18px 0 14px;
                padding:18px;
                border-radius:20px;
                background:#FFFFFF;
                border:1px solid #E2E8F0;
                box-shadow:0 14px 34px rgba(15,23,42,.045);
            }

            .af63-decision-head{
                display:flex;
                align-items:flex-start;
                justify-content:space-between;
                gap:16px;
                margin-bottom:15px;
            }

            .af63-decision-title{
                color:#0B1220!important;
                font-size:18px;
                font-weight:980;
                letter-spacing:-.035em;
                line-height:1.1;
            }

            .af63-decision-copy{
                color:#64748B!important;
                font-size:11px;
                font-weight:760;
                line-height:1.45;
                margin-top:5px;
            }

            .af63-decision-status{
                display:inline-flex;
                align-items:center;
                gap:7px;
                padding:7px 10px;
                border-radius:999px;
                background:#F8FAFC;
                border:1px solid #CBD5E1;
                color:#475569!important;
                font-size:10px;
                font-weight:950;
                white-space:nowrap;
            }

            .af63-decision-status.approved{
                background:#ECFDF5;
                border-color:#A7F3D0;
                color:#047857!important;
            }

            .af63-decision-status.rejected{
                background:#FEF2F2;
                border-color:#FECACA;
                color:#B91C1C!important;
            }

            .af63-decision-status.saved{
                background:#EFF6FF;
                border-color:#BFDBFE;
                color:#1D4ED8!important;
            }

            .af63-decision-grid{
                display:grid;
                grid-template-columns:repeat(4,minmax(0,1fr));
                gap:10px;
                margin-bottom:14px;
            }

            .af63-decision-metric{
                padding:13px 14px;
                border-radius:15px;
                background:#F8FAFC;
                border:1px solid #E2E8F0;
            }

            .af63-decision-metric span{
                display:block;
                color:#64748B!important;
                font-size:9px;
                font-weight:950;
                letter-spacing:.08em;
                text-transform:uppercase;
                margin-bottom:7px;
            }

            .af63-decision-metric strong{
                display:block;
                color:#0B1220!important;
                font-size:15px;
                font-weight:950;
                line-height:1.25;
            }

            .af63-action-help{
                color:#64748B!important;
                font-size:10px;
                line-height:1.45;
                font-weight:740;
                padding-top:5px;
            }

            .st-key-af63_approve button{
                background:#16A34A!important;
                border-color:#16A34A!important;
                color:#FFFFFF!important;
                border-radius:12px!important;
                font-weight:900!important;
            }

            .st-key-af63_reject button{
                background:#FFFFFF!important;
                border-color:#FCA5A5!important;
                color:#B91C1C!important;
                border-radius:12px!important;
                font-weight:900!important;
            }

            .st-key-af63_save button,
            .st-key-af63_download button{
                border-radius:12px!important;
                font-weight:900!important;
            }

            .af63-saved-message{
                display:inline-flex;
                align-items:center;
                gap:7px;
                min-height:42px;
                padding:0 12px;
                border-radius:12px;
                background:#ECFDF5;
                border:1px solid #A7F3D0;
                color:#047857!important;
                font-size:11px;
                font-weight:950;
            }

            @media(max-width:1000px){
                .af63-decision-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
            }

            @media(max-width:700px){
                .af63-decision-head{flex-direction:column;}
                .af63-decision-grid{grid-template-columns:1fr;}
            }

            /* Milestone 6.2C — Persistent Engineering Decision Records */
            .af62c-persist-note{
                display:flex;
                align-items:flex-start;
                gap:9px;
                padding:11px 12px;
                border-radius:14px;
                background:#EFF6FF;
                border:1px solid #BFDBFE;
                color:#1E40AF!important;
                font-size:10px;
                line-height:1.45;
                font-weight:800;
                margin:10px 0 0;
            }

            .af62c-persist-note:before{
                content:"";
                width:8px;
                height:8px;
                min-width:8px;
                margin-top:3px;
                border-radius:50%;
                background:#2563EB;
                box-shadow:0 0 0 3px rgba(37,99,235,.12);
            }

            .af62c-history-head{
                display:flex;
                align-items:center;
                justify-content:space-between;
                gap:12px;
                margin-bottom:10px;
            }

            .af62c-history-count{
                display:inline-flex;
                align-items:center;
                padding:6px 9px;
                border-radius:999px;
                background:#F8FAFC;
                border:1px solid #CBD5E1;
                color:#475569!important;
                font-size:9px;
                font-weight:950;
            }

            .af62c-db-success{
                display:inline-flex;
                align-items:center;
                gap:7px;
                min-height:42px;
                padding:0 12px;
                border-radius:12px;
                background:#ECFDF5;
                border:1px solid #A7F3D0;
                color:#047857!important;
                font-size:11px;
                font-weight:950;
            }

            .af62c-db-warning{
                padding:10px 12px;
                border-radius:12px;
                background:#FFFBEB;
                border:1px solid #FDE68A;
                color:#92400E!important;
                font-size:10px;
                line-height:1.45;
                font-weight:800;
            }

            .st-key-af62c_archive button{
                border-radius:10px!important;
                border-color:#FCA5A5!important;
                color:#B91C1C!important;
                font-weight:900!important;
            }

            .st-key-af63_change_package button,
            .st-key-af63_download button{
                min-height:44px!important;
                border-radius:12px!important;
                font-weight:900!important;
            }
            /* Alternative Finder launch polish: readable, responsive evidence. */
            .af62-field span,
            .af62b-metric span,
            .af62b-score span,
            .af7-factor span,
            .af63-decision-metric span,
            .af122-metric span,
            .af122-eyebrow,
            .af122-list h4{
                font-size:11px!important;
                letter-spacing:.045em!important;
                line-height:1.45!important;
            }

            .af62-field strong,
            .af62b-metric strong,
            .af7-factor strong,
            .af63-decision-metric strong,
            .af122-metric strong{
                font-size:16px!important;
                line-height:1.4!important;
                overflow-wrap:anywhere;
            }

            .af62-card-subtitle,
            .af62b-section-meta,
            .af62b-compare-sub,
            .af62b-analysis-item,
            .af7-factor p,
            .af7-explain-note,
            .af122-copy,
            .af122-list div,
            .af63-action-help{
                font-size:13px!important;
                line-height:1.6!important;
            }

            .af62b-metrics,
            .af7-factor-grid,
            .af62b-analysis-grid,
            .af63-decision-grid,
            .af122-grid,
            .af122-lists{
                gap:14px!important;
            }

            .af62b-metric,
            .af7-factor,
            .af63-decision-metric,
            .af122-metric{
                padding:15px!important;
                min-width:0;
            }

            .af62b-found-pill,
            .af7-confidence-badge,
            .af122-badge{
                font-size:12px!important;
            }

            @media(max-width:1180px){
                .af62b-metrics,
                .af7-factor-grid{
                    grid-template-columns:repeat(3,minmax(0,1fr))!important;
                }
                .af62b-analysis-grid,
                .af63-decision-grid{
                    grid-template-columns:repeat(2,minmax(0,1fr))!important;
                }
            }

            @media(max-width:720px){
                .af62b-metrics,
                .af7-factor-grid,
                .af62b-analysis-grid,
                .af63-decision-grid,
                .af122-grid,
                .af122-lists{
                    grid-template-columns:repeat(2,minmax(0,1fr))!important;
                }
                .af7-intelligence-top,
                .af62b-best-top,
                .af62b-section-head,
                .af62b-compare-head{
                    flex-wrap:wrap;
                }
            }

            @media(max-width:460px){
                .af62b-metrics,
                .af7-factor-grid,
                .af62b-analysis-grid,
                .af63-decision-grid,
                .af122-grid,
                .af122-lists{
                    grid-template-columns:minmax(0,1fr)!important;
                }
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        if "suggested_alternatives" not in st.session_state:
            st.session_state["suggested_alternatives"] = []

        # Search candidates are derived from live supplier evidence.  Do not
        # carry results produced by a previous ranking/discovery algorithm into
        # this UI after a deployment, because their labels and evidence rules
        # may no longer be valid.
        alternative_result_algorithm_version = "supplier-evidence-v3"
        if (
            st.session_state.get("alternative_result_algorithm_version")
            != alternative_result_algorithm_version
        ):
            st.session_state["suggested_alternatives"] = []
            st.session_state["alternative_search_attempted"] = False
            st.session_state["alternative_original_data"] = {}
            st.session_state["alternative_original_risk"] = {}
            st.session_state["alternative_original_lookup_part"] = ""
            st.session_state["alternative_original_lookup_error"] = ""
            st.session_state["alternative_search_error"] = ""
            st.session_state["alternative_candidate_shortlist"] = []
            st.session_state["alternative_result_algorithm_version"] = (
                alternative_result_algorithm_version
            )

        if "alternative_search_attempted" not in st.session_state:
            st.session_state["alternative_search_attempted"] = False

        if "alternative_original_part" not in st.session_state:
            st.session_state["alternative_original_part"] = ""

        alt_nav_context = consume_alternative_finder_context(_qp_value)
        if alt_nav_context:
            apply_alternative_finder_prefill(alt_nav_context)

        if "alternative_original_data" not in st.session_state:
            st.session_state["alternative_original_data"] = {}

        if "alternative_original_risk" not in st.session_state:
            st.session_state["alternative_original_risk"] = {}

        if "alternative_original_lookup_part" not in st.session_state:
            st.session_state["alternative_original_lookup_part"] = ""

        if "alternative_original_lookup_error" not in st.session_state:
            st.session_state["alternative_original_lookup_error"] = ""

        if "alternative_candidate_shortlist" not in st.session_state:
            st.session_state["alternative_candidate_shortlist"] = []

        if "alternative_engineering_decisions" not in st.session_state:
            st.session_state["alternative_engineering_decisions"] = {}

        if "alternative_decision_notes" not in st.session_state:
            st.session_state["alternative_decision_notes"] = {}

        if "alternative_decision_db_status" not in st.session_state:
            st.session_state["alternative_decision_db_status"] = ""

        if "alternative_decision_db_error" not in st.session_state:
            st.session_state["alternative_decision_db_error"] = ""

        if "alternative_decision_flash" not in st.session_state:
            st.session_state["alternative_decision_flash"] = ""

        with st.container(border=True, key="af62_hero"):
            cadivor_section_header(
                "Choose a better replacement with confidence.",
                eyebrow="Alternative Component Finder",
                description=(
                    "Search the original part, compare compatibility, lifecycle, availability, and cost, "
                    "then document a defensible engineering decision in one guided workflow."
                ),
                icon="arrow-right-left",
            )

        with st.container(border=True, key="af62_search"):
            st.markdown(
                """
                <div class="af62-card-head">
                  <div>
                    <div class="af62-card-title">1. Search the original component</div>
                    <div class="af62-card-subtitle">Start with the complete manufacturer part number used in your design.</div>
                  </div>
                  <div class="af62-icon">
                    <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><path d="m21 21-4.3-4.3"></path></svg>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            search_input_col, search_button_col = st.columns([4.5, 1.25], gap="medium")
            with search_input_col:
                original_part = st.text_input(
                    "Manufacturer part number",
                    key="alternative_original_part",
                    placeholder="Example: ATMEGA328P-PU",
                )
            with search_button_col:
                st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
                find_alternatives_clicked = st.button(
                    "Find Alternatives →",
                    type="primary",
                    use_container_width=True,
                    key="alternative_find_button_62a",
                )

        if find_alternatives_clicked:
            searched_part = (original_part or "").strip()

            if not searched_part:
                st.warning("Please enter an original part number.")
            else:
                # Keep this operation entirely inside the authenticated workspace.
                # Supplier/API failures are converted into an in-page result state;
                # they must never fall through to authentication or public routing.
                st.session_state["cadivor_operation"] = "alternative_search"
                search_status = st.empty()
                with search_status.container():
                    operation_status(
                        "Searching component intelligence",
                        "Checking supplier coverage, lifecycle evidence, and replacement candidates.",
                    )
                try:
                    original_lookup = {}
                    try:
                        original_lookup = get_best_part_data(searched_part) or {}
                        if not isinstance(original_lookup, dict):
                            original_lookup = {}
                        try:
                            original_risk = calculate_risk(original_lookup) or {}
                        except Exception:
                            original_risk = {}
                        st.session_state["alternative_original_data"] = original_lookup
                        st.session_state["alternative_original_risk"] = original_risk
                        st.session_state["alternative_original_lookup_part"] = searched_part
                        if original_lookup.get("supplier_data_verified"):
                            st.session_state["alternative_original_lookup_error"] = ""
                        else:
                            st.session_state["alternative_original_lookup_error"] = (
                                f'No exact supplier match was found for "{searched_part}". '
                                "Enter the complete manufacturer part number, including package or suffix where applicable."
                            )
                    except Exception:
                        st.session_state["alternative_original_data"] = {}
                        st.session_state["alternative_original_risk"] = {}
                        st.session_state["alternative_original_lookup_part"] = searched_part
                        st.session_state["alternative_original_lookup_error"] = (
                            "Some original-component details are temporarily unavailable. "
                            "You can still review the available replacement evidence."
                        )

                    try:
                        # A replacement recommendation needs a verified original part as
                        # its comparison baseline. Do not turn a normal no-match into an
                        # apparent supplier outage by calling the candidate engine anyway.
                        if not original_lookup.get("supplier_data_verified"):
                            candidates = []
                        else:
                            candidates = suggest_alternatives_v2(searched_part) or []
                        for candidate in candidates:
                            candidate_part = str(candidate.get("Alternative Part", "") or "").strip()
                            if not candidate_part:
                                continue
                            try:
                                supplier_data = get_best_part_data(candidate_part) or {}
                            except Exception:
                                continue
                            matched_part = str(supplier_data.get("manufacturer_part_number", "") or "").strip()
                            if matched_part.upper() != candidate_part.upper():
                                continue
                            if not supplier_data.get("supplier_data_verified"):
                                continue
                            candidate["Supplier"] = supplier_data.get("source", "")
                            candidate["Sources Available"] = supplier_data.get("sources_available", "")
                            candidate["Supplier Count"] = supplier_data.get("supplier_count", 0)
                            candidate["Stock"] = supplier_data.get("stock_total", 0)
                            candidate["Unit Price"] = supplier_data.get("unit_price", 0)
                            if supplier_data.get("lifecycle_status"):
                                candidate["Lifecycle"] = supplier_data["lifecycle_status"]
                        st.session_state["suggested_alternatives"] = candidates
                        st.session_state["alternative_search_error"] = ""
                    except Exception:
                        st.session_state["suggested_alternatives"] = []
                        st.session_state["alternative_search_error"] = (
                            "Cadivor could not complete the supplier search right now. "
                            "Please try again in a moment."
                        )
                    st.session_state["alternative_search_attempted"] = True
                finally:
                    st.session_state.pop("cadivor_operation", None)
                    search_status.empty()

        if st.session_state.get("alternative_search_error"):
            st.error(st.session_state["alternative_search_error"], icon="⚠️")

        summary_col, tips_col = st.columns([1.35, 0.85], gap="medium")

        current_search = (original_part or "").strip()
        current_display = (
            html.escape(current_search) if current_search else "No component entered"
        )

        lookup_part = st.session_state.get("alternative_original_lookup_part", "")
        lookup_matches_input = bool(
            current_search
            and lookup_part
            and current_search.strip().upper() == lookup_part.strip().upper()
        )

        original_summary_data = (
            st.session_state.get("alternative_original_data", {})
            if lookup_matches_input
            else {}
        )
        original_summary_risk = (
            st.session_state.get("alternative_original_risk", {})
            if lookup_matches_input
            else {}
        )
        original_lookup_error = (
            st.session_state.get("alternative_original_lookup_error", "")
            if lookup_matches_input
            else ""
        )

        def _af62_first(data, keys, fallback="—"):
            if not isinstance(data, dict):
                return fallback
            for key in keys:
                value = data.get(key)
                if value is not None and str(value).strip() not in {"", "None", "nan"}:
                    return str(value).strip()
            return fallback

        def _af62_provider_coverage(data):
            if not isinstance(data, dict):
                return "Not checked"
            labels = {
                "AVAILABLE": "available",
                "PART_NOT_FOUND": "no exact match",
                "NOT_CONFIGURED": "not configured",
                "TIMEOUT": "timed out",
                "RATE_LIMITED": "rate limited",
                "PROVIDER_ERROR": "unavailable",
            }
            coverage = []
            for row in data.get("all_supplier_results") or []:
                if isinstance(row, dict) and row.get("source"):
                    coverage.append(
                        f"{row['source']}: {labels.get(str(row.get('provider_status') or ''), 'unknown')}"
                    )
            return " · ".join(coverage) if coverage else "Not checked"

        manufacturer_display = html.escape(
            _af62_first(
                original_summary_data,
                [
                    "manufacturer",
                    "Manufacturer",
                    "manufacturer_name",
                    "brand",
                ],
            )
        )

        lifecycle_display = html.escape(
            _af62_first(
                original_summary_data,
                [
                    "lifecycle_status",
                    "Lifecycle Status",
                    "lifecycle",
                    "status",
                ],
            )
        )

        package_display = html.escape(
            _af62_first(
                original_summary_data,
                [
                    "package",
                    "Package",
                    "package_type",
                    "case_package",
                ],
            )
        )

        risk_display_raw = _af62_first(
            original_summary_risk,
            ["risk_level", "Risk Level"],
            fallback=_af62_first(
                original_summary_data,
                ["risk_level", "Risk Level", "estimated_risk"],
            ),
        )
        risk_display = html.escape(risk_display_raw)

        risk_class = ""
        if risk_display_raw.lower() == "low":
            risk_class = "risk-low"
        elif risk_display_raw.lower() == "medium":
            risk_class = "risk-medium"
        elif risk_display_raw.lower() == "high":
            risk_class = "risk-high"

        datasheet_url = _af62_first(
            original_summary_data,
            [
                "datasheet_url",
                "datasheet",
                "Datasheet URL",
                "product_detail_url",
                "product_url",
                "url",
            ],
            fallback="",
        )

        if datasheet_url.startswith(("https://", "http://")):
            safe_datasheet_url = html.escape(datasheet_url, quote=True)
            datasheet_display = (
                f'<a class="af62-data-link" href="{safe_datasheet_url}" '
                f'target="_blank" rel="noopener noreferrer">Open source page →</a>'
            )
        else:
            datasheet_display = "Not available"

        if original_lookup_error:
            current_status = (
                "Supplier lookup unavailable"
                if original_summary_data.get("supplier_data_verified")
                else "No exact supplier match"
            )
            current_status_class = "warning"
        elif lookup_matches_input and original_summary_data:
            current_status = "Component intelligence loaded"
            current_status_class = "success"
        elif current_search:
            current_status = "Ready to search"
            current_status_class = ""
        else:
            current_status = "Waiting for a part number"
            current_status_class = ""

        with summary_col:
            with st.container(border=True, key="af62_summary"):
                st.markdown(
                    f"""
                    <div class="af62-card-head">
                      <div>
                        <div class="af62-card-title">Current search</div>
                        <div class="af62-card-subtitle">The original component Cadivor will use as the comparison baseline.</div>
                      </div>
                      <div class="af62-icon green">
                        <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m7.5 4.27 9 5.15"></path><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"></path><path d="m3.3 7 8.7 5 8.7-5"></path><path d="M12 22V12"></path></svg>
                      </div>
                    </div>
                    <div class="af62-summary-grid">
                      <div class="af62-field"><span>Part Number</span><strong>{current_display}</strong></div>
                      <div class="af62-field"><span>Manufacturer</span><strong>{manufacturer_display}</strong></div>
                      <div class="af62-field"><span>Lifecycle</span><strong>{lifecycle_display}</strong></div>
                      <div class="af62-field {risk_class}"><span>Risk</span><strong>{risk_display}</strong></div>
                      <div class="af62-field"><span>Package</span><strong>{package_display}</strong></div>
                      <div class="af62-field"><span>Verified Suppliers</span><strong>{html.escape(_af62_first(original_summary_data, ["sources_available", "source"], fallback="Not available"))}</strong></div>
                      <div class="af62-field"><span>Supplier coverage</span><strong>{html.escape(_af62_provider_coverage(original_summary_data))}</strong></div>
                      <div class="af62-field"><span>Datasheet / Source</span><strong>{datasheet_display}</strong></div>
                    </div>
                    <div class="af62-search-status {current_status_class}">{current_status}</div>
                    """,
                    unsafe_allow_html=True,
                )

        with tips_col:
            with st.container(border=True, key="af62_tips"):
                st.markdown(
                    """
                    <div class="af62-card-head">
                      <div>
                        <div class="af62-card-title">Search tips</div>
                        <div class="af62-card-subtitle">A precise part number produces the strongest comparison set.</div>
                      </div>
                      <div class="af62-icon amber">
                        <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"></path><path d="M10 22h4"></path><path d="M15.09 14c.18-.69.66-1.19 1.15-1.75A6 6 0 1 0 7.76 12.25c.48.55.97 1.05 1.15 1.75"></path></svg>
                      </div>
                    </div>
                    <div class="af62-tips">
                      <div class="af62-tip"><div class="af62-tip-num">1</div><div>Enter the complete manufacturer part number, including package or suffix details.</div></div>
                      <div class="af62-tip"><div class="af62-tip-num">2</div><div>Use the exact part used in the BOM so electrical and package comparisons remain meaningful.</div></div>
                      <div class="af62-tip"><div class="af62-tip-num">3</div><div>Cadivor will rank candidates using compatibility, lifecycle, stock, supplier, and cost signals.</div></div>
                    </div>
                    <div class="af62-examples">
                      <span class="af62-chip">ATMEGA328P-PU</span>
                      <span class="af62-chip">STM32F103C8T6</span>
                      <span class="af62-chip">TPS54331DR</span>
                      <span class="af62-chip">LM358N</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        if st.session_state["suggested_alternatives"]:
            alternatives_df = pd.DataFrame(
                st.session_state["suggested_alternatives"]
            )

            best_alternative = max(
                st.session_state["suggested_alternatives"],
                key=lambda x: x.get("Recommendation Score", 0),
            )

            best_part_number = str(best_alternative.get("Alternative Part", "") or "")
            alternative_options = alternatives_df["Alternative Part"].astype(str).tolist()
            best_index = (
                alternative_options.index(best_part_number)
                if best_part_number in alternative_options
                else 0
            )

            st.markdown(
                f"""
                <div class="af62b-section-head">
                  <div>
                    <div class="af62b-section-title">2. Review evidence-backed candidates</div>
                    <div class="af62b-section-meta">Direct supplier substitutes are shown first. When none are published, Cadivor can show clearly labelled catalog candidates for engineering review.</div>
                  </div>
                  <div class="af62b-found-pill">{len(alternatives_df)} candidates found</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            selected_alternative = st.selectbox(
                "Recommended candidate",
                alternative_options,
                index=best_index,
                key="alternative_selected_candidate_62b",
                help="Choose another candidate to refresh the recommendation and comparison workspace.",
            )

            selected_row = alternatives_df[
                alternatives_df["Alternative Part"].astype(str) == selected_alternative
            ].iloc[0]

            stored_original_data = st.session_state.get(
                "alternative_original_data", {}
            )
            stored_lookup_part = st.session_state.get(
                "alternative_original_lookup_part", ""
            )

            if (
                isinstance(stored_original_data, dict)
                and stored_original_data
                and str(stored_lookup_part).strip().upper()
                == str(original_part).strip().upper()
            ):
                original_data = stored_original_data
            else:
                original_data = get_best_part_data(original_part) or {}
                st.session_state["alternative_original_data"] = original_data
                st.session_state["alternative_original_lookup_part"] = original_part

            def _af62b_value(row, keys, fallback="—"):
                for key in keys:
                    try:
                        value = row.get(key)
                    except Exception:
                        value = None
                    if value is not None and str(value).strip() not in {"", "None", "nan"}:
                        return str(value).strip()
                return fallback

            recommendation_score = int(float(selected_row.get("Recommendation Score", 0) or 0))
            drop_in_confidence = int(float(selected_row.get("Drop-In Confidence", 0) or 0))
            recommendation_evidence = selected_row.get("Recommendation Score Evidence", {})
            if not isinstance(recommendation_evidence, dict):
                recommendation_evidence = {}
            lifecycle_value = _af62b_value(selected_row, ["Lifecycle"], "Unknown")
            risk_value = _af62b_value(selected_row, ["Estimated Risk"], "Unknown")
            supplier_value = _af62b_value(
                selected_row,
                ["Sources Available", "Supplier", "Best Source", "Source"],
                "Supplier not listed",
            )
            stock_value = float(selected_row.get("Stock", 0) or 0)
            price_value = float(selected_row.get("Unit Price", 0) or 0)
            package_value = _af62b_value(selected_row, ["Package"], "Not verified")
            recommendation_copy = _af62b_value(
                selected_row,
                ["Recommendation"],
                "Candidate identified from available engineering and sourcing signals.",
            )
            evidence_type_value = _af62b_value(selected_row, ["Evidence Type"], "Supplier candidate")
            substitute_type_value = _af62b_value(selected_row, ["Substitute Type"], "Not classified")

            original_stock = float(original_data.get("stock_total", 0) or 0)
            alternative_stock = stock_value

            original_price = float(original_data.get("unit_price", 0.0) or 0.0)
            alternative_price = price_value

            if original_stock > 0 and alternative_stock > 0:
                stock_ratio = alternative_stock / original_stock
                if stock_ratio > 1:
                    stock_delta = f"🟢 {stock_ratio:.0f}× more stock available"
                else:
                    stock_delta = f"🔴 {(1 / stock_ratio):.1f}× less stock available"
            elif original_stock > 0 and alternative_stock == 0:
                stock_delta = "🔴 No stock available"
            else:
                stock_delta = "N/A"

            if original_price > 0 and alternative_price > 0:
                price_pct = (
                    (alternative_price - original_price) / original_price
                ) * 100
                if price_pct < 0:
                    price_delta = f"🟢 {abs(price_pct):.1f}% lower cost"
                else:
                    price_delta = f"🔴 {price_pct:.1f}% higher cost"
            else:
                price_delta = "N/A"

            drop_in_reasons = str(
                selected_row.get("Drop-In Reasons", "") or ""
            )
            reason_list = [
                reason.strip()
                for reason in drop_in_reasons.split(";")
                if reason.strip()
            ]

            recommendation_points = []
            warning_points = []
            advantage_points = []
            tradeoff_points = []

            for reason in reason_list:
                lowered = reason.lower()
                if "could not be verified" in lowered:
                    warning_points.append(reason)
                elif reason.startswith("⚠") or reason.startswith("ℹ"):
                    warning_points.append(reason)
                else:
                    recommendation_points.append(reason)

            if stock_delta != "N/A":
                if "more stock" in stock_delta.lower():
                    advantage_points.append(stock_delta)
                else:
                    tradeoff_points.append(stock_delta)

            if price_delta != "N/A":
                if "lower cost" in price_delta.lower():
                    advantage_points.append(price_delta)
                else:
                    tradeoff_points.append(price_delta)

            confidence_label = (
                "High" if drop_in_confidence >= 75
                else "Medium" if drop_in_confidence >= 50
                else "Low"
            )

            recommendation_label = (
                "Strong" if recommendation_score >= 75
                else "Review" if recommendation_score >= 55
                else "Weak"
            )
            recommendation_label_class = (
                "" if recommendation_score >= 75
                else "medium" if recommendation_score >= 55
                else "low"
            )
            confidence_class = (
                "good" if confidence_label == "High"
                else "warn" if confidence_label == "Medium"
                else ""
            )
            lifecycle_class = "good" if lifecycle_value.lower() == "active" else "warn"
            risk_class_62b = "good" if risk_value.lower() == "low" else "warn"

            alternative_reasoning = build_alternative_reasoning(
                original_part=original_part,
                original_data=original_data,
                candidate=selected_row.to_dict(),
                recommendation_score=recommendation_score,
                compatibility_confidence=drop_in_confidence,
                engineering_matches=recommendation_points,
                warnings=warning_points,
                stock_delta=stock_delta,
                price_delta=price_delta,
            )

            with st.container(border=True, key="af62b_best_card"):
                st.markdown(
                    f"""
                    <div class="af62b-best-top">
                      <div>
                        <div class="af62b-eyebrow">★ Supplier-listed candidate</div>
                        <div class="af62b-best-part">{html.escape(selected_alternative)}</div>
                        <div class="af62b-best-copy">{html.escape(recommendation_copy)}</div>
                      </div>
                      <div class="af62b-score">
                        <strong>{recommendation_score}/100</strong>
                        <span>Recommendation score</span>
                        <div class="af63-score-label {recommendation_label_class}">{recommendation_label}</div>
                      </div>
                    </div>

                    <div class="af62b-metrics">
                      <div class="af62b-metric {lifecycle_class}">
                        <span>Lifecycle</span>
                        <strong>{html.escape(lifecycle_value)}</strong>
                      </div>
                      <div class="af62b-metric {risk_class_62b}">
                        <span>Estimated Risk</span>
                        <strong>{html.escape(risk_value)}</strong>
                      </div>
                      <div class="af62b-metric">
                        <span>Available Stock</span>
                        <strong>{int(stock_value):,}</strong>
                      </div>
                      <div class="af62b-metric">
                        <span>Supplier</span>
                        <strong>{html.escape(supplier_value)}</strong>
                      </div>
                      <div class="af62b-metric {confidence_class}">
                        <span>Compatibility Confidence</span>
                        <strong>{drop_in_confidence}% · {confidence_label}</strong>
                      </div>
                    </div>

                    <div class="af62b-metrics" style="margin-top:10px;grid-template-columns:repeat(3,minmax(0,1fr));">
                      <div class="af62b-metric">
                        <span>Package</span>
                        <strong>{html.escape(package_value)}</strong>
                      </div>
                      <div class="af62b-metric">
                        <span>Unit Price</span>
                        <strong>{"$" + format(price_value, ".4g") if price_value > 0 else "Not available"}</strong>
                      </div>
                      <div class="af62b-metric">
                        <span>Source evidence</span>
                        <strong>{html.escape(evidence_type_value)} · {html.escape(substitute_type_value)}</strong>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            # Milestone 7.0 — Explainable Engineering Intelligence
            lifecycle_strength = (
                100 if lifecycle_value.lower() == "active"
                else 55 if lifecycle_value.lower() in {"nrnd", "not recommended for new designs"}
                else 25
            )
            risk_strength = (
                92 if risk_value.lower() == "low"
                else 58 if risk_value.lower() == "medium"
                else 24
            )
            supply_strength = (
                96 if stock_value >= 50000
                else 82 if stock_value >= 10000
                else 62 if stock_value >= 1000
                else 30
            )

            if original_price > 0 and alternative_price > 0:
                cost_strength = max(
                    10,
                    min(
                        100,
                        int(
                            70
                            + ((original_price - alternative_price) / original_price) * 55
                        ),
                    ),
                )
            else:
                cost_strength = 50

            warning_count = len(warning_points)
            if drop_in_confidence >= 75:
                intelligence_summary = (
                    f"{selected_alternative} shows strong compatibility with the original "
                    f"component and is suitable for focused engineering validation."
                )
            elif drop_in_confidence >= 50:
                intelligence_summary = (
                    f"{selected_alternative} is a plausible replacement, but Cadivor identified "
                    f"{warning_count} verification item{'s' if warning_count != 1 else ''} "
                    f"that should be resolved before production release."
                )
            else:
                intelligence_summary = (
                    f"{selected_alternative} should not be treated as a drop-in replacement. "
                    f"The available evidence supports comparison and testing only, with "
                    f"additional electrical and package verification required."
                )

            if "lower cost" in price_delta.lower():
                intelligence_summary += " The candidate also improves estimated unit cost."
            elif "higher cost" in price_delta.lower():
                intelligence_summary += " The candidate introduces a sourcing cost increase."

            if "more stock" in stock_delta.lower():
                intelligence_summary += " Current supplier inventory is stronger than the original."

            compatibility_detail = (
                f"{drop_in_confidence}% confidence"
                if drop_in_confidence > 0
                else "Not verified"
            )
            lifecycle_detail = (
                "Active lifecycle supports continued sourcing."
                if lifecycle_value.lower() == "active"
                else f"Lifecycle status: {lifecycle_value}."
            )
            risk_detail = (
                "Few material engineering risks detected."
                if risk_value.lower() == "low"
                else "Requires additional engineering review."
            )
            supply_detail = (
                f"{int(stock_value):,} units currently identified."
                if stock_value > 0
                else "Inventory was not confirmed."
            )
            cost_detail = (
                price_delta.replace("🟢", "").replace("🔴", "").strip()
                if price_delta != "N/A"
                else "Cost comparison unavailable."
            )

            def _af7_meter_class(value):
                if value >= 75:
                    return "good"
                if value >= 50:
                    return "warn"
                return "bad"

            st.markdown(
                f"""
                <div class="af7-intelligence-card">
                  <div class="af7-intelligence-top">
                    <div>
                      <div class="af7-intelligence-eyebrow">Cadivor engineering intelligence</div>
                      <div class="af7-intelligence-title">Why Cadivor recommends this part</div>
                      <div class="af7-intelligence-summary">{html.escape(intelligence_summary)}</div>
                    </div>
                    <div class="af7-confidence-badge">{recommendation_score}/100 recommendation</div>
                  </div>

                  <div class="af7-factor-grid">
                    <div class="af7-factor">
                      <span>Compatibility</span>
                      <strong>{html.escape(compatibility_detail)}</strong>
                      <p>{len(recommendation_points)} verified match signal{'s' if len(recommendation_points) != 1 else ''}; {warning_count} warning{'s' if warning_count != 1 else ''}.</p>
                      <div class="af7-meter {_af7_meter_class(drop_in_confidence)}"><i style="width:{max(2, min(100, drop_in_confidence))}%"></i></div>
                    </div>
                    <div class="af7-factor">
                      <span>Lifecycle</span>
                      <strong>{html.escape(lifecycle_value)}</strong>
                      <p>{html.escape(lifecycle_detail)}</p>
                      <div class="af7-meter {_af7_meter_class(lifecycle_strength)}"><i style="width:{lifecycle_strength}%"></i></div>
                    </div>
                    <div class="af7-factor">
                      <span>Engineering Risk</span>
                      <strong>{html.escape(risk_value)}</strong>
                      <p>{html.escape(risk_detail)}</p>
                      <div class="af7-meter {_af7_meter_class(risk_strength)}"><i style="width:{risk_strength}%"></i></div>
                    </div>
                    <div class="af7-factor">
                      <span>Supply Position</span>
                      <strong>{int(stock_value):,} units</strong>
                      <p>{html.escape(supply_detail)}</p>
                      <div class="af7-meter {_af7_meter_class(supply_strength)}"><i style="width:{supply_strength}%"></i></div>
                    </div>
                    <div class="af7-factor">
                      <span>Cost Impact</span>
                      <strong>{"$" + format(price_value, ".4g") if price_value > 0 else "Not available"}</strong>
                      <p>{html.escape(cost_detail)}</p>
                      <div class="af7-meter {_af7_meter_class(cost_strength)}"><i style="width:{cost_strength}%"></i></div>
                    </div>
                  </div>

                  <div class="af7-explain-note">
                    Score basis: {drop_in_confidence}% engineering compatibility, {int(recommendation_evidence.get('evidence_quality', 0) or 0)}% retrieved-evidence quality, and {int(recommendation_evidence.get('sourcing_signal', 0) or 0)}% sourcing signal. Documented differences and missing evidence lower the result.
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            def _af122_items(items, empty_text):
                values = list(items or [])
                if not values:
                    return f"<div>{html.escape(empty_text)}</div>"
                return "".join(
                    f"<div>{html.escape(str(item))}</div>"
                    for item in values[:6]
                )

            st.markdown(
                f"""
                <section class="af122-decision">
                  <div class="af122-decision-top">
                    <div>
                      <div class="af122-eyebrow">Cadivor replacement decision</div>
                      <div class="af122-title">{html.escape(alternative_reasoning['disposition'])}</div>
                      <div class="af122-copy">{html.escape(alternative_reasoning['approval_guidance'])}</div>
                    </div>
                    <div class="af122-badge {html.escape(alternative_reasoning['disposition_tone'])}">
                      {alternative_reasoning['decision_confidence']}% decision confidence
                    </div>
                  </div>

                  <div class="af122-grid">
                    <div class="af122-metric">
                      <span>Recommended Use</span>
                      <strong>{html.escape(alternative_reasoning['use_case'])}</strong>
                    </div>
                    <div class="af122-metric">
                      <span>Estimated Engineering Effort</span>
                      <strong>{alternative_reasoning['estimated_effort_hours']} hours</strong>
                    </div>
                    <div class="af122-metric">
                      <span>Open Review Items</span>
                      <strong>{alternative_reasoning['verification_count'] + alternative_reasoning['hard_blocker_count']}</strong>
                      <div class="af122-copy">{alternative_reasoning['verification_count']} verification · {alternative_reasoning['hard_blocker_count']} blocker{'s' if alternative_reasoning['hard_blocker_count'] != 1 else ''}</div>
                    </div>
                  </div>
                </section>

                <div class="af122-lists">
                  <div class="af122-list good">
                    <h4>Confirmed Evidence</h4>
                    {_af122_items(alternative_reasoning['confirmed_matches'], 'No compatibility evidence has been confirmed.')}
                  </div>
                  <div class="af122-list warn">
                    <h4>Verification Required</h4>
                    {_af122_items(alternative_reasoning['verification_required'], 'No additional verification is required.')}
                  </div>
                  <div class="af122-list bad">
                    <h4>Approval Blockers</h4>
                    {_af122_items(alternative_reasoning['blockers'], 'No hard approval blockers were identified.')}
                  </div>
                </div>

                <div class="af122-lists">
                  <div class="af122-list good">
                    <h4>Business Value</h4>
                    {_af122_items(alternative_reasoning['business_value'], 'No confirmed commercial benefit was calculated.')}
                  </div>
                  <div class="af122-list warn">
                    <h4>Expected Engineering Work</h4>
                    {_af122_items(alternative_reasoning['expected_work'], 'No additional engineering work was calculated.')}
                  </div>
                  <div class="af122-list">
                    <h4>Decision Rule</h4>
                    <div>Qualification approval requires compatibility evidence, no unresolved hard blockers, and a completed engineering review record.</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            def _af62b_items(points, empty_text):
                if not points:
                    return f'<div class="af62b-analysis-empty">{html.escape(empty_text)}</div>'
                return '<div class="af62b-analysis-list">' + ''.join(
                    f'<div class="af62b-analysis-item">{html.escape(str(point))}</div>'
                    for point in points[:5]
                ) + '</div>'

            st.markdown(
                f"""
                <div class="af62b-analysis-grid">
                  <div class="af62b-analysis-card good">
                    <div class="af62b-analysis-title">Engineering Matches</div>
                    {_af62b_items(recommendation_points, "No verified compatibility matches were returned.")}
                  </div>
                  <div class="af62b-analysis-card warning">
                    <div class="af62b-analysis-title">Warnings</div>
                    {_af62b_items(warning_points, "No engineering warnings were identified.")}
                  </div>
                  <div class="af62b-analysis-card good">
                    <div class="af62b-analysis-title">Sourcing Advantages</div>
                    {_af62b_items(advantage_points, "No sourcing advantage was calculated.")}
                  </div>
                  <div class="af62b-analysis-card tradeoff">
                    <div class="af62b-analysis-title">Trade-offs</div>
                    {_af62b_items(tradeoff_points, "No significant trade-offs identified.")}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            comparison_df = pd.DataFrame(
                [
                    {
                        "Attribute": "Part Number",
                        "Original": original_part,
                        "Selected Alternative": selected_row.get("Alternative Part", ""),
                    },
                    {
                        "Attribute": "Lifecycle",
                        "Original": original_data.get("lifecycle_status", "Unknown"),
                        "Selected Alternative": selected_row.get("Lifecycle", "Unknown"),
                    },
                    {
                        "Attribute": "Supplier",
                        "Original": original_data.get("source", ""),
                        "Selected Alternative": selected_row.get("Supplier", ""),
                    },
                    {
                        "Attribute": "Stock",
                        "Original": original_data.get("stock_total", 0),
                        "Selected Alternative": selected_row.get("Stock", 0),
                    },
                    {
                        "Attribute": "Unit Price",
                        "Original": original_data.get("unit_price", 0.0),
                        "Selected Alternative": selected_row.get("Unit Price", 0.0),
                    },
                    {
                        "Attribute": "Stock Delta",
                        "Original": "—",
                        "Selected Alternative": stock_delta,
                    },
                    {
                        "Attribute": "Price Delta",
                        "Original": "—",
                        "Selected Alternative": price_delta,
                    },
                    {
                        "Attribute": "Package",
                        "Original": original_data.get("package")
                        or "Not available from supplier data",
                        "Selected Alternative": selected_row.get("Package", ""),
                    },
                    {
                        "Attribute": "Pin Count",
                        "Original": original_data.get("pin_count")
                        or "Not available from supplier data",
                        "Selected Alternative": selected_row.get("Pin Count", ""),
                    },
                    {
                        "Attribute": "Architecture",
                        "Original": original_data.get("architecture")
                        or original_data.get("Architecture")
                        or "Not available from supplier data",
                        "Selected Alternative": selected_row.get("Architecture", ""),
                    },
                    {
                        "Attribute": "Drop-In Confidence",
                        "Original": "—",
                        "Selected Alternative": selected_row.get("Drop-In Confidence", ""),
                    },
                    {
                        "Attribute": "Drop-In Rating",
                        "Original": "—",
                        "Selected Alternative": selected_row.get("Drop-In Rating", ""),
                    },
                ]
            )

            st.markdown(
                """
                <div class="af62b-compare-head">
                  <div>
                    <div class="af62b-compare-title">3. Compare the original and replacement</div>
                    <div class="af62b-compare-sub">Review the selected recommendation against the original component.</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.container(key="af62b_compact_table"):
                cadivor_engineering_dataframe(comparison_df)

            candidate_evidence_data = get_best_part_data(selected_alternative) or {}
            datasheet_comparison = build_datasheet_comparison(
                original_data,
                candidate_evidence_data,
            )
            comparison_counts = datasheet_comparison["counts"]
            st.markdown(
                f"""
                <div style="margin:24px 0 10px;">
                  <div class="af62b-compare-title">Datasheet comparison evidence</div>
                  <div class="af62b-compare-sub">{html.escape(datasheet_comparison['family'])} checks use retrieved supplier fields. Match means the retrieved values agree; it is not an automatic approval.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            evidence_columns = st.columns(3)
            evidence_columns[0].metric("Matches", comparison_counts["Match"])
            evidence_columns[1].metric("Differences", comparison_counts["Different"])
            evidence_columns[2].metric("Needs data", comparison_counts["Needs data"])
            cadivor_engineering_dataframe(pd.DataFrame(datasheet_comparison["rows"]))

            # Alternative evaluation must always expose its evidence workflow; plan limits may govern saved reports, not whether engineers can inspect the source evidence behind a recommendation.
            datasheet_enabled = True
            original_datasheet_url = str(original_data.get("datasheet_url") or "").strip()
            candidate_datasheet_url = str(candidate_evidence_data.get("datasheet_url") or selected_row.get("Datasheet URL") or "").strip()

            # Source links are basic engineering evidence, not a paid analysis
            # output.  Keep them visible for every plan whenever a supplier
            # returned them; only PDF extraction remains plan-gated.
            link_columns = st.columns(2)
            if original_datasheet_url.startswith(("https://", "http://")):
                link_columns[0].link_button("Open original datasheet", original_datasheet_url, use_container_width=True)
            else:
                link_columns[0].caption("Original datasheet not supplied by the source.")
            if candidate_datasheet_url.startswith(("https://", "http://")):
                link_columns[1].link_button("Open candidate datasheet", candidate_datasheet_url, use_container_width=True)
            else:
                link_columns[1].caption("Candidate datasheet not supplied by the source.")

            if not datasheet_enabled:
                st.info(
                    "Official PDF extraction and saved datasheet comparison evidence are included with Professional and above. "
                    "The field comparison remains visible so you can see what is missing."
                )
            else:
                evidence_comparison_key = (
                    f"{str(original_part).strip().upper()}::"
                    f"{str(selected_alternative).strip().upper()}"
                )
                if st.button(
                    "Analyze official datasheet evidence",
                    key=f"datasheet_evidence_{evidence_comparison_key}",
                    type="secondary",
                ):
                    st.session_state["datasheet_evidence_result"] = {
                        "comparison_key": evidence_comparison_key,
                        "original": extract_datasheet_text(original_datasheet_url),
                        "candidate": extract_datasheet_text(candidate_datasheet_url),
                        "original_url": original_datasheet_url,
                        "candidate_url": candidate_datasheet_url,
                    }
                evidence_result = st.session_state.get("datasheet_evidence_result")
                if (
                    isinstance(evidence_result, dict)
                    and evidence_result.get("comparison_key") == evidence_comparison_key
                ):
                    original_pdf = evidence_result.get("original") or {}
                    candidate_pdf = evidence_result.get("candidate") or {}
                    st.caption(
                        "PDF text is retrieved from supplier-provided official datasheet links. "
                        "Cadivor records availability and requires engineering review of every difference."
                    )
                    pdf_evidence_df = pd.DataFrame([
                        {
                            "Document": "Original part",
                            "Official URL": evidence_result.get("original_url") or "Not available",
                            "Readable PDF": "Yes" if original_pdf.get("available") else "No",
                            "Pages extracted": len(original_pdf.get("pages") or []),
                            "Status": original_pdf.get("reason") or "Official datasheet text available",
                        },
                        {
                            "Document": "Selected candidate",
                            "Official URL": evidence_result.get("candidate_url") or "Not available",
                            "Readable PDF": "Yes" if candidate_pdf.get("available") else "No",
                            "Pages extracted": len(candidate_pdf.get("pages") or []),
                            "Status": candidate_pdf.get("reason") or "Official datasheet text available",
                        },
                    ])
                    cadivor_engineering_dataframe(pdf_evidence_df)
                    st.markdown("**Official source documents**")
                    analyzed_link_columns = st.columns(2)
                    if original_datasheet_url.startswith(("https://", "http://")):
                        analyzed_link_columns[0].link_button(
                            "Open original datasheet used in analysis ↗",
                            original_datasheet_url,
                            use_container_width=True,
                        )
                    else:
                        analyzed_link_columns[0].caption("Original datasheet link is unavailable.")
                    if candidate_datasheet_url.startswith(("https://", "http://")):
                        analyzed_link_columns[1].link_button(
                            "Open candidate datasheet used in analysis ↗",
                            candidate_datasheet_url,
                            use_container_width=True,
                        )
                    else:
                        analyzed_link_columns[1].caption("Candidate datasheet link is unavailable.")
                    if original_pdf.get("available") and candidate_pdf.get("available"):
                        st.markdown(
                            '<div class="af62b-compare-sub" style="margin-top:12px;">Official PDF evidence extracted for the engineering-relevant fields below. Page citations point to the text Cadivor retrieved; confirm the original tables and drawings before approval.</div>',
                            unsafe_allow_html=True,
                        )
                        cadivor_engineering_dataframe(
                            pd.DataFrame(
                                build_pdf_field_evidence(
                                    original_pdf,
                                    candidate_pdf,
                                    datasheet_comparison["family"],
                                )
                            )
                        )

            st.markdown(
                """
                <div style="margin:22px 0 10px;">
                  <div class="af62b-compare-title">4. Record the engineering decision</div>
                  <div class="af62b-compare-sub">Record the final disposition after reviewing compatibility evidence and the side-by-side comparison.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            candidate_key = (
                f"{str(original_part).strip().upper()}::"
                f"{str(selected_alternative).strip().upper()}"
            )

            shortlist = st.session_state.get("alternative_candidate_shortlist", [])
            decisions = st.session_state.get("alternative_engineering_decisions", {})
            decision_notes = st.session_state.get("alternative_decision_notes", {})

            already_saved = any(
                isinstance(item, dict) and item.get("candidate_key") == candidate_key
                for item in shortlist
            )
            persistent_candidate_record = None
            try:
                existing_candidate_records = load_analysis_decisions(
                    current_user["id"],
                    original_part=str(original_part),
                    analysis_id=st.session_state.get("analysis_id"),
                    limit=50,
                )
                if not existing_candidate_records:
                    existing_candidate_records = load_analysis_decisions(
                        current_user["id"],
                        original_part=str(original_part),
                        limit=50,
                        include_all_contexts=True,
                    )
                persistent_candidate_record = next(
                    (
                        record
                        for record in existing_candidate_records
                        if str(record.get("alternative_part", "")).strip().upper()
                        == str(selected_alternative).strip().upper()
                    ),
                    None,
                )
            except Exception:
                existing_candidate_records = []

            if persistent_candidate_record:
                persisted_decision = str(
                    persistent_candidate_record.get("decision", "Saved")
                )
                decisions[candidate_key] = persisted_decision
                st.session_state["alternative_engineering_decisions"] = decisions

                persisted_note = str(
                    persistent_candidate_record.get("engineering_note", "") or ""
                )
                if candidate_key not in decision_notes and persisted_note:
                    decision_notes[candidate_key] = persisted_note
                    st.session_state["alternative_decision_notes"] = decision_notes

                already_saved = True

            current_decision = decisions.get(candidate_key, "Pending review")
            decision_status_class = (
                "approved" if current_decision == "Approved"
                else "rejected" if current_decision == "Rejected"
                else "saved" if already_saved
                else ""
            )

            st.markdown(
                f"""
                <div class="af63-decision-shell">
                  <div class="af63-decision-head" style="justify-content:flex-end; margin-bottom:12px;">
                    <div class="af63-decision-status {decision_status_class}">
                      {html.escape(current_decision if current_decision != "Pending review" else "Pending engineering review")}
                    </div>
                  </div>

                  <div class="af63-decision-grid">
                    <div class="af63-decision-metric">
                      <span>Candidate</span>
                      <strong>{html.escape(str(selected_alternative))}</strong>
                    </div>
                    <div class="af63-decision-metric">
                      <span>Compatibility</span>
                      <strong>{drop_in_confidence}% · {confidence_label}</strong>
                    </div>
                    <div class="af63-decision-metric">
                      <span>Engineering Risk</span>
                      <strong>{html.escape(risk_value)}</strong>
                    </div>
                    <div class="af63-decision-metric">
                      <span>Cost Impact</span>
                      <strong>{html.escape(price_delta)}</strong>
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            note_value = decision_notes.get(candidate_key, "")
            engineering_note = st.text_area(
                "Decision note",
                value=note_value,
                placeholder=(
                    "Example: Approve after reviewing the datasheet, compatibility "
                    "evidence, and prototype validation results."
                ),
                height=88,
                key=f"af63_note_{candidate_key}",
            )
            st.session_state["alternative_decision_notes"][candidate_key] = engineering_note

            approve_col, reject_col, save_col = st.columns(
                [1, 1, 1],
                gap="medium",
            )

            active_analysis_id = st.session_state.get("analysis_id")
            active_project_name = (
                st.session_state.get("project_name")
                or st.session_state.get("current_project_name")
                or ""
            )

            decision_engineer_name = (
                profile_for_shell.get("full_name")
                or profile_for_shell.get("name")
                or current_user.get("full_name")
                or current_user.get("name")
                or current_user.get("email")
                or "Cadivor user"
            )

            decision_payload = {
                "analysis_id": active_analysis_id,
                "project_name": str(active_project_name),
                "engineer_name": str(decision_engineer_name),
                "original_part": str(original_part),
                "alternative_part": str(selected_alternative),
                "decision": current_decision,
                "engineering_note": engineering_note,
                "recommendation_score": recommendation_score,
                "recommendation_rating": recommendation_label,
                "compatibility_confidence": drop_in_confidence,
                "compatibility_rating": confidence_label,
                "copilot_disposition": alternative_reasoning.get("disposition"),
                "copilot_decision_confidence": alternative_reasoning.get("decision_confidence"),
                "copilot_approval_blockers": alternative_reasoning.get("blockers"),
                "copilot_verification_required": alternative_reasoning.get("verification_required"),
                "copilot_estimated_effort_hours": alternative_reasoning.get("estimated_effort_hours"),
                "lifecycle": lifecycle_value,
                "risk": risk_value,
                "supplier": supplier_value,
                "stock": int(stock_value),
                "unit_price": price_value,
                "package": package_value,
                "stock_delta": stock_delta,
                "price_delta": price_delta,
                "source_snapshot": {
                    "original": original_data,
                    "selected_alternative": selected_row.to_dict(),
                },
                "comparison_snapshot": {
                    "engineering_matches": recommendation_points,
                    "warnings": warning_points,
                    "advantages": advantage_points,
                    "tradeoffs": tradeoff_points,
                },
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

            def _persist_decision(decision_value):
                persistent_payload = dict(decision_payload)
                persistent_payload["decision"] = decision_value
                persistent_payload["engineering_note"] = engineering_note

                try:
                    saved_record = save_analysis_decision(
                        current_user["id"],
                        persistent_payload,
                    )
                    st.session_state["alternative_engineering_decisions"][
                        candidate_key
                    ] = decision_value
                    st.session_state["alternative_decision_db_status"] = ""
                    st.session_state["alternative_decision_flash"] = (
                        "Engineering Decision Record created"
                    )
                    st.session_state["alternative_decision_db_error"] = ""
                    return saved_record
                except Exception as save_error:
                    st.session_state["alternative_decision_db_status"] = ""
                    st.session_state["alternative_decision_db_error"] = str(save_error)
                    return None

            with approve_col:
                if st.button(
                    "Approve",
                    use_container_width=True,
                    key="af63_approve",
                ):
                    if _persist_decision("Approved"):
                        st.rerun()

            with reject_col:
                if st.button(
                    "Reject",
                    use_container_width=True,
                    key="af63_reject",
                ):
                    if _persist_decision("Rejected"):
                        st.rerun()

            with save_col:
                if already_saved:
                    st.markdown(
                        '<div class="af62c-db-success">✓ Saved permanently</div>',
                        unsafe_allow_html=True,
                    )
                elif st.button(
                    "Save Review",
                    type="primary",
                    use_container_width=True,
                    key="af63_save",
                ):
                    if _persist_decision("Saved"):
                        shortlist.append(
                            {
                                "candidate_key": candidate_key,
                                **decision_payload,
                            }
                        )
                        st.session_state["alternative_candidate_shortlist"] = shortlist
                        st.rerun()

            st.markdown(
                """
                <div style="margin:16px 0 8px;">
                  <div class="af62b-analysis-title">Decision Outputs</div>
                  <div class="af62b-compare-sub">Generate formal records after the engineering disposition has been recorded.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            package_output_col, json_output_col = st.columns([1, 1], gap="medium")

            with json_output_col:
                export_payload = dict(decision_payload)
                export_payload["decision"] = st.session_state.get(
                    "alternative_engineering_decisions", {}
                ).get(candidate_key, "Pending review")
                safe_export_payload = {
                    "original_part": export_payload.get("original_part"),
                    "alternative_part": export_payload.get("alternative_part"),
                    "decision": export_payload.get("decision"),
                    "engineering_note": export_payload.get("engineering_note"),
                    "recommendation_score": export_payload.get(
                        "recommendation_score"
                    ),
                    "recommendation_rating": export_payload.get(
                        "recommendation_rating"
                    ),
                    "compatibility_confidence": export_payload.get(
                        "compatibility_confidence"
                    ),
                    "compatibility_rating": export_payload.get(
                        "compatibility_rating"
                    ),
                    "lifecycle": export_payload.get("lifecycle"),
                    "risk": export_payload.get("risk"),
                    "supplier": export_payload.get("supplier"),
                    "stock": export_payload.get("stock"),
                    "unit_price": export_payload.get("unit_price"),
                    "package": export_payload.get("package"),
                    "stock_delta": export_payload.get("stock_delta"),
                    "price_delta": export_payload.get("price_delta"),
                    "generated_at": export_payload.get("generated_at"),
                    "comparison_snapshot": export_payload.get(
                        "comparison_snapshot", {}
                    ),
                }

                export_bytes = json.dumps(
                    _make_json_safe(safe_export_payload),
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
                st.download_button(
                    "Export Decision Record",
                    data=export_bytes,
                    file_name=(
                        f"{str(original_part).strip()}_to_"
                        f"{str(selected_alternative).strip()}_decision.json"
                    ),
                    mime="application/json",
                    use_container_width=True,
                    key="af63_download",
                )

                st.caption("Download a structured copy of this engineering review.")

            pdf_package = generate_engineering_change_package_pdf(
                original_part=str(original_part),
                alternative_part=str(selected_alternative),
                decision=st.session_state.get(
                    "alternative_engineering_decisions", {}
                ).get(candidate_key, "Pending review"),
                engineering_note=engineering_note,
                recommendation_score=recommendation_score,
                compatibility_confidence=drop_in_confidence,
                lifecycle=lifecycle_value,
                risk=risk_value,
                supplier=supplier_value,
                stock=stock_value,
                unit_price=price_value,
                package=package_value,
                stock_delta=stock_delta,
                price_delta=price_delta,
                engineer_name=decision_engineer_name,
                project_name=active_project_name,
                comparison_snapshot=decision_payload.get(
                    "comparison_snapshot", {}
                ),
            )

            with package_output_col:
                st.download_button(
                    "Generate Professional Change Package",
                    data=pdf_package,
                    file_name=(
                        f"{str(original_part).strip()}_to_"
                        f"{str(selected_alternative).strip()}_change_package.pdf"
                    ),
                    mime="application/pdf",
                    use_container_width=True,
                    key="af63_change_package",
                )
                st.caption(
                    "Create a polished ECO-ready PDF with wrapped evidence, notes, sourcing impact, and next actions."
                )

            db_error = st.session_state.get("alternative_decision_db_error", "")
            decision_flash = st.session_state.get("alternative_decision_flash", "")

            if decision_flash:
                st.toast(decision_flash, icon="✅")
                st.session_state["alternative_decision_flash"] = ""

            if db_error:
                st.error(
                    "Cadivor could not save this engineering decision. Please try again "
                    "or contact support if the problem continues."
                )

            try:
                part_decision_history = load_analysis_decisions(
                    current_user["id"],
                    original_part=str(original_part),
                    analysis_id=st.session_state.get("analysis_id"),
                    limit=25,
                    include_all_contexts=True,
                )
            except Exception:
                part_decision_history = []

            with st.expander(
                f"Engineering decision history for {str(original_part).strip()}",
                expanded=False,
            ):
                st.markdown(
                    f"""
                    <div class="af62c-history-head">
                      <div class="af62b-compare-sub">
                        Previous saved reviews for this original component.
                      </div>
                      <div class="af62c-history-count">
                        {len(part_decision_history)} records
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if not part_decision_history:
                    st.info(
                        "No persistent engineering decisions have been saved for "
                        "this component yet."
                    )
                else:
                    history_rows = []
                    for record in part_decision_history:
                        history_rows.append(
                            {
                                "Date": record.get("updated_at")
                                or record.get("created_at", ""),
                                "Decision": record.get("decision", ""),
                                "Engineer": record.get("engineer_name", "")
                                or "Cadivor user",
                                "Candidate": record.get("alternative_part", ""),
                                "Project": record.get("project_name", "")
                                or (
                                    "Standalone Alternative Finder"
                                    if record.get("context_key") == "standalone"
                                    else record.get("context_key", "")
                                ),
                                "Original": record.get("original_part", ""),
                                "Score": record.get("recommendation_score", 0),
                                "Compatibility": record.get(
                                    "compatibility_confidence", 0
                                ),
                                "Risk": record.get("risk", ""),
                                "Supplier": record.get("supplier", ""),
                                "Note": record.get("engineering_note", ""),
                            }
                        )

                    cadivor_engineering_dataframe(pd.DataFrame(history_rows))

                    decision_options = {
                        (
                            f'{record.get("alternative_part", "Unknown")} — '
                            f'{record.get("decision", "Saved")} — '
                            f'{record.get("updated_at") or record.get("created_at", "")}'
                        ): record.get("id")
                        for record in part_decision_history
                        if record.get("id")
                    }

                    if decision_options:
                        archive_label = st.selectbox(
                            "Select a decision record to archive",
                            list(decision_options.keys()),
                            key="af62c_archive_select",
                        )
                        if st.button(
                            "Archive Decision",
                            type="secondary",
                            key="af62c_archive",
                        ):
                            try:
                                archive_analysis_decision(
                                    current_user["id"],
                                    decision_options[archive_label],
                                )
                                st.session_state["alternative_decision_flash"] = (
                                    "Engineering Decision Record archived"
                                )
                                st.session_state["alternative_decision_db_error"] = ""
                                st.rerun()
                            except Exception:
                                st.error(
                                    "Cadivor could not archive this decision. "
                                    "Please try again or contact support if the problem continues."
                                )

            with st.expander(
                f"View all {len(alternatives_df)} ranked alternatives",
                expanded=False,
            ):
                cadivor_engineering_dataframe(alternatives_df)

            with st.expander("Advanced multi-part comparison", expanded=False):
                st.markdown(
                    '<div class="af62b-advanced-copy">'
                    'Compare the original component against multiple candidates when the '
                    'ranked recommendation needs a broader sourcing or engineering review.'
                    '</div>',
                    unsafe_allow_html=True,
                )

                advanced_input = st.text_input(
                    "Alternative part numbers",
                    value=", ".join(alternative_options),
                    help="Enter comma-separated manufacturer part numbers.",
                    key="af62b_advanced_input",
                )

                if st.button(
                    "Run Advanced Comparison",
                    type="secondary",
                    key="af62b_advanced_compare",
                ):
                    advanced_parts = [
                        part.strip()
                        for part in advanced_input.split(",")
                        if part.strip()
                    ]

                    if not advanced_parts:
                        st.warning("Enter at least one alternative part number.")
                    elif not original_part:
                        st.warning("Enter a valid original part number.")
                    else:
                        with st.spinner(
                            "Comparing supplier, lifecycle, stock, and risk signals..."
                        ):
                            advanced_df = compare_parts(
                                original_part,
                                advanced_parts,
                            )

                        if advanced_df is None or advanced_df.empty:
                            st.warning("No comparison data was returned.")
                        else:
                            def _af62b_risk_badge(level):
                                if level == "High":
                                    return "🔴 High"
                                if level == "Medium":
                                    return "🟡 Medium"
                                return "🟢 Low"

                            if "Risk Level" in advanced_df.columns:
                                advanced_df["Risk Level Display"] = (
                                    advanced_df["Risk Level"].apply(
                                        _af62b_risk_badge
                                    )
                                )

                            sort_columns = [
                                column
                                for column in [
                                    "Risk Score",
                                    "Total Market Stock",
                                ]
                                if column in advanced_df.columns
                            ]
                            if sort_columns:
                                ascending = [
                                    column == "Risk Score"
                                    for column in sort_columns
                                ]
                                advanced_df = advanced_df.sort_values(
                                    by=sort_columns,
                                    ascending=ascending,
                                )

                            preferred_columns = [
                                "Role",
                                "MPN Searched",
                                "Manufacturer",
                                "Best Source",
                                "Supplier Count",
                                "Total Market Stock",
                                "Lifecycle Status",
                                "Risk Score",
                                "Risk Level Display",
                                "Product URL",
                            ]
                            display_columns = [
                                column
                                for column in preferred_columns
                                if column in advanced_df.columns
                            ]

                            cadivor_engineering_dataframe(
                                advanced_df[display_columns]
                                if display_columns
                                else advanced_df,
                                column_config={
                                    "Risk Score": st.column_config.NumberColumn(format="%d"),
                                },
                            )

                            csv = advanced_df.to_csv(index=False).encode("utf-8")
                            st.download_button(
                                "Download Advanced Comparison CSV",
                                data=csv,
                                file_name="alternative_comparison.csv",
                                mime="text/csv",
                                key="af62b_advanced_download",
                            )

            # Milestone 7.0.1 — safe Alternative Finder reset callback
            def _reset_alternative_search():
                """Clear the Alternative Finder before its widgets are recreated."""
                st.session_state["suggested_alternatives"] = []
                st.session_state["alternative_search_attempted"] = False
                st.session_state["alternative_original_data"] = {}
                st.session_state["alternative_original_risk"] = {}
                st.session_state["alternative_original_lookup_part"] = ""
                st.session_state["alternative_original_lookup_error"] = ""
                st.session_state["alternative_search_error"] = ""
                st.session_state["alternative_original_part"] = ""
                reset_alternative_finder_prefill()
                st.session_state["alternative_engineering_decisions"] = {}
                st.session_state["alternative_decision_notes"] = {}

                # Clear selection and comparison state from the previous result set.
                for state_key in (
                    "alternative_selected_candidate",
                    "alternative_compare_parts",
                    "alternative_advanced_parts",
                    "alternative_decision_db_status",
                    "alternative_decision_db_error",
                    "alternative_decision_flash",
                ):
                    st.session_state.pop(state_key, None)

            reset_col, note_col = st.columns([0.28, 0.72], gap="medium")
            with reset_col:
                st.button(
                    "New Alternative Search",
                    type="secondary",
                    use_container_width=True,
                    key="alternative_reset_62b",
                    on_click=_reset_alternative_search,
                )
            with note_col:
                st.markdown(
                    '<div class="af62b-reset-note">The detailed alternative library is collapsed by default so engineers can focus on the strongest recommendation first.</div>',
                    unsafe_allow_html=True,
                )

        elif st.session_state["alternative_search_attempted"]:
            st.warning(
                "No supplier-listed alternative candidates were retrieved from the configured sources. "
                "This does not mean that no market alternatives exist."
            )
            st.caption(
                "Cadivor will show the source and evidence type whenever a candidate is retrieved."
            )

        stop_authenticated_page()
    if app_mode == "BOM Analyzer":

        from integrations.supplier_aggregator import get_best_part_data
        from src.health_score import calculate_bom_health_score, generate_executive_summary
        from src.monitoring_engine import build_monitor_record, build_alert_record, detect_monitor_alerts
        from src.engineering_decision_engine import (
            build_engineering_decision_brief,
            render_engineering_decision_brief,
            get_cached_decision_brief,
            cache_decision_brief,
            decision_brief_cache_key,
        )
        from src.report_generator import save_results_to_excel
        from src.stripe_helper import create_checkout_session
        # Sprint 50.1.2 — returning through navigation resumes the active engineering
        # analysis instead of reopening the Saved BOM selector. A deliberate New
        # Analysis request clears this context above and continues to the selector.
        _resume_analysis_id = _safe_text(
            st.session_state.get("cadivor_active_analysis_id")
            or st.session_state.get("analysis_id"),
            "",
        )
        _show_saved_analyses = _safe_text(_qp_value("show_saved_analyses", ""), "").lower() in {
            "1", "true", "yes", "on"
        }
        if _resume_analysis_id and not _new_analysis_requested and not _show_saved_analyses:
            navigate_to("Analysis Details", analysis_id=_resume_analysis_id)

        st.markdown(
            """
            <style id="cadivor-bom-intelligence-v1">
            .bom8-hero{
                border:1px solid #b9d4ff;
                border-radius:24px;
                padding:26px 28px;
                margin-bottom:22px;
                background:
                    radial-gradient(circle at 95% 5%,rgba(37,99,235,.15),transparent 34%),
                    linear-gradient(135deg,#ffffff 0%,#f8fbff 100%);
                box-shadow:0 18px 46px rgba(15,23,42,.07);
            }
            .bom8-eyebrow{
                display:inline-flex;
                align-items:center;
                gap:8px;
                border:1px solid #bfdbfe;
                border-radius:999px;
                padding:7px 11px;
                color:#2563eb;
                background:#eff6ff;
                font-size:10px;
                font-weight:900;
                letter-spacing:.11em;
                text-transform:uppercase;
                margin-bottom:14px;
            }
            .bom8-hero h1{
                color:#0f172a;
                font-size:34px;
                line-height:1.08;
                letter-spacing:-.035em;
                margin:0 0 10px;
                font-weight:900;
            }
            .bom8-hero p{
                color:#52647c;
                font-size:15px;
                line-height:1.58;
                margin:0;
                max-width:900px;
                font-weight:600;
            }
            .bom8-kpis{
                display:grid;
                grid-template-columns:repeat(4,minmax(0,1fr));
                gap:12px;
                margin:0 0 24px;
            }
            .bom8-kpi{
                border:1px solid #dbe3ef;
                border-radius:18px;
                background:#fff;
                padding:17px 18px;
                min-height:112px;
                box-shadow:0 12px 30px rgba(15,23,42,.045);
            }
            .bom8-kpi-label{
                color:#64748b;
                font-size:9px;
                font-weight:900;
                letter-spacing:.10em;
                text-transform:uppercase;
                margin-bottom:8px;
            }
            .bom8-kpi-value{
                color:#0f172a;
                font-size:29px;
                line-height:1;
                font-weight:900;
                margin-bottom:8px;
            }
            .bom8-kpi-note{
                color:#64748b;
                font-size:11px;
                line-height:1.4;
                font-weight:650;
            }
            .bom8-section-head{
                display:flex;
                align-items:flex-end;
                justify-content:space-between;
                gap:18px;
                margin:4px 0 12px;
            }
            .bom8-section-head h2{
                color:#0f172a;
                font-size:22px;
                margin:0 0 4px;
                letter-spacing:-.025em;
            }
            .bom8-section-head p{
                color:#64748b;
                font-size:12px;
                margin:0;
                font-weight:650;
            }
            .bom8-upload-card{
                border:1px solid #d8e1ed;
                border-radius:22px;
                background:#fff;
                padding:22px 24px;
                box-shadow:0 16px 38px rgba(15,23,42,.055);
                min-height:100%;
            }
            .bom8-upload-title{
                color:#0f172a;
                font-size:20px;
                font-weight:900;
                margin-bottom:5px;
            }
            .bom8-upload-copy{
                color:#64748b;
                font-size:12px;
                line-height:1.5;
                margin-bottom:14px;
                font-weight:600;
            }
            .bom8-checklist{
                display:grid;
                gap:10px;
                margin-top:10px;
            }
            .bom8-check{
                display:flex;
                gap:10px;
                align-items:flex-start;
                border:1px solid #e2e8f0;
                border-radius:14px;
                padding:12px 13px;
                background:#f8fafc;
            }
            .bom8-check-icon{
                flex:0 0 24px;
                width:24px;
                height:24px;
                border-radius:8px;
                display:flex;
                align-items:center;
                justify-content:center;
                background:#ecfdf5;
                border:1px solid #a7f3d0;
                color:#059669;
                font-size:12px;
                font-weight:900;
            }
            .bom8-check strong{
                display:block;
                color:#0f172a;
                font-size:12px;
                margin-bottom:2px;
            }
            .bom8-check span{
                display:block;
                color:#64748b;
                font-size:10.5px;
                line-height:1.4;
            }
            .bom8-trust-strip{
                display:grid;
                grid-template-columns:repeat(3,minmax(0,1fr));
                gap:10px;
                margin-top:14px;
            }
            .bom8-trust{
                border:1px solid #dbeafe;
                border-radius:13px;
                background:#eff6ff;
                padding:10px 11px;
                color:#1e3a8a;
                font-size:10px;
                font-weight:800;
                text-align:center;
            }
            .bom8-path-label{margin:16px 0 7px;color:#0f172a;font-size:12px;font-weight:900}
            .bom8-path-label span{display:block;margin-top:3px;color:#64748b;font-size:10.5px;font-weight:650;line-height:1.45}
            .bom8-path-guide{border:1px solid #bfdbfe;background:#f8fbff;border-radius:16px;padding:14px;margin-bottom:12px}
            .bom8-path-guide-title{color:#0f172a;font-size:13px;font-weight:900;margin-bottom:9px}
            .bom8-path-choice{display:flex;gap:9px;align-items:flex-start;padding:9px 0;border-top:1px solid #dbeafe}
            .bom8-path-choice:first-of-type{border-top:0;padding-top:0}
            .bom8-path-choice strong{display:block;color:#0f172a;font-size:11px;font-weight:900}
            .bom8-path-choice span{display:block;color:#64748b;font-size:10px;line-height:1.4;margin-top:2px}
            .bom8-path-icon{flex:0 0 22px;width:22px;height:22px;border-radius:8px;background:#dbeafe;color:#1d4ed8;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:900}
            .bom8-history-note{
                border:1px solid #dbe3ef;
                border-radius:16px;
                background:#fff;
                padding:13px 15px;
                color:#52647c;
                font-size:11px;
                line-height:1.45;
                margin-top:8px;
            }
            .st-key-bom8_saved_history{
                margin-top:18px;
                margin-bottom:8px;
            }
            .st-key-bom8_saved_history details{
                border:1px solid #dbe3ef!important;
                border-radius:16px!important;
                background:#ffffff!important;
                box-shadow:0 10px 26px rgba(15,23,42,.04);
            }
            .st-key-bom8_saved_history summary{
                color:#1d4ed8!important;
                font-weight:850!important;
            }
            .bom8-saved-summary{
                display:grid;
                grid-template-columns:1.2fr 1.2fr .55fr .75fr;
                gap:10px;
                margin:14px 0;
            }
            .bom8-saved-summary > div{
                border:1px solid #dbe3ef;
                border-radius:14px;
                background:#f8fafc;
                padding:12px 13px;
            }
            .bom8-saved-summary span{
                display:block;
                color:#64748b;
                font-size:9px;
                font-weight:900;
                letter-spacing:.09em;
                text-transform:uppercase;
                margin-bottom:6px;
            }
            .bom8-saved-summary strong{
                display:block;
                color:#0f172a;
                font-size:12px;
                line-height:1.35;
                overflow-wrap:anywhere;
            }
            .st-key-bom8_delete_saved_analysis button{
                border:1px solid #fecaca!important;
                background:#fff!important;
                color:#b91c1c!important;
                font-weight:850!important;
            }
            .bom8-delete-confirmation{
                display:flex;
                gap:12px;
                align-items:flex-start;
                border:1px solid #fecaca;
                border-radius:16px;
                background:#fff7f7;
                padding:14px 15px;
                margin:14px 0 10px;
            }
            .bom8-delete-icon{
                flex:0 0 28px;
                width:28px;
                height:28px;
                border-radius:9px;
                display:flex;
                align-items:center;
                justify-content:center;
                background:#fee2e2;
                border:1px solid #fecaca;
                color:#b91c1c;
                font-weight:900;
            }
            .bom8-delete-confirmation strong{
                display:block;
                color:#991b1b;
                font-size:13px;
                margin-bottom:4px;
            }
            .bom8-delete-confirmation p{
                margin:0;
                color:#7f1d1d;
                font-size:11px;
                line-height:1.5;
            }
            .st-key-bom8_confirm_permanent_delete button{
                border:1px solid #dc2626!important;
                background:#dc2626!important;
                color:#fff!important;
                font-weight:850!important;
            }
            .st-key-bom8_cancel_delete_analysis button{
                border:1px solid #cbd5e1!important;
                background:#fff!important;
                color:#334155!important;
                font-weight:800!important;
            }
            .st-key-bom81_saved_manager{
                margin-top:18px;
                margin-bottom:10px;
            }
            .st-key-bom81_saved_manager details{
                border:1px solid #dbe3ef!important;
                border-radius:18px!important;
                background:#fff!important;
                box-shadow:0 12px 30px rgba(15,23,42,.045);
            }
            .st-key-bom81_saved_manager summary{
                color:#1d4ed8!important;
                font-weight:900!important;
            }
            .bom81-selection-status{
                display:inline-flex;
                align-items:center;
                gap:6px;
                margin:10px 0 12px;
                border:1px solid #bfdbfe;
                background:#eff6ff;
                color:#1e40af;
                border-radius:999px;
                padding:7px 11px;
                font-size:11px;
                font-weight:800;
            }
            .bom81-selection-status strong{
                font-size:13px;
            }
            .bom81-selection-status span{
                color:#475569;
                font-size:10.5px;
                font-weight:750;
                margin-left:3px;
            }
            .st-key-bom81_request_bulk_delete button{
                border:1px solid #fecaca!important;
                background:#fff!important;
                color:#b91c1c!important;
                font-weight:850!important;
            }
            .bom81-delete-confirmation{
                display:flex;
                gap:13px;
                align-items:flex-start;
                border:1px solid #fecaca;
                border-radius:17px;
                background:#fff7f7;
                padding:15px 16px;
                margin:15px 0 11px;
            }
            .bom81-delete-icon{
                flex:0 0 30px;
                width:30px;
                height:30px;
                border-radius:9px;
                display:flex;
                align-items:center;
                justify-content:center;
                background:#fee2e2;
                border:1px solid #fecaca;
                color:#b91c1c;
                font-weight:900;
            }
            .bom81-delete-confirmation strong{
                display:block;
                color:#991b1b;
                font-size:13px;
                margin-bottom:5px;
            }
            .bom81-delete-confirmation p,
            .bom81-delete-confirmation li{
                color:#7f1d1d;
                font-size:11px;
                line-height:1.5;
            }
            .bom81-delete-confirmation p{
                margin:0 0 6px;
            }
            .bom81-delete-confirmation ul{
                margin:4px 0 0 18px;
                padding:0;
            }
            .st-key-bom81_confirm_bulk_delete button{
                border:1px solid #dc2626!important;
                background:#dc2626!important;
                color:#fff!important;
                font-weight:850!important;
            }
            .st-key-bom81_cancel_bulk_delete button,
            .st-key-bom81_clear_selection button{
                border:1px solid #cbd5e1!important;
                background:#fff!important;
                color:#334155!important;
                font-weight:800!important;
            }
            @media(max-width:900px){
                .bom8-saved-summary{grid-template-columns:1fr 1fr;}
            }
            @media(max-width:620px){
                .bom8-saved-summary{grid-template-columns:1fr;}
            }
            .st-key-bom8_try_sample button{
                border:1px solid #2563eb!important;
                background:#2563eb!important;
                color:#fff!important;
                font-weight:800!important;
            }
            .st-key-bom8_try_sample button *{color:#fff!important;}
            .st-key-bom_file_uploader [data-testid="stFileUploader"]{
                border-radius:16px!important;
            }
            @media(max-width:1100px){
                .bom8-kpis{grid-template-columns:repeat(2,minmax(0,1fr));}
            }
            @media(max-width:720px){
                .bom8-kpis,.bom8-trust-strip{grid-template-columns:1fr;}
                .bom8-hero{padding:22px 20px;}
                .bom8-hero h1{font-size:28px;}
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        history_data = load_analysis_history(current_user["id"]) or []
        history_df = pd.DataFrame(history_data)

        if not history_df.empty:
            if "project_name" not in history_df.columns:
                history_df["project_name"] = history_df.get("filename", "Saved analysis")

            numeric_defaults = {
                "health_score": 0,
                "high_risk_count": 0,
                "medium_risk_count": 0,
            }
            for column_name, default_value in numeric_defaults.items():
                if column_name not in history_df.columns:
                    history_df[column_name] = default_value
                history_df[column_name] = pd.to_numeric(
                    history_df[column_name], errors="coerce"
                ).fillna(default_value)

            saved_analysis_count = int(len(history_df))
            average_health = int(round(history_df["health_score"].mean()))
            total_high_risk = int(history_df["high_risk_count"].sum())
            best_health = int(history_df["health_score"].max())
        else:
            saved_analysis_count = 0
            average_health = 0
            total_high_risk = 0
            best_health = 0

        st.markdown(
            """
            <style>
            .cv64-metric-grid a.cv64-metric__action {
              display:inline-flex!important;width:auto!important;max-width:max-content!important;
              margin-top:10px!important;padding:5px 9px!important;border:1px solid #1d4ed8!important;
              border-radius:7px!important;background:#2563eb!important;color:#ffffff!important;
              font-size:12px!important;font-weight:800!important;line-height:1.2!important;
              text-decoration:none!important;
            }
            .cv64-metric-grid a.cv64-metric__action:hover,
            .cv64-metric-grid a.cv64-metric__action:focus,
            .cv64-metric-grid a.cv64-metric__action:visited {color:#ffffff!important;text-decoration:none!important;}
            </style><div class="cv64-page-shell">
            """,
            unsafe_allow_html=True,
        )
        cadivor_section_header(
            "Turn a parts list into an engineering risk decision",
            eyebrow="BOM intelligence workspace",
            description=(
                "Upload a CSV or Excel BOM to evaluate lifecycle exposure, sourcing risk, "
                "component availability, and portfolio health. Cadivor converts the file "
                "into a prioritized engineering review rather than another raw spreadsheet."
            ),
            icon="cpu",
        )
        cadivor_metric_row(
            [
                MetricCard(
                    label="Saved analyses",
                    value=str(saved_analysis_count),
                    detail="Previous BOM engineering reviews",
                    tone="info",
                    icon="folder-archive",
                ),
                MetricCard(
                    label="Average health",
                    value=str(average_health),
                    status="Portfolio baseline",
                    tone="success" if average_health >= 85 else "warning",
                    icon="gauge",
                ),
                MetricCard(
                    label="High-risk findings",
                    value=str(total_high_risk),
                    detail="Components requiring engineering review",
                    tone="danger" if total_high_risk else "success",
                    icon="triangle-alert",
                    href="?page=BOM%20Analyzer&high_risk_review=1#high-risk-components",
                    action_label="Review high-risk components",
                ),
                MetricCard(
                    label="Best recorded health",
                    value=str(best_health),
                    detail="Highest-performing saved BOM",
                    tone="success",
                    icon="trophy",
                ),
            ]
        )

        if st.session_state.get("bom81_high_risk_review"):
            st.markdown('<div id="high-risk-components"></div>', unsafe_allow_html=True)
            st.markdown("### High-risk components")
            st.caption(
                f"{total_high_risk} component{'s' if total_high_risk != 1 else ''} requiring engineering review across your saved BOMs."
            )
            try:
                high_risk_parts_response = (
                    _workspace_query(supabase.table("analysis_parts").select("*"))
                    .eq("user_id", current_user["id"])
                    .limit(5000)
                    .execute()
                )
                high_risk_parts = high_risk_parts_response.data or []
            except Exception:
                high_risk_parts = []

            high_risk_rows = [
                row for row in high_risk_parts
                if str(row.get("risk_level") or row.get("Risk Level") or "").strip().lower() == "high"
            ]
            analysis_labels = {
                str(row.get("id") or ""): str(row.get("project_name") or row.get("filename") or "Saved BOM analysis")
                for row in history_data
            }
            if not high_risk_rows:
                st.info("No saved high-risk component records are currently available to review.")
            else:
                st.markdown(
                    """
                    <style>
                    .bom81-risk-kicker{color:#dc2626;font-size:11px;font-weight:850;letter-spacing:.08em;text-transform:uppercase}
                    .bom81-risk-title{margin:5px 0 3px;color:#0f172a;font-size:18px;font-weight:850}
                    .bom81-risk-meta{color:#64748b;font-size:13px;line-height:1.5}
                    .bom81-risk-meta strong{color:#334155}
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
                for index, part in enumerate(high_risk_rows):
                    part_number = str(
                        part.get("mpn") or part.get("part_number") or part.get("manufacturer_part_number") or "Component"
                    )
                    analysis_id_value = str(part.get("analysis_id") or "")
                    manufacturer = str(part.get("manufacturer") or "Unknown manufacturer")
                    risk_score = part.get("risk_score") or part.get("Risk Score") or "—"
                    project_label = analysis_labels.get(analysis_id_value, "Saved BOM analysis")
                    details_col, action_col = st.columns([0.78, 0.22], gap="medium")
                    with details_col:
                        st.markdown(
                            f'<div class="bom81-risk-kicker">High-risk component · score {html.escape(str(risk_score))}</div>'
                            f'<div class="bom81-risk-title">{html.escape(part_number)}</div>'
                            f'<div class="bom81-risk-meta">{html.escape(manufacturer)} · <strong>Saved BOM:</strong> {html.escape(project_label)}</div>',
                            unsafe_allow_html=True,
                        )
                    with action_col:
                        if st.button(
                            "Open component",
                            key=f"bom81_open_high_risk_{analysis_id_value}_{part_number}_{index}",
                            type="primary",
                            use_container_width=True,
                        ):
                            st.session_state["cadivor_active_analysis_id"] = analysis_id_value
                            st.session_state["analysis_id"] = analysis_id_value
                            st.session_state["cadivor_pending_analysis_section"] = "Components"
                            st.session_state["cadivor_pending_analysis_section_id"] = analysis_id_value
                            navigate_to(
                                "Analysis Details",
                                analysis_id=analysis_id_value,
                                tab="components",
                                component=part_number,
                                focus="component-risk",
                            )
                    st.divider()

        # Milestone 8.1 — Saved BOM Manager
        st.markdown('<div id="saved-bom-manager"></div>', unsafe_allow_html=True)
        cadivor_panel(
            title=f"Saved BOM Manager ({saved_analysis_count})",
            subtitle=(
                "Showing saved analyses with high-risk components."
                if st.session_state.get("bom81_high_risk_review")
                else "Search, sort, open, or select multiple analyses for bulk deletion."
            ),
            tone="soft",
        )
        if st.session_state.get("bom81_high_risk_review"):
            if st.button(
                "Show all saved analyses",
                key="bom81_clear_high_risk_review",
                type="secondary",
            ):
                st.session_state.pop("bom81_high_risk_review", None)
                st.rerun()
        with st.container(key="bom81_saved_manager"):
            with st.expander(
                "Manage saved analyses",
                expanded=bool(history_data),
            ):

                if history_data:
                    manager_df = pd.DataFrame(history_data).copy()

                    required_defaults = {
                        "id": "",
                        "project_name": "Saved BOM analysis",
                        "filename": "—",
                        "health_score": 0,
                        "high_risk_count": 0,
                        "medium_risk_count": 0,
                        "created_at": pd.NaT,
                    }
                    for column_name, default_value in required_defaults.items():
                        if column_name not in manager_df.columns:
                            manager_df[column_name] = default_value

                    manager_df["project_name"] = manager_df["project_name"].fillna(
                        manager_df["filename"]
                    )
                    manager_df["project_name"] = manager_df["project_name"].fillna(
                        "Saved BOM analysis"
                    )
                    manager_df["filename"] = manager_df["filename"].fillna("—")

                    for numeric_column in (
                        "health_score",
                        "high_risk_count",
                        "medium_risk_count",
                    ):
                        manager_df[numeric_column] = pd.to_numeric(
                            manager_df[numeric_column],
                            errors="coerce",
                        ).fillna(0).astype(int)

                    if st.session_state.get("bom81_high_risk_review"):
                        manager_df = manager_df[manager_df["high_risk_count"] > 0]

                    manager_df["created_at_sort"] = pd.to_datetime(
                        manager_df["created_at"],
                        errors="coerce",
                        utc=True,
                    )
                    manager_df["Date"] = manager_df["created_at_sort"].dt.strftime(
                        "%Y-%m-%d"
                    ).fillna("—")

                    filter_col, sort_col = st.columns([0.68, 0.32], gap="medium")

                    with filter_col:
                        manager_search = st.text_input(
                            "Search saved analyses",
                            placeholder="Search by project or source filename",
                            key="bom81_manager_search",
                        )

                    with sort_col:
                        manager_sort = st.selectbox(
                            "Sort analyses",
                            options=[
                                "Newest first",
                                "Oldest first",
                                "Health: high to low",
                                "Health: low to high",
                                "High risk: high to low",
                                "Project name",
                            ],
                            key="bom81_manager_sort",
                        )

                    if manager_search.strip():
                        search_value = manager_search.strip().lower()
                        manager_df = manager_df[
                            manager_df["project_name"]
                            .astype(str)
                            .str.lower()
                            .str.contains(search_value, na=False)
                            | manager_df["filename"]
                            .astype(str)
                            .str.lower()
                            .str.contains(search_value, na=False)
                        ]

                    if manager_sort == "Newest first":
                        manager_df = manager_df.sort_values(
                            "created_at_sort",
                            ascending=False,
                            na_position="last",
                        )
                    elif manager_sort == "Oldest first":
                        manager_df = manager_df.sort_values(
                            "created_at_sort",
                            ascending=True,
                            na_position="last",
                        )
                    elif manager_sort == "Health: high to low":
                        manager_df = manager_df.sort_values(
                            "health_score",
                            ascending=False,
                        )
                    elif manager_sort == "Health: low to high":
                        manager_df = manager_df.sort_values(
                            "health_score",
                            ascending=True,
                        )
                    elif manager_sort == "High risk: high to low":
                        manager_df = manager_df.sort_values(
                            "high_risk_count",
                            ascending=False,
                        )
                    else:
                        manager_df = manager_df.sort_values(
                            "project_name",
                            ascending=True,
                        )

                    if manager_df.empty:
                        st.info("No saved analyses match the current search.")
                    else:
                        editor_df = pd.DataFrame(
                            {
                                # Keep the editor input stable: feeding its selected
                                # rows back into the input remounts the widget and
                                # loses the selection on the following interaction.
                                "Select": False,
                                "Project": manager_df["project_name"].astype(str),
                                "Source File": manager_df["filename"].astype(str),
                                "Health": manager_df["health_score"],
                                "High Risk": manager_df["high_risk_count"],
                                "Medium Risk": manager_df["medium_risk_count"],
                                "Date": manager_df["Date"],
                                "_analysis_id": manager_df["id"].astype(str),
                            }
                        ).reset_index(drop=True)

                        editor_revision = int(
                            st.session_state.get("bom81_saved_analysis_editor_revision", 0)
                        )
                        editor_key = "bom81_saved_analysis_editor"
                        if editor_revision:
                            editor_key = f"{editor_key}_{editor_revision}"

                        edited_manager = st.data_editor(
                            editor_df,
                            use_container_width=True,
                            hide_index=True,
                            height=min(520, 70 + len(editor_df) * 35),
                            disabled=[
                                "Project",
                                "Source File",
                                "Health",
                                "High Risk",
                                "Medium Risk",
                                "Date",
                                "_analysis_id",
                            ],
                            column_config={
                                "Select": st.column_config.CheckboxColumn(
                                    "Select",
                                    help="Select one analysis to open or several analyses to delete.",
                                    width="small",
                                ),
                                "Project": st.column_config.TextColumn(
                                    "Project",
                                    width="large",
                                ),
                                "Source File": st.column_config.TextColumn(
                                    "Source File",
                                    width="medium",
                                ),
                                "Health": st.column_config.NumberColumn(
                                    "Health",
                                    min_value=0,
                                    max_value=100,
                                    format="%d",
                                    width="small",
                                ),
                                "High Risk": st.column_config.NumberColumn(
                                    "High Risk",
                                    format="%d",
                                    width="small",
                                ),
                                "Medium Risk": st.column_config.NumberColumn(
                                    "Medium Risk",
                                    format="%d",
                                    width="small",
                                ),
                                "Date": st.column_config.TextColumn(
                                    "Date",
                                    width="small",
                                ),
                                "_analysis_id": None,
                            },
                            key=editor_key,
                        )

                        selected_rows = edited_manager[
                            edited_manager["Select"] == True
                        ]
                        selected_ids = selected_rows["_analysis_id"].astype(str).tolist()
                        st.session_state["bom81_selected_analysis_ids"] = selected_ids

                        selected_count = len(selected_ids)
                        selection_label = "analysis" if selected_count == 1 else "analyses"

                        selection_copy = (
                            "Select one checkbox to enable Open Analysis."
                            if selected_count == 0
                            else "One analysis selected. Open Analysis is ready."
                            if selected_count == 1
                            else "Multiple analyses selected. Use bulk delete or clear the selection; analyses open one at a time."
                        )
                        st.markdown(
                            f"""
                            <div class="bom81-selection-status">
                              <strong>{selected_count}</strong>
                              {selection_label} selected
                              <span>{html.escape(selection_copy)}</span>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        open_col, delete_col, clear_col = st.columns(
                            [0.34, 0.34, 0.32],
                            gap="medium",
                        )

                        with open_col:
                            if st.button(
                                "Open Selected Analysis" if selected_count == 1 else "Open Analysis (select 1)",
                                type="primary",
                                use_container_width=True,
                                disabled=selected_count != 1,
                                key="bom81_open_selected",
                            ):
                                selected_saved_id = selected_ids[0]
                                st.session_state["cadivor_active_analysis_id"] = str(selected_saved_id)
                                st.session_state["analysis_id"] = str(selected_saved_id)
                                navigate_to("Analysis Details", analysis_id=selected_saved_id)

                        with delete_col:
                            if st.button(
                                f"Delete Selected ({selected_count})",
                                type="secondary",
                                use_container_width=True,
                                disabled=selected_count == 0,
                                key="bom81_request_bulk_delete",
                            ):
                                st.session_state["bom81_pending_delete_ids"] = selected_ids
                                st.rerun()

                        with clear_col:
                            if st.button(
                                "Clear Selection",
                                use_container_width=True,
                                disabled=selected_count == 0,
                                key="bom81_clear_selection",
                            ):
                                st.session_state["bom81_selected_analysis_ids"] = []
                                st.session_state.pop("bom81_pending_delete_ids", None)
                                st.session_state["bom81_saved_analysis_editor_revision"] = (
                                    editor_revision + 1
                                )
                                st.rerun()

                        pending_delete_ids = [
                            str(value)
                            for value in st.session_state.get(
                                "bom81_pending_delete_ids",
                                [],
                            )
                            if str(value).strip()
                        ]

                        if pending_delete_ids:
                            delete_records = manager_df[
                                manager_df["id"].astype(str).isin(pending_delete_ids)
                            ]
                            delete_names = delete_records["project_name"].astype(str).tolist()
                            preview_names = delete_names[:5]
                            remaining_names = max(0, len(delete_names) - len(preview_names))

                            name_lines = "".join(
                                f"<li>{html.escape(name)}</li>"
                                for name in preview_names
                            )
                            if remaining_names:
                                name_lines += (
                                    f"<li>and {remaining_names} more "
                                    f"{'analyses' if remaining_names != 1 else 'analysis'}</li>"
                                )

                            st.markdown(
                                f"""
                                <div class="bom81-delete-confirmation">
                                  <div class="bom81-delete-icon">!</div>
                                  <div>
                                    <strong>Permanently delete {len(pending_delete_ids)}
                                    saved BOM {"analyses" if len(pending_delete_ids) != 1 else "analysis"}?</strong>
                                    <p>
                                      All saved component records associated with these
                                      analyses will also be removed. This action cannot be undone.
                                    </p>
                                    <ul>{name_lines}</ul>
                                  </div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                            confirm_col, cancel_col = st.columns(
                                [0.5, 0.5],
                                gap="medium",
                            )

                            with confirm_col:
                                if st.button(
                                    f"Yes, Delete {len(pending_delete_ids)} Permanently",
                                    type="primary",
                                    use_container_width=True,
                                    key="bom81_confirm_bulk_delete",
                                ):
                                    deletion_errors = []

                                    for analysis_id_value in pending_delete_ids:
                                        try:
                                            supabase.table("analysis_parts").delete().eq(
                                                "analysis_id",
                                                analysis_id_value,
                                            ).execute()

                                            try:
                                                supabase.table(
                                                    "part_monitor_history"
                                                ).delete().eq(
                                                    "analysis_id",
                                                    analysis_id_value,
                                                ).execute()
                                            except Exception:
                                                pass

                                            supabase.table("analyses").delete().eq(
                                                "id",
                                                analysis_id_value,
                                            ).eq(
                                                "user_id",
                                                current_user["id"],
                                            ).execute()
                                        except Exception as deletion_error:
                                            deletion_errors.append(
                                                f"{analysis_id_value}: {deletion_error}"
                                            )

                                    st.session_state["bom81_selected_analysis_ids"] = []
                                    st.session_state["bom81_saved_analysis_editor_revision"] = (
                                        editor_revision + 1
                                    )
                                    st.session_state.pop(
                                        "bom81_pending_delete_ids",
                                        None,
                                    )

                                    if deletion_errors:
                                        st.error(
                                            "Some analyses could not be deleted. "
                                            + " | ".join(deletion_errors[:3])
                                        )
                                    else:
                                        st.success(
                                            f"{len(pending_delete_ids)} saved BOM "
                                            f"{'analyses' if len(pending_delete_ids) != 1 else 'analysis'} "
                                            "permanently deleted."
                                        )
                                        st.rerun()

                            with cancel_col:
                                if st.button(
                                    "Cancel",
                                    use_container_width=True,
                                    key="bom81_cancel_bulk_delete",
                                ):
                                    st.session_state.pop(
                                        "bom81_pending_delete_ids",
                                        None,
                                    )
                                    st.rerun()

                        st.caption(
                            "Opening is a single-analysis action. Select exactly one row to open it. "
                            "Selecting two or more rows does not open them together; it enables bulk deletion. "
                            "The table is read-only except for the selection checkboxes."
                        )
                else:
                    st.markdown(
                        """
                        <div class="bom8-history-note">
                          No saved analyses yet. Your first completed BOM review will
                          appear here with its health score and risk distribution.
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        cadivor_panel_end()

        workflow_steps(["Prepare", "Upload", "Analyze", "Review"], active=1)

        st.markdown(
            """
            <div class="bom8-section-head">
              <div>
                <h2>Start a new BOM analysis</h2>
                <p>Prepare the project, confirm the expected columns, and upload the source file.</p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        input_col, guidance_col = st.columns([0.64, 0.36], gap="large")

        with input_col:
            st.markdown(
                """
                <div class="bom8-upload-card">
                  <div class="bom8-upload-title">Upload engineering BOM</div>
                  <div class="bom8-upload-copy">
                    Give the analysis a recognizable project or revision name, then select
                    the CSV or Excel file used by your engineering or sourcing team.
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            project_name = st.text_input(
                "Project / BOM Name",
                placeholder="Example: Motor Controller Rev A",
                key="bom8_project_name",
                help="Required for your uploaded BOM. The 10-part sample names itself automatically.",
            )
            if not project_name.strip():
                st.caption("Required for your uploaded BOM. The sample BOM is named automatically.")

            sample_bom = pd.DataFrame(
                {
                    "mpn": [
                        "STM32F103C8T6",
                        "TPS5430DDAR",
                        "MCP2551-I/SN",
                        "BQ24074RGTR",
                        "ADS1115IDGSR",
                        "W25Q64JVSSIQ",
                        "SN74LVC2T45DCUR",
                        "PC817X2NSZ1F",
                        "GRM188R71C104KA01D",
                        "RC0603FR-0710KL",
                    ],
                    "quantity": [1, 2, 1, 1, 1, 1, 2, 4, 12, 8],
                    "description": [
                        "32-bit microcontroller",
                        "3 A buck regulator",
                        "CAN transceiver",
                        "Li-ion battery charger",
                        "16-bit ADC",
                        "64 Mbit serial flash memory",
                        "Dual-bit voltage-level translator",
                        "Optocoupler",
                        "0.1 uF ceramic capacitor",
                        "10 kOhm resistor",
                    ],
                }
            )
            st.markdown(
                """
                <div class="cv-beta-trust-note"><strong>Your BOM stays in your authenticated workspace.</strong> Cadivor uses it to generate your analysis and does not present customer BOM data as a product for sale.</div>
                """,
                unsafe_allow_html=True,
            )

            def _start_sample_bom() -> None:
                st.session_state["bom8_sample_mode"] = True
                st.session_state["bom8_sample_auto_analyze"] = True
                st.session_state["bom8_project_name"] = "Cadivor 10-Part Sample BOM"
                for state_key in (
                    "results_df",
                    "analysis_saved",
                    "analysis_id",
                    "health_score",
                    "health_status",
                ):
                    st.session_state.pop(state_key, None)

            def _use_uploaded_bom() -> None:
                st.session_state.pop("bom8_sample_mode", None)
                st.session_state.pop("bom8_sample_auto_analyze", None)

            st.markdown(
                '<div class="bom8-path-label">Option 1 — Explore Cadivor <span>Use Cadivor\'s included example to see a complete analysis. It will be saved as a sample, not your own BOM.</span></div>',
                unsafe_allow_html=True,
            )
            st.button(
                "Analyze the 10-Part Sample BOM",
                key="bom8_try_sample",
                type="primary",
                help="Load and analyze Cadivor's sample BOM in this workspace—no download or re-upload required.",
                on_click=_start_sample_bom,
            )

            st.markdown(
                '<div class="bom8-path-label">Option 2 — Analyze your BOM <span>Upload your own CSV or Excel file for an engineering review of your actual design.</span></div>',
                unsafe_allow_html=True,
            )
            uploaded_file = st.file_uploader(
                "Upload your BOM file",
                type=["csv", "xlsx"],
                key="bom_file_uploader",
                help="Cadivor accepts CSV and XLSX files up to the Streamlit upload limit.",
                on_change=_use_uploaded_bom,
            )

            st.markdown(
                """
                <div class="bom8-trust-strip">
                  <div class="bom8-trust">CSV/XLSX files accepted</div>
                  <div class="bom8-trust">Duplicate part numbers combined</div>
                  <div class="bom8-trust">Lifecycle and sourcing risk scored</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with guidance_col:
            st.markdown(
                """
                <div class="bom8-path-guide">
                  <div class="bom8-path-guide-title">Choose how to begin</div>
                  <div class="bom8-path-choice"><div class="bom8-path-icon">1</div><div><strong>Explore with the sample</strong><span>Use the included 10-part BOM to see Cadivor's analysis without sharing your own data.</span></div></div>
                  <div class="bom8-path-choice"><div class="bom8-path-icon">2</div><div><strong>Analyze your own BOM</strong><span>Upload a CSV or XLSX when you are ready to review a real project.</span></div></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                """
                <div class="bom8-upload-card">
                  <div class="bom8-upload-title">File readiness</div>
                  <div class="bom8-upload-copy">
                    A clean source file creates a stronger and more defensible analysis.
                  </div>
                  <div class="bom8-checklist">
                    <div class="bom8-check">
                      <div class="bom8-check-icon">1</div>
                      <div>
                        <strong>Manufacturer part number</strong>
                        <span>Include an <b>mpn</b> column or a recognized part-number equivalent.</span>
                      </div>
                    </div>
                    <div class="bom8-check">
                      <div class="bom8-check-icon">2</div>
                      <div>
                        <strong>Quantity</strong>
                        <span>Include a numeric <b>quantity</b> or <b>qty</b> column.</span>
                      </div>
                    </div>
                    <div class="bom8-check">
                      <div class="bom8-check-icon">3</div>
                      <div>
                        <strong>One BOM revision</strong>
                        <span>Use a project name that identifies the board and revision.</span>
                      </div>
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


        sample_mode = bool(st.session_state.get("bom8_sample_mode"))
        source_filename = "cadivor_10_part_sample_bom.csv" if sample_mode else (
            uploaded_file.name if uploaded_file is not None else ""
        )

        if uploaded_file is None and not sample_mode:
            if history_data:
                st.info(
                    "Open a saved BOM analysis above, or upload a new CSV or Excel BOM."
                )
            else:
                st.info("Upload a CSV or Excel BOM to begin.")
            st.markdown("</div>", unsafe_allow_html=True)
            stop_authenticated_page()

        if not project_name.strip() and not sample_mode:
            # The requirement is communicated beside the field above; avoid a
            # duplicate bottom-of-page warning that hides the next action.
            st.markdown("</div>", unsafe_allow_html=True)
            stop_authenticated_page()

        try:
            if sample_mode:
                bom_df = sample_bom.copy()
            elif uploaded_file.name.endswith(".csv"):
                bom_df = pd.read_csv(uploaded_file)
            else:
                bom_df = pd.read_excel(uploaded_file)

        except Exception as e:
            st.error(
                f"Could not read the uploaded BOM file: {e}"
            )
            stop_authenticated_page()

        column_rename_map = {
            "part number": "mpn",
            "part_number": "mpn",
            "manufacturer part number": "mpn",
            "manufacturer_part_number": "mpn",
            "qty": "quantity",
        }

        bom_df.columns = [
            col.strip().lower()
            for col in bom_df.columns
        ]

        bom_df.rename(
            columns=column_rename_map,
            inplace=True,
        )

        required_columns = ["mpn", "quantity"]

        normalized_columns = [
            col.strip().lower().replace(" ", "_")
            for col in bom_df.columns
        ]

        missing_columns = [
            col for col in required_columns
            if col not in normalized_columns
        ]

        if missing_columns:
            st.error(
                "Your BOM is missing required columns: "
                + ", ".join(missing_columns)
                + ". Please include at least MPN and Quantity columns."
            )
            stop_authenticated_page()

        if bom_df.empty:
            st.error("The uploaded BOM file is empty.")
            stop_authenticated_page()

        if len(bom_df) == 0:
            st.error("No BOM rows were detected in the uploaded file.")
            stop_authenticated_page()

    


        if st.session_state.get("uploaded_filename") != source_filename:
            st.session_state.pop("results_df", None)
            st.session_state.pop("analysis_saved", None)
            st.session_state["uploaded_filename"] = source_filename

    
        original_row_count = len(bom_df)

        bom_df["mpn"] = bom_df["mpn"].astype(str).str.strip()

        bom_df = (
            bom_df.groupby("mpn", as_index=False)
            .agg({
                "quantity": "sum"
            })
        )

        deduped_row_count = len(bom_df)

        if deduped_row_count < original_row_count:
            st.info(
                f"Duplicate part numbers were merged: {original_row_count} rows reduced to {deduped_row_count} unique parts."
            )

        bom_df["quantity"] = pd.to_numeric(
            bom_df["quantity"],
            errors="coerce",
        )

        if bom_df["quantity"].isna().any():
            st.error("Some quantity values are missing or invalid. Please use numeric quantities only.")
            stop_authenticated_page()

        if (bom_df["quantity"] <= 0).any():
            st.error("Quantity values must be greater than zero.")
            stop_authenticated_page()

        render_upload_detected(
            filename=source_filename,
            component_count=original_row_count,
            deduplicated_count=deduped_row_count,
        )

        st.subheader("Sample BOM Preview" if sample_mode else "Uploaded BOM Preview")
        st.data_editor(
            bom_df,
            use_container_width=True,
            hide_index=True,
        )


        analysis_in_progress = bool(st.session_state.get("bom_analysis_in_progress"))
        analyze_requested = st.button(
            "Analyzing BOM…" if analysis_in_progress else ("Analyze Sample BOM" if sample_mode else "Analyze BOM"),
            type="primary",
            disabled=analysis_in_progress,
            help="Cadivor is analyzing this BOM. This action is unavailable until the current analysis finishes." if analysis_in_progress else None,
        )
        if st.session_state.pop("bom8_sample_auto_analyze", False):
            analyze_requested = True

        if analyze_requested:
            # First render the locked state. The heavy supplier work starts on
            # the following Streamlit run so the user cannot click again.
            st.session_state["bom_analysis_in_progress"] = True
            st.session_state["bom_analysis_queued"] = True
            st.rerun()

        if st.session_state.get("bom_analysis_queued"):
            st.session_state["bom_analysis_queued"] = False
            with st.spinner("Analyzing lifecycle, supplier, inventory, sourcing, and engineering risk…"):
                # A new analysis should be saved as a new database record.
                # These flags prevent old session state from blocking the new save.
                st.session_state.pop("analysis_saved", None)
                st.session_state.pop("analysis_id", None)
                st.session_state.pop("health_score", None)
                st.session_state.pop("health_status", None)

                if is_admin:
                    allowed = True
                    message = "Admin account: plan limits bypassed."
                else:
                    allowed, message = validate_bom_against_plan(
                        bom_df,
                        selected_plan,
                        monthly_upload_count,
                        is_admin=is_admin,
                    )

                if not allowed:
                    upgrade_plan = selected_plan.get("upgrade_to")

                    st.session_state["show_upgrade_checkout"] = True
                    st.session_state["upgrade_message"] = message
                    st.session_state["upgrade_plan_name"] = upgrade_plan

                    # Rerun so the persistent upgrade checkout section below can render.
                    # Using stop_authenticated_page() here would show the text but prevent the button from appearing.
                    st.rerun()

                saved_analysis_count = (
                    _workspace_query(
                        supabase.table("analyses")
                        .select("id", count="exact")
                    )
                    .eq("user_id", current_user["id"])
                    .execute()
                )

                saved_analysis_total = saved_analysis_count.count or 0
                max_saved_boms = selected_plan.get("max_saved_boms", 0)

                if not is_admin and max_saved_boms is not None and saved_analysis_total >= max_saved_boms:
                    st.error(
                        f"Your {selected_plan_name} workspace includes {max_saved_boms:,} saved BOMs and that storage allowance is full. "
                        "Your existing work is safe. Delete an older analysis or upgrade to continue saving new results."
                    )
                    stop_authenticated_page()

                st.success(message)

                try:
                    progress_status = st.empty()
                    progress_bar = st.progress(0)

                    st.session_state["results_df"] = analyze_bom(
                        bom_df,
                        progress_status=progress_status,
                        progress_bar=progress_bar,
                    )

                    progress_status.success("BOM analysis completed successfully.")
                    progress_bar.progress(1.0)

                    # If analysis succeeds, hide any old checkout prompt from a previous blocked attempt.
                    st.session_state.pop("show_upgrade_checkout", None)
                    st.session_state.pop("checkout_url", None)
                    st.session_state.pop("upgrade_message", None)
                    st.session_state.pop("upgrade_plan_name", None)

                except Exception as e:
                    st.session_state["bom_analysis_in_progress"] = False
                    st.error(f"BOM analysis failed unexpectedly: {e}")
                    stop_authenticated_page()

                results_df = st.session_state["results_df"]
                if st.session_state.get("cadivor_supplier_degraded"):
                    st.info(
                        st.session_state.get(
                            "cadivor_supplier_degraded_message",
                            "Some supplier data could not be verified during this analysis.",
                        )
                    )

        if st.session_state.get("show_upgrade_checkout") and not is_admin:
            upgrade_message = st.session_state.get(
                "upgrade_message",
                "Your current plan limit has been reached.",
            )

            upgrade_plan = st.session_state.get("upgrade_plan_name")
            next_plan = get_plan(upgrade_plan) if upgrade_plan else None

            st.error(upgrade_message)

            if upgrade_plan and next_plan:
                st.markdown(
                    f"""
    ---
    ### 🚀 Upgrade to **{upgrade_plan}** ({next_plan['price']})

    Unlock more power:

    - 🔍 **{format_limit(next_plan['monthly_bom_limit'], 'BOM analysis', 'BOM analyses')}** each month
    - 📦 **{format_limit(next_plan['max_parts_per_bom'], 'component')}** per BOM
    - 🌐 Verified multi-supplier intelligence
    - ⚡ Faster sourcing decisions

    👉 Upgrade now to continue your analysis
    ---
    """
                )

                if st.button(f"🚀 Upgrade to {upgrade_plan}", key="upgrade_button_main"):
                    try:
                        price_secret = {
                            "Professional": "STRIPE_PRO_PRICE_ID",
                            "Business": "STRIPE_BUSINESS_PRICE_ID",
                        }.get(upgrade_plan)
                        if not price_secret:
                            raise ValueError("Unsupported checkout plan")
                        checkout_url = create_checkout_session(
                            get_secret(price_secret, required=True),
                            current_user["email"],
                            current_user["id"],
                            success_url=app_checkout_url(checkout="success"),
                            cancel_url=app_checkout_url(checkout="cancel"),
                        )

                        st.session_state["checkout_url"] = checkout_url

                    except Exception:
                        st.error("Secure checkout could not be started. Please try again or contact support.")

                if "checkout_url" in st.session_state:
                    st.link_button(
                        "Continue to Stripe Checkout",
                        st.session_state["checkout_url"],
                    )

            else:
                st.info("No upgrade plan is configured for your current subscription.")

        if "results_df" in st.session_state:
            results_df = st.session_state["results_df"]

            if not st.session_state.get("analysis_saved", False):
                high_count = len(results_df[results_df["Risk Level"] == "High"])
                medium_count = len(results_df[results_df["Risk Level"] == "Medium"])
                low_count = len(results_df[results_df["Risk Level"] == "Low"])
                total_parts = len(results_df)

                health_data = calculate_bom_health_score(results_df)
                health_score = health_data["health_score"]

                if health_score >= 90:
                    health_status = "🟢 Excellent"
                elif health_score >= 75:
                    health_status = "🟢 Healthy"
                elif health_score >= 60:
                    health_status = "🟡 Moderate Risk"
                elif health_score >= 40:
                    health_status = "🟠 High Risk"
                else:
                    health_status = "🔴 Critical"

                st.session_state["health_score"] = health_score
                st.session_state["health_status"] = health_status

                try:
                    analysis_response = supabase.table("analyses").insert(
                        _workspace_payload(
                            {
                                "user_id": current_user["id"],
                                "project_name": project_name or source_filename,
                                "filename": source_filename,
                                "total_parts": total_parts,
                                "high_risk_count": high_count,
                                "medium_risk_count": medium_count,
                                "low_risk_count": low_count,
                                "health_score": health_score,
                            }
                        )
                    ).execute()

                    analysis_id = analysis_response.data[0]["id"]
                    st.session_state["analysis_id"] = analysis_id
                    st.session_state["cadivor_active_analysis_id"] = str(analysis_id)
                    st.session_state["cadivor_active_analysis_tab"] = "Engineering Intelligence"

                except Exception as e:
                    st.error(f"Could not save analysis summary: {e}")
                    stop_authenticated_page()

                part_records = []

                for _, part_row in results_df.iterrows():
                    part_records.append(
                        {
                            "analysis_id": analysis_id,
                            "user_id": current_user["id"],
                            "workspace_id": active_workspace_id,
                            "project_name": project_name or source_filename,
                            "mpn": part_row.get("MPN", ""),
                            "manufacturer": part_row.get("Manufacturer", ""),
                            "risk_score": part_row.get("Risk Score", 0),
                            "risk_level": part_row.get("Risk Level", ""),
                            "risk_reasons": part_row.get("Risk Reasons", ""),
                            "lifecycle_status": part_row.get("Lifecycle Status", ""),
                            "stock_available": _json_safe_number(
                                part_row.get("Stock Available", 0),
                                default=0,
                            ),
                            "supplier_count": _json_safe_number(
                                part_row.get("Supplier Count", 0),
                                default=0,
                            ),
                            "quantity": _json_safe_number(
                                part_row.get("Quantity", 1),
                                default=1,
                            ),
                            "unit_price": _json_safe_number(
                                part_row.get("Unit Price", 0),
                                default=0,
                            ),
                            "primary_supplier": (
                                ""
                                if pd.isna(part_row.get("Best Source", ""))
                                else str(part_row.get("Best Source", "") or "")
                            ),
                            "lead_time_weeks": _json_safe_optional_number(
                                part_row.get("Lead Time Weeks", None)
                            ),
                        }
                    )

                if part_records:
                    try:
                        supabase.table("analysis_parts").insert(part_records).execute()
                    except Exception as e:
                        st.error(f"Could not save BOM parts: {e}")
                        stop_authenticated_page()

                monitor_records = []
                alert_records = []

                for _, row in results_df.iterrows():
                    latest_monitor = (
                        _workspace_query(
                            supabase.table("part_monitor_history")
                            .select("*")
                        )
                        .eq("user_id", current_user["id"])
                        .eq("part_number", row.get("MPN", ""))
                        .order("created_at", desc=True)
                        .limit(1)
                        .execute()
                    )

                    latest_monitor_data = (
                        latest_monitor.data[0]
                        if latest_monitor.data
                        else None
                    )

                    monitor_alerts = []

                    current_snapshot = build_monitor_record(
                        current_user["id"],
                        analysis_id,
                        row,
                        workspace_id=active_workspace_id,
                    )

                    if latest_monitor_data:
                        new_alert_records, monitor_alerts = detect_monitor_alerts(
                            current_user["id"],
                            analysis_id,
                            row.get("MPN", ""),
                            latest_monitor_data,
                            current_snapshot,
                            workspace_id=active_workspace_id,
                        )

                        alert_records.extend(new_alert_records)

                        for alert in new_alert_records:
                            if (
                                alert.get("severity") == "High"
                                and alert.get("alert_type") == "Stock Drop"
                            ):
                                pass  # Email disabled until Resend domain is verified

                    if monitor_alerts:
                        st.warning(
                            f"{row.get('MPN', '')}: "
                            + " | ".join(monitor_alerts)
                        )

                    monitor_records.append(current_snapshot)

                if monitor_records:
                    try:
                        supabase.table("part_monitor_history").insert(
                            monitor_records
                        ).execute()
                    except Exception as e:
                        st.error(f"Could not save monitoring history: {e}")

                if alert_records:
                    try:
                        supabase.table("monitor_alerts").insert(
                            alert_records
                        ).execute()
                    except Exception as e:
                        st.error(f"Could not save monitor alerts: {e}")

                new_upload_count = monthly_upload_count + 1

                try:
                    supabase.table("users").update(
                        {
                            "monthly_upload_count": new_upload_count
                        }
                    ).eq(
                        "id",
                        current_user["id"]
                    ).execute()

                    monthly_upload_count = new_upload_count

                except Exception as e:
                    st.warning(f"Analysis completed, but upload count could not be updated: {e}")

                st.session_state["bom_analysis_in_progress"] = False
                st.session_state["analysis_saved"] = True
                st.session_state["show_analysis_success_29b"] = True
                st.session_state["last_saved_analysis_id"] = analysis_id
                st.session_state["last_saved_analysis_at"] = datetime.now(timezone.utc).isoformat()
                # First-run completion must hand the engineer directly to the
                # result they just created; never require hunting through saved BOMs.
                st.session_state["pending_app_mode"] = "BOM Analyzer"
                st.session_state["app_mode"] = "BOM Analyzer"
                st.toast("Analysis complete. Opening your BOM analysis…", icon="✅")
                # The Saved BOM Manager was rendered earlier in this script run
                # from pre-save history. Rebuild once after persistence so the
                # new analysis appears immediately. analysis_saved prevents a
                # duplicate insert on the rerun.
                st.rerun()
        if "results_df" in st.session_state:
            results_df = st.session_state["results_df"]

            if st.session_state.get("analysis_saved") and st.session_state.get("analysis_id"):
                st.success("Saved automatically to your Cadivor workspace.")

            if st.session_state.get("show_analysis_success_29b") and st.session_state.get("analysis_id"):
                _high = len(results_df[results_df["Risk Level"] == "High"])
                _medium = len(results_df[results_df["Risk Level"] == "Medium"])
                render_analysis_success(
                    project_name=project_name or source_filename or "BOM analysis",
                    total_parts=len(results_df),
                    high_count=_high,
                    medium_count=_medium,
                    health_score=int(st.session_state.get("health_score", 0) or 0),
                    analysis_id=str(st.session_state.get("analysis_id")),
                )

            render_first_analysis_brief(
                results_df,
                health_score=int(st.session_state.get("health_score", 0) or 0),
                analysis_id=str(st.session_state.get("analysis_id") or "") or None,
                project_name=project_name or source_filename or "BOM analysis",
            )

            decision_cache_key = decision_brief_cache_key(
                session_key=str(st.session_state.get("analysis_id") or "live")
            )
            decision_brief = get_cached_decision_brief(decision_cache_key)
            if decision_brief is None:
                decision_brief = build_engineering_decision_brief(
                    results_df=results_df,
                    health_score=int(st.session_state.get("health_score", 0) or 0),
                )
                cache_decision_brief(decision_cache_key, decision_brief)
            render_engineering_decision_brief(decision_brief)

            show_dashboard_summary(results_df)

            results_df["Risk Level Display"] = results_df["Risk Level"].apply(risk_badge)

        
            st.markdown('<div id="detailed-risk-report"></div>', unsafe_allow_html=True)
            st.subheader("Detailed Risk Report")

            risk_filter = st.selectbox(
                "Filter by risk level",
                ["All", "High", "Medium", "Low"],
                key="bom81_detailed_risk_filter",
            )

            search_term = st.text_input("Search by part number")

            filtered_df = results_df.copy()

            if risk_filter != "All":
                filtered_df = filtered_df[filtered_df["Risk Level"] == risk_filter]

            if search_term:
                filtered_df = filtered_df[
                    filtered_df["MPN"].astype(str).str.contains(search_term, case=False, na=False)
                    | filtered_df["Normalized MPN"].astype(str).str.contains(search_term, case=False, na=False)
                ]

            filtered_df = filtered_df.sort_values(by="Risk Score", ascending=False)

            display_columns = [
                "MPN",
                "Manufacturer",
                "Best Source",
                "Sources Available",
                "Supplier Count",
                "Stock Available",
                "Lifecycle Status",
                "Risk Score",
                "Risk Level Display",

            ]

            filtered_df["Risk Level Display"] = filtered_df["Risk Level"].replace(
                {
                    "High": "🔴 High",
                    "Medium": "🟡 Medium",
                    "Low": "🟢 Low",
                }
            )

            cadivor_engineering_dataframe(
                filtered_df[display_columns],
                column_config={
                    "MPN": st.column_config.TextColumn(width="medium"),
                    "Manufacturer": st.column_config.TextColumn(width="medium"),
                    "Best Source": st.column_config.TextColumn(width="small"),
                    "Sources Available": st.column_config.TextColumn(
                        "Available Suppliers", width="medium"
                    ),
                    "Supplier Count": st.column_config.NumberColumn(width="small", format="%,d"),
                    "Stock Available": st.column_config.NumberColumn(width="small", format="%,d"),
                    "Lifecycle Status": st.column_config.TextColumn(width="medium"),
                    "Has Alternates": st.column_config.CheckboxColumn(width="small"),
                    "Risk Score": st.column_config.NumberColumn(width="small", format="%d"),
                    "Risk Level Display": st.column_config.TextColumn(width="small"),
                    "Risk Reasons": st.column_config.TextColumn(
                        "Risk Reasons",
                        width="large",
                    ),
                },
            )


            st.subheader("Part Details")

            for _, row in filtered_df.iterrows():

                risk_reasons = []

                if row["Stock Available"] == 0:
                    risk_reasons.append("No stock available")

                if row["Supplier Count"] <= 1:
                    risk_reasons.append("Single-source supplier")

                lifecycle_text = str(row["Lifecycle Status"]).lower()

                if "obsolete" in lifecycle_text:
                    risk_reasons.append("Component marked obsolete")

                if "unknown" in lifecycle_text:
                    risk_reasons.append("Unknown lifecycle status")

                if "replacement" in lifecycle_text:
                    risk_reasons.append("Replacement suggested")

                with st.expander(
                    f"{row['MPN']} — {row['Risk Level']} Risk"
                ):

                    if risk_reasons:
                        st.markdown("### ⚠️ Risk Drivers")

                        st.markdown(
                            '<div class="cv-action-list">'
                            + "".join(f'<div class="cv-action-row">{html.escape(str(reason))}</div>' for reason in risk_reasons)
                            + '</div>',
                            unsafe_allow_html=True,
                        )


                    col1, col2 = st.columns(2)

                    with col1:
                        st.write(f"**Manufacturer:** {row.get('Manufacturer', '')}")
                        st.write(f"**Lifecycle Status:** {row.get('Lifecycle Status', '')}")
                        st.write(f"**Stock Available:** {row.get('Stock Available', 0)}")
                        st.write(f"**Supplier Count:** {row.get('Supplier Count', 0)}")
                        st.write(
                            f"**Available Suppliers:** "
                            f"{row.get('Sources Available', '') or 'Not available'}"
                        )

                    with col2:
                        st.write(f"**Risk Score:** {row.get('Risk Score', 0)}")
                        st.write(f"**Risk Level:** {row.get('Risk Level', '')}")
                        has_alternates = row.get("Has Alternates", False)
                        st.write(
                            f"**Has Alternates:** {'✅ Yes' if has_alternates else '❌ No'}"
                        )

                    st.write("**Risk Reasons:**")
                    st.info(row.get("Risk Reasons", ""))

                    if row.get("Has Alternates", False):
                        st.write("**Candidate Alternatives:**")
                        st.success(row.get("Alternative Part Numbers", ""))
                    else:
                        st.write("**Candidate Alternatives:** None found")

                    if row.get("Product URL", ""):
                        st.markdown(f"[🔗 Open supplier product page]({row.get('Product URL')})")


            output_path = "reports/bom_risk_report.xlsx"

            save_results_to_excel(
                results_df.drop(columns=["Risk Level Display"]).to_dict("records"),
                output_path,
            )

            with open(output_path, "rb") as file:
                st.download_button(
                    label="Download Excel Report",
                    data=file,
                    file_name="bom_risk_report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            if st.session_state.get("show_upgrade_modal") and not is_admin:
                st.divider()
                st.subheader("Upgrade Your Plan")
                st.info("Paid plans are activated through secure Stripe checkout.")
                if st.button("Compare paid plans", key="secure_upgrade_view_plans"):
                    st.session_state.pop("show_upgrade_modal", None)
                    navigate_to("Pricing")




    # Authentication persistence is intentionally session scoped in this repair.
    # Re-introduce durable persistence only through a server-side/HttpOnly mechanism,
    # not a visible Streamlit component that can schedule frontend reruns.
    inject_workspace_geometry_final()
