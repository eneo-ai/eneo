"""Attachment context-fit policy — the single source of truth.

Persistent assistant attachments are sent whole on every question, together with
the system prompt, so they must fit the model's input window with room left to
ask. This module is the one place that turns a model's input-window size into the
ceiling that prompt + attachments may not exceed, shared by the assembler (which
advertises it to the client) and the service (which enforces it on save) so the
two can never silently disagree.
"""

from eneo.main.config import get_settings


def attachment_token_ceiling(max_input_tokens: int) -> int:
    """The most tokens the system prompt + attachments may use and still leave
    room to ask a question: the model's input window minus a small reserve."""
    reserve = get_settings().attachment_context_reserve_tokens
    return max(max_input_tokens - reserve, 0)
