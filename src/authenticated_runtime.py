Warning: truncated output (original token count: 149041)
Total output lines: 13147

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
        "Help",
        "About",
    ]
    if is_admin:
        NAV_OPTIONS.insert(NAV_OPTIONS.index("Settings"), "Admin Console")

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

    # Single-route authority. Query parameters are consumed only as an initial deep
    # link; internal navigation writes cadivor_route directly. Every shell and page
    # renderer below reads this same committed value.
    try:
        _raw_external_page = st.query_params.get("page", "")
        if isinstance(_raw_external_page, list):
            _raw_external_page = _raw_external_page[0] if _raw_external_page else ""
    except Exception:
        _raw_external_page = ""
    _external_page = _safe_text(_raw_external_page, "")

    app_mode = _safe_text(
        st.session_state.get("cadivor_route")
        or st.session_state.get("app_mode")
        or "Dashboard",
        "Dashboard",
    )
    if _external_page and not st.session_state.get("cadivor_external_route_consumed"):
        app_mode = _external_page
        st.session_state["cadivor_external_route_consumed"] = True

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
    if _incoming_analysis_id:
        st.session_state["cadivor_active_analysis_id"] = _incoming_analysis_id
        st.session_state["analysis_id"] = _incoming_analysis_id
    if _incoming_analysis_tab:
        st.session_state["cadivor_active_analysis_tab"] = _incoming_analysis_tab

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
        elif …89041 tokens truncated…        with st.container(border=True, key="af62b_best_card"):
                st.markdown(
                    f"""
                    <div class="af62b-best-top">
                      <div>
                        <div class="af62b-eyebrow">★ Recommended replacement</div>
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
                        <span>Recommendation Rank</span>
                        <strong>{"Best match" if selected_alternative == best_part_number else "Alternative candidate"}</strong>
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
                    Use these factors to understand the recommendation, then verify package, electrical
                    specifications, lifecycle, and live supplier availability before approving a replacement.
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
            st.warning("No suggested alternatives found.")

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
