"""Utilities for masking tenant API credentials for safe display."""

from __future__ import annotations


def mask_api_key(api_key: str | None) -> str:
    """Mask an API key, preserving recognizable prefixes where helpful.

    Rules (aligned with unit test expectations):
    - Empty or very short keys (≤4 characters) return ``"***"``.
    - Keys starting with ``"sk-"`` keep that prefix (except OpenAI ``sk-proj`` keys).
    - Separators (``-`` and ``_``) are treated as word boundaries; only the trailing
      segment contributes to the suffix shown to users.
    - The final visible portion is capped at four characters and has leading
      separators trimmed (e.g. ``...xyz`` rather than ``..._xyz``).
    """

    if not api_key:
        return "***"

    raw = api_key.strip()
    if len(raw) <= 4:
        return "***"

    # Detect friendly prefix for common OpenAI-style keys.
    prefix = ""
    if raw.startswith("sk-") and not raw.startswith("sk-proj-"):
        prefix = "sk-"

    # Use the last segment after common separators for a cleaner suffix.
    suffix_source = raw
    for separator in ("-", "_"):
        if separator in suffix_source:
            suffix_source = suffix_source.rsplit(separator, 1)[-1]

    suffix = suffix_source[-4:] if len(suffix_source) > 4 else suffix_source
    suffix = suffix.lstrip("-_")

    if not suffix:
        suffix = raw[-4:]

    return f"{prefix}...{suffix}"


__all__ = ["mask_api_key"]
