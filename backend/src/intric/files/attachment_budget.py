"""Attachment token-budget policy — the single source of truth.

Persistent assistant attachments ride along on every question, so they may only
consume a configurable share of the model's input window. This module is the one
place that turns a model's context size into an attachment token budget, shared
by the assembler (which advertises it to the client) and the service (which
enforces it on save) so the two can never silently disagree.
"""

from intric.main.config import get_settings


def compute_attachment_token_budget(max_input_tokens: int) -> int:
    """The maximum tokens persistent attachments may use for a model of this
    input-window size."""
    return int(get_settings().attachment_context_budget_ratio * max_input_tokens)
