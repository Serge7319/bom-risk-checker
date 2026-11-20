"""Public Nexar Supply lookup interface used by Cadivor's supplier pipeline."""
from __future__ import annotations

from integrations.octopart_client import search_octopart_by_part_number


def search_nexar_by_part_number(part_number: str) -> dict:
    """Look up an exact manufacturer part number through Nexar Supply."""
    return search_octopart_by_part_number(part_number)
