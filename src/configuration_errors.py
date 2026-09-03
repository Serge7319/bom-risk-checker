"""Non-secret configuration error types shared across Cadivor modules.

This module intentionally contains no credential resolution and no secret values.
Provider and auth helpers may import ``ConfigurationError`` here so they remain
usable even when tests stub ``src.secrets`` helpers.
"""
from __future__ import annotations


class ConfigurationError(RuntimeError):
    """Raised when a required configuration variable is missing."""
