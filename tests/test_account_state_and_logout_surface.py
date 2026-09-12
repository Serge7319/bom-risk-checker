"""Account-state, plan-label, and signed-out surface contracts."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


class MonotonicOnboardingProgressTests(unittest.TestCase):
    def test_never_downgrades_completed_flags_from_session_false(self):
        from src.onboarding_service import monotonic_progress_updates

        progress = {
            "profile_completed": True,
            "workspace_completed": True,
            "first_bom_completed": True,
            "first_alternative_completed": True,
            "first_report_completed": True,
        }
        inferred = {
            "profile_completed": True,
            "workspace_completed": True,
            "first_bom_completed": True,
            "first_alternative_completed": False,
            "first_report_completed": False,  # session history empty after reload
        }
        self.assertEqual(monotonic_progress_updates(progress, inferred), {})

    def test_promotes_incomplete_flags_when_inferred_true(self):
        from src.onboarding_service import monotonic_progress_updates

        progress = {"profile_completed": False, "first_bom_completed": False}
        inferred = {"profile_completed": True, "first_bom_completed": True}
        self.assertEqual(
            monotonic_progress_updates(progress, inferred),
            {"profile_completed": True, "first_bom_completed": True},
        )


class SetupContinuationGatingTests(unittest.TestCase):
    def test_new_account_shows_continuation(self):
        from src.onboarding_service import should_show_setup_continuation

        self.assertTrue(
            should_show_setup_continuation(
                {
                    "profile_completed": False,
                    "workspace_completed": False,
                    "first_bom_completed": False,
                    "dismissed": False,
                }
            )
        )

    def test_completed_required_steps_hide_continuation(self):
        from src.onboarding_service import should_show_setup_continuation

        self.assertFalse(
            should_show_setup_continuation(
                {
                    "profile_completed": True,
                    "workspace_completed": True,
                    "first_bom_completed": True,
                    "first_alternative_completed": False,
                    "first_report_completed": False,
                    "dismissed": False,
                }
            )
        )

    def test_dismissed_returning_account_hides_continuation(self):
        from src.onboarding_service import should_show_setup_continuation

        self.assertFalse(
            should_show_setup_continuation(
                {
                    "profile_completed": False,
                    "workspace_completed": True,
                    "first_bom_completed": True,
                    "dismissed": True,
                }
            )
        )

    def test_completed_at_returning_account_hides_continuation(self):
        from src.onboarding_service import should_show_setup_continuation

        self.assertFalse(
            should_show_setup_continuation(
                {
                    "profile_completed": True,
                    "workspace_completed": True,
                    "first_bom_completed": True,
                    "completed_at": "2026-01-01T00:00:00Z",
                    "dismissed": False,
                }
            )
        )

    def test_optional_fields_do_not_appear_in_required_missing(self):
        from src.onboarding_service import required_setup_missing

        missing = required_setup_missing(
            {
                "profile_completed": True,
                "workspace_completed": True,
                "first_bom_completed": True,
            }
        )
        self.assertEqual(missing, [])
        # Phone/bio/avatar are not required keys.
        from src.onboarding_service import REQUIRED_SETUP_KEYS

        self.assertNotIn("phone", REQUIRED_SETUP_KEYS)
        self.assertNotIn("bio", REQUIRED_SETUP_KEYS)
        self.assertNotIn("avatar_url", REQUIRED_SETUP_KEYS)


class PlanLabelCanonicalOwnerTests(unittest.TestCase):
    def test_unpaid_starter_stays_usable_as_grandfathered_beta(self):
        from src.plans import PLAN_GRANDFATHERED_BETA, resolve_effective_plan

        name, expired = resolve_effective_plan({"plan": "Starter", "role": "user"})
        self.assertEqual(name, PLAN_GRANDFATHERED_BETA)
        self.assertFalse(expired)

    def test_paid_starter_requires_stripe_confirmation(self):
        from src.plans import PLAN_STARTER, resolve_effective_plan

        name, expired = resolve_effective_plan(
            {
                "plan": "Starter",
                "role": "user",
                "stripe_customer_id": "cus_paid",
                "stripe_subscription_id": "sub_paid",
                "stripe_subscription_status": "active",
            }
        )
        self.assertEqual(name, PLAN_STARTER)
        self.assertFalse(expired)

    def test_resolve_effective_plan_admin_is_enterprise(self):
        from src.plans import resolve_effective_plan

        name, _ = resolve_effective_plan({"plan": "Starter", "role": "admin"})
        self.assertEqual(name, "Enterprise")

    def test_enterprise_user_workspace_effective_plan(self):
        from src.plans import resolve_effective_plan

        name, _ = resolve_effective_plan({"plan": "Enterprise", "role": "user"})
        self.assertEqual(name, "Enterprise")

    def test_user_entitlement_and_workspace_plan_may_differ(self):
        """Product allows distinct entities: users.plan vs workspaces.plan stamp."""
        from src.plans import resolve_effective_plan

        user_plan, _ = resolve_effective_plan(
            {
                "plan": "Professional",
                "role": "user",
                "stripe_subscription_status": "active",
            }
        )
        workspace_plan_stamp = "Starter"  # create-time org stamp, not enforcement
        self.assertEqual(user_plan, "Professional")
        self.assertNotEqual(user_plan, workspace_plan_stamp)

    def test_settings_and_shell_use_selected_plan_name_literals(self):
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        shell = (ROOT / "src" / "ui" / "unified_shell.py").read_text(encoding="utf-8")
        self.assertIn("Your subscription", runtime)
        self.assertIn("selected_plan_name", runtime)
        self.assertIn('profile.get("plan", "Starter")', runtime)  # fallback only
        # Profile/Billing fact rows must prefer selected_plan_name.
        self.assertIn(
            'selected_plan_name or profile.get("plan", "Starter")',
            runtime,
        )
        self.assertIn("Subscription ·", shell)
        self.assertIn("Your subscription", shell)
        self.assertIn("Workspace plan:", runtime)
        # Shell cache key carries the same effective plan as Settings.
        self.assertIn('"plan_name": selected_plan_name', runtime)

    def test_workspace_plan_label_is_explicit_when_distinct(self):
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn("Workspace plan:", runtime)
        self.assertIn("item.get('plan')", runtime)

    def test_workspace_switch_and_reload_reuse_admit_cache_plan_owner(self):
        """Admit cache must store selected_plan_name so switch/reload stay aligned."""
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn('"plan_name": selected_plan_name', runtime)
        self.assertIn("cadivor_workspace_admit_cache", runtime)
        self.assertIn("cadivor_shell_cache", runtime)


class SignedOutShellRetireTests(unittest.TestCase):
    def test_retire_authenticated_shell_hosts_emits_marker_and_rules(self):
        import src.auth_gate as gate

        captured = []

        def _capture(html, unsafe_allow_html=False):
            captured.append(html)

        with patch.object(gate.st, "markdown", side_effect=_capture):
            gate.retire_authenticated_shell_hosts()
        blob = "\n".join(captured)
        self.assertIn('data-cadivor-signed-out-surface="1"', blob)
        self.assertIn("cadivor-authenticated-shell-retire", blob)
        self.assertIn("st-key-cv_foundation_navigation", blob)
        self.assertIn("data-cadivor-page-body", blob)
        self.assertIn("cv56-skeleton-page", blob)

    def test_paint_auth_gate_retires_shell_only_for_login_and_error(self):
        import src.auth_gate as gate

        with patch.object(gate, "retire_authenticated_shell_hosts") as retire, patch.object(
            gate, "render_full_page_gate_surface"
        ), patch.object(gate, "show_auth_ui", create=True), patch.object(
            gate.st, "markdown"
        ):
            gate.paint_auth_gate("authenticating")
            retire.assert_not_called()
            gate.paint_auth_gate("boot")
            retire.assert_not_called()
            gate.paint_auth_gate("login")
            self.assertGreaterEqual(retire.call_count, 1)
            retire.reset_mock()
            gate.paint_auth_gate("error")
            retire.assert_called()

    def test_retire_auth_gate_overlays_hides_signed_out_marker(self):
        import src.auth_gate as gate

        captured = []
        with patch.object(gate.st, "markdown", side_effect=lambda html, **k: captured.append(html)):
            gate.retire_auth_gate_overlays()
        blob = "\n".join(captured)
        self.assertIn("data-cadivor-signed-out-surface", blob)

    def test_begin_logout_clears_shell_cache_keys(self):
        import src.auth_state as auth_state

        session = {
            "cadivor_shell_cache": {"plan_name": "Enterprise"},
            "cadivor_verified_profile": {"plan": "Starter"},
            "cadivor_workspace_admit_cache": {"plan_name": "Enterprise"},
            "cadivor_foundation_shell_mounted": True,
            "user": object(),
            "access_token": "tok",
        }

        class _SS(dict):
            pass

        ss = _SS(session)
        with patch.object(auth_state, "st") as st_mod, patch.object(
            auth_state, "_clear_user_session_for_logout"
        ), patch(
            "src.auth_cookies.clear_auth_cookie"
        ), patch(
            "src.auth_cookies.get_auth_cookie_manager", return_value=MagicMock()
        ), patch.object(
            auth_state, "ThreadPoolExecutor"
        ) as exe, patch.object(
            auth_state, "log_logout_phase"
        ), patch(
            "src.auth_gate.retire_authenticated_shell_hosts"
        ) as retire:
            exe.return_value.submit = MagicMock()
            st_mod.session_state = ss
            st_mod.query_params = MagicMock()
            ss.get = ss.__getitem__
            # get with default for committed check
            def _get(key, default=None):
                return ss[key] if key in ss else default

            ss.get = _get
            auth_state.begin_logout(MagicMock(), MagicMock())
            self.assertFalse(ss.get("cadivor_foundation_shell_mounted"))
            retire.assert_called()


if __name__ == "__main__":
    unittest.main()
