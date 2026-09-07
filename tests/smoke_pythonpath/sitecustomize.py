"""Test-only Python path hook for auth-gate browser smoke.

The harness prepends ``tests/smoke_pythonpath`` to PYTHONPATH so this
``sitecustomize`` runs before ``streamlit_app.py``. Production never adds this
directory and therefore never loads provider doubles.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.auth_gate_smoke_adapter import install_production_path_smoke_patches

install_production_path_smoke_patches()
