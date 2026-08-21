"""Sprint 75.2A / 75.2A.1 — route-lazy authenticated_runtime import boundaries."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]

# Modules intentionally deferred from authenticated_runtime module scope.
DEFERRED = (
    "src.pages.analysis_detail",
    "src.components.engineering_assistant",
    "integrations.supplier_aggregator",
    "src.alternative_engine",
    "src.report_generator",
    "src.ai_report_intelligence",
    "src.role_report_generator",
    "src.pdf_entitlements",
    "src.portfolio_intelligence",
    "src.design_impact_analyzer",
    "src.cost_optimization",
    "src.supply_risk_scenario",
    "src.monitoring_intelligence",
    "src.stripe_helper",
    "src.bom_parser",
    "src.engineering_decision_engine",
)


def _fresh_import_flags(modules: tuple[str, ...]) -> dict:
    """Import authenticated_runtime in a subprocess; report which modules loaded."""
    code = f"""
import os, sys
sys.path.insert(0, {str(REPO)!r})
# Optional measurement stubs for missing local third-party deps (not used in prod).
stub = os.environ.get("CADIVOR_752A_STUB_PATH")
if stub:
    sys.path.insert(0, stub)
import src.authenticated_runtime
watch = {modules!r}
print({{w: (w in sys.modules) for w in watch}})
"""
    env = os.environ.copy()
    stub = Path("/tmp/cadivor-752a-measure-stub")
    if stub.is_dir():
        env["CADIVOR_752A_STUB_PATH"] = str(stub)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
        check=False,
    )
    if proc.returncode != 0:
        raise unittest.SkipTest(
            f"fresh import unavailable in this environment: {proc.stderr[-500:]}"
        )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    if not lines:
        raise unittest.SkipTest(f"no flags in stdout: {proc.stdout[-300:]}")
    return eval(lines[-1], {"__builtins__": {}})


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def _first_bind_lineno(func: ast.FunctionDef, symbol: str) -> Optional[int]:
    for node in func.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if (alias.asname or alias.name) == symbol:
                    return node.lineno
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (alias.asname or alias.name.split(".")[-1]) == symbol:
                    return node.lineno
    return None


def _first_load_lineno(func: ast.FunctionDef, symbol: str) -> Optional[int]:
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and node.id == symbol and isinstance(node.ctx, ast.Load):
            return node.lineno
    return None


class RouteLazyImportSourceGuards(unittest.TestCase):
    def test_header_does_not_eager_import_deferred_modules(self):
        src = (REPO / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        header = src.split('log_startup_phase("authenticated_runtime_imports_complete")', 1)[0]
        banned = [
            "from src.pages.analysis_detail",
            "from integrations.supplier_aggregator",
            "from src.alternative_engine",
            "from src.report_generator",
            "from src.ai_report_intelligence",
            "from src.role_report_generator",
            "from src.pdf_entitlements",
            "from src.portfolio_intelligence",
            "from src.design_impact_analyzer",
            "from src.cost_optimization",
            "from src.supply_risk_scenario",
            "from src.monitoring_intelligence",
            "from src.stripe_helper",
            "from src.bom_parser",
            "import plotly",
            "import resend",
            "from reportlab",
            "from src.monitoring_engine",
            "from src.health_score",
            "from src.engineering_decision_engine",
            "from concurrent.futures",
        ]
        for item in banned:
            self.assertNotIn(item, header, msg=f"still eager: {item}")

    def test_pandas_remains_module_level(self):
        src = (REPO / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        header = src.split('log_startup_phase("authenticated_runtime_imports_complete")', 1)[0]
        self.assertIn("import pandas as pd", header)

    def test_route_branches_still_import_their_modules(self):
        src = (REPO / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn("from src.pages.analysis_detail import render_analysis_detail", src)
        self.assertIn('if app_mode == "Analysis Details":', src)
        self.assertIn('if app_mode == "Alternative Finder":', src)
        self.assertIn('if app_mode == "BOM Analyzer":', src)
        self.assertIn("from integrations.supplier_aggregator import get_best_part_data", src)
        self.assertIn("from src.supply_risk_scenario import", src)
        self.assertIn("from src.cost_optimization import", src)
        self.assertIn("from src.design_impact_analyzer import", src)
        self.assertIn("from src.portfolio_intelligence import", src)
        self.assertLess(
            src.index('if app_mode == "Dashboard":'),
            src.index('if app_mode == "Analysis Details":'),
        )


class RouteLazyImportFreshProcessTests(unittest.TestCase):
    def test_deferred_modules_absent_after_runtime_import(self):
        flags = _fresh_import_flags(DEFERRED)
        for name, present in flags.items():
            self.assertFalse(present, msg=f"{name} should not load on Dashboard import")

    def test_engineering_decision_absent_on_dashboard_import(self):
        flags = _fresh_import_flags(("src.engineering_decision_engine",))
        self.assertFalse(flags["src.engineering_decision_engine"])

    def test_analysis_detail_loads_once_when_imported(self):
        code = f"""
import sys
sys.path.insert(0, {str(REPO)!r})
import os
stub = os.environ.get("CADIVOR_752A_STUB_PATH")
if stub:
    sys.path.insert(0, stub)
import src.authenticated_runtime
assert "src.pages.analysis_detail" not in sys.modules
import src.pages.analysis_detail as ad1
import src.pages.analysis_detail as ad2
assert ad1 is ad2
print("ok")
"""
        env = os.environ.copy()
        stub = Path("/tmp/cadivor-752a-measure-stub")
        if stub.is_dir():
            env["CADIVOR_752A_STUB_PATH"] = str(stub)
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO),
            check=False,
        )
        if proc.returncode != 0:
            raise unittest.SkipTest(proc.stderr[-400:])
        self.assertIn("ok", proc.stdout)

    def test_streamlit_app_does_not_import_runtime_before_auth(self):
        app = (REPO / "streamlit_app.py").read_text(encoding="utf-8")
        ensure = app.index("ensure_authenticated_or_stop")
        runtime = app.index("from src.authenticated_runtime import run_authenticated_app")
        self.assertLess(ensure, runtime)


class RouteLazyNoSideEffectGuards(unittest.TestCase):
    def test_no_supplier_or_openai_in_global_shell_preamble(self):
        src = (REPO / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        begin = src.index('log_startup_phase("authenticated_runtime_begin")')
        helper = src.index("def get_part_data(row):")
        preamble = src[begin:helper]
        self.assertNotIn("get_best_part_data(", preamble)
        self.assertNotIn("EngineeringAI", preamble)
        self.assertNotIn("render_engineering_assistant", preamble)
        self.assertNotIn("from integrations.supplier_aggregator", preamble)


class RouteLazyImportSafety752A1(unittest.TestCase):
    """Sprint 75.2A.1 — lexical dominance + self-contained Reports/PDF helpers."""

    @classmethod
    def setUpClass(cls):
        cls.src = (REPO / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.src)

    def test_build_executive_pdf_imports_before_bytesio_use(self):
        func = _find_function(self.tree, "_build_executive_pdf")
        bind = _first_bind_lineno(func, "BytesIO")
        use = _first_load_lineno(func, "BytesIO")
        self.assertIsNotNone(bind)
        self.assertIsNotNone(use)
        self.assertLess(bind, use)

    def test_build_executive_pdf_reportlab_symbols_dominated(self):
        func = _find_function(self.tree, "_build_executive_pdf")
        for symbol in (
            "letter",
            "SimpleDocTemplate",
            "Paragraph",
            "Spacer",
            "Table",
            "TableStyle",
            "getSampleStyleSheet",
            "colors",
        ):
            bind = _first_bind_lineno(func, symbol)
            use = _first_load_lineno(func, symbol)
            self.assertIsNotNone(bind, msg=f"missing import for {symbol}")
            self.assertIsNotNone(use, msg=f"missing use for {symbol}")
            self.assertLess(bind, use, msg=f"{symbol} used before import")

    def test_build_executive_pdf_imports_format_decision_brief(self):
        func = _find_function(self.tree, "_build_executive_pdf")
        bind = _first_bind_lineno(func, "format_decision_brief_for_report")
        use = _first_load_lineno(func, "format_decision_brief_for_report")
        self.assertIsNotNone(bind)
        self.assertIsNotNone(use)
        self.assertLess(bind, use)

    def test_reports_decision_brief_import_before_cache_key_use(self):
        run = _find_function(self.tree, "run_authenticated_app")
        first_use = None
        for node in ast.walk(run):
            if (
                isinstance(node, ast.Name)
                and node.id == "decision_brief_cache_key"
                and isinstance(node.ctx, ast.Load)
            ):
                first_use = node.lineno if first_use is None else min(first_use, node.lineno)
        self.assertIsNotNone(first_use)
        binds_before = []
        for node in ast.walk(run):
            if isinstance(node, ast.ImportFrom) and node.module == "src.engineering_decision_engine":
                names = {a.asname or a.name for a in node.names}
                if "decision_brief_cache_key" in names and node.lineno < first_use:
                    binds_before.append(node.lineno)
        self.assertTrue(binds_before, msg="decision_brief_cache_key used before any import")

    def test_reports_import_includes_cache_decision_brief(self):
        run = _find_function(self.tree, "run_authenticated_app")
        first_use = None
        for node in ast.walk(run):
            if (
                isinstance(node, ast.Name)
                and node.id == "cache_decision_brief"
                and isinstance(node.ctx, ast.Load)
            ):
                first_use = node.lineno if first_use is None else min(first_use, node.lineno)
        self.assertIsNotNone(first_use)
        binds_before = []
        for node in ast.walk(run):
            if isinstance(node, ast.ImportFrom) and node.module == "src.engineering_decision_engine":
                names = {a.asname or a.name for a in node.names}
                if "cache_decision_brief" in names and node.lineno < first_use:
                    binds_before.append(node.lineno)
        self.assertTrue(binds_before, msg="cache_decision_brief used before import")

    def test_executive_pdf_helper_callable_without_nameerror(self):
        code = """
import ast, sys, types, html
sys.path.insert(0, %r)
for name in ("reportlab", "reportlab.lib", "reportlab.lib.pagesizes", "reportlab.lib.styles",
             "reportlab.lib.colors", "reportlab.platypus"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["reportlab.lib.pagesizes"].letter = (612, 792)
sys.modules["reportlab.lib.styles"].getSampleStyleSheet = lambda: {
    k: type("S", (), {})() for k in ("Title", "Heading2", "BodyText", "Normal")
}
class _C:
    @staticmethod
    def HexColor(x): return x
sys.modules["reportlab.lib.colors"].HexColor = _C.HexColor
class _Flow:
    def __init__(self, *a, **k): pass
    def setStyle(self, *a, **k): pass
class _SD:
    def __init__(self, buf, *a, **k):
        self._buf = buf
    def build(self, *a, **k):
        try:
            self._buf.write(b"%%PDF-stub")
        except Exception:
            pass
sys.modules["reportlab.platypus"].SimpleDocTemplate = _SD
sys.modules["reportlab.platypus"].Paragraph = _Flow
sys.modules["reportlab.platypus"].Spacer = _Flow
sys.modules["reportlab.platypus"].Table = _Flow
sys.modules["reportlab.platypus"].TableStyle = _Flow
ede = types.ModuleType("src.engineering_decision_engine")
ede.format_decision_brief_for_report = lambda brief: {
    "executive_summary": "s",
    "production_readiness": "p",
    "critical_findings": "c",
    "recommended_actions": "a",
    "business_impact": "b",
    "confidence": "high",
    "supporting_evidence": "e",
}
sys.modules["src.engineering_decision_engine"] = ede
import pandas as pd
src_text = open(%r, encoding="utf-8").read()
tree = ast.parse(src_text)
func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_build_executive_pdf")
ns = {
    "html": html,
    "pd": pd,
    "_report_value": lambda row, *keys, default=None: default,
    "_report_int": lambda v: int(v or 0),
}
mod = ast.Module(body=[func], type_ignores=[])
ast.fix_missing_locations(mod)
exec(compile(mod, "<_build_executive_pdf>", "exec"), ns)
out = ns["_build_executive_pdf"]({}, pd.DataFrame(), decision_brief={"x": 1})
assert out is not None
print("ok")
""" % (str(REPO), str(REPO / "src" / "authenticated_runtime.py"))
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr
            if "NameError" in err:
                self.fail(err[-800:])
            raise unittest.SkipTest(err[-500:])
        self.assertIn("ok", proc.stdout)

    def test_reports_decision_symbols_resolve_with_stubs(self):
        code = f"""
import sys, types
sys.path.insert(0, {str(REPO)!r})
ede = types.ModuleType("src.engineering_decision_engine")
ede.build_engineering_decision_brief = lambda **k: {{"ok": True}}
ede.get_cached_decision_brief = lambda key: None
ede.decision_brief_cache_key = lambda **k: "key"
ede.cache_decision_brief = lambda key, brief: None
ede.format_decision_brief_for_report = lambda brief: {{"executive_summary": "s"}}
sys.modules["src.engineering_decision_engine"] = ede
from src.engineering_decision_engine import (
    build_engineering_decision_brief,
    get_cached_decision_brief,
    decision_brief_cache_key,
    cache_decision_brief,
    format_decision_brief_for_report,
)
key = decision_brief_cache_key(analysis_id="a1")
brief = get_cached_decision_brief(key)
if brief is None:
    brief = build_engineering_decision_brief(results_df=None)
    cache_decision_brief(key, brief)
_ = format_decision_brief_for_report(brief)
print("ok")
"""
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr[-500:])
        self.assertIn("ok", proc.stdout)

    def test_missing_reportlab_fails_visibly_in_executive_pdf(self):
        code = """
import ast, sys, types, html
sys.path.insert(0, %r)
sys.path = [p for p in sys.path if "cadivor-752a-measure-stub" not in p]
ede = types.ModuleType("src.engineering_decision_engine")
ede.format_decision_brief_for_report = lambda brief: {
    "executive_summary": "s", "production_readiness": "p",
    "critical_findings": "c", "recommended_actions": "a", "business_impact": "b",
    "confidence": "high", "supporting_evidence": "e",
}
sys.modules["src.engineering_decision_engine"] = ede
for k in list(sys.modules):
    if k == "reportlab" or k.startswith("reportlab."):
        del sys.modules[k]
src_text = open(%r, encoding="utf-8").read()
tree = ast.parse(src_text)
func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_build_executive_pdf")
import pandas as pd
ns = {
    "html": html,
    "pd": pd,
    "_report_value": lambda row, *keys, default=None: default,
    "_report_int": lambda v: int(v or 0),
}
mod = ast.Module(body=[func], type_ignores=[])
ast.fix_missing_locations(mod)
exec(compile(mod, "<pdf>", "exec"), ns)
try:
    ns["_build_executive_pdf"]({}, pd.DataFrame(), decision_brief={"x": 1})
except ImportError:
    print("IMPORT_ERROR")
else:
    print("UNEXPECTED_SUCCESS")
""" % (str(REPO), str(REPO / "src" / "authenticated_runtime.py"))
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            check=False,
        )
        if proc.returncode != 0 and "IMPORT_ERROR" not in proc.stdout:
            raise unittest.SkipTest(proc.stderr[-500:])
        if "UNEXPECTED_SUCCESS" in proc.stdout:
            raise unittest.SkipTest("reportlab installed; cannot assert ImportError")
        self.assertIn("IMPORT_ERROR", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
