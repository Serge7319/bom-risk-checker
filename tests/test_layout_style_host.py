"""Regression tests for CSS-only Streamlit elements reserving page height."""
from pathlib import Path
import ast
import re
import unittest

from src.procurement_advisor import procurement_workspace_panels_html


ROOT = Path(__file__).resolve().parents[1]
_STYLE_BLOCK = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.I | re.S)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


class LayoutStyleHostTests(unittest.TestCase):
    def test_workspace_css_collapses_only_explicitly_marked_style_hosts(self):
        css = (ROOT / "src/assets/css/premium.css").read_text(encoding="utf-8")
        self.assertIn(
            'has(style[data-cadivor-layout-style="true"])',
            css,
        )
        self.assertIn(
            'div[data-testid="stLayoutWrapper"]:has(> div[data-testid="stElementContainer"]:has(style[data-cadivor-layout-style="true"]))',
            css,
        )
        self.assertNotIn('div[data-testid="stElementContainer"]:has(style),', css)

    def test_common_stylesheet_injectors_mark_their_empty_hosts(self):
        injectors = (
            "src/ui/framework.py",
            "src/readability_system.py",
            "src/ui/design_system_v1.py",
            "src/ui/design_system_v2.py",
            "src/ui/workspace_consistency.py",
            "src/ui/premium_interaction_repair.py",
            "src/ui/unified_shell.py",
            "src/ui/core_premium_ui.py",
            "src/ui/main_transition.py",
            "src/ui/navigation.py",
        )
        for relative_path in injectors:
            with self.subTest(path=relative_path):
                source = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn('data-cadivor-layout-style="true"', source)

    def test_standalone_markdown_stylesheets_all_mark_their_hosts(self):
        """Catch page-level style blocks as well as the shared shell injectors."""
        for path in (ROOT / "src").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "st"
                    and node.func.attr == "markdown"
                    and node.args
                ):
                    continue
                argument = node.args[0]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    markup = argument.value
                elif isinstance(argument, ast.JoinedStr):
                    markup = "".join(
                        value.value if isinstance(value, ast.Constant) and isinstance(value.value, str)
                        else "__DYNAMIC__" if isinstance(value, ast.FormattedValue)
                        else ""
                        for value in argument.values
                    )
                else:
                    continue
                if "<style" not in markup.lower():
                    continue
                visible_markup = _HTML_COMMENT.sub("", _STYLE_BLOCK.sub("", markup)).strip()
                if visible_markup:
                    continue
                with self.subTest(path=path.relative_to(ROOT), line=node.lineno):
                    self.assertRegex(
                        markup,
                        r"data-cadivor-layout-style=['\"]true['\"]",
                    )

        # This helper returns a CSS-only string that is passed to st.markdown
        # indirectly, so the AST scan above cannot see its call-site content.
        report_styles = (ROOT / "src/ui/ei_bom_report.py").read_text(encoding="utf-8")
        self.assertIn('<style data-cadivor-layout-style="true">', report_styles)

    def test_procurement_panel_styles_are_not_marked_as_empty_hosts(self):
        markup = procurement_workspace_panels_html(
            {"mpn": "TPS54331D", "description": "Power controller"},
            {"Recommendation": "Complete sourcing data", "Next Step": "Confirm the quote."},
        )
        self.assertIn("<div class='cv-pa-summary'>", markup)
        self.assertIn("<div class='cv-pa-recommendation-v2'>", markup)
        self.assertNotIn('data-cadivor-layout-style="true"', markup)


if __name__ == "__main__":
    unittest.main()
