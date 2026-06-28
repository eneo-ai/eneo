# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from eneo.main.models import ModelId
from eneo.questions.question import UseTools


class _ConversationTarget(BaseModel):
    """Shared targeting fields for chat-style requests.

    Exactly one of `session_id`, `assistant_id`, or `group_chat_id` must be
    present. Centralized here so the validator stays in one place — adding a
    new target type later is a single edit.
    """

    session_id: Optional[UUID] = None
    assistant_id: Optional[UUID] = None
    group_chat_id: Optional[UUID] = None

    @model_validator(mode="after")
    def _validate_exactly_one_target(self) -> "_ConversationTarget":
        ids = [
            value
            for value in (self.session_id, self.assistant_id, self.group_chat_id)
            if value is not None
        ]
        if len(ids) == 0:
            raise ValueError(
                "Provide exactly one of session_id, assistant_id, or group_chat_id."
            )
        if len(ids) > 1:
            raise ValueError(
                "Provide exactly one of session_id, assistant_id, or group_chat_id, not multiple."
            )
        return self


# Hard cap on attachments per preflight call. Mirrors a reasonable per-message
# upload limit and bounds the DB lookup + token-counting work a single request
# can trigger. Chat itself is already bounded by file-size limits.
_MAX_FILES_PER_PREFLIGHT = 50


class PreflightRequest(_ConversationTarget):
    """Request shape for /conversations/preflight.

    Inherits the "exactly one target" rule from `_ConversationTarget`. Adds
    its own rule that at least one of `question` or `file_ids` must be
    non-empty — an empty preflight would still trigger a model lookup with
    no useful answer.
    """

    question: str = ""
    file_ids: list[UUID] = Field(default=[], max_length=_MAX_FILES_PER_PREFLIGHT)
    tools: Optional[UseTools] = None

    @model_validator(mode="after")
    def _require_question_or_files(self) -> "PreflightRequest":
        if not self.question and not self.file_ids:
            raise ValueError(
                "Preflight requires at least one of `question` or `file_ids`."
            )
        return self


class PreflightResponse(BaseModel):
    """Estimated token cost the next request will add to the context window.

    Excludes knowledge/RAG chunks and web-search results — those are selected
    at request time. Provider tokenization is authoritative and can differ from
    this local estimate, especially for multimodal inputs. The frontend pairs
    this delta with the persisted history tokens to project total context fill.

    `model_name` and `context_window` are echoed so a client can compute the
    percentage fill locally without a separate round-trip to fetch model
    metadata.

    `excluded_file_count` is the number of attached files we could not
    tokenise here (images and other binary payloads use provider-specific
    multimodal accounting). Callers should treat the response as a
    conservative lower bound when this is non-zero.
    """

    input_tokens: int
    file_tokens: int
    excluded_file_count: int = 0
    model_name: str
    context_window: int


class ConversationRequest(_ConversationTarget):
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
    files: list[ModelId] = Field(default=[])
    stream: bool = False
    tools: Optional[UseTools] = None
    use_web_search: bool = False
    require_tool_approval: bool = False
    # MCP servers the user turned off in the composer for this message. Narrows
    # the otherwise-active set (assistant's own servers, or policy-granted ones
    # for a personal assistant); it can never enable a server that isn't active.
    disabled_mcp_server_ids: list[UUID] = Field(default=[])


class ConversationRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_name(self) -> "ConversationRenameRequest":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name cannot be empty")
        return self
