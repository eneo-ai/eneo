# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import TYPE_CHECKING, Optional

from intric.completion_models.infrastructure.static_prompts import (
    SET_TITLE_OF_CONVERSATION_PROMPT,
)
from intric.sessions.session import SessionUpdate

if TYPE_CHECKING:
    from uuid import UUID

    from intric.assistants.assistant_service import AssistantService
    from intric.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from intric.group_chat.application.group_chat_service import GroupChatService
    from intric.sessions.session import AskChatResponse, SessionInDB
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
    ):
        self.assistant_service = assistant_service
        self.group_chat_service = group_chat_service
        self.session_service = session_service
        self.completion_service = completion_service
        self.space_service = space_service

    async def ask_conversation(
        self,
        question: str,
        session_id: Optional["UUID"] = None,
        assistant_id: Optional["UUID"] = None,
        group_chat_id: Optional["UUID"] = None,
        file_ids: list["UUID"] = None,
        stream: bool = False,
        tool_assistant_id: Optional["UUID"] = None,
        version: int = 1,
        use_web_search: bool = False,
        require_tool_approval: bool = False,
    ) -> "AskChatResponse":
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
        if file_ids is None:
            file_ids = []

        # case 1: continuing a conversation (session_id is provided)
        if session_id:
            # get session information to determine where it belongs
            session = await self.session_service.get_session_by_uuid(session_id)

            if session.group_chat_id:
                # this is a group chat conversation
                return await self.group_chat_service.ask_group_chat(
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
                return await self.assistant_service.ask(
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
                return await self.group_chat_service.ask_group_chat(
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
                return await self.assistant_service.ask(
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

    async def set_title_of_conversation(self, session_id: "UUID") -> "SessionInDB":
        session = await self.session_service.get_session_by_uuid(session_id)
        space = await self.space_service.get_space_by_assistant(assistant_id=session.assistant.id)
        assistant = space.get_assistant(assistant_id=session.assistant.id)

        response = await self.completion_service.get_response(
            text_input="Please set the title of the conversation",
            model=assistant.completion_model,
            prompt=SET_TITLE_OF_CONVERSATION_PROMPT,
            session=session,
        )

        return await self.session_service.update_session(
            SessionUpdate(id=session_id, name=response.completion.text)
        )
