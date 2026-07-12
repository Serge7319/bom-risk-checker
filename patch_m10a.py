
"""Idempotent installer for Cadivor Milestone 10A.

Run once from the repository root:

    python patch_m10a.py

It only inserts:
1. an import for apply_milestone10a_design_system
2. one function call immediately after inject_v32_ux_css()

It does not replace or rewrite existing page logic.
"""

from pathlib import Path
import sys

APP = Path("streamlit_app.py")

IMPORT_LINE = "from src.ui.milestone10a import apply_milestone10a_design_system"
CALL_LINE = "apply_milestone10a_design_system()"


def main() -> int:
    if not APP.exists():
        print("ERROR: streamlit_app.py was not found. Run this script from the repository root.")
        return 1

    text = APP.read_text(encoding="utf-8")
    original = text

    if IMPORT_LINE not in text:
        marker = "from src.ui.framework import ("
        index = text.find(marker)
        if index >= 0:
            text = text[:index] + IMPORT_LINE + "\n" + text[index:]
        else:
            marker = "import streamlit as st"
            index = text.find(marker)
            if index < 0:
                print("ERROR: Could not find a safe import insertion point.")
                return 1
            end = text.find("\n", index)
            text = text[: end + 1] + IMPORT_LINE + "\n" + text[end + 1 :]

    if CALL_LINE not in text:
        marker = "inject_v32_ux_css()"
        index = text.find(marker)
        if index < 0:
            marker = "inject_premium_css()"
            index = text.find(marker)
        if index < 0:
            print("ERROR: Could not find the existing CSS initialization call.")
            return 1

        end = text.find("\n", index)
        text = text[: end + 1] + CALL_LINE + "\n" + text[end + 1 :]

    if text == original:
        print("Milestone 10A is already installed. No changes were needed.")
        return 0

    backup = APP.with_suffix(".py.m10a_backup")
    backup.write_text(original, encoding="utf-8")
    APP.write_text(text, encoding="utf-8")

    print("Milestone 10A installed successfully.")
    print(f"Backup created: {backup}")
    print("Updated: streamlit_app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
