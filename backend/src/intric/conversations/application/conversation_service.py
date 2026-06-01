# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import TYPE_CHECKING, Optional

from intric.completion_models.infrastructure.context_builder import (
    build_files_string,
    count_tokens,
)
from intric.completion_models.infrastructure.static_prompts import (
    SET_TITLE_OF_CONVERSATION_PROMPT,
)
from intric.conversations.conversation_models import PreflightResponse
from intric.files.file_models import FileType
from intric.main.exceptions import BadRequestException
from intric.sessions.session import SessionUpdate

if TYPE_CHECKING:
    from uuid import UUID

    from intric.assistants.api.assistant_models import AssistantResponse
    from intric.assistants.assistant_service import AssistantService
    from intric.completion_models.domain.completion_model import CompletionModel
    from intric.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from intric.files.file_service import FileService
    from intric.group_chat.application.group_chat_service import GroupChatService
    from intric.sessions.session import SessionInDB
    from intric.sessions.session_service import SessionService
    from intric.spaces.space_service import SpaceService


class ConversationService:
    """
    Service for handling conversations with assistants and group chats.
    This service abstracts the routing logic between different conversation types.
    """

    def __init__(
        self,
        assistant_service: "AssistantService",
        group_chat_service: "GroupChatService",
        session_service: "SessionService",
        completion_service: "CompletionService",
        space_service: "SpaceService",
        file_service: "FileService",
    ) -> None:
        super().__init__()
        self.assistant_service = assistant_service
        self.group_chat_service = group_chat_service
        self.session_service = session_service
        self.completion_service = completion_service
        self.space_service = space_service
        self.file_service = file_service

    async def ask_conversation(
        self,
        question: str,
        session_id: Optional["UUID"] = None,
        assistant_id: Optional["UUID"] = None,
        group_chat_id: Optional["UUID"] = None,
        file_ids: "list[UUID] | None" = None,
        stream: bool = False,
        tool_assistant_id: Optional["UUID"] = None,
        version: int = 1,
        use_web_search: bool = False,
        require_tool_approval: bool = False,
    ) -> "AssistantResponse":
        """
        Routes a conversation request to the appropriate service based on the parameters.

        Args:
            question: The question to ask
            session_id: The existing session ID to continue a conversation, if any
            assistant_id: The assistant ID to start a new conversation with, if no session_id
            group_chat_id: The group chat ID to start a new conversation with, if no session_id
            file_ids: List of file IDs to attach to the question
            stream: Whether to stream the response
            tool_assistant_id: Optional ID of a specific assistant to target (for tools.assistants)
            version: API version

        Returns:
            The response from the appropriate service

        Raises:
            ValueError: If neither session_id, assistant_id, nor group_chat_id is provided
        """
        if not file_ids:
            file_ids = []

        if require_tool_approval and group_chat_id is not None:
            raise BadRequestException("Tool approval is not supported for group chats.")

        # case 1: continuing a conversation (session_id is provided)
        if session_id:
            # get session information to determine where it belongs
            session = await self.session_service.get_session_by_uuid(session_id)
            assert session is not None

            if session.group_chat_id:
                if require_tool_approval:
                    raise BadRequestException(
                        "Tool approval is not supported for group chats."
                    )
                # this is a group chat conversation
                return await self.group_chat_service.ask_group_chat(  # type: ignore[return-value]
                    question=question,
                    group_chat_id=session.group_chat_id,
                    file_ids=file_ids,
                    stream=stream,
                    session_id=session_id,
                    tool_assistant_id=tool_assistant_id,
                    version=version,
                )
            else:
                # this is an assistant conversation
                assert session.assistant is not None
                return await self.assistant_service.ask(  # type: ignore[return-value]
                    question=question,
                    assistant_id=session.assistant.id,
                    file_ids=file_ids,
                    stream=stream,
                    session_id=session_id,
                    tool_assistant_id=tool_assistant_id,
                    version=version,
                    use_web_search=use_web_search,
                    require_tool_approval=require_tool_approval,
                )

        # case 2: starting a new conversation
        else:
            if group_chat_id:
                # starting a new group chat conversation
                return await self.group_chat_service.ask_group_chat(  # type: ignore[return-value]
                    question=question,
                    group_chat_id=group_chat_id,
                    file_ids=file_ids,
                    stream=stream,
                    session_id=None,  # explicitly None for new conversation
                    tool_assistant_id=tool_assistant_id,
                    version=version,
                )
            elif assistant_id:
                # starting a new assistant conversation
                return await self.assistant_service.ask(  # type: ignore[return-value]
                    question=question,
                    assistant_id=assistant_id,
                    file_ids=file_ids,
                    stream=stream,
                    session_id=None,  # explicitly None for new conversation
                    tool_assistant_id=tool_assistant_id,
                    version=version,
                    use_web_search=use_web_search,
                    require_tool_approval=require_tool_approval,
                )
            else:
                # should never happen due to model validation, but just to be safe
                raise ValueError(
                    "Either session_id, assistant_id, or group_chat_id must be provided"
                )

    async def preflight_tokens(
        self,
        question: str,
        file_ids: "list[UUID]",
        session_id: Optional["UUID"] = None,
        assistant_id: Optional["UUID"] = None,
        group_chat_id: Optional["UUID"] = None,
        tool_assistant_id: Optional["UUID"] = None,
    ) -> PreflightResponse:
        """Count the tokens this request would add to context, without sending.

        Returns the exact delta: the user's text plus the JSON-wrapped text-file
        prefix that context_builder would prepend. Excludes knowledge/RAG and
        web-search content because both are selected at request time and have
        no stable cost to report up-front. Model name and context window are
        echoed so the caller can compute percentage fill without a round-trip.
        """
        model, selector_tokens = await self._resolve_preflight_model(
            question=question,
            session_id=session_id,
            assistant_id=assistant_id,
            group_chat_id=group_chat_id,
            tool_assistant_id=tool_assistant_id,
        )

        # count_tokens already returns 0 for empty input — no need to short-circuit.
        input_tokens = count_tokens(question, model.name) + selector_tokens

        file_tokens = 0
        excluded_file_count = 0
        if file_ids:
            # User-scoped lookup matches the actual chat endpoint (assistant_service.ask
            # uses get_files_by_ids), so preflight refuses files the user can't send.
            files = await self.file_service.get_files_by_ids(file_ids=file_ids)
            # Only text files reach the LLM via the input string; binary/image
            # files use provider-specific token accounting we can't preview here.
            text_files = [f for f in files if f.file_type == FileType.TEXT and f.text]
            excluded_file_count = len(files) - len(text_files)
            if text_files:
                # Mirror context_builder.build_files_string: that wrapper text
                # is what actually gets tokenized when the request runs.
                file_tokens = count_tokens(build_files_string(text_files), model.name)

        return PreflightResponse(
            input_tokens=input_tokens,
            file_tokens=file_tokens,
            excluded_file_count=excluded_file_count,
            model_name=model.name,
            context_window=model.token_limit,
        )

    async def _resolve_preflight_model(
        self,
        question: str,
        session_id: Optional["UUID"],
        assistant_id: Optional["UUID"],
        group_chat_id: Optional["UUID"],
        tool_assistant_id: Optional["UUID"] = None,
    ) -> "tuple[CompletionModel, int]":
        """Resolve the completion model the next chat request would target.

        Mirrors ask_conversation routing rules so the preflight count uses the
        same tokenizer the actual request will. Group chat auto-routing is
        selected by an LLM at send time, so preflight uses the smallest context
        window among the candidate assistants as a conservative projection.

        Raises BadRequestException for the same configurations that would fail
        on actual send (no assistants in group chat, no completion model set).
        """
        if session_id:
            session = await self.session_service.get_session_by_uuid(session_id)
            assert session is not None
            if session.group_chat_id:
                model, selector_tokens = await self._group_chat_preflight_model(
                    session.group_chat_id,
                    question=question,
                    tool_assistant_id=tool_assistant_id,
                )
            else:
                assert session.assistant is not None
                assistant, _ = await self.assistant_service.get_assistant(
                    session.assistant.id
                )
                model = assistant.completion_model
                selector_tokens = 0
        elif assistant_id:
            assistant, _ = await self.assistant_service.get_assistant(assistant_id)
            model = assistant.completion_model
            selector_tokens = 0
        elif group_chat_id:
            model, selector_tokens = await self._group_chat_preflight_model(
                group_chat_id,
                question=question,
                tool_assistant_id=tool_assistant_id,
            )
        else:
            raise BadRequestException(
                "Provide session_id, assistant_id, or group_chat_id."
            )

        if model is None:
            raise BadRequestException(
                "No completion model configured for this conversation."
            )
        return model, selector_tokens

    async def _group_chat_preflight_model(
        self,
        group_chat_id: "UUID",
        question: str,
        tool_assistant_id: Optional["UUID"] = None,
    ) -> "tuple[CompletionModel | None, int]":
        group_chat = await self.group_chat_service.get_group_chat(group_chat_id)
        if not group_chat.assistants:
            raise BadRequestException("No assistants in the group chat")

        if tool_assistant_id is not None:
            if not group_chat.allow_mentions:
                raise BadRequestException(
                    "This group chat does not allow targeting specific assistants"
                )
            selected = group_chat.get_assistant_by_id(tool_assistant_id)
            if selected is None:
                raise BadRequestException(
                    "The specified assistant is not part of this group chat"
                )
            return selected.assistant.completion_model, 0

        models = [
            group_chat_assistant.assistant.completion_model
            for group_chat_assistant in group_chat.assistants
            if group_chat_assistant.assistant.completion_model is not None
        ]
        if not models:
            return None, 0
        if len(group_chat.assistants) <= 1:
            return models[0], 0

        selector_model = await self.group_chat_service.find_suitable_completion_model(
            group_chat.assistants
        )
        if selector_model is None:
            return min(models, key=lambda model: model.token_limit), 0

        selection_prompt = self.group_chat_service.create_assistant_selection_prompt(
            question, group_chat.assistants
        )
        selector_tokens = count_tokens(selection_prompt, selector_model.name)
        return min(models, key=lambda model: model.token_limit), selector_tokens

    async def set_title_of_conversation(
        self, session_id: "UUID"
    ) -> "SessionInDB | None":
        session = await self.session_service.get_session_by_uuid(session_id)
        assert session is not None
        assert session.assistant is not None
        space = await self.space_service.get_space_by_assistant(
            assistant_id=session.assistant.id
        )
        assistant = space.get_assistant(assistant_id=session.assistant.id)
        assert assistant.completion_model is not None

        response = await self.completion_service.get_response(
            text_input="Please set the title of the conversation",
            model=assistant.completion_model,  # pyright: ignore[reportArgumentType]  # domain CompletionModel aliases ai_models one
            prompt=SET_TITLE_OF_CONVERSATION_PROMPT,
            session=session,
        )

        return await self.session_service.update_session(
            SessionUpdate(id=session_id, name=response.completion.text)  # type: ignore[union-attr]
        )
