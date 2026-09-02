"""Regression coverage for durable Alternative Finder session-state persistence."""

import unittest

from src.alternative_finder_state import (
    ALT_FINDER_RESULT_KEY,
    STATUS_COMPLETED,
    STATUS_IDLE,
    alternative_search_was_attempted,
    clear_alternative_finder_search,
    complete_alternative_finder_search,
    get_active_alternative_finder_result,
    get_alternative_finder_candidates,
    get_alternative_finder_display_mpn,
    get_alternative_finder_original_data,
    get_alternative_finder_selected_candidate,
    init_alternative_finder_state,
    sanitize_for_session,
    set_alternative_finder_selected_candidate,
    should_apply_alternative_finder_prefill,
    should_start_new_alternative_search,
)


def _sample_candidates(count: int = 35) -> list[dict]:
    return [
        {
            "Alternative Part": f"CAND-{index:03d}",
            "Recommendation Score": 90 - index,
            "Classification": "Verified direct substitute",
            "Comparison Family": "Capacitor",
            "Feature Tags": {"automotive"},
        }
        for index in range(count)
    ]


class AlternativeFinderResultPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.session: dict = {}

    def test_completed_search_survives_blank_widget_rerun(self):
        complete_alternative_finder_search(
            self.session,
            entered_mpn="C0603C104K5RACTU",
            canonical_mpn="C0603C104K5RACTU",
            original_data={"manufacturer_part_number": "C0603C104K5RACTU", "package": "0603"},
            original_risk={"risk_level": "Low"},
            candidates=_sample_candidates(),
            selected_candidate_mpn="CAND-000",
        )

        self.assertEqual(
            get_alternative_finder_display_mpn(self.session, widget_value=""),
            "C0603C104K5RACTU",
        )
        self.assertEqual(len(get_alternative_finder_candidates(self.session)), 35)
        self.assertEqual(
            get_alternative_finder_original_data(self.session)["package"],
            "0603",
        )

    def test_candidate_selection_persists_across_rerun(self):
        complete_alternative_finder_search(
            self.session,
            entered_mpn="C0603C104K5RACTU",
            canonical_mpn="C0603C104K5RACTU",
            original_data={"package": "0603"},
            original_risk={},
            candidates=_sample_candidates(),
        )
        set_alternative_finder_selected_candidate(self.session, "CAND-012")

        self.assertEqual(
            get_alternative_finder_selected_candidate(
                self.session,
                fallback="CAND-000",
            ),
            "CAND-012",
        )
        active = get_active_alternative_finder_result(self.session)
        assert active is not None
        self.assertEqual(active["selected_candidate_mpn"], "CAND-012")

    def test_init_restores_completed_result_into_legacy_keys(self):
        complete_alternative_finder_search(
            self.session,
            entered_mpn="C0603C104K5RACTU",
            canonical_mpn="C0603C104K5RACTU",
            original_data={"package": "0603"},
            original_risk={},
            candidates=_sample_candidates(),
        )
        self.session.pop("suggested_alternatives")
        self.session.pop("alternative_original_lookup_part")

        init_alternative_finder_state(self.session)

        self.assertEqual(len(self.session.get("suggested_alternatives") or []), 35)
        self.assertEqual(
            self.session.get("alternative_original_lookup_part"),
            "C0603C104K5RACTU",
        )

    def test_explicit_new_search_clears_completed_result(self):
        complete_alternative_finder_search(
            self.session,
            entered_mpn="C0603C104K5RACTU",
            canonical_mpn="C0603C104K5RACTU",
            original_data={"package": "0603"},
            original_risk={},
            candidates=_sample_candidates(),
        )
        clear_alternative_finder_search(self.session)

        self.assertIsNone(get_active_alternative_finder_result(self.session))
        self.assertEqual(get_alternative_finder_candidates(self.session), [])
        self.assertEqual(self.session[ALT_FINDER_RESULT_KEY]["status"], STATUS_IDLE)

    def test_new_search_for_different_mpn_is_allowed(self):
        complete_alternative_finder_search(
            self.session,
            entered_mpn="C0603C104K5RACTU",
            canonical_mpn="C0603C104K5RACTU",
            original_data={},
            original_risk={},
            candidates=_sample_candidates(2),
        )

        self.assertTrue(
            should_start_new_alternative_search(self.session, "LM358N")
        )
        self.assertFalse(
            should_start_new_alternative_search(self.session, "C0603C104K5RACTU")
        )

    def test_prefill_does_not_clear_completed_result_for_same_mpn(self):
        complete_alternative_finder_search(
            self.session,
            entered_mpn="C0603C104K5RACTU",
            canonical_mpn="C0603C104K5RACTU",
            original_data={},
            original_risk={},
            candidates=_sample_candidates(3),
        )

        self.assertFalse(
            should_apply_alternative_finder_prefill(
                self.session,
                mpn="C0603C104K5RACTU",
                analysis_id="analysis-1",
            )
        )

    def test_sanitize_for_session_converts_sets_for_streamlit_persistence(self):
        payload = sanitize_for_session(
            {"Feature Tags": {"automotive", "high_voltage"}, "score": 90}
        )
        self.assertIsInstance(payload["Feature Tags"], list)
        self.assertEqual(sorted(payload["Feature Tags"]), ["automotive", "high_voltage"])

    def test_completed_result_retains_engineering_evidence_fields(self):
        candidates = _sample_candidates(1)
        candidates[0]["Engineering Comparison Confidence"] = 92
        candidates[0]["Supplier Relationship Confidence"] = 95
        candidates[0]["Engineering Evidence Summary"] = (
            "Engineering evidence: substantial — 7 confirmed matches, 1 field need verification"
        )
        complete_alternative_finder_search(
            self.session,
            entered_mpn="C0603C104K5RACTU",
            canonical_mpn="C0603C104K5RACTU",
            original_data={},
            original_risk={},
            candidates=candidates,
        )

        stored = get_alternative_finder_candidates(self.session)[0]
        self.assertEqual(stored["Engineering Comparison Confidence"], 92)
        self.assertEqual(stored["Supplier Relationship Confidence"], 95)
        self.assertIn("substantial", stored["Engineering Evidence Summary"])

    def test_brand_new_session_initializes_idle_alternative_finder_state(self):
        session: dict = {}

        init_alternative_finder_state(session)

        self.assertFalse(session.get("alternative_search_attempted"))
        self.assertFalse(alternative_search_was_attempted(session))
        self.assertEqual(session[ALT_FINDER_RESULT_KEY]["status"], STATUS_IDLE)
        self.assertEqual(get_alternative_finder_candidates(session), [])
        self.assertEqual(get_alternative_finder_display_mpn(session, widget_value=""), "")

        stored_candidates = get_alternative_finder_candidates(session)
        entered_results_branch = False
        entered_attempted_empty_branch = False
        if stored_candidates:
            entered_results_branch = True
        elif alternative_search_was_attempted(session):
            entered_attempted_empty_branch = True

        self.assertFalse(entered_results_branch)
        self.assertFalse(entered_attempted_empty_branch)

        init_alternative_finder_state(session)
        self.assertFalse(alternative_search_was_attempted(session))


class AlternativeFinderRuntimeContractTests(unittest.TestCase):
    def test_runtime_uses_durable_result_helpers(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py"
        ).read_text(encoding="utf-8")
        alt_section = source.split('if app_mode == "Alternative Finder":', 1)[1]
        alt_section = alt_section.split("\n    if app_mode == ", 1)[0]

        for needle in (
            "init_alternative_finder_state",
            "run_alternative_finder_search",
            "get_alternative_finder_display_mpn",
            "get_alternative_finder_candidates",
            "clear_alternative_finder_search",
            "alternative_search_was_attempted",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, alt_section)

    def test_runtime_does_not_read_alternative_search_attempted_unsafely(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py"
        ).read_text(encoding="utf-8")
        alt_section = source.split('if app_mode == "Alternative Finder":', 1)[1]
        alt_section = alt_section.split("\n    if app_mode == ", 1)[0]
        self.assertNotIn('st.session_state["alternative_search_attempted"]', alt_section)
        self.assertIn("alternative_search_was_attempted(st.session_state)", alt_section)

    def test_runtime_no_longer_gates_summary_on_widget_match(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py"
        ).read_text(encoding="utf-8")
        alt_section = source.split('if app_mode == "Alternative Finder":', 1)[1]
        alt_section = alt_section.split("\n    if app_mode == ", 1)[0]
        self.assertNotIn("lookup_matches_input", alt_section)


if __name__ == "__main__":
    unittest.main()
