"""Helpers for temporarily stubbing ``src.secrets`` without leaking across tests.

Auth and Streamlit unit tests often replace ``sys.modules["src.secrets"]`` with a
reduced stub.  Those stubs must never persist into later modules in the same
unittest process — especially Alternative Finder imports that need the real
``get_secret`` helper.
"""
from __future__ import annotations

import sys
import types
from typing import Any, Callable


def install_src_secrets_stub(**attrs: Any) -> tuple[types.ModuleType, Callable[[], None]]:
    """Replace ``sys.modules["src.secrets"]`` with a stub and return a restorer.

    The restorer puts back the exact prior module object when one existed, or
    removes the entry when the key was previously absent.  Callers must register
    the restorer with ``addCleanup`` / ``tearDown`` so restoration runs on both
    pass and failure.
    """
    prior_present = "src.secrets" in sys.modules
    prior = sys.modules.get("src.secrets")
    stub = types.ModuleType("src.secrets")
    for name, value in attrs.items():
        setattr(stub, name, value)
    sys.modules["src.secrets"] = stub

    def restore() -> None:
        if prior_present:
            sys.modules["src.secrets"] = prior
        else:
            # Only remove our stub; do not delete a newer legitimate module that
            # another cleanup path may have already restored.
            if sys.modules.get("src.secrets") is stub:
                sys.modules.pop("src.secrets", None)

    return stub, restore


def ensure_real_src_secrets_module() -> None:
    """Drop a reduced secrets stub so the next import loads the real module.

    Stubs are ``types.ModuleType`` instances without ``__file__``.  Even stubs
    that expose ``get_secret`` must be cleared — otherwise Alternative Finder
    imports can bind to a test double instead of the real helper.
    """
    current = sys.modules.get("src.secrets")
    if current is None:
        return
    if getattr(current, "__file__", None) is None:
        sys.modules.pop("src.secrets", None)
        return
    if not hasattr(current, "get_secret") or not hasattr(current, "ConfigurationError"):
        sys.modules.pop("src.secrets", None)
