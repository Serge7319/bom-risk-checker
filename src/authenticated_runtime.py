Warning: truncated output (original token count: 152368)
Total output lines: 13304

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
                        f"Compatibility Notes: {row.get('compatibility…122368 tokens truncated…      border-radius:17px;
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
            .st-key-bom8_sample button{
                border:1px solid #bfdbfe!important;
                background:#eff6ff!important;
                color:#1d4ed8!important;
                font-weight:800!important;
            }
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

        st.markdown('<div class="cv64-page-shell">', unsafe_allow_html=True)
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

        # Milestone 8.1 — Saved BOM Manager
        cadivor_panel(
            title=f"Saved BOM Manager ({saved_analysis_count})",
            subtitle="Search, sort, open, or select multiple analyses for bulk deletion.",
            tone="soft",
        )
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
            )

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
            sample_csv = sample_bom.to_csv(index=False).encode("utf-8")

            st.markdown(
                """
                <div class="bom8-column-example" aria-label="Recommended BOM columns">
                  <span>Manufacturer Part Number</span><span>Quantity</span><span>Description (optional)</span>
                </div>
                <div class="cv-beta-trust-note"><strong>Your BOM stays in your authenticated workspace.</strong> Cadivor uses it to generate your analysis and does not present customer BOM data as a product for sale.</div>
                """,
                unsafe_allow_html=True,
            )

            st.download_button(
                label="Download 10-Part Sample BOM",
                data=sample_csv,
                file_name="cadivor_10_part_sample_bom.csv",
                mime="text/csv",
                key="bom8_sample",
            )

            uploaded_file = st.file_uploader(
                "Upload your BOM file",
                type=["csv", "xlsx"],
                key="bom_file_uploader",
                help="Cadivor accepts CSV and XLSX files up to the Streamlit upload limit.",
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


        if uploaded_file is None:
            if history_data:
                st.info(
                    "Open a saved BOM analysis above, or upload a new CSV or Excel BOM."
                )
            else:
                st.info("Upload a CSV or Excel BOM to begin.")
            st.markdown("</div>", unsafe_allow_html=True)
            stop_authenticated_page()

        if not project_name.strip():
            st.warning("Please enter a Project / BOM Name before analyzing")
            st.markdown("</div>", unsafe_allow_html=True)
            stop_authenticated_page()

        try:
            if uploaded_file.name.endswith(".csv"):
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

    


        if st.session_state.get("uploaded_filename") != uploaded_file.name:
            st.session_state.pop("results_df", None)
            st.session_state["uploaded_filename"] = uploaded_file.name

    
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
            filename=uploaded_file.name,
            component_count=original_row_count,
            deduplicated_count=deduped_row_count,
        )

        st.subheader("Uploaded BOM Preview")
        st.data_editor(
            bom_df,
            use_container_width=True,
            hide_index=True,
        )


        if st.button("Analyze BOM", type="primary"):
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
                                "project_name": project_name or uploaded_file.name,
                                "filename": uploaded_file.name,
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
                            "project_name": project_name or uploaded_file.name,
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

                st.session_state["analysis_saved"] = True
                st.session_state["show_analysis_success_29b"] = True
                st.session_state["last_saved_analysis_id"] = analysis_id
                st.session_state["last_saved_analysis_at"] = datetime.now(timezone.utc).isoformat()
                st.toast("Analysis saved to your workspace.", icon="✅")
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
                    project_name=project_name or (uploaded_file.name if uploaded_file else "BOM analysis"),
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
                project_name=project_name or (uploaded_file.name if uploaded_file else "BOM analysis"),
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

        
            st.subheader("Detailed Risk Report")

            risk_filter = st.selectbox(
                "Filter by risk level",
                ["All", "High", "Medium", "Low"],
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
