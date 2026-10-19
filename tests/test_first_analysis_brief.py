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

    def test_unassessed_component_card_shows_evidence_and_no_zero_score(self):
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
        self.assertEqual(reviewed, {"con-usb", "conusb"})
        self.assertIn("Not assessed", content)
        self.assertIn("Supplier coverage", content)
        self.assertIn("Verify the part match", content)
        self.assertIn("overall exposure cannot be confirmed", content)
        self.assertNotIn(">0/100<", content)

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
        self.assertIn("Supplier evidence incomplete", content)
        self.assertIn("9 remain unassessed", content)
        self.assertIn("Rated risks to review", content)
        self.assertNotIn("No critical exposure is recorded", content)

    def test_priority_card_parts_are_filtered_out_of_repeated_details_section(self):
        from pathlib import Path

        source = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn(
            "reviewed_component_keys = render_first_analysis_brief(",
            source,
        )
        self.assertIn("detail_df = filtered_df[", source)
        self.assertIn("~filtered_df.apply(_is_reviewed_component, axis=1)", source)
        self.assertIn(
            "Detailed records for components not already summarized in the priority cards.",
            source,
        )


if __name__ == "__main__":
    unittest.main()
