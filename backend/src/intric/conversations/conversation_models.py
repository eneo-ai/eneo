# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from intric.main.config import get_settings
from intric.main.models import ModelId
from intric.questions.question import UseTools


class ConversationRequest(BaseModel):
    """
    A unified model for asking questions to either assistants or group chats.

    Either session_id, assistant_id, or group_chat_id must be provided.
    If session_id is provided, the conversation will continue with the existing session.

    For group chats:
    - If tools.assistants contains an assistant, that specific assistant will be targeted
      (requires the group chat to have allow_mentions=True).
    - If no assistant is targeted, the most appropriate assistant will be selected.
    """

    question: str
    session_id: Optional[UUID] = None
    assistant_id: Optional[UUID] = None
    group_chat_id: Optional[UUID] = None
    files: list[ModelId] = Field(max_length=get_settings().max_in_question, default=[])
    stream: bool = False
    tools: Optional[UseTools] = None
    use_web_search: bool = False
    require_tool_approval: bool = False

    @model_validator(mode="after")
    def validate_ids(self) -> "ConversationRequest":
        """Validate that exactly one of session_id, assistant_id, or group_chat_id is provided."""
        ids = [
            value
            for value in (self.session_id, self.assistant_id, self.group_chat_id)
            if value is not None
        ]
        if len(ids) == 0:
            raise ValueError("Provide exactly one of session_id, assistant_id, or group_chat_id.")
        if len(ids) > 1:
            raise ValueError(
                "Provide exactly one of session_id, assistant_id, or group_chat_id, not multiple."
            )
        return self
