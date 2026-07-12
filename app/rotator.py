"""Compatibility imports for the canonical browser backend rotator.

New code must import :mod:`app.scrapers.rotator`. This module remains so older
callers do not break while sharing exactly the same implementation and circuit
state.
"""

from .scrapers.rotator import (
    classify_backend_error,
    fetch_html,
    reset_backend_circuits,
)

__all__ = ["classify_backend_error", "fetch_html", "reset_backend_circuits"]
