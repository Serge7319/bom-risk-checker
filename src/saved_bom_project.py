"""Project grouping for a saved BOM.

A project is the optional parent stored in front of the BOM name:

    Project — BOM name

BOMs with the same project text belong to one group. The BOM name, filename,
and part records stay as they were when only the project changes.
"""

from __future__ import annotations

from typing import Any

DEFAULT_WORKSPACE_PROJECT = "General"
PROJECT_SEPARATOR = " — "
NEW_PROJECT_CHOICE = "Enter a new project"


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return text


def split_project_and_bom(row: dict[str, Any]) -> tuple[str, str]:
    """Return (project, bom name). An ungrouped analysis has an empty project."""
    stored = _clean(row.get("project_name") or row.get("name"))
    filename = _clean(row.get("filename") or row.get("source_filename"))
    if filename in {"—", "-"}:
        filename = ""
    project = ""
    bom_name = stored
    if PROJECT_SEPARATOR in stored:
        project, bom_name = [part.strip() for part in stored.split(PROJECT_SEPARATOR, 1)]
    if not bom_name:
        bom_name = filename or "Saved BOM"
    return project, bom_name


def analysis_title_for_upload(project: str, bom_name: str) -> str:
    """Store a new analysis. A blank project uses the workspace General project."""
    bom = _clean(bom_name) or "Saved BOM"
    chosen = _clean(project) or DEFAULT_WORKSPACE_PROJECT
    return f"{chosen}{PROJECT_SEPARATOR}{bom}"


def resolve_project_choice(selected: str, typed: str, *, blank_uses_general: bool) -> str:
    """Existing choice, or a typed name. A blank upload lands in General."""
    typed_name = _clean(typed)
    if typed_name:
        return typed_name
    choice = _clean(selected)
    if choice in {"", NEW_PROJECT_CHOICE}:
        return DEFAULT_WORKSPACE_PROJECT if blank_uses_general else ""
    return choice


def project_choices(rows: list[dict[str, Any]] | None) -> list[str]:
    """General, then the other project names already stored on saved BOMs."""
    found: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        project, _bom = split_project_and_bom(row)
        if project and project not in found:
            found.append(project)
    others = sorted(name for name in found if name != DEFAULT_WORKSPACE_PROJECT)
    return [DEFAULT_WORKSPACE_PROJECT, *others]


def assign_project(row: dict[str, Any], new_project: str) -> dict[str, Any]:
    """Change only the project. BOM name, filename, and part counts stay put."""
    project = _clean(new_project)
    if not project:
        raise ValueError("A project name is required.")
    _previous, bom_name = split_project_and_bom(row)
    updated = dict(row)
    updated["project_name"] = f"{project}{PROJECT_SEPARATOR}{bom_name}"
    return updated
