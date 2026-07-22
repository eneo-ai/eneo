"""Prompt and attachment context-fit policy — the single source of truth."""

from collections.abc import Sequence

from eneo.completion_models.infrastructure.context_builder import (
    count_attachment_tokens,
    count_tokens,
)
from eneo.files.file_models import File, FileType
from eneo.main.config import get_settings
from eneo.main.exceptions import BadRequestException


def attachment_token_ceiling(max_input_tokens: int) -> int:
    """The most tokens the system prompt + attachments may use and still leave
    room to ask a question: the model's input window minus a small reserve."""
    reserve = get_settings().attachment_context_reserve_tokens
    return max(max_input_tokens - reserve, 0)


def assert_prompt_and_files_fit_context(
    *,
    max_input_tokens: int,
    model_name: str,
    prompt_text: str,
    files: Sequence[File],
) -> None:
    ceiling = attachment_token_ceiling(max_input_tokens)
    used = count_tokens(prompt_text, model_name) + count_attachment_tokens(
        text_files=[file for file in files if file.file_type == FileType.TEXT],
        image_files=[file for file in files if file.file_type == FileType.IMAGE],
        model_name=model_name,
    )
    if used > ceiling:
        raise BadRequestException(
            f"The prompt and attachments need ~{used} tokens, but only "
            f"{ceiling} fit this model's context window. Remove content or "
            f"choose a model with a larger context."
        )
