from __future__ import annotations

from contextlib import nullcontext
import unittest
from unittest.mock import patch

import pandas as pd

from src.components import first_analysis_brief


class FirstAnalysisBriefTests(unittest.TestCase):
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
        self.assertIn("This is an evidence gap, not a low-risk result.", content)
        self.assertNotIn(">0/100<", content)

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
