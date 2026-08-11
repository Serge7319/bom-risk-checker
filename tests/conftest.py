"""Shared pytest hooks for Cadivor test isolation."""
from __future__ import annotations

import pytest


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item, nextitem) -> None:
    """Restore stubbed modules when finishing the last test in a file."""
    if nextitem is not None and nextitem.path == item.path:
        return
    from tests.ask_cadivor_streamlit_stub import restore_ask_cadivor_streamlit_modules

    restore_ask_cadivor_streamlit_modules()
