from __future__ import annotations

from contextlib import nullcontext
import unittest
from unittest.mock import patch

import pandas as pd

from src.components import first_analysis_brief


class FirstAnalysisBriefTests(unittest.TestCase):
    def test_analysis_success_does_not_show_partial_bom_health_score(self):
        from src.components.onboarding import _analysis_health_display

        self.assertEqual(
            _analysis_health_display(91, needs_verification_count=9),
            "Needs verification",
        )
        self.assertEqual(
            _analysis_health_display(91, needs_verification_count=0),
            "91/100",
        )
        self.assertEqual(
            _analysis_health_display(None, needs_verification_count=0),
            "Needs verification",
        )

    def test_result_summary_shows_rated_and_verification_groups(self):
        rendered = []
        fake_streamlit = type(
            "FakeStreamlit",
            (),
            {
                "markdown": staticmethod(lambda body, **_kwargs: rendered.append(body)),
                "subheader": staticmethod(lambda *_args, **_kwargs: None),
                "caption": staticmethod(lambda *_args, **_kwargs: None),
                "warning": staticmethod(lambda *_args, **_kwargs: None),
                "success": staticmethod(lambda *_args, **_kwargs: None),
                "container": staticmethod(lambda **_kwargs: nullcontext()),
                "columns": staticmethod(
                    lambda *_args, **_kwargs: [nullcontext(), nullcontext()]
                ),
                "button": staticmethod(lambda *_args, **_kwargs: False),
            },
        )()

        with patch.object(first_analysis_brief, "st", fake_streamlit):
            reviewed = first_analysis_brief.render_first_analysis_brief(
                pd.DataFrame(
                    [
                        {
                            "MPN": "CON-USB",
                            "Normalized MPN": "CONUSB",
                            "Manufacturer": "Not recorded",
                            "Lifecycle Status": "Unknown",
                            "Stock Available": None,
                            "Supplier Data Verified": False,
                            "Supplier Count": 0,
                            "Lead Time Weeks": None,
                            "Risk Level": "Needs verification",
                            "Risk Score": 0,
                            "Risk Reasons": "No supplier match",
                            "Supplier Coverage": (
                                "No configured supplier returned a matching part record."
                            ),
                        }
                    ]
                ),
                health_score=91,
                analysis_id="analysis-1",
                project_name="Prototype BOM",
            )

        content = "\n".join(rendered)
        self.assertEqual(reviewed, set())
        self.assertIn("Rated components", content)
        self.assertIn("Components needing verification", content)
        self.assertIn("1 component needs verification", content)
        self.assertIn("Supplier or part-number match incomplete", content)
        self.assertIn("Verify part data", content)
        self.assertNotIn("CON-USB", content)

    def test_result_header_has_metadata_status_and_existing_navigation_actions(self):
        from src.components import onboarding

        rendered = []
        buttons = []
        fake_streamlit = type(
            "FakeStreamlit",
            (),
            {
                "markdown": staticmethod(lambda body, **_kwargs: rendered.append(body)),
                "container": staticmethod(lambda **_kwargs: nullcontext()),
                "columns": staticmethod(
                    lambda *_args, **_kwargs: [nullcontext(), nullcontext()]
                ),
                "button": staticmethod(
                    lambda label, **_kwargs: buttons.append(label) or False
                ),
            },
        )()
        with patch.object(onboarding, "st", fake_streamlit):
            onboarding.render_analysis_success(
                project_name="Prototype BOM",
                total_parts=10,
                high_count=1,
                medium_count=0,
                health_score=None,
                analysis_id="analysis-1",
                needs_verification_count=9,
                source_filename="sample_bom.xlsx",
            )

        content = "\n".join(rendered)
        self.assertIn("Overall BOM risk needs verification", content)
        self.assertIn("Prototype BOM", content)
        self.assertIn("sample_bom.xlsx", content)
        self.assertIn("9</strong><span>need verification", content)
        self.assertEqual(
            buttons,
            ["↗  Open Engineering Intelligence", "Generate detailed report"],
        )

    def test_majority_unassessed_bom_does_not_say_no_critical_exposure(self):
        rendered = []
        fake_streamlit = type(
            "FakeStreamlit",
            (),
            {
                "markdown": staticmethod(lambda body, **_kwargs: rendered.append(body)),
                "subheader": staticmethod(lambda *_args, **_kwargs: None),
                "caption": staticmethod(lambda *_args, **_kwargs: None),
                "warning": staticmethod(lambda *_args, **_kwargs: None),
                "success": staticmethod(lambda *_args, **_kwargs: None),
                "container": staticmethod(lambda **_kwargs: nullcontext()),
                "columns": staticmethod(
                    lambda *_args, **_kwargs: [nullcontext(), nullcontext()]
                ),
                "button": staticmethod(lambda *_args, **_kwargs: False),
            },
        )()
        rows = [
            {
                "MPN": "REVIEW-1",
                "Manufacturer": "Example",
                "Risk Level": "Medium",
                "Risk Score": 55,
                "Supplier Data Verified": True,
            }
        ] + [
            {
                "MPN": f"UNVERIFIED-{index}",
                "Manufacturer": "Not recorded",
                "Risk Level": "Needs verification",
                "Risk Score": 0,
                "Supplier Data Verified": False,
                "Risk Reasons": "No supplier match",
            }
            for index in range(1, 10)
        ]

        with patch.object(first_analysis_brief, "st", fake_streamlit):
            first_analysis_brief.render_first_analysis_brief(
                pd.DataFrame(rows),
                health_score=91,
                analysis_id="analysis-majority-unassessed",
                project_name="Project #1",
            )

        content = "\n".join(rendered)
        self.assertIn("9 components need verification", content)
        self.assertIn("1 medium risk", content)
        self.assertIn("Components needing verification", content)
        self.assertNotIn("No critical exposure is recorded", content)

    def test_summary_keeps_component_details_in_the_existing_register(self):
        from pathlib import Path

        source = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn(
            "reviewed_component_keys = render_first_analysis_brief(",
            source,
        )
        self.assertIn("detail_df = filtered_df[", source)
        self.assertIn("~filtered_df.apply(_is_reviewed_component, axis=1)", source)
        self.assertIn(
            "Expand a component to review its supplier, lifecycle, stock, and evidence details.",
            source,
        )


if __name__ == "__main__":
    unittest.main()
