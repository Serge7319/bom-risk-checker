YªçŠx-®éÜj×¢ëiºÚ+Š§j[h‘éÜ¢éíãO9çN|ç­¸o+^²‰¢¶×"""Cadivor authenticated application runtime.

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
from typing import Any
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
    render_portfolio_intelligence_workspace,
)
from src.decision_engine import (
    build_decision_center,
    decision_target_cell,
    decision_target_context,
    decision_target_label,
    decision_target_type,
    partition_decision_queue,
    STATUSES,
)
from src.decision_dashboard import packet_header_html
from src.bom_review_progress import (
    PROGRESS_CACHE_SECONDS,
    bom_review_parts_html,
    bom_review_progress_cache_key,
    bom_review_progress_html,
    load_bom_review_progress,
)
from src.decision_repository import (
    DECISION_LOAD_TIMEOUT_TOKEN,
    DEFAULT_DECISION_LOAD_BUDGET_SECONDS,
    load_decision_state,
    save_decision_workflow,
    save_decision_source_evidence,
    add_decision_note,
)
from src.procurement_advisor import build_procurement_advisor
from src.engineering_overview import build_engineering_overview
from src.plans import (
    PLANS,
    PLAN_TRIAL,
    PLAN_TRIAL_EXPIRED,
    PLAN_GRANDFATHERED_BETA,
    PLAN_SUBSCRIPTION_INACTIVE,
    get_plan,
    validate_bom_against_plan,
    resolve_effective_plan,
    format_limit,
    plan_display_label,
    trial_days_remaining,
    may_self_serve_checkout,
    annual_price_line,
    CHECKOUT_PLAN_TOKENS,
)
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
import logging
import time
import html
import re
import json
import math
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

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
from src.urls import app_checkout_url, app_url
from src.secrets import get_secret
from src.email_delivery import (
    EmailDeliveryError,
    email_delivery_configured,
    send_transactional_email,
    send_workspace_invitation_email,
)
from src.email_routing import BILLING_EMAIL, mailto_href
from src.monitoring_email_preferences import monitoring_email_enabled
from src.ui.navigation import (
    ALTERNATIVE_FINDER_PAGE,
    ALT_FINDER_RETURN_COMPONENT_KEY,
    ALT_FINDER_RETURN_DECISION_ID_KEY,
    ALT_FINDER_RETURN_MPN_KEY,
    ALT_FINDER_RETURN_PAGE_KEY,
    alternative_finder_href,
    apply_alternative_finder_prefill,
    begin_authenticated_page,
    consume_alternative_finder_context,
    consume_new_analysis_navigation,
    consume_navigation_error,
    DELAY_ROUTE_BODY_REVEAL_KEY,
    get_presented_route,
    internal_nav_button,
    mount_main_transition_loading,
    navigate_to,
    navigate_to_alternative_finder,
    open_high_risk_component_review,
    open_component_in_saved_bom,
    open_saved_bom,
    render_command_nav_triggers,
    reset_alternative_finder_prefill,
    reveal_authenticated_page_body,
    route_needs_main_transition,
    should_paint_opening_overlay,
    replace_navigation_query_params,
)
from src.browser_navigation import consume_browser_navigation_event
from src.ui.route_body import (
    claim_authenticated_route_body,
    enter_authenticated_route_body,
    exit_authenticated_route_body,
)
from src.ui.unified_shell import (
    render_unified_shell,
    inject_unified_shell_css,
)
from src.ui.workspace_consistency import inject_workspace_consistency_css
from src.ui.premium_interaction_repair import inject_premium_interaction_css
from src.ui.premium_interactions import render_premium_interactions
from src.components.command_center import render_command_center
from src.core.workspace_search import (
    build_workspace_commands,
    workspace_command_cache_is_fresh,
)
from src.ui.design_system_v1 import inject_design_system_v1
from src.ui.core_premium_ui import (
    inject_core_premium_ui,
    inject_workspace_geometry_final,
    mark_authenticated_surface_ready,
    stop_authenticated_page as _stop_authenticated_page_impl,
)


def stop_authenticated_page(*args, **kwargs):
    """End the page; never leave Openingâ€¦ mounted without a body reveal."""
    if st.session_state.get(DELAY_ROUTE_BODY_REVEAL_KEY):
        reveal_authenticated_page_body(
            str(
                st.session_state.get("cadivor_route")
                or st.session_state.get("app_mode")
                or ""
            )
        )
    exit_authenticated_route_body()
    return _stop_authenticated_page_impl(*args, **kwargs)
from src.ui.executive_workspace import inject_executive_workspace_css, render_page_context
from src.ui.executive_ux import inject_executive_ux_css, workflow_steps
from src.ui.enterprise_experience import inject_enterprise_experience_css, operation_status
from src.ui.cadivor_components import page_header as ds_page_header, kpi_grid as ds_kpi_grid, section_header as ds_section_header, empty_state as ds_empty_state
from src.ui.cadivor_design_system import (
    ExpandableTableColumn,
    MetricCard,
    cadivor_button_wrap,
    cadivor_button_wrap_end,
    cadivor_engineering_dataframe,
    cadivor_expandable_table,
    cadivor_smart_dataframe,
    cadivor_comparison_matrix_dataframe,
    humanize_table_date,
    cadivor_metric_row,
    cadivor_panel,
    cadivor_panel_end,
    cadivor_section_header,
    cadivor_table,
    render_decision_card_actions,
    render_kpi_row_safe,
    semantic_priority_label,
)
from src.alternative_candidate_intelligence import build_alternative_candidate_insight
from src.components.onboarding import (
    render_analysis_success,
    render_upload_detected,
    render_first_run_dashboard,
    render_activation_strip,
)
from src.components.upgrade_prompt import render_upgrade_prompt
from src.components.first_analysis_brief import render_first_analysis_brief
from src.shell_admin_entitlement import (
    is_admin_from_users_role,
    resolve_shell_admin_before_paint,
)
from src.onboarding_service import (
    ensure_onboarding_progress,
    update_onboarding_progress,
    completion_count,
    monotonic_progress_updates,
    required_setup_missing,
    should_show_setup_continuation,
)
from src.services.onboarding_progress_cache import (
    recent_onboarding_progress,
    remember_onboarding_progress,
)
from src.customer_profile_service import (
    ensure_customer_profile,
    update_customer_profile,
    ensure_user_preferences,
    notification_preferences_from_record,
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
    accept_my_pending_workspace_invites,
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
    """Load the Cadivor users row for the authenticated session.

    Idle recovery: refresh an expired/stale access token once before treating
    profile initialization as failed. Do not provision a new profile merely
    because a read failed under an expired JWT.
    """
    from src.auth_idle_recovery import load_workspace_profile
    from src.services.authenticated_profile_cache import (
        recent_verified_profile,
        remember_verified_profile,
    )
    from src.services.user_provisioning import (
        ensure_user_profile,
        repair_recent_default_trial_profile,
    )

    def _read_profile(user_id):
        return execute_supabase_read(
            supabase.table("users").select("*").eq("id", user_id),
            operation="load_user_data",
        )

    def _ensure_profile(client, auth_user):
        return ensure_user_profile(client, auth_user, operation="load_user_data")

    return load_workspace_profile(
        supabase=supabase,
        session_state=st.session_state,
        cookie_manager=cookie_manager,
        read_profile=_read_profile,
        ensure_profile=_ensure_profile,
        recent_profile=recent_verified_profile,
        remember_profile=remember_verified_profile,
        transport_error_type=SupabaseReadTransportError,
        repair_profile=repair_recent_default_trial_profile,
    )



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
            <h1 id="cadivor-maintenance-heading">Weâ€™re improving Cadivor.</h1>
            <p class="maintenance-message">{safe_message}</p>
            <div class="maintenance-assurance"><span class="maintenance-shield">&#9670;</span><span><strong>Your engineering data is safe.</strong><br/>Your workspace and saved analyses will be available again when service is restored.</span></div>
            <p class="maintenance-footer">Please check back shortly. For beta access or a launch blocker, contact <a href="mailto:beta@cadivor.com?subject=Cadivor%20Beta%20Blocker">beta@cadivor.com</a>.</p>
          </section>
        </main>
        """,
        unsafe_allow_html=True,
    )


_AUTH_USER_PROFILE_UNSET = object()


def get_user_profile(current_user, *, auth_user=_AUTH_USER_PROFILE_UNSET):
    """Return user-facing profile fields without assuming optional DB columns exist."""
    if not isinstance(current_user, dict):
        current_user = {}
    if auth_user is _AUTH_USER_PROFILE_UNSET:
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


def _workspace_commands_expected_scope(user_id):
    return (
        f"{str(user_id or '').strip()}:"
        f"{str(st.session_state.get('active_workspace_id') or '').strip()}"
    )


def _workspace_commands_cache_scope_matches(user_id):
    return (
        isinstance(st.session_state.get("cadivor_workspace_command_cache"), list)
        and str(st.session_state.get("cadivor_workspace_command_cache_scope") or "")
        == _workspace_commands_expected_scope(user_id)
    )


def _workspace_commands_cache_fresh(user_id):
    return workspace_command_cache_is_fresh(
        st.session_state.get("cadivor_workspace_command_cache"),
        st.session_state.get("cadivor_workspace_command_cache_at"),
        st.session_state.get("cadivor_workspace_command_cache_scope"),
        _workspace_commands_expected_scope(user_id),
    )


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
    context_key = (
        str(payload.get("context_key") or _decision_context_key(analysis_id)).strip()
        or "standalone"
    )

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
        "archived_at": None,
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
    project_name=None,
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

    if project_name:
        query = query.eq("project_name", str(project_name).strip())
    elif not include_all_contexts:
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
    comparison_family = str(
        comparison_snapshot.get("comparison_family")
        or ""
    )
    architecture_meaningful = False
    try:
        from src.component_family_profiles import get_family_profile

        architecture_meaningful = bool(
            get_family_profile(comparison_family).architecture_meaningful
        ) if comparison_family else False
    except Exception:
        architecture_meaningful = False
    if any(word in combined_warnings for word in ("package", "mounting", "footprint")):
        next_steps.append("Verify PCB footprint, land pattern, and mounting constraints.")
    if "voltage" in combined_warnings:
        next_steps.append("Confirm voltage ratings against the circuit operating limits.")
    if architecture_meaningful and any(
        word in combined_warnings for word in ("architecture", "channel")
    ):
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
            "âœ“": "",
            "âš ": "",
            "â„¹": "",
            "â—": "",
            "ðŸ”´": "",
            "ðŸŸ¢": "",
            "ðŸŸ¡": "",
            "â– ": "",
            "â–ª": "",
            "â–¡": "-",
            "â†’": "to",
            "â€¢": "-",
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
            cleaned_item = cleaned_item.replace("â– ", "").replace("â–ª", "").strip()

            if prefix == "ADVANTAGE:":
                stock_match = re.search(
                    r"([0-9]+(?:\.[0-9]+)?)\s*[xÃ—]\s*more stock",
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
                    "meta": f"{item.get('total_parts', 0)} parts â€¢ Health {item.get('health_score', 'â€”')} â€¢ {item.get('created_at', '')}",
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
                    "meta": f"{part.get('manufacturer', 'Unknown manufacturer')} â€¢ {part.get('risk_level', 'Unknown risk')} â€¢ {part.get('lifecycle_status', 'Unknown lifecycle')}",
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
                    "title": f"{alt.get('original_part', '')} â†’ {alt.get('alternative_part', '')}",
                    "meta": f"{alt.get('supplier', 'Unknown supplier')} â€¢ Score {alt.get('recommendation_score', 'â€”')} â€¢ Stock {alt.get('stock', 'â€”')}",
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
                "âŒ•",
            )
        else:
            for index, result in enumerate(results):
                page_name = str(result.get("page") or "Dashboard")
                st.markdown(
                    f"""
                    <div class="cv-result-card">
                      <div>
                        <div class="cv-result-title">{result.get('title', '')}</div>
                        <div class="cv-result-meta">{result.get('type', '')} â€¢ {result.get('meta', '')}</div>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                internal_nav_button(
                    "Open",
                    page_name,
                    key=f"global_search_open_{index}",
                    type="secondary",
                    analysis_id=result.get("analysis_id") or result.get("id") or "",
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
                    from integrations.pin_count import effective_pin_count

                    trusted_pins = effective_pin_count(
                        {
                            "pin_count": row.get("pin_count", 0),
                            "package": row.get("package", ""),
                        }
                    )
                    pin_display = (
                        str(trusted_pins) if trusted_pins > 0 else "Needs data"
                    )
                    engineering_text = (
                        f"<b>{row.get('alternative_part', '')}</b><br/>"
                        f"Architecture: {row.get('architecture', '')}<br/>"
                        f"Package: {row.get('package', '')}<br/>"
                        f"Pin Count: {pin_display}<br/>"
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
                                f"â€” ${float(best_value_row['unit_price']):.2f} "
                                f"with available stock of {best_value_row['stock']} units."
                            ),
                            styles["BodyText"],
                        )
                    )

                story.append(Spacer(1, 14))

           
    doc.build(story)

    buffer.seek(0)

    return buffer



def _canonical_route_allowlist() -> frozenset[str]:
    return frozenset(
        {
            "Dashboard",
            "BOM Analyzer",
            "BOM Settings",
            "High Risk Review",
            "Alternative Finder",
            "Compare Parts",
            "Datasheet Q&A",
            "Monitoring",
            "Engineering Decisions",
            "Procurement Advisor",
            "Portfolio Intelligence",
            "Design Impact Analyzer",
            "Cost Optimization",
            "Supply Risk Scenario",
            "Reports",
            "Pricing",
            "Single BOM Report",
            "Settings",
            "Workspace",
            "Notifications",
            "About",
            "Admin Console",
            "Help",
            "Admin",
            "Analysis Details",
            "Onboarding",
        }
    )


def resolve_canonical_app_route(*, allow_admin: bool = True) -> str:
    """Resolve one route for URL, session, shell chrome, and page dispatch.

    Browser Back/Forward events are authoritative. Streamlit can leave its
    server-side query snapshot on the page that was just left, so a restored
    browser route is retained until that stale snapshot catches up or the user
    starts a new in-app navigation.
    """
    from src.ui.navigation import (
        HISTORY_RESTORE_EVENT_KEY,
        HISTORY_RESTORE_SNAPSHOT_KEY,
        LAST_HISTORY_PUSH_PARAMS_KEY,
        LAST_HISTORY_PUSH_PAGE_KEY,
        PENDING_NAVIGATION_CONTEXT_KEY,
        commit_navigation_query_params,
        read_query_params,
    )

    browser_page = ""
    browser_params: dict[str, str] = {}
    observed_browser_params: dict[str, str] = {}
    browser_reason = ""
    browser_event_id = ""

    def _clean_query_state(values: dict[str, Any]) -> dict[str, str]:
        return {
            str(key): str(value).strip()
            for key, value in values.items()
            if str(key) not in {"cadivor_signed_out", "auth", "source"}
            and str(value or "").strip()
        }

    server_query_state = _clean_query_state(read_query_params())
    browser_event = consume_browser_navigation_event()
    previous_route = _safe_text(
        st.session_state.get("cadivor_route") or st.session_state.get("app_mode"),
        "",
    )
    if browser_event:
        event_id = _safe_text(browser_event.get("event_id"), "")
        href = _safe_text(browser_event.get("href"), "")
        browser_reason = _safe_text(browser_event.get("reason"), "")
        if (
            event_id
            and event_id != st.session_state.get("cadivor_last_browser_navigation_event_id")
            and href
        ):
            browser_event_id = event_id
            try:
                browser_params = {
                    key: values[-1]
                    for key, values in parse_qs(
                        urlparse(href).query,
                        keep_blank_values=True,
                    ).items()
                    if values
                }
            except Exception:
                browser_params = {}
            observed_browser_params = dict(browser_params)
            browser_page = _safe_text(browser_params.get("page"), "")
            st.session_state["cadivor_last_browser_navigation_event_id"] = event_id
            # The polling fallback also sees intentional in-app URL writes.
            # Compare the complete query state: a Back/Forward hop can keep the
            # same page while restoring a different analysis or focused part.
            browser_query_state = _clean_query_state(browser_params)
            last_push_state = st.session_state.get(LAST_HISTORY_PUSH_PARAMS_KEY)
            if not isinstance(last_push_state, dict):
                last_push_state = {}
            last_push_state = {
                str(key): str(value).strip()
                for key, value in last_push_state.items()
                if str(key) not in {"cadivor_signed_out", "auth", "source"}
                and str(value or "").strip()
            }
            if browser_reason == "url-change" and browser_query_state and (
                browser_query_state == server_query_state
                or (last_push_state and browser_query_state == last_push_state)
            ):
                browser_page = ""
                browser_params = {}
                browser_reason = ""
                browser_event_id = ""

    try:
        raw_qp = st.query_params.get("page", "")
        if isinstance(raw_qp, list):
            raw_qp = raw_qp[0] if raw_qp else ""
    except Exception:
        raw_qp = ""
    query_page = _safe_text(raw_qp, "")
    session_page = previous_route

    restore_snapshot_raw = st.session_state.get(HISTORY_RESTORE_SNAPSHOT_KEY)
    restore_snapshot = (
        dict(restore_snapshot_raw)
        if isinstance(restore_snapshot_raw, dict)
        else {}
    )
    snapshot_route = _safe_text(restore_snapshot.get("route"), "")
    snapshot_stale_query_page = _safe_text(
        restore_snapshot.get("stale_query_page"),
        "",
    )
    snapshot_target_params = _clean_query_state(
        restore_snapshot.get("params")
        if isinstance(restore_snapshot.get("params"), dict)
        else {}
    )
    snapshot_stale_params = _clean_query_state(
        restore_snapshot.get("stale_query_params")
        if isinstance(restore_snapshot.get("stale_query_params"), dict)
        else {}
    )
    if snapshot_route and session_page and snapshot_route != session_page:
        st.session_state.pop(HISTORY_RESTORE_SNAPSHOT_KEY, None)
        restore_snapshot = {}
        snapshot_route = ""
        snapshot_stale_query_page = ""
        snapshot_target_params = {}
        snapshot_stale_params = {}

    snapshot_active = bool(snapshot_route and snapshot_route == session_page)
    snapshot_query_pending = bool(
        snapshot_active
        and snapshot_target_params
        and server_query_state != snapshot_target_params
    )
    query_diverged = bool(
        query_page and session_page and query_page != session_page
    )
    # An explicit BOM Analyzer click can race a stale Analysis Details query.
    # That snapshot has no analysis id and paints the red empty-report error.
    # Keep the catalog until the user opens a saved BOM.
    if (
        not browser_page
        and session_page == "BOM Analyzer"
        and bool(st.session_state.get("cadivor_bom_catalog_requested"))
        and query_page != "BOM Analyzer"
    ):
        query_diverged = False
    stale_query_after_restore = snapshot_query_pending or bool(
        snapshot_active
        and not snapshot_stale_params
        and query_diverged
        and query_page == snapshot_stale_query_page
    )
    history_restore = bool(browser_page) or (
        query_diverged and not stale_query_after_restore
    )

    if browser_page:
        route = browser_page
    elif query_diverged and not stale_query_after_restore:
        # When the bridge event is missed, a genuinely new query route can
        # still restore browser history. The exact stale query recorded by a
        # prior bridge restore is never allowed to bounce the user forward.
        route = query_page
    elif session_page:
        route = session_page
    elif query_page:
        route = query_page
    else:
        route = "Dashboard"

    allow = _canonical_route_allowlist()
    if not allow_admin:
        allow = allow - {"Admin Console", "Help", "Admin"}
    if route not in allow:
        route = "Dashboard"

    pending_navigation_context = _clean_query_state(
        st.session_state.get(PENDING_NAVIGATION_CONTEXT_KEY)
        if isinstance(st.session_state.get(PENDING_NAVIGATION_CONTEXT_KEY), dict)
        else {}
    )
    if browser_page or (
        pending_navigation_context
        and pending_navigation_context.get("page") != route
    ):
        # A real Back/Forward event or a different destination supersedes a
        # same-page callback that was waiting for StreÛ]µçkh‘éì¶»§q«^uÈ½¹”µÑ¥µ”	=4É•Á½ÉÐ¥ÌÉ•…‘ä¸UÁ±½…ÕÀÑ¼í=9}Q%5}	=5}5a}AIQMôÕ¹¥ÅÕ”½µÁ½¹•¹ÑÌì€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰Ñ¡”Í…Ù•	=4…¹¥ÑÌÉ•Á½ÉÐÁ…­…”Ý¥±°É•µ…¥¸¥¸å½ÕÈÝ½É­ÍÁ…”¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•±¥˜}½¹•}Ñ¥µ•}¥¹}ÁÉ½É•ÍÌè(€€€€€€€€€€€€€€€€€€€ÍÐ¹¥¹™¼ (€€€€€€€€€€€€€€€€€€€€€€€€‰Á…¥	=4…¹…±åÍ¥Ì¥Ì…±É•…‘ä¥¸ÁÉ½É•ÍÌ™½ÈÑ¡¥Ì…½Õ¹Ð¸€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€‰I•ÑÕÉ¸Ñ¼¥ÑÌ½Á•¸Ñ…ˆ°½È½¹Ñ…ÐÍÕÁÁ½ÉÐ¥˜¥ÐÝ…Ì¥¹Ñ•ÉÉÕÁÑ•¸€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€‰¸¥¹Ñ•ÉÉÕÁÑ•É•Í•ÉÙ…Ñ¥½¸‰•½µ•Ì…Ù…¥±…‰±”……¥¸…™Ñ•È™½ÕÈ¡½ÕÉÌ¸ˆ(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤(€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}™•…ÑÕÉ•}•¹…‰±•…¹ÕÁ±½…‘•‘}™¥±”¥Ì9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Ý…É¹¥¹œ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰M…Ù•	=5Ì…¹É•Á½ÉÑÌÉ•µ…¥¸…Ù…¥±…‰±”¸¡½½Í”„Á±…¸½È‰Õä„½¹”µÑ¥µ”€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰É•Á½ÉÐÑ¼Í…Ù”„¹•Ü™Õ±°…¹…±åÍ¥Ì¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹…ÁÑ¥½¸ (€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰=¹”É•Á½ÉÐ½Ù•ÉÌÕÀÑ¼í=9}Q%5}	=5}5a}AIQMôÕ¹¥ÅÕ”½µÁ½¹•¹ÑÌ…¹¥¹±Õ‘•Ì€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰Ñ¡”ÍÑ…¹‘…ÉA…¹MX¸e½Ô…¸…¹…±åé”™¥ÉÍÐÑ¼ÁÉ•Ù¥•ÜÑ¡”É•ÍÕ±ÑÌì€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰…‘¥Ù½ÈÝ¥±°…Í¬™½ÈÁ…åµ•¹Ð‰•™½É”Í…Ù¥¹œÑ¡”™Õ±°É•Á½ÉÐ¸9¼ÍÕ‰ÍÉ¥ÁÑ¥½¸¥ÌÉ•ÅÕ¥É•¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€}¡•­½ÕÑ}­•ä€ô˜‰…‘¥Ù½É}½¹•}Ñ¥µ•}¡•­½ÕÑ}í}½¹•}Ñ¥µ•}ÕÍ•É}¥‘ôˆ(€€€€€€€€€€€€€€€€€€€€€€€}Á•¹‘¥¹}¡•­½ÕÐ€ôÁ•¹‘¥¹}½¹•}Ñ¥µ•}¡•­½ÕÐ¡}½¹•}Ñ¥µ•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}ÁÉ¥”€ô½¹•}Ñ¥µ•}É•Á½ÉÑ}ÁÉ¥•}±…‰•° (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÑÈ¡•Ñ}Í•É•Ð ‰MQI%A}=9}Q%5}	=5}IA=IQ}AI%}%ˆ°É•ÅÕ¥É•õQÉÕ”¤¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€•á•ÁÐ=¹•Q¥µ•	=5ÉÉ½È…Ì•áŒè(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È¡ÍÑÈ¡•áŒ¤¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}ÁÉ¥”€ô€ˆˆ(€€€€€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}ÁÉ¥”…¹¹½Ð}Á•¹‘¥¹}¡•­½ÕÐ…¹ÍÐ¹‰ÕÑÑ½¸ (€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰	Õä½¹”	=4É•Á½ÉÐƒ
Üí}½¹•}Ñ¥µ•}ÁÉ¥•ôˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€­•äô‰‰½µ}½¹•}Ñ¥µ•}‰Õäˆ°ÑåÁ”ô‰ÁÉ¥µ…Éäˆ°(€€€€€€€€€€€€€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•m}¡•­½ÕÑ}­•åt€ô‰•¥¹}½¹•}Ñ¥µ•}¡•­½ÕÐ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÑÈ¡ÕÉÉ•¹Ñ}ÕÍ•È¹•Ð ‰•µ…¥°ˆ¤½È€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…ÁÁ}¡•­½ÕÑ}ÕÉ°¡Á…”ô‰	=4¹…±åé•Èˆ°¡•­½ÕÐô‰Í¥¹±•}‰½µ}ÍÕ•ÍÌˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…ÁÁ}¡•­½ÕÑ}ÕÉ°¡Á…”ô‰	=4¹…±åé•Èˆ°¡•­½ÕÐô‰Í¥¹±•}‰½µ}…¹•°ˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€•á•ÁÐ=¹•Q¥µ•	=5ÉÉ½È…Ì•áŒè(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È¡ÍÑÈ¡•áŒ¤¤(€€€€€€€€€€€€€€€€€€€€€€€¥˜}Á•¹‘¥¹}¡•­½ÕÐè(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹¥¹™¼ ‰¡•­½ÕÐ¥ÌÁÉ½•ÍÍ¥¹œ¸I•™É•Í Í¡½ÉÑ±äÑ¼Í•”å½ÕÈÁ…¥É•Á½ÉÐÉ•‘¥Ð¸ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€•±¥˜ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð¡}¡•­½ÕÑ}­•ä¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹±¥¹­}‰ÕÑÑ½¸ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰½¹Ñ¥¹Õ”Ñ¼Í•ÕÉ”¡•­½ÕÐƒŠHˆ°ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•m}¡•­½ÕÑ}­•åt°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÑåÁ”ô‰ÁÉ¥µ…Éäˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€¥˜}Í…™•}Ñ•áÐ¡}É•Í½±Ù•‘}ÅÁ}Ù…±Õ” ‰¡•­½ÕÐˆ°€ˆˆ¤¤€ôô€‰Í¥¹±•}‰½µ}ÍÕ•ÍÌˆè(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹¥¹™¼ ‰A…åµ•¹Ð½¹™¥Éµ…Ñ¥½¸¥ÌÁÉ½•ÍÍ¥¹œ¸I•™É•Í Ñ¡¥ÌÁ…”¥¸„µ½µ•¹ÐÑ¼ÕÍ”å½ÕÈÉ•Á½ÉÐÉ•‘¥Ð¸ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€•±¥˜}Í…™•}Ñ•áÐ¡}É•Í½±Ù•‘}ÅÁ}Ù…±Õ” ‰¡•­½ÕÐˆ°€ˆˆ¤¤€ôô€‰Í¥¹±•}‰½µ}…¹•°ˆè(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹¥¹™¼ ‰¡•­½ÕÐÝ…Ì…¹•±•¸9¼É•Á½ÉÐÉ•‘¥ÐÝ…ÌÁÕÉ¡…Í•¸ˆ¤(€€€€€€€€€€€€€€€€€€€•±¥˜Í•±•Ñ•‘}Á±…¹}¹…µ”€ôôA19}MU	MI%AQ%=9}%9Q%Yè(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Ý…É¹¥¹œ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰Q¡¥ÌÍÕ‰ÍÉ¥ÁÑ¥½¸¥Ì¹½Ð…Ñ¥Ù”¸M…Ù•…¹…±åÍ•Ì…‰½Ù”É•µ…¥¸…Ù…¥±…‰±”Ñ¼½Á•¸…¹‘½Ý¹±½…¸€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰¡½½Í”„Á…¥Á±…¸Ñ¼É•…Ñ”„¹•Ü…¹…±åÍ¥Ì¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Ý…É¹¥¹œ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰e½ÕÈÑÉ¥…°¡…Ì•¹‘•¸M…Ù•…¹…±åÍ•Ì…‰½Ù”É•µ…¥¸…Ù…¥±…‰±”Ñ¼½Á•¸…¹‘½Ý¹±½…¸€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰¡½½Í”„Á…¥Á±…¸Ñ¼É•…Ñ”„¹•Ü…¹…±åÍ¥Ì¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€¥˜¹½Ð}½¹•}Ñ¥µ•}™•…ÑÕÉ•}•¹…‰±•½ÈÕÁ±½…‘•‘}™¥±”¥Ì9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€¥˜ÍÐ¹‰ÕÑÑ½¸ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰½µÁ…É”Á±…¹Ìˆ¥˜}½¹•}Ñ¥µ•}™•…ÑÕÉ•}•¹…‰±••±Í”€‰¡½½Í”„Á…¥Á±…¸ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€­•äô‰‰½µ}ÑÉ¥…±}•áÁ¥É•‘}¡½½Í•}Á±…¸ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÑåÁ”ô‰Í•½¹‘…Éäˆ¥˜}½¹•}Ñ¥µ•}™•…ÑÕÉ•}•¹…‰±••±Í”€‰ÁÉ¥µ…Éäˆ°(€€€€€€€€€€€€€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€¹…Ù¥…Ñ•}Ñ¼ ‰AÉ¥¥¹œˆ¤(€€€€€€€€€€€€€€€€€€€¥˜¹½Ð}½¹•}Ñ¥µ•}™•…ÑÕÉ•}•¹…‰±•è(€€€€€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤((€€€€€€€€€€€…¹…±åÍ¥Í}¥¹}ÁÉ½É•ÍÌ€ô‰½½° (€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}…¹…±åÍ¥Í}™ÕÑÕÉ”ˆ¤(€€€€€€€€€€€€€€€½È}…ÁÁÉ½Ù•‘}…¹…±åÍ¥Í}É•ÅÕ•ÍÑ•(€€€€€€€€€€€€€€€½ÈÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}…¹…±åÍ¥Í}Á•¹‘¥¹œˆ¤(€€€€€€€€€€€€€€€½ÈÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}Í…µÁ±•}…ÕÑ½}…¹…±åé”ˆ¤(€€€€€€€€€€€€€€€½ÈÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}…¹…±åÍ¥Í}¥¹}ÁÉ½É•ÍÌˆ¤(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}…¹•±±•‘}¹½Ñ¥”ˆ°…±Í”¤è(€€€€€€€€€€€€€€€ÍÐ¹ÍÕ•ÍÌ ‰¹…±åÍ¥Ì…¹•±•¸9¼	=4…¹…±åÍ¥ÌÝ…ÌÍ…Ù•¸ˆ¤(€€€€€€€€€€€Í…µÁ±•}‰½´€ôÁ¹…Ñ…É…µ” ¤(€€€€€€€€€€€¥˜Í¡½Õ±‘}É•¹‘•É}±•…å}‰½µ}Ý½É­ÍÁ…”¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¤è(€€€€€€€€€€€€€€€}‰½µ}Ý½É­ÍÁ…•}É¥‘}½¹Ñ•áÐ€ôÍÐ¹½¹Ñ…¥¹•È¡­•äô‰‰½´å}Ý½É­ÍÁ…•}É¥ˆ¤(€€€€€€€€€€€€€€€}‰½µ}Ý½É­ÍÁ…•}É¥‘}½¹Ñ•áÐ¹}}•¹Ñ•É}| ¤(€€€€€€€€€€€€€€€¥¹ÁÕÑ}½°°Í…Ù•‘}µ…¹…•É}½°€ôÍÐ¹½±Õµ¹Ì¡lÀ¸Ìà°€À¸ØÉt°…Àô‰±…É”ˆ¤((€€€€€€€€€€€€€€€Ý¥Ñ ¥¹ÁÕÑ}½°è(€€€€€€€€€€€€€€€€€€€}‰½µ}ÕÁ±½…‘}Á…¹•±}½¹Ñ•áÐ€ôÍÐ¹½¹Ñ…¥¹•È (€€€€€€€€€€€€€€€€€€€€€€€‰½É‘•ÈõQÉÕ”°(€€€€€€€€€€€€€€€€€€€€€€€­•äô‰‰½´å}ÕÁ±½…‘}Á…¹•°ˆ°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€}‰½µ}ÕÁ±½…‘}Á…¹•±}½¹Ñ•áÐ¹}}•¹Ñ•É}| ¤(€€€€€€€€€€€€€€€€€€€}‰½µ}ÕÁ±½…‘}¥¹ÑÉ¼€ô€ (€€€€€€€€€€€€€€€€€€€€€€€€‰9…µ”Ñ¡”Ý½É¬°Ñ¡•¸ÕÁ±½…å½ÕÈ½Ý¸MX½Èá•°™¥±”¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}‰±½­•‘}Á±…¸•±Í”(€€€€€€€€€€€€€€€€€€€€€€€€‰9…µ”Ñ¡”Ý½É¬°Ñ¡•¸¡½½Í”…‘¥Ù½ÈÌÍ…µÁ±”½ÈÕÁ±½…å½ÕÈ½Ý¸MX½Èá•°™¥±”¸ˆ(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹µ…É­‘½Ý¸ (€€€€€€€€€€€€€€€€€€€€€€€˜ˆˆˆ(€€€€€€€€€€€€€€€€€€€€€€€€ñ‘¥Ø±…ÍÌô‰‰½´äµÕÁ±½…µµ…É­•Èˆøð½‘¥Øø(€€€€€€€€€€€€€€€€€€€€€€€€ñÍ•Ñ¥½¸±…ÍÌô‰‰½´äµÁ…¹•°µ¥¹ÑÉ¼ˆø(€€€€€€€€€€€€€€€€€€€€€€€€€€ñ‘¥Øø(€€€€€€€€€€€€€€€€€€€€€€€€€€€€ñ‘¥Ø±…ÍÌô‰‰½´äµÁ…¹•°µ­¥­•Èˆù9•Ü…¹…±åÍ¥Ìð½‘¥Øø(€€€€€€€€€€€€€€€€€€€€€€€€€€€€ñ ÈùUÁ±½…•¹¥¹••É¥¹œ	=4ð½ Èø(€€€€€€€€€€€€€€€€€€€€€€€€€€€€ñÀùí}‰½µ}ÕÁ±½…‘}¥¹ÑÉ½ôð½Àø(€€€€€€€€€€€€€€€€€€€€€€€€€€ð½‘¥Øø(€€€€€€€€€€€€€€€€€€€€€€€€ð½Í•Ñ¥½¸ø(€€€€€€€€€€€€€€€€€€€€€€€€ˆˆˆ°(€€€€€€€€€€€€€€€€€€€€€€€Õ¹Í…™•}…±±½Ý}¡Ñµ°õQÉÕ”°(€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€ÁÉ½©•Ñ}¹…µ•}½°°‰½µ}¹…µ•}½°€ôÍÐ¹½±Õµ¹Ì È°…Àô‰Íµ…±°ˆ¤(€€€€€€€€€€€€€€€€€€€Ý¥Ñ ÁÉ½©•Ñ}¹…µ•}½°è(€€€€€€€€€€€€€€€€€€€€€€€ÁÉ½©•Ñ}¹…µ”€ôÍÐ¹Ñ•áÑ}¥¹ÁÕÐ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰AÉ½©•Ð9…µ”€¡½ÁÑ¥½¹…°¤ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€Á±…•¡½±‘•Èô‰á…µÁ±”è5½Ñ½È½¹ÑÉ½±±•Èˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€­•äô‰‰½´á}ÁÉ½©•Ñ}¹…µ”ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€…ÕÑ½½µÁ±•Ñ”ô‰½™˜ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€‘¥Í…‰±•õ…¹…±åÍ¥Í}¥¹}ÁÉ½É•ÍÌ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€¡•±Àô‰UÍ”„ÁÉ½©•ÐÑ¼É½ÕÀµÕ±Ñ¥Á±”	=4É•Ù¥Í¥½¹Ì½È…ÍÍ•µ‰±¥•Ì¸ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€Ý¥Ñ ‰½µ}¹…µ•}½°è(€€€€€€€€€€€€€€€€€€€€€€€‰½µ}¹…µ”€ôÍÐ¹Ñ•áÑ}¥¹ÁÕÐ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰	=49…µ”ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€Á±…•¡½±‘•Èô‰á…µÁ±”è5½Ñ½È½¹ÑÉ½±±•ÈI•Øˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€­•äô‰‰½´á}‰½µ}¹…µ”ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€…ÕÑ½½µÁ±•Ñ”ô‰½™˜ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€‘¥Í…‰±•õ…¹…±åÍ¥Í}¥¹}ÁÉ½É•ÍÌ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€¡•±Àô‰I•ÅÕ¥É•¸9…µ”Ñ¡¥ÌÍÁ•¥™¥Œ	=4°É•Ù¥Í¥½¸°½È…ÍÍ•µ‰±ä¸ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€¥˜¹½Ð‰½µ}¹…µ”¹ÍÑÉ¥À ¤…¹¹½ÐÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}Í…µÁ±•}…ÕÑ½}…¹…±åé”ˆ¤è(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹µ…É­‘½Ý¸ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€ˆˆˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€ñ‘¥Ø±…ÍÌô‰‰½´äµ™½É´µ¹½Ñ”ˆÉ½±”ô‰ÍÑ…ÑÕÌˆø(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ñÍÑÉ½¹œùI•ÅÕ¥É•ð½ÍÑÉ½¹œø(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ñÍÁ…¸ù‘„	=49…µ”‰•™½É”ÕÁ±½…‘¥¹œ¸AÉ½©•Ð9…µ”¥Ì½ÁÑ¥½¹…°…¹¡•±ÁÌÉ½ÕÀÉ•Ù¥Í¥½¹Ì¸ð½ÍÁ…¸ø(€€€€€€€€€€€€€€€€€€€€€€€€€€€€ð½‘¥Øø(€€€€€€€€€€€€€€€€€€€€€€€€€€€€ˆˆˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€Õ¹Í…™•}…±±½Ý}¡Ñµ°õQÉÕ”°(€€€€€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€Í…µÁ±•}‰½´€ôÁ¹…Ñ…É…µ” (€€€€€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰µÁ¸ˆèl(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰MQ4ÌÉÄÀÍáPØˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰QALÔÐÌÁHˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰5@ÈÔÔÄµ$½M8ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰	DÈÐÀÜÑIQHˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰LÄÄÄÕ%MHˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰\ÈÕDØÑ)YMM%Dˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰M8ÜÑ1YÉPÐÕUHˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰AàÄÝ`É9MhÅˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰I4ÄàáHÜÅÄÀÑ-ÀÅˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰IÀØÀÍH´ÀÜÄÁ-0ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÅÕ…¹Ñ¥ÑäˆèlÄ°€È°€Ä°€Ä°€Ä°€Ä°€È°€Ð°€ÄÈ°€át°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰‘•ÍÉ¥ÁÑ¥½¸ˆèl(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ˆÌÈµ‰¥Ðµ¥É½½¹ÑÉ½±±•Èˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ˆÌ‰Õ¬É•Õ±…Ñ½Èˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰8ÑÉ…¹Í•¥Ù•Èˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰1¤µ¥½¸‰…ÑÑ•Éä¡…É•Èˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ˆÄØµ‰¥Ðˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ˆØÐ5‰¥ÐÍ•É¥…°™±…Í µ•µ½Éäˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰Õ…°µ‰¥ÐÙ½±Ñ…”µ±•Ù•°ÑÉ…¹Í±…Ñ½Èˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰=ÁÑ½½ÕÁ±•Èˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ˆÀ¸ÄÕ•É…µ¥Œ…Á…¥Ñ½Èˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ˆÄÀ­=¡´É•Í¥ÍÑ½Èˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€t°(€€€€€€€€€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹µ…É­‘½Ý¸ (€€€€€€€€€€€€€€€€€€€€€€€€ˆˆˆ(€€€€€€€€€€€€€€€€€€€€€€€€ñ‘¥Ø±…ÍÌô‰Øµ‰•Ñ„µÑÉÕÍÐµ¹½Ñ”ˆøñÍÑÉ½¹œùe½ÕÈ	=4ÍÑ…åÌ¥¸å½ÕÈ…ÕÑ¡•¹Ñ¥…Ñ•Ý½É­ÍÁ…”¸ð½ÍÑÉ½¹œø…‘¥Ù½ÈÕÍ•Ì¥ÐÑ¼•¹•É…Ñ”å½ÕÈ…¹…±åÍ¥Ì…¹‘½•Ì¹½ÐÁÉ•Í•¹ÐÕÍÑ½µ•È	=4‘…Ñ„…Ì„ÁÉ½‘ÕÐ™½ÈÍ…±”¸ð½‘¥Øø(€€€€€€€€€€€€€€€€€€€€€€€€ˆˆˆ°(€€€€€€€€€€€€€€€€€€€€€€€Õ¹Í…™•}…±±½Ý}¡Ñµ°õQÉÕ”°(€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€‘•˜}ÍÑ…ÉÑ}Í…µÁ±•}‰½´ ¤€´ø9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}Í…µÁ±•}µ½‘”‰t€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}Í…µÁ±•}…ÕÑ½}…¹…±åé”‰t€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}ÁÉ½©•Ñ}¹…µ”‰t€ô€‰…‘¥Ù½ÈÍ…µÁ±”ˆ(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}‰½µ}¹…µ”‰t€ô€ˆÄÀµA…ÉÐM…µÁ±”	=4ˆ(€€€€€€€€€€€€€€€€€€€€€€€™½ÈÍÑ…Ñ•}­•ä¥¸€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰É•ÍÕ±ÑÍ}‘˜ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰…¹…±åÍ¥Í}Í…Ù•ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰…¹…±åÍ¥Í}¥ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰¡•…±Ñ¡}Í½É”ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰¡•…±Ñ¡}ÍÑ…ÑÕÌˆ°(€€€€€€€€€€€€€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À¡ÍÑ…Ñ•}­•ä°9½¹”¤((€€€€€€€€€€€€€€€€€€€‘•˜}ÕÍ•}ÕÁ±½…‘•‘}‰½´ ¤€´ø9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}Í…µÁ±•}µ½‘”ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}Í…µÁ±•}…ÕÑ½}…¹…±åé”ˆ°9½¹”¤((€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}‰±½­•‘}Á±…¸è(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹…ÁÑ¥½¸ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰e½ÕÈÁ…¥É•Á½ÉÐÉ•‘¥Ð¥Ì™½Èå½ÕÈ½Ý¸	=4¸Q¡”…‘¥Ù½ÈÍ…µÁ±”Ý¥±°¹½ÐÕÍ”¥Ð¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹µ…É­‘½Ý¸ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€œñ‘¥Ø±…ÍÌô‰‰½´àµÁ…Ñ µ±…‰•°ˆù=ÁÑ¥½¸€ÄƒŠPáÁ±½É”…‘¥Ù½È€ñÍÁ…¸ùUÍ”…‘¥Ù½ÉpÌ¥¹±Õ‘••á…µÁ±”Ñ¼Í•”„½µÁ±•Ñ”…¹…±åÍ¥Ì¸%ÐÝ¥±°‰”Í…Ù•…Ì„Í…µÁ±”°¹½Ðå½ÕÈ½Ý¸	=4¸ð½ÍÁ…¸øð½‘¥Øøœ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€Õ¹Í…™•}…±±½Ý}¡Ñµ°õQÉÕ”°(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹‰ÕÑÑ½¸ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰¹…±åé”Ñ¡”€ÄÀµA…ÉÐM…µÁ±”	=4ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€­•äô‰‰½´á}ÑÉå}Í…µÁ±”ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÑåÁ”ô‰ÁÉ¥µ…Éäˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€¡•±Àô‰1½……¹…¹…±åé”…‘¥Ù½ÈÌÍ…µÁ±”	=4¥¸Ñ¡¥ÌÝ½É­ÍÁ…—ŠQ¹¼‘½Ý¹±½…½ÈÉ”µÕÁ±½…É•ÅÕ¥É•¸ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€½¹}±¥¬õ}ÍÑ…ÉÑ}Í…µÁ±•}‰½´°(€€€€€€€€€€€€€€€€€€€€€€€€€€€‘¥Í…‰±•õ…¹…±åÍ¥Í}¥¹}ÁÉ½É•ÍÌ°(€€€€€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€ÍÐ¹µ…É­‘½Ý¸ (€€€€€€€€€€€€€€€€€€€€€€€€œñ‘¥Ø±…ÍÌô‰‰½´àµÁ…Ñ µ±…‰•°ˆù¹…±åé”å½ÕÈ	=4€ñÍÁ…¸ùUÁ±½…å½ÕÈ½Ý¸MX½Èá•°™¥±”™½È…¸•¹¥¹••É¥¹œÉ•Ù¥•Ü½˜å½ÕÈ…ÑÕ…°‘•Í¥¸¸ð½ÍÁ…¸øð½‘¥Øøœ¥˜}½¹•}Ñ¥µ•}‰±½­•‘}Á±…¸•±Í”(€€€€€€€€€€€€€€€€€€€€€€€€œñ‘¥Ø±…ÍÌô‰‰½´àµÁ…Ñ µ±…‰•°ˆù=ÁÑ¥½¸€ÈƒŠP¹…±åé”å½ÕÈ	=4€ñÍÁ…¸ùUÁ±½…å½ÕÈ½Ý¸MX½Èá•°™¥±”™½È…¸•¹¥¹••É¥¹œÉ•Ù¥•Ü½˜å½ÕÈ…ÑÕ…°‘•Í¥¸¸ð½ÍÁ…¸øð½‘¥Øøœ°(€€€€€€€€€€€€€€€€€€€€€€€Õ¹Í…™•}…±±½Ý}¡Ñµ°õQÉÕ”°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€ÕÁ±½…‘•‘}™¥±”€ôÍÐ¹™¥±•}ÕÁ±½…‘•È (€€€€€€€€€€€€€€€€€€€€‰UÁ±½…å½ÕÈ	=4™¥±”ˆ°(€€€€€€€€€€€€€€€€€€€€€€€ÑåÁ”õl‰ÍØˆ°€‰á±Íà‰t°(€€€€€€€€€€€€€€€€€€€€€€€­•äô‰‰½µ}™¥±•}ÕÁ±½…‘•Èˆ°(€€€€€€€€€€€€€€€€€€€€€€€¡•±Àô‰…‘¥Ù½È…•ÁÑÌMX…¹a1M`™¥±•ÌÕÀÑ¼Ñ¡”MÑÉ•…µ±¥ÐÕÁ±½…±¥µ¥Ð¸ˆ°(€€€€€€€€€€€€€€€€€€€€€€€½¹}¡…¹”õ}ÕÍ•}ÕÁ±½…‘•‘}‰½´°(€€€€€€€€€€€€€€€€€€€€€€€‘¥Í…‰±•õ…¹…±åÍ¥Í}¥¹}ÁÉ½É•ÍÌ°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€}‰½µ}ÕÁ±½…‘}Á…¹•±}½¹Ñ•áÐ¹}}•á¥Ñ}|¡9½¹”°9½¹”°9½¹”¤((€€€€€€€€€€€€€€€Ý¥Ñ Í…Ù•‘}µ…¹…•É}½°è(€€€€€€€€€€€€€€€€€€€}‰½µ}Í…Ù•‘}Á…¹•±}½¹Ñ•áÐ€ôÍÐ¹½¹Ñ…¥¹•È (€€€€€€€€€€€€€€€€€€€€€€€‰½É‘•ÈõQÉÕ”°(€€€€€€€€€€€€€€€€€€€€€€€­•äô‰‰½´å}Í…Ù•‘}Á…¹•°ˆ°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€}‰½µ}Í…Ù•‘}Á…¹•±}½¹Ñ•áÐ¹}}•¹Ñ•É}| ¤(€€€€€€€€€€€€€€€€€€€}É•¹‘•É}Í…Ù•‘}‰½µ}µ…¹…•È ¤(€€€€€€€€€€€€€€€€€€€}‰½µ}Í…Ù•‘}Á…¹•±}½¹Ñ•áÐ¹}}•á¥Ñ}|¡9½¹”°9½¹”°9½¹”¤((€€€€€€€€€€€€€€€}‰½µ}Ý½É­ÍÁ…•}É¥‘}½¹Ñ•áÐ¹}}•á¥Ñ}|¡9½¹”°9½¹”°9½¹”¤(€€€€€€€Í…µÁ±•}µ½‘”€ô‰½½°¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}Í…µÁ±•}µ½‘”ˆ¤¤(€€€€€€€Í½ÕÉ•}™¥±•¹…µ”€ô€‰…‘¥Ù½É|ÄÁ}Á…ÉÑ}Í…µÁ±•}‰½´¹ÍØˆ¥˜Í…µÁ±•}µ½‘”•±Í”€ (€€€€€€€€€€€ÕÁ±½…‘•‘}™¥±”¹¹…µ”¥˜ÕÁ±½…‘•‘}™¥±”¥Ì¹½Ð9½¹”•±Í”€ˆˆ(€€€€€€€€¤(€€€€€€€¥˜}¡…Í}½µÁ±•Ñ•‘}Í…Ù•‘}É•ÍÕ±ÑÌ…¹ÕÁ±½…‘•‘}™¥±”¥Ì9½¹”è(€€€€€€€€€€€Í½ÕÉ•}™¥±•¹…µ”€ôÍÑÈ (€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰ÕÁ±½…‘•‘}™¥±•¹…µ”ˆ¤½È€‰Í…Ù•‘}‰½µ}…¹…±åÍ¥Ì¹ÍØˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€ÁÉ½©•Ñ}¹…µ”€ôÍÑÈ¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}ÁÉ½©•Ñ}¹…µ”ˆ¤½È€ˆˆ¤(€€€€€€€€€€€‰½µ}¹…µ”€ôÍÑÈ¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}‰½µ}¹…µ”ˆ¤½È€ˆˆ¤(€€€€€€€¥˜}É•ÍÕµ•}Á•¹‘¥¹}½¹•}Ñ¥µ•}…¹…±åÍ¥Ì…¹ÕÁ±½…‘•‘}™¥±”¥Ì9½¹”è(€€€€€€€€€€€Í½ÕÉ•}™¥±•¹…µ”€ôÍÑÈ (€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰…‘¥Ù½É}½¹•}Ñ¥µ•}Á•¹‘¥¹}Í½ÕÉ•}™¥±•¹…µ”ˆ¤(€€€€€€€€€€€€€€€½ÈÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰ÕÁ±½…‘•‘}™¥±•¹…µ”ˆ¤(€€€€€€€€€€€€€€€½È€‰Á…¥‘}‰½µ}…¹…±åÍ¥Ì¹ÍØˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€ÁÉ½©•Ñ}¹…µ”€ôÍÑÈ (€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰…‘¥Ù½É}½¹•}Ñ¥µ•}Á•¹‘¥¹}ÁÉ½©•Ñ}¹…µ”ˆ¤(€€€€€€€€€€€€€€€½ÈÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}ÁÉ½©•Ñ}¹…µ”ˆ¤(€€€€€€€€€€€€€€€½ÈÁÉ½©•Ñ}¹…µ”(€€€€€€€€€€€€€€€½È€ˆˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€‰½µ}¹…µ”€ôÍÑÈ (€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰…‘¥Ù½É}½¹•}Ñ¥µ•}Á•¹‘¥¹}‰½µ}¹…µ”ˆ¤(€€€€€€€€€€€€€€€½ÈÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}‰½µ}¹…µ”ˆ¤(€€€€€€€€€€€€€€€½È‰½µ}¹…µ”(€€€€€€€€€€€€€€€½È€‰A…¥	=4É•Á½ÉÐˆ(€€€€€€€€€€€€¤((€€€€€€€¥˜€ (€€€€€€€€€€€ÕÁ±½…‘•‘}™¥±”¥Ì9½¹”(€€€€€€€€€€€…¹¹½ÐÍ…µÁ±•}µ½‘”(€€€€€€€€€€€…¹¹½Ð}É•ÍÕµ•}Á•¹‘¥¹}½¹•}Ñ¥µ•}…¹…±åÍ¥Ì(€€€€€€€€€€€…¹¹½Ð}¡…Í}½µÁ±•Ñ•‘}Í…Ù•‘}É•ÍÕ±ÑÌ(€€€€€€€€¤è(€€€€€€€€€€€ÍÐ¹µ…É­‘½Ý¸ ˆð½‘¥Øøˆ°Õ¹Í…™•}…±±½Ý}¡Ñµ°õQÉÕ”¤(€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤((€€€€€€€ÑÉäè(€€€€€€€€€€€¥˜}¡…Í}½µÁ±•Ñ•‘}Í…Ù•‘}É•ÍÕ±ÑÌ…¹ÕÁ±½…‘•‘}™¥±”¥Ì9½¹”è(€€€€€€€€€€€€€€€}½µÁ±•Ñ•‘}É•ÍÕ±ÑÍ}‘˜€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰É•ÍÕ±ÑÍ}‘˜‰t(€€€€€€€€€€€€€€€}µÁ¹}½±Õµ¸€ô¹•áÐ (€€€€€€€€€€€€€€€€€€€€ (€€€€€€€€€€€€€€€€€€€€€€€½±Õµ¸™½È½±Õµ¸¥¸}½µÁ±•Ñ•‘}É•ÍÕ±ÑÍ}‘˜¹½±Õµ¹Ì(€€€€€€€€€€€€€€€€€€€€€€€¥˜ÍÑÈ¡½±Õµ¸¤¹ÍÑÉ¥À ¤¹…Í•™½± ¤¹É•Á±…” ‰|ˆ°€ˆ€ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€¥¸ì‰µÁ¸ˆ°€‰µ…¹Õ™…ÑÕÉ•ÈÁ…ÉÐ¹Õµ‰•È‰ô(€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€9½¹”°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€}ÅÕ…¹Ñ¥Ñå}½±Õµ¸€ô¹•áÐ (€€€€€€€€€€€€€€€€€€€€ (€€€€€€€€€€€€€€€€€€€€€€€½±Õµ¸™½È½±Õµ¸¥¸}½µÁ±•Ñ•‘}É•ÍÕ±ÑÍ}‘˜¹½±Õµ¹Ì(€€€€€€€€€€€€€€€€€€€€€€€¥˜ÍÑÈ¡½±Õµ¸¤¹ÍÑÉ¥À ¤¹…Í•™½± ¤¥¸ì‰ÅÕ…¹Ñ¥Ñäˆ°€‰ÅÑä‰ô(€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€9½¹”°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€¥˜}µÁ¹}½±Õµ¸¥Ì9½¹”è(€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È (€€€€€€€€€€€€€€€€€€€€€€€€‰Q¡”Í…Ù•	=4É•ÍÕ±Ð½Õ±¹½Ð‰”É•½Á•¹•‰•…ÕÍ”¥Ð¡…Ì¹¼Á…ÉÐµ¹Õµ‰•È½±Õµ¸¸ˆ(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤(€€€€€€€€€€€€€€€‰½µ}‘˜€ôÁ¹…Ñ…É…µ” (€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€‰µÁ¸ˆè}½µÁ±•Ñ•‘}É•ÍÕ±ÑÍ}‘™m}µÁ¹}½±Õµ¹t¹…ÍÑåÁ”¡ÍÑÈ¤¹ÍÑÈ¹ÍÑÉ¥À ¤°(€€€€€€€€€€€€€€€€€€€€€€€€‰ÅÕ…¹Ñ¥Ñäˆè€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€Á¹Ñ½}¹Õµ•É¥Œ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€}½µÁ±•Ñ•‘}É•ÍÕ±ÑÍ}‘™m}ÅÕ…¹Ñ¥Ñå}½±Õµ¹t°•ÉÉ½ÉÌô‰½•É”ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤¹™¥±±¹„ Ä¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜}ÅÕ…¹Ñ¥Ñå}½±Õµ¸¥Ì¹½Ð9½¹”(€€€€€€€€€€€€€€€€€€€€€€€€€€€•±Í”€Ä(€€€€€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€•±¥˜}É•ÍÕµ•}Á•¹‘¥¹}½¹•}Ñ¥µ•}…¹…±åÍ¥Ì…¹ÕÁ±½…‘•‘}™¥±”¥Ì9½¹”è(€€€€€€€€€€€€€€€}Á•¹‘¥¹}É•ÍÕ±ÑÍ}‘˜€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰É•ÍÕ±ÑÍ}‘˜‰t(€€€€€€€€€€€€€€€}µÁ¹}½±Õµ¸€ô¹•áÐ (€€€€€€€€€€€€€€€€€€€€ (€€€€€€€€€€€€€€€€€€€€€€€½±Õµ¸™½È½±Õµ¸¥¸}Á•¹‘¥¹}É•ÍÕ±ÑÍ}‘˜¹½±Õµ¹Ì(€€€€€€€€€€€€€€€€€€€€€€€¥˜ÍÑÈ¡½±Õµ¸¤¹ÍÑÉ¥À ¤¹…Í•™½± ¤¹É•Á±…” ‰|ˆ°€ˆ€ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€¥¸ì‰µÁ¸ˆ°€‰µ…¹Õ™…ÑÕÉ•ÈÁ…ÉÐ¹Õµ‰•È‰ô(€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€9½¹”°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€}ÅÕ…¹Ñ¥Ñå}½±Õµ¸€ô¹•áÐ (€€€€€€€€€€€€€€€€€€€€ (€€€€€€€€€€€€€€€€€€€€€€€½±Õµ¸™½È½±Õµ¸¥¸}Á•¹‘¥¹}É•ÍÕ±ÑÍ}‘˜¹½±Õµ¹Ì(€€€€€€€€€€€€€€€€€€€€€€€¥˜ÍÑÈ¡½±Õµ¸¤¹ÍÑÉ¥À ¤¹…Í•™½± ¤¥¸ì‰ÅÕ…¹Ñ¥Ñäˆ°€‰ÅÑä‰ô(€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€9½¹”°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€¥˜}µÁ¹}½±Õµ¸¥Ì9½¹”è(€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È (€€€€€€€€€€€€€€€€€€€€€€€€‰Q¡”…¹…±åé•	=4½Õ±¹½Ð‰”É•ÍÑ½É•¸A±•…Í”½¹Ñ…ÐÍÕÁÁ½ÉÐì€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€‰‘¼¹½ÐÁÕÉ¡…Í”…¹½Ñ¡•ÈÉ•Á½ÉÐ¸ˆ(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤(€€€€€€€€€€€€€€€‰½µ}‘˜€ôÁ¹…Ñ…É…µ” (€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€‰µÁ¸ˆè}Á•¹‘¥¹}É•ÍÕ±ÑÍ}‘™m}µÁ¹}½±Õµ¹t¹…ÍÑåÁ”¡ÍÑÈ¤¹ÍÑÈ¹ÍÑÉ¥À ¤°(€€€€€€€€€€€€€€€€€€€€€€€€‰ÅÕ…¹Ñ¥Ñäˆè€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€Á¹Ñ½}¹Õµ•É¥Œ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€}Á•¹‘¥¹}É•ÍÕ±ÑÍ}‘™m}ÅÕ…¹Ñ¥Ñå}½±Õµ¹t°•ÉÉ½ÉÌô‰½•É”ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤¹™¥±±¹„ Ä¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜}ÅÕ…¹Ñ¥Ñå}½±Õµ¸¥Ì¹½Ð9½¹”(€€€€€€€€€€€€€€€€€€€€€€€€€€€•±Í”€Ä(€€€€€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€•±¥˜Í…µÁ±•}µ½‘”è(€€€€€€€€€€€€€€€‰½µ}‘˜€ôÍ…µÁ±•}‰½´¹½Áä ¤(€€€€€€€€€€€•±¥˜ÕÁ±½…‘•‘}™¥±”¹¹…µ”¹•¹‘ÍÝ¥Ñ  ˆ¹ÍØˆ¤è(€€€€€€€€€€€€€€€ÕÁ±½…‘•‘}™¥±”¹Í••¬ À¤(€€€€€€€€€€€€€€€‰½µ}‘˜€ôÁ¹É•…‘}ÍØ¡ÕÁ±½…‘•‘}™¥±”¤(€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€ÕÁ±½…‘•‘}™¥±”¹Í••¬ À¤(€€€€€€€€€€€€€€€‰½µ}‘˜€ôÁ¹É•…‘}•á•°¡ÕÁ±½…‘•‘}™¥±”¤((€€€€€€€•á•ÁÐá•ÁÑ¥½¸…Ì”è(€€€€€€€€€€€ÍÐ¹•ÉÉ½È (€€€€€€€€€€€€€€€˜‰½Õ±¹½ÐÉ•…Ñ¡”ÕÁ±½…‘•	=4™¥±”èí•ôˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤((€€€€€€€™É½´ÍÉŒ¹‰½µ}Á…ÉÍ•È¥µÁ½ÉÐ¹½Éµ…±¥é•}‰½µ}½±Õµ¹Ì…Ì}¹½Éµ…±¥é•}…¹…±åÍ¥Í}‰½µ}½±Õµ¹Ì(€€€€€€€™É½´ÍÉŒ¹‰½µ}Á…ÉÍ•È¥µÁ½ÉÐ…É•…Ñ•}‰½µ}É½ÝÌ((€€€€€€€‰½µ}‘˜€ô}¹½Éµ…±¥é•}…¹…±åÍ¥Í}‰½µ}½±Õµ¹Ì¡‰½µ}‘˜¤((€€€€€€€É•ÅÕ¥É•‘}½±Õµ¹Ì€ôl‰µÁ¸ˆ°€‰ÅÕ…¹Ñ¥Ñä‰t((€€€€€€€¹½Éµ…±¥é•‘}½±Õµ¹Ì€ôl(€€€€€€€€€€€½°¹ÍÑÉ¥À ¤¹±½Ý•È ¤¹É•Á±…” ˆ€ˆ°€‰|ˆ¤(€€€€€€€€€€€™½È½°¥¸‰½µ}‘˜¹½±Õµ¹Ì(€€€€€€€t((€€€€€€€µ¥ÍÍ¥¹}½±Õµ¹Ì€ôl(€€€€€€€€€€€½°™½È½°¥¸É•ÅÕ¥É•‘}½±Õµ¹Ì(€€€€€€€€€€€¥˜½°¹½Ð¥¸¹½Éµ…±¥é•‘}½±Õµ¹Ì(€€€€€€€t((€€€€€€€¥˜µ¥ÍÍ¥¹}½±Õµ¹Ìè(€€€€€€€€€€€ÍÐ¹•ÉÉ½È (€€€€€€€€€€€€€€€€‰e½ÕÈ	=4¥Ìµ¥ÍÍ¥¹œÉ•ÅÕ¥É•½±Õµ¹Ìè€ˆ(€€€€€€€€€€€€€€€€¬€ˆ°€ˆ¹©½¥¸¡µ¥ÍÍ¥¹}½±Õµ¹Ì¤(€€€€€€€€€€€€€€€€¬€ˆ¸A±•…Í”¥¹±Õ‘”…Ð±•…ÍÐ5A8…¹EÕ…¹Ñ¥Ñä½±Õµ¹Ì¸ˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤((€€€€€€€¥˜‰½µ}‘˜¹•µÁÑäè(€€€€€€€€€€€ÍÐ¹•ÉÉ½È ‰Q¡”ÕÁ±½…‘•	=4™¥±”¥Ì•µÁÑä¸ˆ¤(€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤((€€€€€€€¥˜±•¸¡‰½µ}‘˜¤€ôô€Àè(€€€€€€€€€€€ÍÐ¹•ÉÉ½È ‰9¼	=4É½ÝÌÝ•É”‘•Ñ•Ñ•¥¸Ñ¡”ÕÁ±½…‘•™¥±”¸ˆ¤(€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤((€€€€(((€€€€€€€¥˜€ (€€€€€€€€€€€¹½Ð}É•ÍÕµ•}Á•¹‘¥¹}½¹•}Ñ¥µ•}…¹…±åÍ¥Ì(€€€€€€€€€€€…¹ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰ÕÁ±½…‘•‘}™¥±•¹…µ”ˆ¤€„ôÍ½ÕÉ•}™¥±•¹…µ”(€€€€€€€€¤è(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰É•ÍÕ±ÑÍ}‘˜ˆ°9½¹”¤(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰…¹…±åÍ¥Í}Í…Ù•ˆ°9½¹”¤(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰…‘¥Ù½É}½¹•}Ñ¥µ•}Á•¹‘¥¹}½µÁ½¹•¹Ñ}½Õ¹Ðˆ°9½¹”¤(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰ÕÁ±½…‘•‘}™¥±•¹…µ”‰t€ôÍ½ÕÉ•}™¥±•¹…µ”(€€€€€€€•±¥˜}É•ÍÕµ•}Á•¹‘¥¹}½¹•}Ñ¥µ•}…¹…±åÍ¥Ì…¹¹½ÐÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰ÕÁ±½…‘•‘}™¥±•¹…µ”ˆ¤è(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰ÕÁ±½…‘•‘}™¥±•¹…µ”‰t€ôÍ½ÕÉ•}™¥±•¹…µ”(€€€€(€€€€€€€½É¥¥¹…±}É½Ý}½Õ¹Ð€ô±•¸¡‰½µ}‘˜¤((€€€€€€€‰½µ}‘™l‰µÁ¸‰t€ô‰½µ}‘™l‰µÁ¸‰t¹…ÍÑåÁ”¡ÍÑÈ¤¹ÍÑÈ¹ÍÑÉ¥À ¤((€€€€€€€‰½µ}‘˜€ô…É•…Ñ•}‰½µ}É½ÝÌ¡‰½µ}‘˜¤((€€€€€€€‘•‘ÕÁ•‘}É½Ý}½Õ¹Ð€ô±•¸¡‰½µ}‘˜¤((€€€€€€€¥˜‘•‘ÕÁ•‘}É½Ý}½Õ¹Ð€ð½É¥¥¹…±}É½Ý}½Õ¹Ðè(€€€€€€€€€€€ÍÐ¹¥¹™¼ (€€€€€€€€€€€€€€€˜‰ÕÁ±¥…Ñ”Á…ÉÐ¹Õµ‰•ÉÌÝ•É”µ•É•èí½É¥¥¹…±}É½Ý}½Õ¹ÑôÉ½ÝÌÉ•‘Õ•Ñ¼í‘•‘ÕÁ•‘}É½Ý}½Õ¹ÑôÕ¹¥ÅÕ”Á…ÉÑÌ¸ˆ(€€€€€€€€€€€€¤((€€€€€€€‰½µ}‘™l‰ÅÕ…¹Ñ¥Ñä‰t€ôÁ¹Ñ½}¹Õµ•É¥Œ (€€€€€€€€€€€‰½µ}‘™l‰ÅÕ…¹Ñ¥Ñä‰t°(€€€€€€€€€€€•ÉÉ½ÉÌô‰½•É”ˆ°(€€€€€€€€¤((€€€€€€€¥˜‰½µ}‘™l‰ÅÕ…¹Ñ¥Ñä‰t¹¥Í¹„ ¤¹…¹ä ¤è(€€€€€€€€€€€ÍÐ¹•ÉÉ½È ‰M½µ”ÅÕ…¹Ñ¥ÑäÙ…±Õ•Ì…É”µ¥ÍÍ¥¹œ½È¥¹Ù…±¥¸A±•…Í”ÕÍ”¹Õµ•É¥ŒÅÕ…¹Ñ¥Ñ¥•Ì½¹±ä¸ˆ¤(€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤((€€€€€€€¥˜€¡‰½µ}‘™l‰ÅÕ…¹Ñ¥Ñä‰t€ðô€À¤¹…¹ä ¤è(€€€€€€€€€€€ÍÐ¹•ÉÉ½È ‰EÕ…¹Ñ¥ÑäÙ…±Õ•ÌµÕÍÐ‰”É•…Ñ•ÈÑ¡…¸é•É¼¸ˆ¤(€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤((€€€€€€€¥˜¹½Ð…¹…±åÍ¥Í}¥¹}ÁÉ½É•ÍÌ…¹¹½Ð}¡…Í}½µÁ±•Ñ•‘}Í…Ù•‘}É•ÍÕ±ÑÌè(€€€€€€€€€€€É•¹‘•É}ÕÁ±½…‘}‘•Ñ•Ñ• (€€€€€€€€€€€€€€€™¥±•¹…µ”õÍ½ÕÉ•}™¥±•¹…µ”°(€€€€€€€€€€€€€€€½µÁ½¹•¹Ñ}½Õ¹Ðõ½É¥¥¹…±}É½Ý}½Õ¹Ð°(€€€€€€€€€€€€€€€‘•‘ÕÁ±¥…Ñ•‘}½Õ¹Ðõ‘•‘ÕÁ•‘}É½Ý}½Õ¹Ð°(€€€€€€€€€€€€¤((€€€€€€€}½¹•}Ñ¥µ•}ÁÉ•™±¥¡Ñ}ÁÉ¥”€ô€ˆˆ(€€€€€€€¥˜€ (€€€€€€€€€€€}½¹•}Ñ¥µ•}‰±½­•‘}Á±…¸(€€€€€€€€€€€…¹¹½Ð€¡}½¹•}Ñ¥µ•}É•Í•ÉÙ•½È}½¹•}Ñ¥µ•}…Ù…¥±…‰±”¤(€€€€€€€€€€€…¹¹½Ð}¡…Í}½µÁ±•Ñ•‘}Í…Ù•‘}É•ÍÕ±ÑÌ(€€€€€€€€¤è(€€€€€€€€€€€¥˜±•¸¡‰½µ}‘˜¤€ø=9}Q%5}	=5}5a}AIQLè(€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È (€€€€€€€€€€€€€€€€€€€˜‰Q¡¥Ì	=4¡…Ìí±•¸¡‰½µ}‘˜¥ôÕ¹¥ÅÕ”½µÁ½¹•¹ÑÌ¸Q¡”½¹”µÑ¥µ”É•Á½ÉÐ½Ù•ÉÌ€ˆ(€€€€€€€€€€€€€€€€€€€˜‰ÕÀÑ¼í=9}Q%5}	=5}5a}AIQMôì¹¼Á…åµ•¹ÐÝ¥±°‰”É•ÅÕ•ÍÑ•¸€ˆ(€€€€€€€€€€€€€€€€€€€€‰I•‘Õ”Ñ¡”	=4½È½µÁ…É”Á±…¹Ì™½È„±…É•È…¹…±åÍ¥Ì¸ˆ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}ÁÉ•™±¥¡Ñ}ÁÉ¥”€ô½¹•}Ñ¥µ•}É•Á½ÉÑ}ÁÉ¥•}±…‰•° (€€€€€€€€€€€€€€€€€€€€€€€ÍÑÈ¡•Ñ}Í•É•Ð ‰MQI%A}=9}Q%5}	=5}IA=IQ}AI%}%ˆ°É•ÅÕ¥É•õQÉÕ”¤¤(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•á•ÁÐ=¹•Q¥µ•	=5ÉÉ½È…Ì•áŒè(€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È¡ÍÑÈ¡•áŒ¤¤(€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€ÍÐ¹¥¹™¼ (€€€€€€€€€€€€€€€€€€€€€€€˜‰í±•¸¡‰½µ}‘˜¥ôÕ¹¥ÅÕ”½µÁ½¹•¹ÑÌ¸IÕ¸Ñ¡”…¹…±åÍ¥Ì™¥ÉÍÐì€ˆ(€€€€€€€€€€€€€€€€€€€€€€€˜‰Ñ¡•¸Á…äí}½¹•}Ñ¥µ•}ÁÉ•™±¥¡Ñ}ÁÉ¥•ô½¹”Ñ¼Õ¹±½¬Ñ¡”™Õ±°É•Á½ÉÐ¸€ˆ(€€€€€€€€€€€€€€€€€€€€€€€˜‰1¥µ¥Ðèí=9}Q%5}	=5}5a}AIQMôÕ¹¥ÅÕ”½µÁ½¹•¹ÑÌì¹¼ÍÕ‰ÍÉ¥ÁÑ¥½¸¸ˆ(€€€€€€€€€€€€€€€€€€€€¤(((€€€€€€€‰½µ}¹…µ•}µ¥ÍÍ¥¹œ€ô¹½Ð‰½µ}¹…µ”¹ÍÑÉ¥À ¤…¹¹½ÐÍ…µÁ±•}µ½‘”(€€€€€€€™É½´ÍÉŒ¹Í…Ù•‘}‰½µ}ÁÉ½©•Ð¥µÁ½ÉÐ…¹…±åÍ¥Í}Ñ¥Ñ±•}™½É}ÕÁ±½…((€€€€€€€…¹…±åÍ¥Í}¹…µ”€ô…¹…±åÍ¥Í}Ñ¥Ñ±•}™½É}ÕÁ±½… (€€€€€€€€€€€ÁÉ½©•Ñ}¹…µ”°(€€€€€€€€€€€‰½µ}¹…µ”¹ÍÑÉ¥À ¤½ÈÍ½ÕÉ•}™¥±•¹…µ”°(€€€€€€€€¤(€€€€€€€}½¹•}Ñ¥µ•}…¹…±åÍ¥Í}‰±½­•€ô€ (€€€€€€€€€€€}½¹•}Ñ¥µ•}‰±½­•‘}Á±…¸(€€€€€€€€€€€…¹¹½Ð€¡}½¹•}Ñ¥µ•}É•Í•ÉÙ•½È}½¹•}Ñ¥µ•}…Ù…¥±…‰±”¤(€€€€€€€€€€€…¹€ (€€€€€€€€€€€€€€€±•¸¡‰½µ}‘˜¤€ø=9}Q%5}	=5}5a}AIQL(€€€€€€€€€€€€€€€½È¹½Ð}½¹•}Ñ¥µ•}ÁÉ•™±¥¡Ñ}ÁÉ¥”(€€€€€€€€€€€€¤(€€€€€€€€¤(€€€€€€€…¹…±åé•}±¥­•€ô…±Í”(€€€€€€€¥˜€ (€€€€€€€€€€€¹½Ð}…ÁÁÉ½Ù•‘}‰½µ}Á¥Á•±¥¹•}…Ñ¥Ù”(€€€€€€€€€€€…¹¹½Ð}É•ÍÕµ•}Á•¹‘¥¹}½¹•}Ñ¥µ•}…¹…±åÍ¥Ì(€€€€€€€€€€€…¹¹½Ð}¡…Í}½µÁ±•Ñ•‘}Í…Ù•‘}É•ÍÕ±ÑÌ(€€€€€€€€¤è(€€€€€€€€€€€…¹…±åé•}±¥­•€ôÍÐ¹‰ÕÑÑ½¸ (€€€€€€€€€€€€€€€€‰¹…±åé¥¹œ	=7Š˜ˆ¥˜…¹…±åÍ¥Í}¥¹}ÁÉ½É•ÍÌ•±Í”€ ‰¹…±åé”M…µÁ±”	=4ˆ¥˜Í…µÁ±•}µ½‘”•±Í”€‰¹…±åé”	=4ˆ¤°(€€€€€€€€€€€€€€€ÑåÁ”ô‰ÁÉ¥µ…Éäˆ°(€€€€€€€€€€€€€€€‘¥Í…‰±•õ‰½µ}¹…µ•}µ¥ÍÍ¥¹œ½È…¹…±åÍ¥Í}¥¹}ÁÉ½É•ÍÌ½È}½¹•}Ñ¥µ•}…¹…±åÍ¥Í}‰±½­•°(€€€€€€€€€€€€€€€ÕÍ•}½¹Ñ…¥¹•É}Ý¥‘Ñ õ…±Í”°(€€€€€€€€€€€€¤(€€€€€€€¥˜…¹…±åé•}±¥­•è(€€€€€€€€€€€€ŒI•¹‘•ÈÑ¡”‰ÕÍäÍÑ…Ñ”‰•™½É”Ñ¡”±½¹œµÉÕ¹¹¥¹œÍÕÁÁ±¥•È…¹É¥Í¬…¹…±åÍ¥Ì¸(€€€€€€€€€€€™É½´ÍÉŒ¹Õ¤¹µ…¥¹}ÑÉ…¹Í¥Ñ¥½¸¥µÁ½ÉÐ…Éµ}‰½µ}…¹…±åÍ¥Í}ÑÉ…¹Í¥Ñ¥½¸(€€€€€€€€€€€™É½´ÍÉŒ¹Õ¤¹¹…Ù¥…Ñ¥½¸¥µÁ½ÉÐÉ•ÅÕ•ÍÑ}µ…¥¹}ÍÉ½±±}É•Í•Ð((€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}…¹…±åÍ¥Í}¥¹}ÁÉ½É•ÍÌ‰t€ôQÉÕ”(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}…¹…±åÍ¥Í}Á•¹‘¥¹œ‰t€ôQÉÕ”(€€€€€€€€€€€É•ÅÕ•ÍÑ}µ…¥¹}ÍÉ½±±}É•Í•Ð ¤(€€€€€€€€€€€…Éµ}‰½µ}…¹…±åÍ¥Í}ÑÉ…¹Í¥Ñ¥½¸¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”°€‰ÍÑ…ÉÐˆ¤(€€€€€€€€€€€ÍÐ¹É•ÉÕ¸ ¤((€€€€€€€…¹…±åÍ¥Í}™ÕÑÕÉ”€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}…¹…±åÍ¥Í}™ÕÑÕÉ”ˆ¤(€€€€€€€¥˜…¹…±åÍ¥Í}™ÕÑÕÉ”¥Ì¹½Ð9½¹”è(€€€€€€€€€€€ÍÐ¹™É…µ•¹Ð¡ÉÕ¹}•Ù•ÉäôÄ¸À¤(€€€€€€€€€€€‘•˜}É•¹‘•É}…Ñ¥Ù•}‰½µ}…¹…±åÍ¥Ì ¤è(€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}™ÕÑÕÉ”€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}…¹…±åÍ¥Í}™ÕÑÕÉ”ˆ¤(€€€€€€€€€€€€€€€¥˜ÕÉÉ•¹Ñ}™ÕÑÕÉ”¥Ì9½¹”è(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€€€€€ÁÉ½É•ÍÍ}ÅÕ•Õ”€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}…¹…±åÍ¥Í}ÁÉ½É•ÍÍ}ÅÕ•Õ”ˆ¤(€€€€€€€€€€€€€€€½µÁ±•Ñ•°Ñ½Ñ…±}Á…ÉÑÌ°ÕÉÉ•¹Ñ}µÁ¸€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð (€€€€€€€€€€€€€€€€€€€€‰‰½´á}…¹…±åÍ¥Í}ÁÉ½É•ÍÌˆ°(€€€€€€€€€€€€€€€€€€€€ À°±•¸¡‰½µ}‘˜¤°€ˆˆ¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€Ý¡¥±”ÁÉ½É•ÍÍ}ÅÕ•Õ”¥Ì¹½Ð9½¹”…¹¹½ÐÁÉ½É•ÍÍ}ÅÕ•Õ”¹•µÁÑä ¤è(€€€€€€€€€€€€€€€€€€€½µÁ±•Ñ•°Ñ½Ñ…±}Á…ÉÑÌ°ÕÉÉ•¹Ñ}µÁ¸€ôÁÉ½É•ÍÍ}ÅÕ•Õ”¹•Ñ}¹½Ý…¥Ð ¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}…¹…±åÍ¥Í}ÁÉ½É•ÍÌ‰t€ô€ (€€€€€€€€€€€€€€€€€€€€€€€½µÁ±•Ñ•°(€€€€€€€€€€€€€€€€€€€€€€€Ñ½Ñ…±}Á…ÉÑÌ°(€€€€€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}µÁ¸°(€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€¥˜ÍÐ¹‰ÕÑÑ½¸ (€€€€€€€€€€€€€€€€€€€€‰…¹•°…¹…±åÍ¥Ìˆ°(€€€€€€€€€€€€€€€€€€€­•äô‰‰½´á}…¹•±}…¹…±åÍ¥Ìˆ°(€€€€€€€€€€€€€€€€€€€ÑåÁ”ô‰Í•½¹‘…Éäˆ°(€€€€€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€€€€€…¹•±}•Ù•¹Ð€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰‰½´á}…¹…±åÍ¥Í}…¹•±}•Ù•¹Ðˆ¤(€€€€€€€€€€€€€€€€€€€¥˜…¹•±}•Ù•¹Ð¥Ì¹½Ð9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€…¹•±}•Ù•¹Ð¹Í•Ð ¤(€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}É•Í•ÉÙ•è(€€€€€€€€€€€€€€€€€€€€€€€¥˜É•±•…Í•}½¹•}Ñ¥µ•}É•‘¥Ð¡}½¹•}Ñ¥µ•}ÕÍ•É}¥°}½¹•}Ñ¥µ•}½É‘•É}¥¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰…‘¥Ù½É}½¹•}Ñ¥µ•}‰½µ}½É‘•É}¥ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€•á•ÕÑ½È€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}•á•ÕÑ½Èˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€¥˜•á•ÕÑ½È¥Ì¹½Ð9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€•á•ÕÑ½È¹Í¡ÕÑ‘½Ý¸¡Ý…¥Ðõ…±Í”°…¹•±}™ÕÑÕÉ•ÌõQÉÕ”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}™ÕÑÕÉ”ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}ÁÉ½É•ÍÍ}ÅÕ•Õ”ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}…¹•±}•Ù•¹Ðˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}ÁÉ½É•ÍÌˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€™¥¹¥Í¡}…ÁÁÉ½Ù•‘}‰½µ}ÍÕ‰µ¥ÍÍ¥½¸¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”°É•½Á•¹}ÕÁ±½…õQÉÕ”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}…¹…±åÍ¥Í}…¹•±±•‘}¹½Ñ¥”‰t€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€ÍÐ¹É•ÉÕ¸ ¤((€€€€€€€€€€€€€€€¥˜¹½ÐÕÉÉ•¹Ñ}™ÕÑÕÉ”¹‘½¹” ¤è(€€€€€€€€€€€€€€€€€€€ÍÐ¹¥¹™¼ (€€€€€€€€€€€€€€€€€€€€€€€€ˆ¨©¹…±åÍ¥Ì¥¸ÁÉ½É•ÍÌ¨¨ƒŠP€ˆ(€€€€€€€€€€€€€€€€€€€€€€€˜‰í½µÁ±•Ñ•‘ô½˜íÑ½Ñ…±}Á…ÉÑÍô½µÁ½¹•¹ÑÌ½µÁ±•Ñ”ˆ(€€€€€€€€€€€€€€€€€€€€€€€€¬€¡˜ˆƒ
Ü¡•­¥¹œíÕÉÉ•¹Ñ}µÁ¹ôˆ¥˜ÕÉÉ•¹Ñ}µÁ¸•±Í”€‹Š˜ˆ¤(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹ÁÉ½É•ÍÌ¡½µÁ±•Ñ•€¼Ñ½Ñ…±}Á…ÉÑÌ¥˜Ñ½Ñ…±}Á…ÉÑÌ•±Í”€À¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€…¹…±åÍ¥Í}É•ÍÕ±Ð€ôÕÉÉ•¹Ñ}™ÕÑÕÉ”¹É•ÍÕ±Ð ¤(€€€€€€€€€€€€€€€•á•ÁÐá•ÁÑ¥½¸…Ì”è(€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}É•Í•ÉÙ•è(€€€€€€€€€€€€€€€€€€€€€€€¥˜É•±•…Í•}½¹•}Ñ¥µ•}É•‘¥Ð¡}½¹•}Ñ¥µ•}ÕÍ•É}¥°}½¹•}Ñ¥µ•}½É‘•É}¥¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰…‘¥Ù½É}½¹•}Ñ¥µ•}‰½µ}½É‘•É}¥ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}™ÕÑÕÉ”ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€™…¥±•‘}•á•ÕÑ½È€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}•á•ÕÑ½Èˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€¥˜™…¥±•‘}•á•ÕÑ½È¥Ì¹½Ð9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€™…¥±•‘}•á•ÕÑ½È¹Í¡ÕÑ‘½Ý¸¡Ý…¥Ðõ…±Í”°…¹•±}™ÕÑÕÉ•ÌõQÉÕ”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}ÁÉ½É•ÍÍ}ÅÕ•Õ”ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}…¹•±}•Ù•¹Ðˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}ÁÉ½É•ÍÌˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€™¥¹¥Í¡}…ÁÁÉ½Ù•‘}‰½µ}ÍÕ‰µ¥ÍÍ¥½¸¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”°É•½Á•¹}ÕÁ±½…õQÉÕ”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}‰½µ}…¹…±åÍ¥Í}•ÉÉ½È‰t€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€ÍÐ¹É•ÉÕ¸ ¤((€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}™ÕÑÕÉ”ˆ°9½¹”¤(€€€€€€€€€€€€€€€•á•ÕÑ½È€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}•á•ÕÑ½Èˆ°9½¹”¤(€€€€€€€€€€€€€€€¥˜•á•ÕÑ½È¥Ì¹½Ð9½¹”è(€€€€€€€€€€€€€€€€€€€•á•ÕÑ½È¹Í¡ÕÑ‘½Ý¸¡Ý…¥Ðõ…±Í”°…¹•±}™ÕÑÕÉ•ÌõQÉÕ”¤(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}ÁÉ½É•ÍÍ}ÅÕ•Õ”ˆ°9½¹”¤(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}…¹•±}•Ù•¹Ðˆ°9½¹”¤(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}ÁÉ½É•ÍÌˆ°9½¹”¤((€€€€€€€€€€€€€€€¥˜…¹…±åÍ¥Í}É•ÍÕ±Ð¥Ì9½¹”è(€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}É•Í•ÉÙ•è(€€€€€€€€€€€€€€€€€€€€€€€¥˜É•±•…Í•}½¹•}Ñ¥µ•}É•‘¥Ð¡}½¹•}Ñ¥µ•}ÕÍ•É}¥°}½¹•}Ñ¥µ•}½É‘•É}¥¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰…‘¥Ù½É}½¹•}Ñ¥µ•}‰½µ}½É‘•É}¥ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€™¥¹¥Í¡}…ÁÁÉ½Ù•‘}‰½µ}ÍÕ‰µ¥ÍÍ¥½¸¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”°É•½Á•¹}ÕÁ±½…õQÉÕ”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}…¹…±åÍ¥Í}…¹•±±•‘}¹½Ñ¥”‰t€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€ÍÐ¹É•ÉÕ¸ ¤((€€€€€€€€€€€€€€€É•ÍÕ±ÑÍ}‘˜°‘•É…‘•€ô…¹…±åÍ¥Í}É•ÍÕ±Ð(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰É•ÍÕ±ÑÍ}‘˜‰t€ôÉ•ÍÕ±ÑÍ}‘˜(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}½¹•}Ñ¥µ•}Á•¹‘¥¹}Í½ÕÉ•}™¥±•¹…µ”‰t€ôÍ½ÕÉ•}™¥±•¹…µ”(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}½¹•}Ñ¥µ•}Á•¹‘¥¹}ÁÉ½©•Ñ}¹…µ”‰t€ôÍÑÈ¡ÁÉ½©•Ñ}¹…µ”½È€ˆˆ¤(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}½¹•}Ñ¥µ•}Á•¹‘¥¹}‰½µ}¹…µ”‰t€ôÍÑÈ¡‰½µ}¹…µ”½È€ˆˆ¤(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}ÍÕÁÁ±¥•É}‘•É…‘•‰t€ô‘•É…‘•(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}ÍÕÁÁ±¥•É}‘•É…‘•‘}µ•ÍÍ…”‰t€ô€ (€€€€€€€€€€€€€€€€€€€€‰M½µ”ÍÕÁÁ±¥•È‘…Ñ„½Õ±¹½Ð‰”Ù•É¥™¥•‘ÕÉ¥¹œÑ¡¥Ì…¹…±åÍ¥Ì¸ˆ(€€€€€€€€€€€€€€€€€€€¥˜‘•É…‘•(€€€€€€€€€€€€€€€€€€€•±Í”€ˆˆ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€ÍÐ¹É•ÉÕ¸ ¤((€€€€€€€€€€€Ý¥Ñ ÍÐ¹½¹Ñ…¥¹•È¡­•äô‰‰½´á}…¹…±åÍ¥Í}ÁÉ½É•ÍÍ}…Éˆ°‰½É‘•ÈõQÉÕ”¤è(€€€€€€€€€€€€€€€}É•¹‘•É}…Ñ¥Ù•}‰½µ}…¹…±åÍ¥Ì ¤(€€€€€€€€€€€ÍÐ¹ÍÑ½À ¤((€€€€€€€¡…Í}½µÁ±•Ñ•‘}É•ÍÕ±ÑÌ€ô‰½½° (€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰É•ÍÕ±ÑÍ}‘˜ˆ¤¥Ì¹½Ð9½¹”(€€€€€€€€€€€…¹¹½Ð•Ñ…ÑÑÈ¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰É•ÍÕ±ÑÍ}‘˜ˆ¤°€‰•µÁÑäˆ°QÉÕ”¤(€€€€€€€€¤(€€€€€€€¥˜}É•ÍÕµ•}Á•¹‘¥¹}½¹•}Ñ¥µ•}…¹…±åÍ¥Ì…¹ÕÁ±½…‘•‘}™¥±”¥Ì9½¹”è(€€€€€€€€€€€Ý¥Ñ ÍÐ¹•áÁ…¹‘•È ‰I•Ù¥•ÜÕÁ±½…‘•½µÁ½¹•¹ÑÌˆ°•áÁ…¹‘•õ…±Í”¤è(€€€€€€€€€€€€€€€ÍÐ¹…ÁÑ¥½¸ (€€€€€€€€€€€€€€€€€€€€‰Q¡”½µÁ±•Ñ•…¹…±åÍ¥Ì¥Ì‰•¥¹œÍ…Ù•Ý¥Ñ¡½ÕÐÉ•Á•…Ñ¥¹œÍÕÁÁ±¥•È±½½­ÕÁÌ¸ˆ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€ÍÐ¹‘…Ñ…™É…µ”¡‰½µ}‘˜°ÕÍ•}½¹Ñ…¥¹•É}Ý¥‘Ñ õQÉÕ”°¡¥‘•}¥¹‘•àõQÉÕ”¤(€€€€€€€•±¥˜¹½Ð…¹…±åÍ¥Í}¥¹}ÁÉ½É•ÍÌ…¹¹½Ð¡…Í}½µÁ±•Ñ•‘}É•ÍÕ±ÑÌè(€€€€€€€€€€€Ý¥Ñ ÍÐ¹•áÁ…¹‘•È ‰I•Ù¥•ÜÕÁ±½…‘•½µÁ½¹•¹ÑÌˆ°•áÁ…¹‘•õ…±Í”¤è(€€€€€€€€€€€€€€€ÍÐ¹‘…Ñ…™É…µ”¡‰½µ}‘˜°ÕÍ•}½¹Ñ…¥¹•É}Ý¥‘Ñ õQÉÕ”°¡¥‘•}¥¹‘•àõQÉÕ”¤(€€€€€€€…¹…±åé•}É•ÅÕ•ÍÑ•€ô…±Í”(€€€€€€€¥˜¹½Ð}É•ÍÕµ•}Á•¹‘¥¹}½¹•}Ñ¥µ•}…¹…±åÍ¥Ìè(€€€€€€€€€€€…¹…±åé•}É•ÅÕ•ÍÑ•€ô}…ÁÁÉ½Ù•‘}…¹…±åÍ¥Í}É•ÅÕ•ÍÑ•½È‰½½° (€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}Á•¹‘¥¹œˆ°…±Í”¤(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}Í…µÁ±•}…ÕÑ½}…¹…±åé”ˆ°…±Í”¤è(€€€€€€€€€€€€€€€…¹…±åé•}É•ÅÕ•ÍÑ•€ôQÉÕ”((€€€€€€€¥˜…¹…±åé•}É•ÅÕ•ÍÑ•è(€€€€€€€€€€€€ŒQ¡”¹•Ü…¹…±åÍ¥ÌÉ•Á±…•ÌÑ¡”ÕÁ±½…½É•Ù¥•ÜÍÕÉ™…”Ý¥Ñ¡½ÕÐ„(€€€€€€€€€€€€ŒÉ½ÕÑ”¡…¹”¸M¡•‘Õ±”Ñ¡”Í…µ”ÍÑ…‰¥±¥é•Ñ½ÀÉ•Í•ÐÕÍ•½¸(€€€€€€€€€€€€ŒÁ…”¹…Ù¥…Ñ¥½¸Í¼ÁÉ½É•ÍÌ¹•Ù•È½Á•¹Ì¡…±™Ý…ä‘½Ý¸Ñ¡”Á…”¸(€€€€€€€€€€€™É½´ÍÉŒ¹Õ¤¹¹…Ù¥…Ñ¥½¸¥µÁ½ÉÐÉ•ÅÕ•ÍÑ}µ…¥¹}ÍÉ½±±}É•Í•Ð((€€€€€€€€€€€É•ÅÕ•ÍÑ}µ…¥¹}ÍÉ½±±}É•Í•Ð ¤(€€€€€€€€€€€€Œ¹•Ü…¹…±åÍ¥ÌÍ¡½Õ±‰”Í…Ù•…Ì„¹•Ü‘…Ñ…‰…Í”É•½É¸(€€€€€€€€€€€€ŒQ¡•Í”™±…ÌÁÉ•Ù•¹Ð½±Í•ÍÍ¥½¸ÍÑ…Ñ”™É½´‰±½­¥¹œÑ¡”¹•ÜÍ…Ù”¸(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰…¹…±åÍ¥Í}Í…Ù•ˆ°9½¹”¤(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰…¹…±åÍ¥Í}¥ˆ°9½¹”¤(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰¡•…±Ñ¡}Í½É”ˆ°9½¹”¤(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰¡•…±Ñ¡}ÍÑ…ÑÕÌˆ°9½¹”¤((€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}‰±½­•‘}Á±…¸è(€€€€€€€€€€€€€€€¥˜±•¸¡‰½µ}‘˜¤€ø=9}Q%5}	=5}5a}AIQLè(€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È (€€€€€€€€€€€€€€€€€€€€€€€˜‰Q¡¥Ì	=4¡…Ìí±•¸¡‰½µ}‘˜¥ôÕ¹¥ÅÕ”½µÁ½¹•¹ÑÌ¸Q¡”½¹”µÑ¥µ”É•Á½ÉÐ½Ù•ÉÌ€ˆ(€€€€€€€€€€€€€€€€€€€€€€€˜‰ÕÀÑ¼í=9}Q%5}	=5}5a}AIQMôì¹¼Á…åµ•¹ÐÝ…ÌÉ•ÅÕ•ÍÑ•¸I•‘Õ”Ñ¡”	=4€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€‰½È½µÁ…É”Á±…¹Ì™½È„±…É•È…¹…±åÍ¥Ì¸ˆ(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤(€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}É•Í•ÉÙ•è(€€€€€€€€€€€€€€€€€€€…±±½Ý•€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€µ•ÍÍ…”€ô€‰e½ÕÈÁ…¥½¹”µÑ¥µ”É•Á½ÉÐ¥ÌÉ•Í•ÉÙ•™½ÈÑ¡¥Ì…¹…±åÍ¥Ì¸ˆ(€€€€€€€€€€€€€€€•±¥˜}½¹•}Ñ¥µ•}…Ù…¥±…‰±”è(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}½É‘•É}¥€ôÉ•Í•ÉÙ•}½¹•}Ñ¥µ•}É•‘¥Ð¡}½¹•}Ñ¥µ•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€€€€€•á•ÁÐ=¹•Q¥µ•	=5ÉÉ½È…Ì•áŒè(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È¡ÍÑÈ¡•áŒ¤¤(€€€€€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}½¹•}Ñ¥µ•}‰½µ}½É‘•É}¥‰t€ô}½¹•}Ñ¥µ•}½É‘•É}¥(€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}É•Í•ÉÙ•€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€…±±½Ý•€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€µ•ÍÍ…”€ô€‰e½ÕÈÁ…¥½¹”µÑ¥µ”É•Á½ÉÐ¥ÌÉ•Í•ÉÙ•™½ÈÑ¡¥Ì…¹…±åÍ¥Ì¸ˆ(€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€¥˜¹½Ð}½¹•}Ñ¥µ•}ÁÉ•™±¥¡Ñ}ÁÉ¥”è(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È ‰Q¡”½¹”µÑ¥µ”É•Á½ÉÐÁÉ¥”¥ÌÕ¹…Ù…¥±…‰±”¸9¼…¹…±åÍ¥ÌÝ…ÌÍÑ…ÉÑ•¸ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}½¹•}Ñ¥µ•}Á•¹‘¥¹}½µÁ½¹•¹Ñ}½Õ¹Ð‰t€ô¥¹Ð¡±•¸¡‰½µ}‘˜¤¤(€€€€€€€€€€€€€€€€€€€…±±½Ý•€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€µ•ÍÍ…”€ô€‰e½ÕÈ	=4¥Ì‰•¥¹œ…¹…±åé•¸Q¡”™Õ±°É•Á½ÉÐÝ¥±°‰”½™™•É•…™Ñ•ÈÑ¡”½µÁ½¹•¹Ð½Õ¹Ð¥Ì½¹™¥Éµ•¸ˆ(€€€€€€€€€€€•±¥˜¥Í}…‘µ¥¸è(€€€€€€€€€€€€€€€…±±½Ý•€ôQÉÕ”(€€€€€€€€€€€€€€€µ•ÍÍ…”€ô€‰‘µ¥¸…½Õ¹ÐèÁ±…¸±¥µ¥ÑÌ‰åÁ…ÍÍ•¸ˆ(€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€…±±½Ý•°µ•ÍÍ…”€ôÙ…±¥‘…Ñ•}‰½µ}……¥¹ÍÑ}Á±…¸ (€€€€€€€€€€€€€€€€€€€‰½µ}‘˜°(€€€€€€€€€€€€€€€€€€€Í•±•Ñ•‘}Á±…¸°(€€€€€€€€€€€€€€€€€€€µ½¹Ñ¡±å}ÕÁ±½…‘}½Õ¹Ð°(€€€€€€€€€€€€€€€€€€€¥Í}…‘µ¥¸õ¥Í}…‘µ¥¸°(€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€¥˜¹½Ð…±±½Ý•è(€€€€€€€€€€€€€€€ÕÁÉ…‘•}Á±…¸€ôÍ•±•Ñ•‘}Á±…¸¹•Ð ‰ÕÁÉ…‘•}Ñ¼ˆ¤(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰Í¡½Ý}ÕÁÉ…‘•}¡•­½ÕÐ‰t€ôQÉÕ”(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰ÕÁÉ…‘•}µ•ÍÍ…”‰t€ôµ•ÍÍ…”(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰ÕÁÉ…‘•}Á±…¹}¹…µ”‰t€ôÕÁÉ…‘•}Á±…¸(€€€€€€€€€€€€€€€ÍÐ¹É•ÉÕ¸ ¤((€€€€€€€€€€€Í…Ù•‘}…¹…±åÍ¥Í}½Õ¹Ð€ô€ (€€€€€€€€€€€€€€€}Ý½É­ÍÁ…•}ÅÕ•Éä (€€€€€€€€€€€€€€€€€€€ÍÕÁ…‰…Í”¹Ñ…‰±” ‰…¹…±åÍ•Ìˆ¤(€€€€€€€€€€€€€€€€€€€€¹Í•±•Ð ‰¥ˆ°½Õ¹Ðô‰•á…Ðˆ¤(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€¹•Ä ‰ÕÍ•É}¥ˆ°ÕÉÉ•¹Ñ}ÕÍ•Él‰¥‰t¤(€€€€€€€€€€€€€€€€¹•á•ÕÑ” ¤(€€€€€€€€€€€€¤(€€€€€€€€€€€Í…Ù•‘}…¹…±åÍ¥Í}Ñ½Ñ…°€ôÍ…Ù•‘}…¹…±åÍ¥Í}½Õ¹Ð¹½Õ¹Ð½È€À(€€€€€€€€€€€µ…á}Í…Ù•‘}‰½µÌ€ôÍ•±•Ñ•‘}Á±…¸¹•Ð ‰µ…á}Í…Ù•‘}‰½µÌˆ°€À¤((€€€€€€€€€€€¥˜¹½Ð¥Í}…‘µ¥¸…¹¹½Ð}½¹•}Ñ¥µ•}‰±½­•‘}Á±…¸…¹µ…á}Í…Ù•‘}‰½µÌ¥Ì¹½Ð9½¹”…¹Í…Ù•‘}…¹…±åÍ¥Í}Ñ½Ñ…°€øôµ…á}Í…Ù•‘}‰½µÌè(€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È (€€€€€€€€€€€€€€€€€€€˜‰e½ÕÈíÍ•±•Ñ•‘}Á±…¹}¹…µ•ôÝ½É­ÍÁ…”¥¹±Õ‘•Ìíµ…á}Í…Ù•‘}‰½µÌè±ôÍ…Ù•	=5Ì…¹Ñ¡…ÐÍÑ½É…”…±±½Ý…¹”¥Ì™Õ±°¸€ˆ(€€€€€€€€€€€€€€€€€€€€‰e½ÕÈ•á¥ÍÑ¥¹œÝ½É¬¥ÌÍ…™”¸•±•Ñ”…¸½±‘•È…¹…±åÍ¥Ì½ÈÕÁÉ…‘”Ñ¼½¹Ñ¥¹Õ”Í…Ù¥¹œ¹•ÜÉ•ÍÕ±ÑÌ¸ˆ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤((€€€€€€€€€€€™É½´½¹ÕÉÉ•¹Ð¹™ÕÑÕÉ•Ì¥µÁ½ÉÐQ¡É•…‘A½½±á•ÕÑ½È(€€€€€€€€€€€¥µÁ½ÉÐÅÕ•Õ”(€€€€€€€€€€€¥µÁ½ÉÐÑ¡É•…‘¥¹œ((€€€€€€€€€€€ÁÉ½É•ÍÍ}ÅÕ•Õ”€ôÅÕ•Õ”¹EÕ•Õ” ¤(€€€€€€€€€€€…¹•±}•Ù•¹Ð€ôÑ¡É•…‘¥¹œ¹Ù•¹Ð ¤(€€€€€€€€€€€•á•ÕÑ½È€ôQ¡É•…‘A½½±á•ÕÑ½È¡µ…á}Ý½É­•ÉÌôÄ¤(€€€€€€€€€€€™É½´ÍÉŒ¹Õ¤¹µ…¥¹}ÑÉ…¹Í¥Ñ¥½¸¥µÁ½ÉÐ…Éµ}‰½µ}…¹…±åÍ¥Í}ÑÉ…¹Í¥Ñ¥½¸((€€€€€€€€€€€ÉÕ¹}µ½‘”€ô€ (€€€€€€€€€€€€€€€€‰É•ÉÕ¸ˆ(€€€€€€€€€€€€€€€¥˜ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰…‘¥Ù½É}Í…Ù•‘}‰½µ}É•ÉÕ¹}…Ñ¥Ù”ˆ¤(€€€€€€€€€€€€€€€•±Í”€‰ÍÑ…ÉÐˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€…Éµ}‰½µ}…¹…±åÍ¥Í}ÑÉ…¹Í¥Ñ¥½¸¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”°ÉÕ¹}µ½‘”¤(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}…¹…±åÍ¥Í}ÁÉ½É•ÍÍ}ÅÕ•Õ”‰t€ôÁÉ½É•ÍÍ}ÅÕ•Õ”(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}…¹…±åÍ¥Í}…¹•±}•Ù•¹Ð‰t€ô…¹•±}•Ù•¹Ð(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}…¹…±åÍ¥Í}•á•ÕÑ½È‰t€ô•á•ÕÑ½È(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}…¹…±åÍ¥Í}™ÕÑÕÉ”‰t€ô•á•ÕÑ½È¹ÍÕ‰µ¥Ð (€€€€€€€€€€€€€€€…¹…±åé•}‰½´°(€€€€€€€€€€€€€€€‰½µ}‘˜¹½Áä¡‘••ÀõQÉÕ”¤°(€€€€€€€€€€€€€€€ÁÉ½É•ÍÍ}ÅÕ•Õ”°(€€€€€€€€€€€€€€€…¹•±}•Ù•¹Ð°(€€€€€€€€€€€€¤(€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰‰½´á}…¹…±åÍ¥Í}ÁÉ½É•ÍÌ‰t€ô€ À°±•¸¡‰½µ}‘˜¤°€ˆˆ¤(€€€€€€€€€€€ÍÐ¹É•ÉÕ¸ ¤((€€€€€€€¥˜ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰Í¡½Ý}ÕÁÉ…‘•}¡•­½ÕÐˆ¤…¹¹½Ð¥Í}…‘µ¥¸è(€€€€€€€€€€€ÕÁÉ…‘•}µ•ÍÍ…”€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð (€€€€€€€€€€€€€€€€‰ÕÁÉ…‘•}µ•ÍÍ…”ˆ°(€€€€€€€€€€€€€€€€‰e½ÕÈÕÉÉ•¹ÐÁ±…¸±¥µ¥Ð¡…Ì‰••¸É•…¡•¸ˆ°(€€€€€€€€€€€€¤((€€€€€€€€€€€ÕÁÉ…‘•}Á±…¸€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰ÕÁÉ…‘•}Á±…¹}¹…µ”ˆ¤(€€€€€€€€€€€¹•áÑ}Á±…¸€ô•Ñ}Á±…¸¡ÕÁÉ…‘•}Á±…¸¤¥˜ÕÁÉ…‘•}Á±…¸•±Í”9½¹”((€€€€€€€€€€€ÍÐ¹•ÉÉ½È¡ÕÁÉ…‘•}µ•ÍÍ…”¤((€€€€€€€€€€€¥˜ÕÁÉ…‘•}Á±…¸…¹¹•áÑ}Á±…¸è(€€€€€€€€€€€€€€€ÍÐ¹µ…É­‘½Ý¸ (€€€€€€€€€€€€€€€€€€€˜ˆˆˆ(€€€€´´´(€€€€ŒŒŒƒÂ~j UÁÉ…‘”Ñ¼€¨©íÕÁÉ…‘•}Á±…¹ô¨¨€¡í¹•áÑ}Á±…¹lÁÉ¥”uô¤((€€€U¹±½¬µ½É”Á½Ý•Èè((€€€€´ƒÂ~R4€¨©í™½Éµ…Ñ}±¥µ¥Ð¡¹•áÑ}Á±…¹lµ½¹Ñ¡±å}‰½µ}±¥µ¥Ðt°€	=4…¹…±åÍ¥Ìœ°€	=4…¹…±åÍ•Ìœ¥ô¨¨•… µ½¹Ñ (€€€€´ƒÂ~N˜€¨©í™½Éµ…Ñ}±¥µ¥Ð¡¹•áÑ}Á±…¹lµ…á}Á…ÉÑÍ}Á•É}‰½´t°€½µÁ½¹•¹Ðœ¥ô¨¨Á•È	=4(€€€€´ƒÂ~2@Y•É¥™¥•µÕ±Ñ¤µÍÕÁÁ±¥•È¥¹Ñ•±±¥•¹”(€€€€´ƒŠj„…ÍÑ•ÈÍ½ÕÉ¥¹œ‘•¥Í¥½¹Ì((€€€ƒÂ~F$UÁÉ…‘”¹½ÜÑ¼½¹Ñ¥¹Õ”å½ÕÈ…¹…±åÍ¥Ì(€€€€´´´(€€€€ˆˆˆ(€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€¥˜ÍÐ¹‰ÕÑÑ½¸¡˜‹Â~j UÁÉ…‘”Ñ¼íÕÁÉ…‘•}Á±…¹ôˆ°­•äô‰ÕÁÉ…‘•}‰ÕÑÑ½¹}µ…¥¸ˆ¤è(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€ÁÉ¥•}Í•É•Ð€ôì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰MÑ…ÉÑ•Èˆè€‰MQI%A}MQIQI}AI%}%ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰AÉ½™•ÍÍ¥½¹…°ˆè€‰MQI%A}AI=}AI%}%ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰	ÕÍ¥¹•ÍÌˆè€‰MQI%A}	UM%9MM}AI%}%ˆ°(€€€€€€€€€€€€€€€€€€€€€€€ô¹•Ð¡ÕÁÉ…‘•}Á±…¸¤(€€€€€€€€€€€€€€€€€€€€€€€¥˜¹½ÐÁÉ¥•}Í•É•Ð½ÈÕÁÉ…‘•}Á±…¸¹½Ð¥¸!-=UQ}A19}Q=-9Lè(€€€€€€€€€€€€€€€€€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰U¹ÍÕÁÁ½ÉÑ•¡•­½ÕÐÁ±…¸ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€¡•­½ÕÑ}ÕÉ°€ôÉ•…Ñ•}¡•­½ÕÑ}Í•ÍÍ¥½¸ (€€€€€€€€€€€€€€€€€€€€€€€€€€€•Ñ}Í•É•Ð¡ÁÉ¥•}Í•É•Ð°É•ÅÕ¥É•õQÉÕ”¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}ÕÍ•Él‰•µ…¥°‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}ÕÍ•Él‰¥‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÕ•ÍÍ}ÕÉ°õ…ÁÁ}¡•­½ÕÑ}ÕÉ°¡¡•­½ÕÐô‰ÍÕ•ÍÌˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€…¹•±}ÕÉ°õ…ÁÁ}¡•­½ÕÑ}ÕÉ°¡¡•­½ÕÐô‰…¹•°ˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€…‘¥Ù½É}Á±…¸õ!-=UQ}A19}Q=-9MmÕÁÉ…‘•}Á±…¹t°(€€€€€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰¡•­½ÕÑ}ÕÉ°‰t€ô¡•­½ÕÑ}ÕÉ°((€€€€€€€€€€€€€€€€€€€•á•ÁÐá•ÁÑ¥½¸è(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰M•ÕÉ”¡•­½ÕÐ½Õ±¹½Ð‰”ÍÑ…ÉÑ•¸€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰A±•…Í”ÑÉä……¥¸½È½¹Ñ…Ðí	%11%9}5%1ô¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€¥˜€‰¡•­½ÕÑ}ÕÉ°ˆ¥¸ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”è(€€€€€€€€€€€€€€€€€€€ÍÐ¹±¥¹­}‰ÕÑÑ½¸ (€€€€€€€€€€€€€€€€€€€€€€€€‰½¹Ñ¥¹Õ”Ñ¼MÑÉ¥Á”¡•­½ÕÐˆ°(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰¡•­½ÕÑ}ÕÉ°‰t°(€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€ÍÐ¹¥¹™¼ ‰9¼ÕÁÉ…‘”Á±…¸¥Ì½¹™¥ÕÉ•™½Èå½ÕÈÕÉÉ•¹ÐÍÕ‰ÍÉ¥ÁÑ¥½¸¸ˆ¤((€€€€€€€¥˜€‰É•ÍÕ±ÑÍ}‘˜ˆ¥¸ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”è(€€€€€€€€€€€É•ÍÕ±ÑÍ}‘˜€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰É•ÍÕ±ÑÍ}‘˜‰t((€€€€€€€€€€€¥˜¹½ÐÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰…¹…±åÍ¥Í}Í…Ù•ˆ°…±Í”¤è(€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}‰±½­•‘}Á±…¸…¹¹½Ð}½¹•}Ñ¥µ•}É•Í•ÉÙ•è(€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}½µÁ½¹•¹Ñ}½Õ¹Ð€ô¥¹Ð (€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰…‘¥Ù½É}½¹•}Ñ¥µ•}Á•¹‘¥¹}½µÁ½¹•¹Ñ}½Õ¹Ðˆ°±•¸¡É•ÍÕ±ÑÍ}‘˜¤(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}½µÁ½¹•¹Ñ}½Õ¹Ð€ø=9}Q%5}	=5}5a}AIQLè(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È (€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰Q¡”½¹”µÑ¥µ”É•Á½ÉÐ½Ù•ÉÌÕÀÑ¼í=9}Q%5}	=5}5a}AIQMôÕ¹¥ÅÕ”½µÁ½¹•¹ÑÌ¸€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰Q¡¥Ì	=4¡…Ìí}½¹•}Ñ¥µ•}½µÁ½¹•¹Ñ}½Õ¹Ñôì¹¼Á…åµ•¹ÐÝ…ÌÉ•ÅÕ•ÍÑ•¸€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰I•‘Õ”Ñ¡”	=4½È½µÁ…É”Á±…¹Ì™½È„±…É•È…¹…±åÍ¥Ì¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤(€€€€€€€€€€€€€€€€€€€¥˜¹½Ð½¹•}Ñ¥µ•}É•‘¥Ñ}…Ù…¥±…‰±”¡}½¹•}Ñ¥µ•}ÕÍ•É}¥¤è(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹µ…É­‘½Ý¸ ˆŒŒŒe½ÕÈ	=4…¹…±åÍ¥Ì¥ÌÉ•…‘äˆ¤(€€€€€€€€€€€€€€€€€€€€€€€¥˜¹½Ð½¹•}Ñ¥µ•}‰½µ}•¹…‰±• ¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Ý…É¹¥¹œ ‰=¹”µÑ¥µ”¡•­½ÕÐ¥ÌÑ•µÁ½É…É¥±äÕ¹…Ù…¥±…‰±”¸e½ÕÈÉ•Á½ÉÐ¡…Ì¹½Ð‰••¸Í…Ù•¸ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤(€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}Õ¹…ÍÍ•ÍÍ•‘}½Õ¹Ð€ô¥¹Ð (€€€€€€€€€€€€€€€€€€€€€€€€€€€É•ÍÕ±ÑÍ}‘˜¹•Ð (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰I¥Í¬1•Ù•°ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Á¹M•É¥•Ì ˆˆ°¥¹‘•àõÉ•ÍÕ±ÑÍ}‘˜¹¥¹‘•à¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤¹…ÍÑåÁ”¡ÍÑÈ¤¹ÍÑÈ¹…Í•™½± ¤¹•Ä ‰¹••‘ÌÙ•É¥™¥…Ñ¥½¸ˆ¤¹ÍÕ´ ¤(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}•Ù¥‘•¹•}…­¹½Ý±•‘•€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}Õ¹…ÍÍ•ÍÍ•‘}½Õ¹Ðè(€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}µÁ¹}Ù…±Õ•Ì€ô€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€É•ÍÕ±ÑÍ}‘˜¹•Ð ‰5A8ˆ°Á¹M•É¥•Ì¡‘ÑåÁ”õÍÑÈ¤¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¹…ÍÑåÁ”¡ÍÑÈ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¹Ñ½±¥ÍÐ ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}•Ù¥‘•¹•}­•ä€ô¡…Í¡±¥ˆ¹Í¡„ÈÔØ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰q¸ˆ¹©½¥¸¡Í½ÉÑ•¡}½¹•}Ñ¥µ•}µÁ¹}Ù…±Õ•Ì¤¤¹•¹½‘” ‰ÕÑ˜´àˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤¹¡•á‘¥•ÍÐ ¥lèÄÉt(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Ý…É¹¥¹œ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰í}½¹•}Ñ¥µ•}Õ¹…ÍÍ•ÍÍ•‘}½Õ¹Ñô½˜í±•¸¡É•ÍÕ±ÑÍ}‘˜¥ô½µÁ½¹•¹ÑÌ€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰½Õ±¹½Ð‰”É¥Í¬µÉ…Ñ•‰•…ÕÍ”Ñ¡”Í…Ù•…¹…±åÍ¥Ì±…­Ì„Ù•É¥™¥•€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÕÁÁ±¥•Èµ…Ñ ¸%˜Ñ¡•Í”…É”Á±…•¡½±‘•ÉÌ°É•Á±…”Ñ¡•´Ý¥Ñ €ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰µ…¹Õ™…ÑÕÉ•ÈÁ…ÉÐ¹Õµ‰•ÉÌ…¹É•ÉÕ¸‰•™½É”ÁÕÉ¡…Í¥¹œ¸A…åµ•¹Ð€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰‘½•Ì¹½Ð…‘µ¥ÍÍ¥¹œÍÕÁÁ±¥•È½Ù•É…”¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}•Ù¥‘•¹•}…­¹½Ý±•‘•€ôÍÐ¹¡•­‰½à (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰$Õ¹‘•ÉÍÑ…¹Ñ¡¥ÌÉ•Á½ÉÐÝ¥±°¥¹±Õ‘”Õ¹…ÍÍ•ÍÍ•½µÁ½¹•¹ÑÌ¸ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€­•äõ˜‰‰½´á}É•Á½ÉÑ}•Ù¥‘•¹•}…­}í}½¹•}Ñ¥µ•}•Ù¥‘•¹•}­•åôˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}™¥¹…±}ÁÉ¥”€ô½¹•}Ñ¥µ•}É•Á½ÉÑ}ÁÉ¥•}±…‰•° (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÑÈ¡•Ñ}Í•É•Ð ‰MQI%A}=9}Q%5}	=5}IA=IQ}AI%}%ˆ°É•ÅÕ¥É•õQÉÕ”¤¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹…ÁÑ¥½¸ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰…‘¥Ù½È…¹…±åé•í}½¹•}Ñ¥µ•}½µÁ½¹•¹Ñ}½Õ¹ÑôÕ¹¥ÅÕ”½µÁ½¹•¹ÑÌ¸€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰=¹”µÑ¥µ”É•Á½ÉÐ½Ù•ÉÌÕÀÑ¼í=9}Q%5}	=5}5a}AIQMôì¹¼ÍÕ‰ÍÉ¥ÁÑ¥½¸¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}Á•¹‘¥¹œ€ôÁ•¹‘¥¹}½¹•}Ñ¥µ•}¡•­½ÕÐ¡}½¹•}Ñ¥µ•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}Á•¹‘¥¹œ…¹}½¹•}Ñ¥µ•}Á•¹‘¥¹lÁt€ôô€‰½Á•¸ˆè(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}¡•­½ÕÑ}ÕÉ°€ô€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}Á•¹‘¥¹lÅt(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}•Ù¥‘•¹•}…­¹½Ý±•‘•(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•±Í”€ˆˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€•±¥˜}½¹•}Ñ¥µ•}Á•¹‘¥¹œè(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}¡•­½ÕÑ}ÕÉ°€ô€ˆˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹¥¹™¼ ‰MÑÉ¥Á”¥Ì½¹™¥Éµ¥¹œå½ÕÈÁ…åµ•¹Ð¸e½ÕÈÉ•Á½ÉÐÝ¥±°Õ¹±½¬¡•É”…ÕÑ½µ…Ñ¥…±±ä¸ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€•±¥˜}½¹•}Ñ¥µ•}•Ù¥‘•¹•}…­¹½Ý±•‘•è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}¡•­½ÕÑ}ÕÉ°€ô‰•¥¹}½¹•}Ñ¥µ•}¡•­½ÕÐ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÑÈ¡ÕÉÉ•¹Ñ}ÕÍ•È¹•Ð ‰•µ…¥°ˆ¤½È€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…ÁÁ}¡•­½ÕÑ}ÕÉ°¡Á…”ô‰	=4¹…±åé•Èˆ°¡•­½ÕÐô‰Í¥¹±•}‰½µ}ÍÕ•ÍÌˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…ÁÁ}¡•­½ÕÑ}ÕÉ°¡Á…”ô‰	=4¹…±åé•Èˆ°¡•­½ÕÐô‰Í¥¹±•}‰½µ}…¹•°ˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}¡•­½ÕÑ}ÕÉ°€ô€ˆˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹¥¹™¼ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰½ÉÉ•ÐÑ¡”Á…ÉÐ¹Õµ‰•ÉÌ…¹É•ÉÕ¸°½È…­¹½Ý±•‘”Ñ¡”½Ù•É…”€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰±¥µ¥ÐÑ¼½¹Ñ¥¹Õ”Ñ¼Á…åµ•¹Ð¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}¡•­½ÕÑ}ÕÉ°è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Ý¥Ñ ÍÐ¹½¹Ñ…¥¹•È (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€­•äô‰‰½´á}½¹•}Ñ¥µ•}Á…åµ•¹Ñ}…Ñ¥½¸ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰½É‘•ÈõQÉÕ”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹±¥¹­}‰ÕÑÑ½¸ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰A…äí}½¹•}Ñ¥µ•}™¥¹…±}ÁÉ¥•ô…¹Õ¹±½¬É•Á½ÉÐˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}¡•­½ÕÑ}ÕÉ°°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÑåÁ”ô‰ÁÉ¥µ…Éäˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÕÍ•}½¹Ñ…¥¹•É}Ý¥‘Ñ õ…±Í”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹…ÁÑ¥½¸ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰-••ÀÑ¡¥ÌÑ…ˆ½Á•¸¸™Ñ•ÈÁ…åµ•¹Ð°Ñ¡”É•Á½ÉÐ…ÁÁ•…ÉÌ¡•É”€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰…¹¥¸¹…±åÍ¥Ì•Ñ…¥±Ì¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€•á•ÁÐ=¹•Q¥µ•	=5ÉÉ½È…Ì•áŒè(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È¡ÍÑÈ¡•áŒ¤¤((€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹™É…µ•¹Ð¡ÉÕ¹}•Ù•ÉäôˆÕÌˆ¤(€€€€€€€€€€€€€€€€€€€€€€€‘•˜}Á½±±}½¹•}Ñ¥µ•}É•Á½ÉÑ}Á…åµ•¹Ð ¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜½¹•}Ñ¥µ•}É•‘¥Ñ}…Ù…¥±…‰±”¡}½¹•}Ñ¥µ•}ÕÍ•É}¥¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÍÕ•ÍÌ ‰A…åµ•¹Ð½¹™¥Éµ•¸U¹±½­¥¹œå½ÕÈ™Õ±°É•Á½ÉÓŠ˜ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹É•ÉÕ¸ ¤((€€€€€€€€€€€€€€€€€€€€€€€}Á½±±}½¹•}Ñ¥µ•}É•Á½ÉÑ}Á…åµ•¹Ð ¤(€€€€€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}½É‘•É}¥€ôÉ•Í•ÉÙ•}½¹•}Ñ¥µ•}É•‘¥Ð¡}½¹•}Ñ¥µ•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€€€€€•á•ÁÐ=¹•Q¥µ•	=5ÉÉ½È…Ì•áŒè(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È¡ÍÑÈ¡•áŒ¤¤(€€€€€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}½¹•}Ñ¥µ•}‰½µ}½É‘•É}¥‰t€ô}½¹•}Ñ¥µ•}½É‘•É}¥(€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}É•Í•ÉÙ•€ôQÉÕ”(€€€€€€€€€€€€€€€¡¥¡}½Õ¹Ð€ô±•¸¡É•ÍÕ±ÑÍ}‘™mÉ•ÍÕ±ÑÍ}‘™l‰I¥Í¬1•Ù•°‰t€ôô€‰!¥ ‰t¤(€€€€€€€€€€€€€€€µ•‘¥Õµ}½Õ¹Ð€ô±•¸¡É•ÍÕ±ÑÍ}‘™mÉ•ÍÕ±ÑÍ}‘™l‰I¥Í¬1•Ù•°‰t€ôô€‰5•‘¥Õ´‰t¤(€€€€€€€€€€€€€€€±½Ý}½Õ¹Ð€ô±•¸¡É•ÍÕ±ÑÍ}‘™mÉ•ÍÕ±ÑÍ}‘™l‰I¥Í¬1•Ù•°‰t€ôô€‰1½Ü‰t¤(€€€€€€€€€€€€€€€Ñ½Ñ…±}Á…ÉÑÌ€ô±•¸¡É•ÍÕ±ÑÍ}‘˜¤((€€€€€€€€€€€€€€€¡•…±Ñ¡}‘…Ñ„€ô…±Õ±…Ñ•}‰½µ}¡•…±Ñ¡}Í½É”¡É•ÍÕ±ÑÍ}‘˜¤(€€€€€€€€€€€€€€€¡•…±Ñ¡}Í½É”€ô¡•…±Ñ¡}‘…Ñ„¹•Ð ‰¡•…±Ñ¡}Í½É”ˆ¤((€€€€€€€€€€€€€€€¥˜¡•…±Ñ¡}Í½É”¥Ì9½¹”è(€€€€€€€€€€€€€€€€€€€¡•…±Ñ¡}ÍÑ…ÑÕÌ€ô€‹Šj¨9••‘ÌÙ•É¥™¥…Ñ¥½¸ˆ(€€€€€€€€€€€€€€€•±¥˜¡•…±Ñ¡}Í½É”€øô€äÀè(€€€€€€€€€€€€€€€€€€€¡•…±Ñ¡}ÍÑ…ÑÕÌ€ô€‹Â~~ˆá•±±•¹Ðˆ(€€€€€€€€€€€€€€€•±¥˜¡•…±Ñ¡}Í½É”€øô€ÜÔè(€€€€€€€€€€€€€€€€€€€¡•…±Ñ¡}ÍÑ…ÑÕÌ€ô€‹Â~~ˆ!•…±Ñ¡äˆ(€€€€€€€€€€€€€€€•±¥˜¡•…±Ñ¡}Í½É”€øô€ØÀè(€€€€€€€€€€€€€€€€€€€¡•…±Ñ¡}ÍÑ…ÑÕÌ€ô€‹Â~~„5½‘•É…Ñ”I¥Í¬ˆ(€€€€€€€€€€€€€€€•±¥˜¡•…±Ñ¡}Í½É”€øô€ÐÀè(€€€€€€€€€€€€€€€€€€€¡•…±Ñ¡}ÍÑ…ÑÕÌ€ô€‹Â~~€!¥ I¥Í¬ˆ(€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€¡•…±Ñ¡}ÍÑ…ÑÕÌ€ô€‹Â~RÐÉ¥Ñ¥…°ˆ((€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰¡•…±Ñ¡}Í½É”‰t€ô¡•…±Ñ¡}Í½É”(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰¡•…±Ñ¡}ÍÑ…ÑÕÌ‰t€ô¡•…±Ñ¡}ÍÑ…ÑÕÌ((€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}É•Í•ÉÙ•è(€€€€€€€€€€€€€€€€€€€€€€€™É½´ÕÕ¥¥µÁ½ÉÐÕÕ¥Ð(€€€€€€€€€€€€€€€€€€€€€€€…¹…±åÍ¥Í}¥€ôÍÑÈ¡ÕÕ¥Ð ¤¤(€€€€€€€€€€€€€€€€€€€€€€€…ÑÑ…¡}½¹•}Ñ¥µ•}…¹…±åÍ¥Ì (€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}ÕÍ•É}¥°}½¹•}Ñ¥µ•}½É‘•É}¥°…¹…±åÍ¥Í}¥(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€…¹…±åÍ¥Í}É•ÍÁ½¹Í”€ôÍÕÁ…‰…Í”¹Ñ…‰±” ‰…¹…±åÍ•Ìˆ¤¹¥¹Í•ÉÐ (€€€€€€€€€€€€€€€€€€€€€€€}Ý½É­ÍÁ…•}Á…å±½… (€€€€€€€€€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¨¨¡ì‰¥ˆè…¹…±åÍ¥Í}¥‘ô¥˜}½¹•}Ñ¥µ•}É•Í•ÉÙ••±Í”íô¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÕÍ•É}¥ˆèÕÉÉ•¹Ñ}ÕÍ•Él‰¥‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÁÉ½©•Ñ}¹…µ”ˆè…¹…±åÍ¥Í}¹…µ”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰™¥±•¹…µ”ˆèÍ½ÕÉ•}™¥±•¹…µ”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰Ñ½Ñ…±}Á…ÉÑÌˆèÑ½Ñ…±}Á…ÉÑÌ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰¡¥¡}É¥Í­}½Õ¹Ðˆè¡¥¡}½Õ¹Ð°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰µ•‘¥Õµ}É¥Í­}½Õ¹Ðˆèµ•‘¥Õµ}½Õ¹Ð°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰±½Ý}É¥Í­}½Õ¹Ðˆè±½Ý}½Õ¹Ð°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰¡•…±Ñ¡}Í½É”ˆè¡•…±Ñ¡}Í½É”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€¤¹•á•ÕÑ” ¤((€€€€€€€€€€€€€€€€€€€…¹…±åÍ¥Í}¥€ô…¹…±åÍ¥Í}É•ÍÁ½¹Í”¹‘…Ñ…lÁul‰¥‰t(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…¹…±åÍ¥Í}¥‰t€ô…¹…±åÍ¥Í}¥(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}…Ñ¥Ù•}…¹…±åÍ¥Í}¥‰t€ôÍÑÈ¡…¹…±åÍ¥Í}¥¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}…Ñ¥Ù•}…¹…±åÍ¥Í}Ñ…ˆ‰t€ô€‰¹¥¹••É¥¹œ%¹Ñ•±±¥•¹”ˆ((€€€€€€€€€€€€€€€•á•ÁÐá•ÁÑ¥½¸…Ì”è(€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}É•Í•ÉÙ•è(€€€€€€€€€€€€€€€€€€€€€€€¥˜É•±•…Í•}½¹•}Ñ¥µ•}É•‘¥Ð¡}½¹•}Ñ¥µ•}ÕÍ•É}¥°}½¹•}Ñ¥µ•}½É‘•É}¥¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰…‘¥Ù½É}½¹•}Ñ¥µ•}‰½µ}½É‘•É}¥ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰É•ÍÕ±ÑÍ}‘˜ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È¡˜‰½Õ±¹½ÐÍ…Ù”…¹…±åÍ¥ÌÍÕµµ…Éäèí•ôˆ¤(€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤((€€€€€€€€€€€€€€€™É½´ÍÉŒ¹Á…ÉÑ}¥µ…•Ì¥µÁ½ÉÐ¹½Éµ…±¥é•}ÍÕÁÁ±¥•É}¥µ…•}ÕÉ°(€€€€€€€€€€€€€€€™É½´ÍÉŒ¹Í…Ù•‘}‰½µ}½ÍÐ¥µÁ½ÉÐ€ (€€€€€€€€€€€€€€€€€€€=AQ%=91}MY}AIQ}=1U59L°(€€€€€€€€€€€€€€€€€€€…¹…±åÍ¥Í}Á…ÉÑ}½ÍÑ}™¥•±‘Ì°(€€€€€€€€€€€€€€€€€€€©Í½¹}Í…™•}Ù…±Õ”°(€€€€€€€€€€€€€€€€€€€½µ¥ÑÑ•‘}½ÁÑ¥½¹…±}½±Õµ¸°(€€€€€€€€€€€€€€€€€€€Ý¥Ñ¡½ÕÑ}½±Õµ¸°(€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€Á…ÉÑ}É•½É‘Ì€ômt((€€€€€€€€€€€€€€€™½È|°Á…ÉÑ}É½Ü¥¸É•ÍÕ±ÑÍ}‘˜¹¥Ñ•ÉÉ½ÝÌ ¤è(€€€€€€€€€€€€€€€€€€€½ÍÑ}™¥•±‘Ì€ô…¹…±åÍ¥Í}Á…ÉÑ}½ÍÑ}™¥•±‘Ì¡Á…ÉÑ}É½Ü¤(€€€€€€€€€€€€€€€€€€€Á…ÉÑ}É•½É‘Ì¹…ÁÁ•¹ (€€€€€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰…¹…±åÍ¥Í}¥ˆè…¹…±åÍ¥Í}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÕÍ•É}¥ˆèÕÉÉ•¹Ñ}ÕÍ•Él‰¥‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰Ý½É­ÍÁ…•}¥ˆè…Ñ¥Ù•}Ý½É­ÍÁ…•}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰¥µ…•}ÕÉ°ˆè¹½Éµ…±¥é•}ÍÕÁÁ±¥•É}¥µ…•}ÕÉ° (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Á…ÉÑ}É½Ü¹•Ð ‰A¡½Ñ¼ˆ°€ˆˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÁÉ½©•Ñ}¹…µ”ˆè…¹…±åÍ¥Í}¹…µ”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰µÁ¸ˆèÁ…ÉÑ}É½Ü¹•Ð ‰5A8ˆ°€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰µ…¹Õ™…ÑÕÉ•ÈˆèÁ…ÉÑ}É½Ü¹•Ð ‰5…¹Õ™…ÑÕÉ•Èˆ°€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰‘•ÍÉ¥ÁÑ¥½¸ˆèÍÑÈ¡Á…ÉÑ}É½Ü¹•Ð ‰•ÍÉ¥ÁÑ¥½¸ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤½È9½¹”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰…Ñ•½ÉäˆèÍÑÈ¡Á…ÉÑ}É½Ü¹•Ð ‰…Ñ•½Éäˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤½È9½¹”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÕÁÁ±¥•É}‘…Ñ…}Ù•É¥™¥•ˆè‰½½°¡Á…ÉÑ}É½Ü¹•Ð ‰MÕÁÁ±¥•È…Ñ„Y•É¥™¥•ˆ°…±Í”¤¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰Í½ÕÉ¥¹}ÕÁ‘…Ñ•‘}…ÐˆèÁ…ÉÑ}É½Ü¹•Ð ‰M½ÕÉ¥¹œUÁ‘…Ñ•Ðˆ¤½È9½¹”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰É¥Í­}Í½É”ˆè}©Í½¹}Í…™•}½ÁÑ¥½¹…±}¹Õµ‰•È¡Á…ÉÑ}É½Ü¹•Ð ‰I¥Í¬M½É”ˆ¤¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰É¥Í­}±•Ù•°ˆèÁ…ÉÑ}É½Ü¹•Ð ‰I¥Í¬1•Ù•°ˆ°€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰É¥Í­}É•…Í½¹ÌˆèÁ…ÉÑ}É½Ü¹•Ð ‰I¥Í¬I•…Í½¹Ìˆ°€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰±¥™•å±•}ÍÑ…ÑÕÌˆèÁ…ÉÑ}É½Ü¹•Ð ‰1¥™•å±”MÑ…ÑÕÌˆ°€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÑ½­}…Ù…¥±…‰±”ˆè}©Í½¹}Í…™•}½ÁÑ¥½¹…±}¹Õµ‰•È¡Á…ÉÑ}É½Ü¹•Ð ‰MÑ½¬Ù…¥±…‰±”ˆ¤¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÕÁÁ±¥•É}½Õ¹Ðˆè}©Í½¹}Í…™•}½ÁÑ¥½¹…±}¹Õµ‰•È¡Á…ÉÑ}É½Ü¹•Ð ‰MÕÁÁ±¥•È½Õ¹Ðˆ¤¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÕÁÁ±¥•É}½Ù•É…”ˆèÍÑÈ¡Á…ÉÑ}É½Ü¹•Ð ‰MÕÁÁ±¥•È½Ù•É…”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤½È9½¹”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÑ½­}‘…Ñ…}Í½ÕÉ•ÌˆèÁ…ÉÑ}É½Ü¹•Ð ‰MÑ½¬…Ñ„M½ÕÉ•Ìˆ¤½Èmt°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÑ½­}‘…Ñ…}½µÁ±•Ñ”ˆè‰½½°¡Á…ÉÑ}É½Ü¹•Ð ‰MÑ½¬…Ñ„½µÁ±•Ñ”ˆ°…±Í”¤¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰±¥™•å±•}•Ù¥‘•¹”ˆèÁ…ÉÑ}É½Ü¹•Ð ‰1¥™•å±”Ù¥‘•¹”ˆ¤½Èmt°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰±¥™•å±•}½¹™±¥Ðˆè‰½½°¡Á…ÉÑ}É½Ü¹•Ð ‰1¥™•å±”½¹™±¥Ðˆ°…±Í”¤¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰±•…‘}Ñ¥µ•}Í½ÕÉ”ˆèÍÑÈ¡Á…ÉÑ}É½Ü¹•Ð ‰1•…Q¥µ”M½ÕÉ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤½È9½¹”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰…±Ñ•É¹…Ñ•}Í•…É¡}ÍÑ…ÑÕÌˆèÍÑÈ¡Á…ÉÑ}É½Ü¹•Ð ‰±Ñ•É¹…Ñ”M•…É MÑ…ÑÕÌˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤½È9½¹”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÅÕ…¹Ñ¥Ñäˆè½ÍÑ}™¥•±‘Íl‰ÅÕ…¹Ñ¥Ñä‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰Õ¹¥Ñ}ÁÉ¥”ˆè½ÍÑ}™¥•±‘Íl‰Õ¹¥Ñ}ÁÉ¥”‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰Õ¹¥Ñ}ÁÉ¥•}ÕÉÉ•¹äˆè½ÍÑ}™¥•±‘Íl‰Õ¹¥Ñ}ÁÉ¥•}ÕÉÉ•¹ä‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÁÉ¥µ…Éå}ÍÕÁÁ±¥•Èˆè½ÍÑ}™¥•±‘Íl‰ÁÉ¥µ…Éå}ÍÕÁÁ±¥•È‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÁÉ½‘ÕÑ}ÕÉ°ˆè½ÍÑ}™¥•±‘Íl‰ÁÉ½‘ÕÑ}ÕÉ°‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰‘…Ñ…Í¡••Ñ}ÕÉ°ˆè½ÍÑ}™¥•±‘Íl‰‘…Ñ…Í¡••Ñ}ÕÉ°‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÕÁÁ±¥•É}½™™•ÉÌˆè½ÍÑ}™¥•±‘Íl‰ÍÕÁÁ±¥•É}½™™•ÉÌ‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰±•…‘}Ñ¥µ•}Ý••­Ìˆè}©Í½¹}Í…™•}½ÁÑ¥½¹…±}¹Õµ‰•È (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Á…ÉÑ}É½Ü¹•Ð ‰1•…Q¥µ”]••­Ìˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€¥˜Á…ÉÑ}É•½É‘Ìè(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€Á•¹‘¥¹}É•½É‘Ì€ôm©Í½¹}Í…™•}Ù…±Õ”¡É•½É¤™½ÈÉ•½É¥¸Á…ÉÑ}É•½É‘Ít(€€€€€€€€€€€€€€€€€€€€€€€™½È}…ÑÑ•µÁÐ¥¸É…¹”¡±•¸¡=AQ%=91}MY}AIQ}=1U59L¤€¬€Ä¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÕÁ…‰…Í”¹Ñ…‰±” ‰…¹…±åÍ¥Í}Á…ÉÑÌˆ¤¹¥¹Í•ÉÐ¡Á•¹‘¥¹}É•½É‘Ì¤¹•á•ÕÑ” ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰É•…¬(€€€€€€€€€€€€€€€€€€€€€€€€€€€•á•ÁÐá•ÁÑ¥½¸…Ì½ÁÑ¥½¹…±}½±Õµ¹}•ÉÉ½Èè(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€µ¥ÍÍ¥¹}½±Õµ¸€ô½µ¥ÑÑ•‘}½ÁÑ¥½¹…±}½±Õµ¸¡ÍÑÈ¡½ÁÑ¥½¹…±}½±Õµ¹}•ÉÉ½È¤¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜¹½Ðµ¥ÍÍ¥¹}½±Õµ¸½È…±° (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€µ¥ÍÍ¥¹}½±Õµ¸¹½Ð¥¸É•½É™½ÈÉ•½É¥¸Á•¹‘¥¹}É•½É‘Ì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€É…¥Í”(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Á•¹‘¥¹}É•½É‘Ì€ôÝ¥Ñ¡½ÕÑ}½±Õµ¸¡Á•¹‘¥¹}É•½É‘Ì°µ¥ÍÍ¥¹}½±Õµ¸¤(€€€€€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È ‰½Õ±¹½ÐÍ…Ù”	=4Á…ÉÑÌ…™Ñ•È‘É½ÁÁ¥¹œÕ¹­¹½Ý¸½±Õµ¹Ì¸ˆ¤(€€€€€€€€€€€€€€€€€€€•á•ÁÐá•ÁÑ¥½¸…Ì”è(€€€€€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}É•Í•ÉÙ•è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€Œ¸¥¹½µÁ±•Ñ”ÍÕµµ…Éä¥Ì¹½Ð„‘•±¥Ù•É•É•Á½ÉÐ¸(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‘•±•Ñ•€ô€¡ÍÕÁ…‰…Í”¹Ñ…‰±” ‰…¹…±åÍ•Ìˆ¤¹‘•±•Ñ” ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¹•Ä ‰¥ˆ°…¹…±åÍ¥Í}¥¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¹•Ä ‰ÕÍ•É}¥ˆ°}½¹•}Ñ¥µ•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¹Í•±•Ð ‰¥ˆ¤¹•á•ÕÑ” ¤¤¹‘…Ñ„(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜‘•±•Ñ•è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜É•±•…Í•}½¹•}Ñ¥µ•}É•‘¥Ð¡}½¹•}Ñ¥µ•}ÕÍ•É}¥°}½¹•}Ñ¥µ•}½É‘•É}¥¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰…‘¥Ù½É}½¹•}Ñ¥µ•}‰½µ}½É‘•É}¥ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰É•ÍÕ±ÑÍ}‘˜ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…¹…±åÍ¥Í}Í…Ù•‰t€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€€€€€€€€€•á•ÁÐá•ÁÑ¥½¸è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…¹…±åÍ¥Í}Í…Ù•‰t€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰½Õ±¹½ÐÍ…Ù”	=4Á…ÉÑÌ¸e½ÕÈÁ…åµ•¹ÐÉ•µ…¥¹ÌÉ•½É‘•¸€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰½¹Ñ…ÐÍÕÁÁ½ÉÐ¥˜Ñ¡¥ÌÁ•ÉÍ¥ÍÑÌ¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}É•Í•ÉÙ••±Í”˜‰½Õ±¹½ÐÍ…Ù”	=4Á…ÉÑÌèí•ôˆ(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤((€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}É•Í•ÉÙ•è(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€½¹ÍÕµ•}½¹•}Ñ¥µ•}É•‘¥Ð (€€€€€€€€€€€€€€€€€€€€€€€€€€€}½¹•}Ñ¥µ•}ÕÍ•É}¥°}½¹•}Ñ¥µ•}½É‘•É}¥°ÍÑÈ¡…¹…±åÍ¥Í}¥¤(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€•á•ÁÐ=¹•Q¥µ•	=5ÉÉ½È…Ì•áŒè(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…¹…±åÍ¥Í}Í…Ù•‰t€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È¡ÍÑÈ¡•áŒ¤¤(€€€€€€€€€€€€€€€€€€€€€€€ÍÑ½Á}…ÕÑ¡•¹Ñ¥…Ñ•‘}Á…” ¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰…‘¥Ù½É}½¹•}Ñ¥µ•}‰½µ}½É‘•É}¥ˆ°9½¹”¤((€€€€€€€€€€€€€€€µ½¹¥Ñ½É}É•½É‘Ì€ômt(€€€€€€€€€€€€€€€…±•ÉÑ}É•½É‘Ì€ômt(€€€€€€€€€€€€€€€µ½¹¥Ñ½É}•µ…¥±}…±±½Ý•°µ½¹¥Ñ½É}ÁÉ•™•É•¹•}•ÉÉ½È€ô€ (€€€€€€€€€€€€€€€€€€€µ½¹¥Ñ½É¥¹}•µ…¥±}•¹…‰±• (€€€€€€€€€€€€€€€€€€€€€€€ÍÕÁ…‰…Í”°(€€€€€€€€€€€€€€€€€€€€€€€ÍÑÈ¡ÕÉÉ•¹Ñ}ÕÍ•È¹•Ð ‰¥ˆ¤½È€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€µ½¹¥Ñ½É}•µ…¥±}É•¥Á¥•¹Ð€ô}Í…™•}Ñ•áÐ¡ÕÉÉ•¹Ñ}ÕÍ•È¹•Ð ‰•µ…¥°ˆ¤°€ˆˆ¤(€€€€€€€€€€€€€€€¥˜µ½¹¥Ñ½É}ÁÉ•™•É•¹•}•ÉÉ½Èè(€€€€€€€€€€€€€€€€€€€µ½¹¥Ñ½É}•µ…¥±}…±±½Ý•€ô…±Í”((€€€€€€€€€€€€€€€™½È|°É½Ü¥¸É•ÍÕ±ÑÍ}‘˜¹¥Ñ•ÉÉ½ÝÌ ¤è(€€€€€€€€€€€€€€€€€€€±…Ñ•ÍÑ}µ½¹¥Ñ½È€ô€ (€€€€€€€€€€€€€€€€€€€€€€€}Ý½É­ÍÁ…•}ÅÕ•Éä (€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÕÁ…‰…Í”¹Ñ…‰±” ‰Á…ÉÑ}µ½¹¥Ñ½É}¡¥ÍÑ½Éäˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¹Í•±•Ð ˆ¨ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€¹•Ä ‰ÕÍ•É}¥ˆ°ÕÉÉ•¹Ñ}ÕÍ•Él‰¥‰t¤(€€€€€€€€€€€€€€€€€€€€€€€€¹•Ä ‰Á…ÉÑ}¹Õµ‰•Èˆ°É½Ü¹•Ð ‰5A8ˆ°€ˆˆ¤¤(€€€€€€€€€€€€€€€€€€€€€€€€¹½É‘•È ‰É•…Ñ•‘}…Ðˆ°‘•ÍŒõQÉÕ”¤(€€€€€€€€€€€€€€€€€€€€€€€€¹±¥µ¥Ð Ä¤(€€€€€€€€€€€€€€€€€€€€€€€€¹•á•ÕÑ” ¤(€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€±…Ñ•ÍÑ}µ½¹¥Ñ½É}‘…Ñ„€ô€ (€€€€€€€€€€€€€€€€€€€€€€€±…Ñ•ÍÑ}µ½¹¥Ñ½È¹‘…Ñ…lÁt(€€€€€€€€€€€€€€€€€€€€€€€¥˜±…Ñ•ÍÑ}µ½¹¥Ñ½È¹‘…Ñ„(€€€€€€€€€€€€€€€€€€€€€€€•±Í”9½¹”(€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€µ½¹¥Ñ½É}…±•ÉÑÌ€ômt((€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}Í¹…ÁÍ¡½Ð€ô‰Õ¥±‘}µ½¹¥Ñ½É}É•½É (€€€€€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}ÕÍ•Él‰¥‰t°(€€€€€€€€€€€€€€€€€€€€€€€…¹…±åÍ¥Í}¥°(€€€€€€€€€€€€€€€€€€€€€€€É½Ü°(€€€€€€€€€€€€€€€€€€€€€€€Ý½É­ÍÁ…•}¥õ…Ñ¥Ù•}Ý½É­ÍÁ…•}¥°(€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€¥˜±…Ñ•ÍÑ}µ½¹¥Ñ½É}‘…Ñ„è(€€€€€€€€€€€€€€€€€€€€€€€¹•Ý}…±•ÉÑ}É•½É‘Ì°µ½¹¥Ñ½É}…±•ÉÑÌ€ô‘•Ñ•Ñ}µ½¹¥Ñ½É}…±•ÉÑÌ (€€€€€€€€€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}ÕÍ•Él‰¥‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€…¹…±åÍ¥Í}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€É½Ü¹•Ð ‰5A8ˆ°€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€±…Ñ•ÍÑ}µ½¹¥Ñ½É}‘…Ñ„°(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}Í¹…ÁÍ¡½Ð°(€€€€€€€€€€€€€€€€€€€€€€€€€€€Ý½É­ÍÁ…•}¥õ…Ñ¥Ù•}Ý½É­ÍÁ…•}¥°(€€€€€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€€€€€…±•ÉÑ}É•½É‘Ì¹•áÑ•¹¡¹•Ý}…±•ÉÑ}É•½É‘Ì¤((€€€€€€€€€€€€€€€€€€€€€€€™½È…±•ÉÐ¥¸¹•Ý}…±•ÉÑ}É•½É‘Ìè(€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…±•ÉÐ¹•Ð ‰Í•Ù•É¥Ñäˆ¤€ôô€‰!¥ ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…¹…±•ÉÐ¹•Ð ‰…±•ÉÑ}ÑåÁ”ˆ¤€ôô€‰MÑ½¬É½Àˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…¹µ½¹¥Ñ½É}•µ…¥±}…±±½Ý•(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…¹µ½¹¥Ñ½É}•µ…¥±}É•¥Á¥•¹Ð(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Í•¹‘}µ½¹¥Ñ½É}…±•ÉÑ}•µ…¥° (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€µ½¹¥Ñ½É}•µ…¥±}É•¥Á¥•¹Ð°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰!¥ M•Ù•É¥Ñä	=45½¹¥Ñ½É¥¹œ±•ÉÐˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰A…ÉÐèíÉ½Ü¹•Ð 5A8œ°€œœ¥õq¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰±•ÉÐèí…±•ÉÐ¹•Ð …±•ÉÑ}µ•ÍÍ…”œ°€œœ¥õq¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰M•Ù•É¥Ñäèí…±•ÉÐ¹•Ð Í•Ù•É¥Ñäœ°€œœ¥ôˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•á•ÁÐµ…¥±•±¥Ù•ÉåÉÉ½Èè(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Ý…É¹¥¹œ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰¡¥ µÍ•Ù•É¥Ñäµ½¹¥Ñ½É¥¹œ…±•ÉÐÝ…ÌÍ…Ù•°€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰‰ÕÐ¥ÑÌ•µ…¥°½Õ±¹½Ð‰”‘•±¥Ù•É•¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€¥˜µ½¹¥Ñ½É}…±•ÉÑÌè(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹Ý…É¹¥¹œ (€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰íÉ½Ü¹•Ð 5A8œ°€œœ¥ôè€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¬€ˆð€ˆ¹©½¥¸¡µ½¹¥Ñ½É}…±•ÉÑÌ¤(€€€€€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€µ½¹¥Ñ½É}É•½É‘Ì¹…ÁÁ•¹¡ÕÉÉ•¹Ñ}Í¹…ÁÍ¡½Ð¤((€€€€€€€€€€€€€€€¥˜µ½¹¥Ñ½É}É•½É‘Ì…¹¹½ÐÍ…Ù•}µ½¹¥Ñ½É}¡¥ÍÑ½Éä¡ÍÕÁ…‰…Í”°µ½¹¥Ñ½É}É•½É‘Ì¤è(€€€€€€€€€€€€€€€€€€€ÍÐ¹Ý…É¹¥¹œ (€€€€€€€€€€€€€€€€€€€€€€€€‰e½ÕÈ	=4…¹…±åÍ¥ÌÝ…ÌÍ…Ù•°‰ÕÐµ½¹¥Ñ½É¥¹œ¡¥ÍÑ½Éä½Õ±¹½Ð‰”ÕÁ‘…Ñ•¸€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€‰e½Ô…¸ÍÑ¥±°½Á•¸…¹‘½Ý¹±½…Ñ¡”É•Á½ÉÐ¸ˆ(€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€¥˜…±•ÉÑ}É•½É‘Ìè(€€€€€€€€€€€€€€€€€€€¥˜¹½ÐÍ…Ù•}µ½¹¥Ñ½É}…±•ÉÑÌ¡ÍÕÁ…‰…Í”°…±•ÉÑ}É•½É‘Ì¤è(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹•ÉÉ½È ‰½Õ±¹½ÐÍ…Ù”µ½¹¥Ñ½È…±•ÉÑÌ¸e½ÕÈ	=4…¹…±åÍ¥ÌÝ…ÌÍ…Ù•¸ˆ¤((€€€€€€€€€€€€€€€¹•Ý}ÕÁ±½…‘}½Õ¹Ð€ôµ½¹Ñ¡±å}ÕÁ±½…‘}½Õ¹Ð€¬€ À¥˜}½¹•}Ñ¥µ•}‰±½­•‘}Á±…¸•±Í”€Ä¤((€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€ÍÕÁ…‰…Í”¹Ñ…‰±” ‰ÕÍ•ÉÌˆ¤¹ÕÁ‘…Ñ” (€€€€€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰µ½¹Ñ¡±å}ÕÁ±½…‘}½Õ¹Ðˆè¹•Ý}ÕÁ±½…‘}½Õ¹Ð(€€€€€€€€€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€€€€€€¤¹•Ä (€€€€€€€€€€€€€€€€€€€€€€€€‰¥ˆ°(€€€€€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}ÕÍ•Él‰¥‰t(€€€€€€€€€€€€€€€€€€€€¤¹•á•ÕÑ” ¤((€€€€€€€€€€€€€€€€€€€µ½¹Ñ¡±å}ÕÁ±½…‘}½Õ¹Ð€ô¹•Ý}ÕÁ±½…‘}½Õ¹Ð((€€€€€€€€€€€€€€€•á•ÁÐá•ÁÑ¥½¸…Ì”è(€€€€€€€€€€€€€€€€€€€ÍÐ¹Ý…É¹¥¹œ¡˜‰¹…±åÍ¥Ì½µÁ±•Ñ•°‰ÕÐÕÁ±½…½Õ¹Ð½Õ±¹½Ð‰”ÕÁ‘…Ñ•èí•ôˆ¤((€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…¹…±åÍ¥Í}Í…Ù•‰t€ôQÉÕ”(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰Í¡½Ý}…¹…±åÍ¥Í}ÍÕ•ÍÍ|Èåˆ‰t€ôQÉÕ”(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰±…ÍÑ}Í…Ù•‘}…¹…±åÍ¥Í}¥‰t€ô…¹…±åÍ¥Í}¥(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰±…ÍÑ}Í…Ù•‘}…¹…±åÍ¥Í}…Ð‰t€ô‘…Ñ•Ñ¥µ”¹¹½Ü¡Ñ¥µ•é½¹”¹ÕÑŒ¤¹¥Í½™½Éµ…Ð ¤(€€€€€€€€€€€€€€€™½È}Á•¹‘¥¹}­•ä¥¸€ (€€€€€€€€€€€€€€€€€€€€‰…‘¥Ù½É}½¹•}Ñ¥µ•}Á•¹‘¥¹}Í½ÕÉ•}™¥±•¹…µ”ˆ°(€€€€€€€€€€€€€€€€€€€€‰…‘¥Ù½É}½¹•}Ñ¥µ•}Á•¹‘¥¹}ÁÉ½©•Ñ}¹…µ”ˆ°(€€€€€€€€€€€€€€€€€€€€‰…‘¥Ù½É}½¹•}Ñ¥µ•}Á•¹‘¥¹}‰½µ}¹…µ”ˆ°(€€€€€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À¡}Á•¹‘¥¹}­•ä°9½¹”¤(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}¥¹}ÁÉ½É•ÍÌˆ°9½¹”¤(€€€€€€€€€€€€€€€™¥¹¥Í¡}…ÁÁÉ½Ù•‘}‰½µ}ÍÕ‰µ¥ÍÍ¥½¸¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¤(€€€€€€€€€€€€€€€Í…Ù•‘}‰½µ}É•ÉÕ¹}½µÁ±•Ñ•€ô‰½½° (€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰…‘¥Ù½É}Í…Ù•‘}‰½µ}É•ÉÕ¹}…Ñ¥Ù”ˆ°…±Í”¤(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰Á•¹‘¥¹}…ÁÁ}µ½‘”‰t€ô€ (€€€€€€€€€€€€€€€€€€€€‰	=4M•ÑÑ¥¹Ìˆ¥˜Í…Ù•‘}‰½µ}É•ÉÕ¹}½µÁ±•Ñ••±Í”€‰	=4¹…±åé•Èˆ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…ÁÁ}µ½‘”‰t€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰Á•¹‘¥¹}…ÁÁ}µ½‘”‰t(€€€€€€€€€€€€€€€¥˜Í…Ù•‘}‰½µ}É•ÉÕ¹}½µÁ±•Ñ•è(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}‰½µ}É•ÉÕ¹}½µÁ±•Ñ•}¹½Ñ¥”‰t€ôì(€€€€€€€€€€€€€€€€€€€€€€€€‰…¹…±åÍ¥Í}¥ˆèÍÑÈ¡…¹…±åÍ¥Í}¥¤°(€€€€€€€€€€€€€€€€€€€€€€€€‰ÁÉ½©•Ñ}¹…µ”ˆèÍÑÈ¡ÁÉ½©•Ñ}¹…µ”½È€‰•¹•É…°ˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€‰‰½µ}¹…µ”ˆèÍÑÈ¡‰½µ}¹…µ”½È…¹…±åÍ¥Í}¹…µ”½È€‰UÁ‘…Ñ•	=4ˆ¤°(€€€€€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰…‘¥Ù½É}‰½µ}Á¥Á•±¥¹•}…Ñ¥Ù”ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰‰½´á}…¹…±åÍ¥Í}ÕÁ±½…‘}™¥±”ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}‰½µ}ÕÁ±½…‘}½Á•¸‰t€ô…±Í”(€€€€€€€€€€€€€€€€€€€ÍÐ¹Ñ½…ÍÐ ‰UÁ‘…Ñ•	=4…¹…±åÍ¥Ì¥ÌÉ•…‘ä¸e½×ŠeÉ”‰…¬¥¸Ñ¡”	=4•‘¥Ñ½È¸ˆ°¥½¸ô‹Šrˆ¤(€€€€€€€€€€€€€€€€€€€¹…Ù¥…Ñ•}Ñ¼ (€€€€€€€€€€€€€€€€€€€€€€€€‰	=4M•ÑÑ¥¹Ìˆ°(€€€€€€€€€€€€€€€€€€€€€€€Í…Ù•‘}‰½µ}¥õÍÑÈ¡…¹…±åÍ¥Í}¥¤°(€€€€€€€€€€€€€€€€€€€€€€€Í…Ù•‘}‰½µ}…Ñ¥½¸ô‰½Á•¸ˆ°(€€€€€€€€€€€€€€€€€€€€€€€…Éµ}½Á•¹¥¹œõ…±Í”°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€Œ¹•ÜÕÁ±½…½Á•¹Ì¥ÑÌÉ•ÍÕ±Ð‘¥É•Ñ±ä¸M…Ù•µ	=4É•ÉÕ¹Ì(€€€€€€€€€€€€€€€€€€€€ŒÉ•ÑÕÉ¸Ñ¼Ñ¡•¥È•‘¥Ñ½È…¹±•…Ù”É•Á½ÉÐ¹…Ù¥…Ñ¥½¸•áÁ±¥¥Ð¸(€€€€€€€€€€€€€€€€€€€ÍÐ¹Ñ½…ÍÐ ‰¹…±åÍ¥Ì½µÁ±•Ñ”¸=Á•¹¥¹œå½ÕÈ	=4…¹…±åÍ¥ÏŠ˜ˆ°¥½¸ô‹Šrˆ¤(€€€€€€€€€€€€€€€¥˜}½¹•}Ñ¥µ•}‰±½­•‘}Á±…¸…¹¹½ÐÍ…Ù•‘}‰½µ}É•ÉÕ¹}½µÁ±•Ñ•è(€€€€€€€€€€€€€€€€€€€¹…Ù¥…Ñ•}Ñ¼ ‰¹…±åÍ¥Ì•Ñ…¥±Ìˆ°…¹…±åÍ¥Í}¥õÍÑÈ¡…¹…±åÍ¥Í}¥¤¤(€€€€€€€€€€€€€€€€ŒQ¡”M…Ù•	=45…¹…•ÈÝ…ÌÉ•¹‘•É••…É±¥•È¥¸Ñ¡¥ÌÍÉ¥ÁÐÉÕ¸(€€€€€€€€€€€€€€€€Œ™É½´ÁÉ”µÍ…Ù”¡¥ÍÑ½Éä¸I•‰Õ¥±½¹”…™Ñ•ÈÁ•ÉÍ¥ÍÑ•¹”Í¼Ñ¡”(€€€€€€€€€€€€€€€€Œ¹•Ü…¹…±åÍ¥Ì…ÁÁ•…ÉÌ¥µµ•‘¥…Ñ•±ä¸…¹…±åÍ¥Í}Í…Ù•ÁÉ•Ù•¹ÑÌ„(€€€€€€€€€€€€€€€€Œ‘ÕÁ±¥…Ñ”¥¹Í•ÉÐ½¸Ñ¡”É•ÉÕ¸¸(€€€€€€€€€€€€€€€ÍÐ¹É•ÉÕ¸ ¤(€€€€€€€¥˜€‰É•ÍÕ±ÑÍ}‘˜ˆ¥¸ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”è(€€€€€€€€€€€É•ÍÕ±ÑÍ}‘˜€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰É•ÍÕ±ÑÍ}‘˜‰t((€€€€€€€€€€€¥˜ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰Í¡½Ý}…¹…±åÍ¥Í}ÍÕ•ÍÍ|Èåˆˆ¤…¹ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰…¹…±åÍ¥Í}¥ˆ¤è(€€€€€€€€€€€€€€€}¡¥ €ô±•¸¡É•ÍÕ±ÑÍ}‘™mÉ•ÍÕ±ÑÍ}‘™l‰I¥Í¬1•Ù•°‰t€ôô€‰!¥ ‰t¤(€€€€€€€€€€€€€€€}µ•‘¥Õ´€ô±•¸¡É•ÍÕ±ÑÍ}‘™mÉ•ÍÕ±ÑÍ}‘™l‰I¥Í¬1•Ù•°‰t€ôô€‰5•‘¥Õ´‰t¤(€€€€€€€€€€€€€€€É•¹‘•É}…¹…±åÍ¥Í}ÍÕ•ÍÌ (€€€€€€€€€€€€€€€€€€€ÁÉ½©•Ñ}¹…µ”õ…¹…±åÍ¥Í}¹…µ”½È€‰	=4…¹…±åÍ¥Ìˆ°(€€€€€€€€€€€€€€€€€€€Ñ½Ñ…±}Á…ÉÑÌõ±•¸¡É•ÍÕ±ÑÍ}‘˜¤°(€€€€€€€€€€€€€€€€€€€¡¥¡}½Õ¹Ðõ}¡¥ °(€€€€€€€€€€€€€€€€€€€µ•‘¥Õµ}½Õ¹Ðõ}µ•‘¥Õ´°(€€€€€€€€€€€€€€€€€€€¡•…±Ñ¡}Í½É”õÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰¡•…±Ñ¡}Í½É”ˆ¤°(€€€€€€€€€€€€€€€€€€€…¹…±åÍ¥Í}¥õÍÑÈ¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰…¹…±åÍ¥Í}¥ˆ¤¤°(€€€€€€€€€€€€€€€€€€€¹••‘Í}Ù•É¥™¥…Ñ¥½¹}½Õ¹Ðõ¥¹Ð (€€€€€€€€€€€€€€€€€€€€€€€€¡É•ÍÕ±ÑÍ}‘™l‰I¥Í¬1•Ù•°‰t€ôô€‰9••‘ÌÙ•É¥™¥…Ñ¥½¸ˆ¤¹ÍÕ´ ¤(€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€Í½ÕÉ•}™¥±•¹…µ”õÍ½ÕÉ•}™¥±•¹…µ”°(€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€É•Ù¥•Ý•‘}½µÁ½¹•¹Ñ}­•åÌ€ôÉ•¹‘•É}™¥ÉÍÑ}…¹…±åÍ¥Í}‰É¥•˜ (€€€€€€€€€€€€€€€É•ÍÕ±ÑÍ}‘˜°(€€€€€€€€€€€€€€€¡•…±Ñ¡}Í½É”õÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰¡•…±Ñ¡}Í½É”ˆ¤°(€€€€€€€€€€€€€€€…¹…±åÍ¥Í}¥õÍÑÈ¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰…¹…±åÍ¥Í}¥ˆ¤½È€ˆˆ¤½È9½¹”°(€€€€€€€€€€€€€€€ÁÉ½©•Ñ}¹…µ”õ…¹…±åÍ¥Í}¹…µ”½È€‰	=4…¹…±åÍ¥Ìˆ°(€€€€€€€€€€€€¤((€€€€€€€€€€€‘•¥Í¥½¹}…¡•}­•ä€ô‘•¥Í¥½¹}‰É¥•™}…¡•}­•ä (€€€€€€€€€€€€€€€Í•ÍÍ¥½¹}­•äõÍÑÈ¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰…¹…±åÍ¥Í}¥ˆ¤½È€‰±¥Ù”ˆ¤(€€€€€€€€€€€€¤(€€€€€€€€€€€‘•¥Í¥½¹}‰É¥•˜€ô•Ñ}…¡•‘}‘•¥Í¥½¹}‰É¥•˜¡‘•¥Í¥½¹}…¡•}­•ä¤(€€€€€€€€€€€¥˜‘•¥Í¥½¹}‰É¥•˜¥Ì9½¹”è(€€€€€€€€€€€€€€€‘•¥Í¥½¹}‰É¥•˜€ô‰Õ¥±‘}•¹¥¹••É¥¹}‘•¥Í¥½¹}‰É¥•˜ (€€€€€€€€€€€€€€€€€€€É•ÍÕ±ÑÍ}‘˜õÉ•ÍÕ±ÑÍ}‘˜°(€€€€€€€€€€€€€€€€€€€¡•…±Ñ¡}Í½É”õÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰¡•…±Ñ¡}Í½É”ˆ¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€…¡•}‘•¥Í¥½¹}‰É¥•˜¡‘•¥Í¥½¹}…¡•}­•ä°‘•¥Í¥½¹}‰É¥•˜¤(€€€€€€€€€€€Ý¥Ñ ÍÐ¹•áÁ…¹‘•È ‰¹¥¹••É¥¹œ‘•¥Í¥½¹Ì…¹É•½µµ•¹‘…Ñ¥½¹Ìˆ°•áÁ…¹‘•õ…±Í”¤è(€€€€€€€€€€€€€€€É•¹‘•É}•¹¥¹••É¥¹}‘•¥Í¥½¹}‰É¥•˜¡‘•¥Í¥½¹}‰É¥•˜¤((€€€€€€€€€€€Ý¥Ñ ÍÐ¹•áÁ…¹‘•È ‰A½ÉÑ™½±¥¼…¹…±åÑ¥Ìˆ°•áÁ…¹‘•õ…±Í”¤è(€€€€€€€€€€€€€€€Í¡½Ý}‘…Í¡‰½…É‘}ÍÕµµ…Éä¡É•ÍÕ±ÑÍ}‘˜¤((€€€€€€€€€€€É•ÍÕ±ÑÍ}‘™l‰I¥Í¬1•Ù•°¥ÍÁ±…ä‰t€ôÉ•ÍÕ±ÑÍ}‘™l‰I¥Í¬1•Ù•°‰t¹…ÁÁ±ä¡É¥Í­}‰…‘”¤((€€€€€€€€(€€€€€€€€€€€ÍÐ¹µ…É­‘½Ý¸ œñ‘¥Ø¥ô‰‘•Ñ…¥±•µÉ¥Í¬µÉ•Á½ÉÐˆøð½‘¥Øøœ°Õ¹Í…™•}…±±½Ý}¡Ñµ°õQÉÕ”¤(€€€€€€€€€€€ÍÐ¹ÍÕ‰¡•…‘•È ‰½µÁ½¹•¹ÐÉ•¥ÍÑ•Èˆ¤((€€€€€€€€€€€É¥Í­}™¥±Ñ•È€ôÍÐ¹Í•±•Ñ‰½à (€€€€€€€€€€€€€€€€‰¥±Ñ•È‰äÉ¥Í¬±•Ù•°ˆ°(€€€€€€€€€€€€€€€l‰±°ˆ°€‰!¥ ˆ°€‰5•‘¥Õ´ˆ°€‰1½Üˆ°€‰9••‘ÌÙ•É¥™¥…Ñ¥½¸‰t°(€€€€€€€€€€€€€€€­•äô‰‰½´àÅ}‘•Ñ…¥±•‘}É¥Í­}™¥±Ñ•Èˆ°(€€€€€€€€€€€€¤((€€€€€€€€€€€Í•…É¡}Ñ•É´€ôÍÐ¹Ñ•áÑ}¥¹ÁÕÐ ‰M•…É ‰äÁ…ÉÐ¹Õµ‰•Èˆ¤((€€€€€€€€€€€™¥±Ñ•É•‘}‘˜€ôÉ•ÍÕ±ÑÍ}‘˜¹½Áä ¤((€€€€€€€€€€€¥˜É¥Í­}™¥±Ñ•È€„ô€‰±°ˆè(€€€€€€€€€€€€€€€™¥±Ñ•É•‘}‘˜€ô™¥±Ñ•É•‘}‘™m™¥±Ñ•É•‘}‘™l‰I¥Í¬1•Ù•°‰t€ôôÉ¥Í­}™¥±Ñ•Ét((€€€€€€€€€€€¥˜Í•…É¡}Ñ•É´è(€€€€€€€€€€€€€€€™¥±Ñ•É•‘}‘˜€ô™¥±Ñ•É•‘}‘™l(€€€€€€€€€€€€€€€€€€€™¥±Ñ•É•‘}‘™l‰5A8‰t¹…ÍÑåÁ”¡ÍÑÈ¤¹ÍÑÈ¹½¹Ñ…¥¹Ì¡Í•…É¡}Ñ•É´°…Í”õ…±Í”°¹„õ…±Í”¤(€€€€€€€€€€€€€€€€€€€ð™¥±Ñ•É•‘}‘™l‰9½Éµ…±¥é•5A8‰t¹…ÍÑåÁ”¡ÍÑÈ¤¹ÍÑÈ¹½¹Ñ…¥¹Ì¡Í•…É¡}Ñ•É´°…Í”õ…±Í”°¹„õ…±Í”¤(€€€€€€€€€€€€€€€t((€€€€€€€€€€€™¥±Ñ•É•‘}‘˜€ô™¥±Ñ•É•‘}‘˜¹Í½ÉÑ}Ù…±Õ•Ì¡‰äô‰I¥Í¬M½É”ˆ°…Í•¹‘¥¹œõ…±Í”¤((€€€€€€€€€€€™É½´ÍÉŒ¹Õ¤¹…ÁÁÉ½Ù•‘}Á…•Ì¥µÁ½ÉÐÉ•¹‘•É}‰½µ}½µÁ½¹•¹Ñ}Ñ…‰±”(€€€€€€€€€€€É•¹‘•É}‰½µ}½µÁ½¹•¹Ñ}Ñ…‰±”¡™¥±Ñ•É•‘}‘˜¤((€€€€€€€€€€€‘•˜}É•Ù¥•Ý•‘}Á…ÉÑ}­•ä¡Ù…±Õ”¤€´øÍÑÈè(€€€€€€€€€€€€€€€¥˜Ù…±Õ”¥Ì9½¹”è(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸€ˆˆ(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€¥˜Á¹¥Í¹„¡Ù…±Õ”¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸€ˆˆ(€€€€€€€€€€€€€€€•á•ÁÐ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€€€€€€€€€€€€€Á…ÍÌ(€€€€€€€€€€€€€€€É•ÑÕÉ¸€ˆˆ¹©½¥¸¡ÍÑÈ¡Ù…±Õ”¤¹…Í•™½± ¤¹ÍÁ±¥Ð ¤¤((€€€€€€€€€€€‘•˜}¥Í}É•Ù¥•Ý•‘}½µÁ½¹•¹Ð¡É½Ü¤€´ø‰½½°è(€€€€€€€€€€€€€€€™½È½±Õµ¸¥¸€ ‰5A8ˆ°€‰9½Éµ…±¥é•5A8ˆ¤è(€€€€€€€€€€€€€€€€€€€­•ä€ô}É•Ù¥•Ý•‘}Á…ÉÑ}­•ä¡É½Ü¹•Ð¡½±Õµ¸¤¤(€€€€€€€€€€€€€€€€€€€¥˜­•ä…¹­•ä¥¸É•Ù¥•Ý•‘}½µÁ½¹•¹Ñ}­•åÌè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸QÉÕ”(€€€€€€€€€€€€€€€É•ÑÕÉ¸…±Í”((€€€€€€€€€€€‘•Ñ…¥±}‘˜€ô™¥±Ñ•É•‘}‘™l(€€€€€€€€€€€€€€€ù™¥±Ñ•É•‘}‘˜¹…ÁÁ±ä¡}¥Í}É•Ù¥•Ý•‘}½µÁ½¹•¹Ð°…á¥ÌôÄ¤(€€€€€€€€€€€t(€€€€€€€€€€€¥˜¹½Ð‘•Ñ…¥±}‘˜¹•µÁÑäè(€€€€€€€€€€€€€€€ÍÐ¹ÍÕ‰¡•…‘•È ‰A…ÉÐ•Ñ…¥±Ìˆ¤(€€€€€€€€€€€€€€€ÍÐ¹…ÁÑ¥½¸ ‰áÁ…¹„½µÁ½¹•¹ÐÑ¼É•Ù¥•Ü¥ÑÌÍÕÁÁ±¥•È°±¥™•å±”°ÍÑ½¬°…¹•Ù¥‘•¹”‘•Ñ…¥±Ì¸ˆ¤(€€€€€€€€€€€€€€€™É½´ÍÉŒ¹…±Ñ•É¹…Ñ•}É•™•É•¹•}Á…ÉÍ•È¥µÁ½ÉÐ•áÑÉ…Ñ}‘•ÍÉ¥ÁÑ¥½¹}…±Ñ•É¹…Ñ•Ì(€€€€€€€€€€€€€€€™½È|°É½Ü¥¸‘•Ñ…¥±}‘˜¹¥Ñ•ÉÉ½ÝÌ ¤è((€€€€€€€€€€€€€€€€€€€É¥Í­}É•…Í½¹Ì€ômt((€€€€€€€€€€€€€€€€€€€ÍÑ½­}Ù…±Õ”€ôÉ½Ü¹•Ð ‰MÑ½¬Ù…¥±…‰±”ˆ¤(€€€€€€€€€€€€€€€€€€€¥˜‰½½°¡É½Ü¹•Ð ‰MÕÁÁ±¥•È…Ñ„Y•É¥™¥•ˆ°…±Í”¤¤…¹Á¹¹½Ñ¹„¡ÍÑ½­}Ù…±Õ”¤…¹™±½…Ð¡ÍÑ½­}Ù…±Õ”¤€ôô€Àè(€€€€€€€€€€€€€€€€€€€€€€€É¥Í­}É•…Í½¹Ì¹…ÁÁ•¹ ‰9¼½¸µ¡…¹ÍÑ½¬Ý…ÌÉ•Á½ÉÑ•‰äÑ¡”¡•­•ÍÕÁÁ±¥•ÉÌˆ¤((€€€€€€€€€€€€€€€€€€€ÍÕÁÁ±¥•É}½Õ¹Ñ}Ù…±Õ”€ôÉ½Ü¹•Ð ‰MÕÁÁ±¥•È½Õ¹Ðˆ¤(€€€€€€€€€€€€€€€€€€€¥˜Á¹¹½Ñ¹„¡ÍÕÁÁ±¥•É}½Õ¹Ñ}Ù…±Õ”¤…¹¥¹Ð¡ÍÕÁÁ±¥•É}½Õ¹Ñ}Ù…±Õ”¤€ôô€Äè(€€€€€€€€€€€€€€€€€€€€€€€É¥Í­}É•…Í½¹Ì¹…ÁÁ•¹ ‰=¹±ä½¹”¡•­•ÍÕÁÁ±¥•È±¥ÍÑÌÑ¡¥ÌÁ…ÉÐˆ¤((€€€€€€€€€€€€€€€€€€€±¥™•å±•}Ñ•áÐ€ôÍÑÈ¡É½Ýl‰1¥™•å±”MÑ…ÑÕÌ‰t¤¹±½Ý•È ¤((€€€€€€€€€€€€€€€€€€€¥˜€‰½‰Í½±•Ñ”ˆ¥¸±¥™•å±•}Ñ•áÐè(€€€€€€€€€€€€€€€€€€€€€€€É¥Í­}É•…Í½¹Ì¹…ÁÁ•¹ ‰½µÁ½¹•¹Ðµ…É­•½‰Í½±•Ñ”ˆ¤((€€€€€€€€€€€€€€€€€€€¥˜€‰Õ¹­¹½Ý¸ˆ¥¸±¥™•å±•}Ñ•áÐè(€€€€€€€€€€€€€€€€€€€€€€€É¥Í­}É•…Í½¹Ì¹…ÁÁ•¹ ‰1¥™•å±”ÍÑ…ÑÕÌÝ…Ì¹½ÐÉ•Á½ÉÑ•‰äÑ¡”µ…Ñ¡•ÍÕÁÁ±¥•Èˆ¤(€€€€€€€€€€€€€€€€€€€¥˜€‰½¹™±¥Ñ¥¹œˆ¥¸±¥™•å±•}Ñ•áÐè(€€€€€€€€€€€€€€€€€€€€€€€É¥Í­}É•…Í½¹Ì¹…ÁÁ•¹ ‰5…Ñ¡•ÍÕÁÁ±¥•ÉÌÉ•ÑÕÉ¹•½¹™±¥Ñ¥¹œ±¥™•å±”ÍÑ…ÑÕÍ•Ìˆ¤((€€€€€€€€€€€€€€€€€€€¥˜€‰É•Á±…•µ•¹Ðˆ¥¸±¥™•å±•}Ñ•áÐè(€€€€€€€€€€€€€€€€€€€€€€€É¥Í­}É•…Í½¹Ì¹…ÁÁ•¹ ‰I•Á±…•µ•¹ÐÍÕ•ÍÑ•ˆ¤((€€€€€€€€€€€€€€€€€€€Ý¥Ñ ÍÐ¹•áÁ…¹‘•È (€€€€€€€€€€€€€€€€€€€€€€€˜‰íÉ½Ýl5A8uôƒŠPíÉ½ÝlI¥Í¬1•Ù•°uôˆ(€€€€€€€€€€€€€€€€€€€€¤è((€€€€€€€€€€€€€€€€€€€€€€€¥˜É¥Í­}É•…Í½¹Ìè(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹µ…É­‘½Ý¸ ˆŒŒŒƒŠjƒ¾â<I¥Í¬É¥Ù•ÉÌˆ¤((€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹µ…É­‘½Ý¸ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€œñ‘¥Ø±…ÍÌô‰Øµ…Ñ¥½¸µ±¥ÍÐˆøœ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¬€ˆˆ¹©½¥¸¡˜œñ‘¥Ø±…ÍÌô‰Øµ…Ñ¥½¸µÉ½Üˆùí¡Ñµ°¹•Í…Á”¡ÍÑÈ¡É•…Í½¸¤¥ôð½‘¥Øøœ™½ÈÉ•…Í½¸¥¸É¥Í­}É•…Í½¹Ì¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¬€œð½‘¥Øøœ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Õ¹Í…™•}…±±½Ý}¡Ñµ°õQÉÕ”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(((€€€€€€€€€€€€€€€€€€€€€€€½°Ä°½°È€ôÍÐ¹½±Õµ¹Ì È¤((€€€€€€€€€€€€€€€€€€€€€€€Ý¥Ñ ½°Äè(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ”¡˜ˆ¨©5…¹Õ™…ÑÕÉ•Èè¨¨íÉ½Ü¹•Ð 5…¹Õ™…ÑÕÉ•Èœ°€œœ¥ôˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ”¡˜ˆ¨©1¥™•å±”MÑ…ÑÕÌè¨¨íÉ½Ü¹•Ð 1¥™•å±”MÑ…ÑÕÌœ°€œœ¥ôˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ”¡˜ˆ¨©MÑ½¬Ù…¥±…‰±”è¨¨íÉ½Ü¹•Ð MÑ½¬Ù…¥±…‰±”œ¤¥˜Á¹¹½Ñ¹„¡É½Ü¹•Ð MÑ½¬Ù…¥±…‰±”œ¤¤•±Í”€9½ÐÉ•Á½ÉÑ•ôˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ”¡˜ˆ¨©MÑ½¬Ù¥‘•¹”è¨¨íÉ½Ü¹•Ð MÑ½¬Ù¥‘•¹”œ°€9½ÐÉ•Á½ÉÑ•‰äµ…Ñ¡•ÍÕÁÁ±¥•ÉÌœ¥ôˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ”¡˜ˆ¨©MÕÁÁ±¥•È½Õ¹Ðè¨¨íÉ½Ü¹•Ð MÕÁÁ±¥•È½Õ¹Ðœ¤¥˜Á¹¹½Ñ¹„¡É½Ü¹•Ð MÕÁÁ±¥•È½Õ¹Ðœ¤¤•±Í”€9½ÐÙ•É¥™¥•ôˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ”¡˜ˆ¨©MÕÁÁ±¥•È½Ù•É…”è¨¨íÉ½Ü¹•Ð MÕÁÁ±¥•È½Ù•É…”œ¤½È€9½ÐÉ•Á½ÉÑ•ôˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ”¡˜ˆ¨©1•…Q¥µ”M½ÕÉ”è¨¨íÉ½Ü¹•Ð 1•…Q¥µ”M½ÕÉ”œ¤½È€9½ÐÉ•Á½ÉÑ•ôˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ”¡˜ˆ¨©1¥™•å±”Ù¥‘•¹”è¨¨íÉ½Ü¹•Ð 1¥™•å±”Ù¥‘•¹”MÕµµ…Éäœ¤½È€9½ÐÉ•Á½ÉÑ•ôˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜ˆ¨©Ù…¥±…‰±”MÕÁÁ±¥•ÉÌè¨¨€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰íÉ½Ü¹•Ð M½ÕÉ•ÌÙ…¥±…‰±”œ°€œœ¤½È€9½Ð…Ù…¥±…‰±”ôˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€€€€€Ý¥Ñ ½°Èè(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ”¡˜ˆ¨©I¥Í¬M½É”è¨¨íÉ½Ü¹•Ð I¥Í¬M½É”œ°€À¥ôˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ”¡˜ˆ¨©I¥Í¬1•Ù•°è¨¨íÉ½Ü¹•Ð I¥Í¬1•Ù•°œ°€œœ¥ôˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€‘•ÍÉ¥ÁÑ¥½¹}…¹‘¥‘…Ñ•Ì€ô•áÑÉ…Ñ}‘•ÍÉ¥ÁÑ¥½¹}…±Ñ•É¹…Ñ•Ì (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€É½Ü¹•Ð ‰•ÍÉ¥ÁÑ¥½¸ˆ°€ˆˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜‘•ÍÉ¥ÁÑ¥½¹}…¹‘¥‘…Ñ•Ìè(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹¥¹™¼ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰MÕÁÁ±¥•È‘•ÍÉ¥ÁÑ¥½¸µ•¹Ñ¥½¹ÌÁ½ÍÍ¥‰±”É•Á±…•µ•¹Ð¡Ì¤è€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¬€ˆ°€ˆ¹©½¥¸¡‘•ÍÉ¥ÁÑ¥½¹}…¹‘¥‘…Ñ•Ì¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¬€ˆ¸QÉ•…ÐÑ¡•Í”…ÌÕ¹Ù•É¥™¥•Í•…É ±•…‘Ì°¹½Ð…ÁÁÉ½Ù•½È™½É´µ™¥Ðµ™Õ¹Ñ¥½¸µ…Ñ¡•Ì¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€¡…Í}…±Ñ•É¹…Ñ•Ì€ôÉ½Ü¹•Ð ‰!…Ì±Ñ•É¹…Ñ•Ìˆ°…±Í”¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜ˆ¨©±Ñ•É¹…Ñ”Í•…É è¨¨íÉ½Ü¹•Ð ±Ñ•É¹…Ñ”M•…É MÑ…ÑÕÌœ¤½È€ …¹‘¥‘…Ñ•ÌÉ•ÑÕÉ¹•œ¥˜¡…Í}…±Ñ•É¹…Ñ•Ì•±Í”€9½Ð¡•­•œ¥ôˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ” ˆ¨©I¥Í¬I•…Í½¹Ìè¨¨ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹¥¹™¼¡É½Ü¹•Ð ‰I¥Í¬I•…Í½¹Ìˆ°€ˆˆ¤¤((€€€€€€€€€€€€€€€€€€€€€€€¥˜É½Ü¹•Ð ‰!…Ì±Ñ•É¹…Ñ•Ìˆ°…±Í”¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ” ˆ¨©…¹‘¥‘…Ñ”±Ñ•É¹…Ñ¥Ù•Ìè¨¨ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÍÕ•ÍÌ¡É½Ü¹•Ð ‰±Ñ•É¹…Ñ¥Ù”A…ÉÐ9Õµ‰•ÉÌˆ°€ˆˆ¤¤(€€€€€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹ÝÉ¥Ñ” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ˆ¨©…¹‘¥‘…Ñ”±Ñ•É¹…Ñ¥Ù•Ìè¨¨9¼…¹‘¥‘…Ñ•ÌÝ•É”É•ÑÕÉ¹•¸€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰M•…É ½Ù•É…”µ…ä‰”¥¹½µÁ±•Ñ”ìÉ•Ù¥•ÜÑ¡”Á…ÉÐ¥¸¥¹„É•Á±…•µ•¹Ð¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€€€€€€€€€€€€€¥˜É½Ü¹•Ð ‰AÉ½‘ÕÐUI0ˆ°€ˆˆ¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÐ¹µ…É­‘½Ý¸¡˜‰oÂ~R\=Á•¸ÍÕÁÁ±¥•ÈÁÉ½‘ÕÐÁ…•t¡íÉ½Ü¹•Ð AÉ½‘ÕÐUI0œ¥ô¤ˆ¤(((€€€€€€€€€€€™É½´¥¼¥µÁ½ÉÐ	åÑ•Í%<(€€€€€€€€€€€É•Á½ÉÑ}É•½É‘Ì€ôÉ•ÍÕ±ÑÍ}‘˜¹‘É½À (€€€€€€€€€€€€€€€½±Õµ¹Ìõl‰I¥Í¬1•Ù•°¥ÍÁ±…ä‰t°•ÉÉ½ÉÌô‰¥¹½É”ˆ(€€€€€€€€€€€€¤¹Ñ½}‘¥Ð ‰É•½É‘Ìˆ¤(€€€€€€€€€€€É•Á½ÉÑ}¥‘•¹Ñ¥Ñä€ô©Í½¸¹‘ÕµÁÌ (€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰…¹…±åÍ¥Í}¥ˆèÍÑÈ¡ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰…¹…±åÍ¥Í}¥ˆ¤½È€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€‰‰½µ}¹…µ”ˆè…¹…±åÍ¥Í}¹…µ”½È€‰	=4…¹…±åÍ¥Ìˆ°(€€€€€€€€€€€€€€€€€€€€‰Í½ÕÉ•}™¥±•¹…µ”ˆèÍ½ÕÉ•}™¥±•¹…µ”°(€€€€€€€€€€€€€€€€€€€€‰Á…ÉÑÌˆèÉ•Á½ÉÑ}É•½É‘Ì°(€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€Í½ÉÑ}­•åÌõQÉÕ”°(€€€€€€€€€€€€€€€Í•Á…É…Ñ½ÉÌô ˆ°ˆ°€ˆèˆ¤°(€€€€€€€€€€€€€€€‘•™…Õ±ÐõÍÑÈ°(€€€€€€€€€€€€¤(€€€€€€€€€€€É•Á½ÉÑ}…¡•}­•ä€ô¡…Í¡±¥ˆ¹Í¡„ÈÔØ¡É•Á½ÉÑ}¥‘•¹Ñ¥Ñä¹•¹½‘” ‰ÕÑ˜´àˆ¤¤¹¡•á‘¥•ÍÐ ¤(€€€€€€€€€€€…¡•‘}É•Á½ÉÐ€ôÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰…‘¥Ù½É}‰½µ}É•Á½ÉÑ}•á•±}…¡”ˆ¤½Èíô(€€€€€€€€€€€¥˜…¡•‘}É•Á½ÉÐ¹•Ð ‰­•äˆ¤€„ôÉ•Á½ÉÑ}…¡•}­•äè(€€€€€€€€€€€€€€€•á•±}É•Á½ÉÐ€ô	åÑ•Í%< ¤(€€€€€€€€€€€€€€€Í…Ù•}É•ÍÕ±ÑÍ}Ñ½}•á•° (€€€€€€€€€€€€€€€€€€€É•Á½ÉÑ}É•½É‘Ì°(€€€€€€€€€€€€€€€€€€€•á•±}É•Á½ÉÐ°(€€€€€€€€€€€€€€€€€€€‰½µ}¹…µ”õ…¹…±åÍ¥Í}¹…µ”½È€‰	=4…¹…±åÍ¥Ìˆ°(€€€€€€€€€€€€€€€€€€€Í½ÕÉ•}™¥±•¹…µ”õÍ½ÕÉ•}™¥±•¹…µ”°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€…¡•‘}É•Á½ÉÐ€ôì(€€€€€€€€€€€€€€€€€€€€‰­•äˆèÉ•Á½ÉÑ}…¡•}­•ä°(€€€€€€€€€€€€€€€€€€€€‰‰åÑ•Ìˆè•á•±}É•Á½ÉÐ¹•ÑÙ…±Õ” ¤°(€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ•l‰…‘¥Ù½É}‰½µ}É•Á½ÉÑ}•á•±}…¡”‰t€ô…¡•‘}É•Á½ÉÐ(€€€€€€€€€€€ÍÐ¹‘½Ý¹±½…‘}‰ÕÑÑ½¸ (€€€€€€€€€€€€€€€±…‰•°ô‰½Ý¹±½…á•°I•Á½ÉÐˆ°(€€€€€€€€€€€€€€€‘…Ñ„õ…¡•‘}É•Á½ÉÐ¹•Ð ‰‰åÑ•Ìˆ°ˆˆˆ¤°(€€€€€€€€€€€€€€€™¥±•}¹…µ”ô‰‰½µ}É¥Í­}É•Á½ÉÐ¹á±Íàˆ°(€€€€€€€€€€€€€€€µ¥µ”ô‰…ÁÁ±¥…Ñ¥½¸½Ù¹¹½Á•¹áµ±™½Éµ…ÑÌµ½™™¥•‘½Õµ•¹Ð¹ÍÁÉ•…‘Í¡••Ñµ°¹Í¡••Ðˆ°(€€€€€€€€€€€€¤((€€€€€€€€€€€¥˜ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹•Ð ‰Í¡½Ý}ÕÁÉ…‘•}µ½‘…°ˆ¤…¹¹½Ð¥Í}…‘µ¥¸è(€€€€€€€€€€€€€€€ÍÐ¹‘¥Ù¥‘•È ¤(€€€€€€€€€€€€€€€ÍÐ¹ÍÕ‰¡•…‘•È ‰UÁÉ…‘”e½ÕÈA±…¸ˆ¤(€€€€€€€€€€€€€€€ÍÐ¹¥¹™¼ ‰A…¥Á±…¹Ì…É”…Ñ¥Ù…Ñ•Ñ¡É½Õ Í•ÕÉ”MÑÉ¥Á”¡•­½ÕÐ¸ˆ¤(€€€€€€€€€€€€€€€¥˜ÍÐ¹‰ÕÑÑ½¸ ‰½µÁ…É”Á…¥Á±…¹Ìˆ°­•äô‰Í•ÕÉ•}ÕÁÉ…‘•}Ù¥•Ý}Á±…¹Ìˆ¤è(€€€€€€€€€€€€€€€€€€€ÍÐ¹Í•ÍÍ¥½¹}ÍÑ…Ñ”¹Á½À ‰Í¡½Ý}ÕÁÉ…‘•}µ½‘…°ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€¹…Ù¥…Ñ•}Ñ¼ ‰AÉ¥¥¹œˆ¤(((€€€€€€€¥˜}‰½µ}¹•Ý}…¹…±åÍ¥Í}½¹Ñ•áÐ¥Ì¹½Ð9½¹”è(€€€€€€€€€€€}‰½µ}¹•Ý}…¹…±åÍ¥Í}½¹Ñ•áÐ¹}}•á¥Ñ}|¡9½¹”°9½¹”°9½¹”¤((€€€€ŒÕÑ¡•¹Ñ¥…Ñ¥½¸Á•ÉÍ¥ÍÑ•¹”¥Ì¥¹Ñ•¹Ñ¥½¹…±±äÍ•ÍÍ¥½¸Í½Á•¥¸Ñ¡¥ÌÉ•Á…¥È¸(€€€€ŒI”µ¥¹ÑÉ½‘Õ”‘ÕÉ…‰±”Á•ÉÍ¥ÍÑ•¹”½¹±äÑ¡É½Õ „Í•ÉÙ•ÈµÍ¥‘”½!ÑÑÁ=¹±äµ•¡…¹¥Í´°(€€€€Œ¹½Ð„Ù¥Í¥‰±”MÑÉ•…µ±¥Ð½µÁ½¹•¹ÐÑ¡…Ð…¸Í¡•‘Õ±”™É½¹Ñ•¹É•ÉÕ¹Ì¸(€€€•á¥Ñ}…ÕÑ¡•¹Ñ¥…Ñ•‘}É½ÕÑ•}‰½‘ä ¤(€€€¥¹©•Ñ}Ý½É­ÍÁ…•}•½µ•ÑÉå}™¥¹…° ¤(