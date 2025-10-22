"""Utilities for storing per-request logging context using contextvars."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict


_request_context: ContextVar[Dict[str, Any]] = ContextVar("request_context", default={})


def get_request_context() -> Dict[str, Any]:
    """Return a copy of the current request context."""
    context = _request_context.get()
    # Ensure callers cannot mutate the stored context in place
    return dict(context) if context else {}


def set_request_context(**values: Any) -> Dict[str, Any]:
    """Merge provided values into the stored context.

    Passing ``None`` clears the value for that key.
    """

    current = get_request_context()
    for key, value in values.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    _request_context.set(current)
    return current


def clear_request_context() -> None:
    """Remove all stored context for the active task."""

    _request_context.set({})
