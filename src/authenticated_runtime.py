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
from src.safe_diagnostics import safe_exception_frames
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
    """End the page; never leave Opening… mounted without a body reveal."""
    if st.session_state.get(DELAY_ROUTE_BODY_REVEAL_KEY):
        reveal_authenticated_page_body(
            str(
                st.session_state.get("cadivor_route")
                or st.session_state.get("app_mode")
                or ""
            ),
            force=True,
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
from src.workspace_write_scope import (
    build_workspace_payload as _build_workspace_payload,
    can_create_analysis as _can_create_analysis,
    sync_active_workspace_context as _sync_active_workspace_context,
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
            <h1 id="cadivor-maintenance-heading">We’re improving Cadivor.</h1>
            <p class="maintenance-message">{safe_message}</p>
            <div class="maintenance-assurance"><span class="maintenance-shield">&#9670;</span><span><strong>Your engineering data is safe.</strong><br/>Your workspace and saved analyses will be available again when service is restored.</span></div>
            <p class="maintenance-f