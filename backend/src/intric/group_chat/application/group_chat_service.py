# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.
import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Union

from intric.ai_models.completion_models.completion_model import Completion, ResponseType
from intric.assistants.api.assistant_models import AssistantResponse
from intric.completion_models.infrastructure.context_builder import count_tokens
from intric.group_chat.domain.entities.group_chat import (
    GroupChat,
    GroupChatAssistant,
    GroupChatAssistantData,
)
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.main.models import NOT_PROVIDED, NotProvided
from intric.questions.question import ToolAssistant, UseTools

if TYPE_CHECKING:
    from uuid import UUID

    from intric.actors import ActorManager
    from intric.assistants.assistant_service import AssistantService
    from intric.completion_models.domain.completion_model import CompletionModel
    from intric.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from intric.icons.icon_repo import IconRepository
    from intric.sessions.session import SessionInDB
    from intric.sessions.session_service import SessionService
    from intric.spaces.space_repo import SpaceRepository
    from intric.spaces.space_service import SpaceService
    from intric.users.user import UserInDB


# Strict contract with the selector model: a routing decision is the whole
# response and nothing else. Anything that isn't an exact `ASSISTANT=<n>` line
# is treated as clarification prose and surfaced to the user — including
# digits embedded in clarification text, which previously caused false-positive
# routing or crashes.
_ASSISTANT_SENTINEL = re.compile(r"\s*ASSISTANT\s*=\s*(\d+)\s*", re.IGNORECASE)


@dataclass
class GroupChatAssistantSelectionResult:
    assistant: Optional[GroupChatAssistant]
    response_str: str
    assistant_selector_tokens: int


class GroupChatService:
    def __init__(
        self,
        user: "UserInDB",
        space_service: "SpaceService",
        space_repo: "SpaceRepository",
        actor_manager: "ActorManager",
        assistant_service: "AssistantService",
        session_service: "SessionService",
        completion_service: "CompletionService",
        icon_repo: "IconRepository",
    ) -> None:
        super().__init__()
        self.user = user
        self.space_service = space_service
        self.space_repo = space_repo
        self.actor_manager = actor_manager
        self.assistant_service = assistant_service
        self.session_service = session_service
        self.completion_service = completion_service
        self.icon_repo = icon_repo

    async def create_group_chat(self, space_id: "UUID", name: str) -> "GroupChat":
        space = await self.space_service.get_space(id=space_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_create_group_chats():
            raise UnauthorizedException(
                "You do not have permission to create group chats in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "group_chat",
                    "action": "create",
                    "auth_layer": "domain_policy",
                },
            )

        group_chat = GroupChat.create(
            name=name, space_id=space_id, user_id=self.user.id
        )

        space.add_group_chat(group_chat)
        updated_space = await self.space_repo.update(space=space)

        return updated_space.get_group_chat(group_chat_id=group_chat.id)

    async def delete_group_chat(self, group_chat_id: "UUID") -> "GroupChat | None":
        space = await self.space_service.get_space_by_group_chat(
            group_chat_id=group_chat_id
        )
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_delete_group_chats():
            raise UnauthorizedException(
                "You do not have permission to delete this group chat.",
                code="forbidden_action",
                context={
                    "resource_type": "group_chat",
                    "action": "delete",
                    "auth_layer": "domain_policy",
                },
            )

        group_chat = space.get_group_chat(group_chat_id=group_chat_id)
        icon_id = group_chat.icon_id

        space.remove_group_chat(group_chat)
        await self.space_repo.update(space=space)

        if icon_id:
            await self.icon_repo.delete(icon_id)

    async def update_group_chat(
        self,
        id: "UUID",
        # TODO: should maybe be a dictionary directly instead of this thing...
        current_assistants: Optional[list["GroupChatAssistantData"]] = None,
        name: Optional[str] = None,
        allow_mentions: Optional[bool] = None,
        show_response_label: Optional[bool] = None,
        published: Optional[bool] = None,
        insight_enabled: Optional[bool] = None,
        metadata_json: Union[dict[str, object], None, NotProvided] = NOT_PROVIDED,
        icon_id: Union["UUID", None, NotProvided] = NOT_PROVIDED,
    ) -> "GroupChat":
        space = await self.space_service.get_space_by_group_chat(group_chat_id=id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_group_chats():
            raise UnauthorizedException(
                "You do not have permission to edit this group chat.",
                code="forbidden_action",
                context={
                    "resource_type": "group_chat",
                    "action": "update",
                    "auth_layer": "domain_policy",
                },
            )

        # Check if user has permission to toggle insights
        if insight_enabled is not None:
            if not actor.can_toggle_insight():
                raise UnauthorizedException("Only admins can toggle insights")

        group_chat = space.get_group_chat(group_chat_id=id)
        # If current_assistants is explicitly None, don't update assistants
        # If current_assistants is an empty list, set assistants to empty list (clear all)
        # If current_assistants has items, convert them to GroupChatAssistant objects
        if current_assistants is None:
            assistants = None
        else:
            assistants = [
                GroupChatAssistant(
                    assistant=space.get_assistant(assistant.id),
                    user_description=assistant.user_description,
                )
                for assistant in current_assistants
            ]

        group_chat.update(
            name=name,
            allow_mentions=allow_mentions,
            show_response_label=show_response_label,
            published=published,
            new_assistants=assistants,
            insight_enabled=insight_enabled,
            metadata_json=metadata_json,
            icon_id=icon_id,
        )

        updated_space = await self.space_repo.update(space=space)

        updated_group_chat = updated_space.get_group_chat(group_chat_id=id)
        updated_group_chat.permissions = actor.get_group_chat_permissions(
            group_chat=updated_group_chat
        )

        return updated_group_chat

    async def get_group_chat(
        self,
        group_chat_id: "UUID",
    ) -> "GroupChat":
        space = await self.space_service.get_space_by_group_chat(
            group_chat_id=group_chat_id
        )
        actor = self.actor_manager.get_space_actor_from_space(space)
        group_chat = space.get_group_chat(group_chat_id=group_chat_id)

        if not actor.can_read_group_chat(group_chat=group_chat):
            raise UnauthorizedException(
                "You do not have permission to read this group chat.",
                code="forbidden_action",
                context={
                    "resource_type": "group_chat",
                    "action": "read",
                    "auth_layer": "domain_policy",
                },
            )

        group_chat.permissions = actor.get_group_chat_permissions(group_chat=group_chat)

        return group_chat

    async def find_suitable_completion_model(
        self, assistants: list[GroupChatAssistant]
    ):
        """Return the completion model of the first assistant in the list"""
        if not assistants:
            raise BadRequestException("No assistants in the group chat")

        # Use the completion model of the first assistant
        first_assistant = assistants[0].assistant
        return first_assistant.completion_model

    async def _find_suitable_completion_model(
        self, assistants: list[GroupChatAssistant]
    ):
        return await self.find_suitable_completion_model(assistants)

    def create_assistant_selection_prompt(
        self, question: str, assistants: list[GroupChatAssistant]
    ) -> str:
        """Create a prompt for the model to select the most appropriate assistant"""

        assistant_info: list[str] = []
        for i, assistant in enumerate(assistants):
            description = (
                assistant.user_description
                or assistant.assistant.description
                or "No description"  # should not be able to happen
            )
            assistant_info.append(f"{i + 1}. {assistant.assistant.name}: {description}")

        assistant_list = "\n".join(assistant_info)

        return f"""
                You are routing a user question to one of {len(assistants)} AI assistants.

                User Question: {question}

                Available Assistants:
                {assistant_list}

                Reply with EXACTLY ONE of:
                - The literal line `ASSISTANT=<n>` where <n> is an integer in
                  1-{len(assistants)}, when one assistant is the clear best match. Nothing
                  else on the line. No commentary, no quotes, no punctuation.
                - A friendly clarification in the language of the question when the
                  question is ambiguous or spans multiple assistants. Never include the
                  token `ASSISTANT=` anywhere in clarification text.

                Take earlier questions in the conversation into account.
                """

    def _create_assistant_selection_prompt(
        self, question: str, assistants: list[GroupChatAssistant]
    ) -> str:
        return self.create_assistant_selection_prompt(question, assistants)

    def _is_match(
        self, response_text: str, assistants: list[GroupChatAssistant]
    ) -> int | None:
        """Parse the model's response to a 1-indexed assistant number, or None.

        Routing requires the response to be exactly `ASSISTANT=<n>` (with
        flexible whitespace and case). Anything else — including bare digits,
        prose containing numbers, or out-of-range sentinels — returns None and
        the caller surfaces the text as a clarification reply.
        """
        match = _ASSISTANT_SENTINEL.fullmatch(response_text)
        if match is None:
            return None
        n = int(match.group(1))
        if 1 <= n <= len(assistants):
            return n
        return None

    async def _select_assistant_with_completion_model(
        self,
        question: str,
        assistants: list[GroupChatAssistant],
        session: Optional["SessionInDB"] = None,
    ) -> GroupChatAssistantSelectionResult | None:
        """Select the most appropriate assistant using a completion model to analyze the question"""

        # if no assistants, no need for completion model
        if not assistants:
            raise BadRequestException("No assistants in the group chat")

        if len(assistants) == 1:
            return GroupChatAssistantSelectionResult(
                assistant=assistants[0],
                response_str="",
                assistant_selector_tokens=0,
            )

        completion_model = await self.find_suitable_completion_model(assistants)
        assert (
            completion_model is not None
        )  # _find_suitable_completion_model raises if no assistants

        # create the prompt for assistant selection
        selection_prompt = self.create_assistant_selection_prompt(question, assistants)
        model_name = completion_model.name if completion_model else ""
        assistant_selector_tokens = count_tokens(selection_prompt, model_name)
        # get model's response
        response = await self.completion_service.get_response(
            model=completion_model,  # pyright: ignore[reportArgumentType]  # domain.CompletionModel vs ai_models.CompletionModel; structurally compatible at runtime
            prompt=selection_prompt,
            stream=False,
            session=session,
            text_input=question,
        )
        assistant_match = self._is_match(
            response.completion.text,  # type: ignore[union-attr]
            assistants,
        )
        if assistant_match is not None:
            return GroupChatAssistantSelectionResult(
                assistant=assistants[assistant_match - 1],
                response_str=response.completion.text,  # type: ignore[union-attr]
                assistant_selector_tokens=assistant_selector_tokens,
            )
        return GroupChatAssistantSelectionResult(
            assistant=None,
            response_str=response.completion.text,  # type: ignore[union-attr]
            assistant_selector_tokens=assistant_selector_tokens,
        )

    async def _handle_response(
        self,
        response: str,
        question: str,
        completion_model: "CompletionModel",
        session: "SessionInDB",
        stream: bool,
        question_id: "UUID",
        assistant_selector_tokens: int = 0,
    ):
        """Handle response for group chat selector, matching assistant_service"""

        # Capture tenant_id outside the generator so the abort-path background save
        # doesn't depend on self.user being safely accessible during teardown.
        tenant_id = self.user.tenant_id

        if stream:

            async def response_stream():
                response_string = ""
                completed = False

                try:
                    chunk_response = response.split()
                    for i, chunk in enumerate(chunk_response):
                        if i < len(chunk_response):
                            chunk_text = chunk + " "
                        else:
                            chunk_text = chunk

                        response_string += chunk_text
                        # yield empty references and chunk text, matching assistant_service format
                        yield Completion(
                            text=chunk_text,
                            response_type=ResponseType.TEXT,
                            reference_chunks=[],
                        )
                        await asyncio.sleep(0.05)

                    # NOTE: refactor question_token_count to include the whole contructed prompt.
                    question_token_count = count_tokens(question, completion_model.name)
                    token_count = count_tokens(response, completion_model.name)
                    await self.session_service.complete_question_with_answer(
                        question_id=question_id,
                        answer=response,
                        num_tokens_question=question_token_count
                        + assistant_selector_tokens,
                        num_tokens_answer=token_count,
                        completion_model=completion_model,  # pyright: ignore[reportArgumentType]  # domain.CompletionModel vs ai_models.CompletionModel; structurally compatible at runtime
                        info_blob_chunks=[],
                        logging_details=None,
                    )
                    completed = True
                finally:
                    # Selector-echo stream did not reach normal completion. The
                    # placeholder already captures the question; only schedule a
                    # background UPDATE when there's actual content to persist.
                    if not completed and response_string:
                        from intric.sessions.session_service import (
                            persist_partial_question_answer,
                            safe_count_tokens,
                            schedule_background_save,
                        )

                        partial_tokens_answer = safe_count_tokens(
                            response_string, completion_model.name
                        )
                        schedule_background_save(
                            persist_partial_question_answer(
                                tenant_id=tenant_id,
                                question_id=question_id,
                                answer=response_string,
                                num_tokens_answer=partial_tokens_answer,
                            )
                        )

            return response_stream()
        else:
            # NOTE: refactor question_token_count to include the whole contructed prompt.
            question_token_count = count_tokens(question, completion_model.name)
            token_count = count_tokens(response, completion_model.name)
            await self.session_service.complete_question_with_answer(
                question_id=question_id,
                answer=response,
                num_tokens_question=question_token_count + assistant_selector_tokens,
                num_tokens_answer=token_count,
                completion_model=completion_model,  # pyright: ignore[reportArgumentType]  # domain.CompletionModel vs ai_models.CompletionModel; structurally compatible at runtime
                info_blob_chunks=[],
                logging_details=None,
            )
            return response

    async def ask_group_chat(
        self,
        question: str,
        group_chat_id: "UUID",
        session_id: Optional["UUID"] = None,
        file_ids: Optional[list["UUID"]] = None,
        stream: bool = False,
        version: int = 1,
        tool_assistant_id: Optional["UUID"] = None,
    ) -> AssistantResponse:
        """Ask a question to the most appropriate assistant in a group chat

        If tool_assistant_id is provided and allow_mentions is True for the group chat,
        the question will be directed to the specified assistant. Otherwise, the most
        appropriate assistant will be selected based on the question.
        """
        group_chat = await self.get_group_chat(group_chat_id=group_chat_id)
        response_from_selector = None
        if not group_chat.assistants:
            raise BadRequestException("No assistants in the group chat")

        # get or create session first so we can use it for assistant selection
        if session_id is None:
            session = await self.session_service.create_session(
                name=question,
                group_chat_id=group_chat_id,
            )
            session_id = session.id
        else:
            session = await self.session_service.get_session_by_uuid(id=session_id)

        selection_result = None
        if tool_assistant_id is not None:
            # verify allow_mentions is enabled
            if not group_chat.allow_mentions:
                raise BadRequestException(
                    "This group chat does not allow targeting specific assistants"
                )

            group_chat_assistant_ids = [
                assistant.assistant.id for assistant in group_chat.assistants
            ]
            if tool_assistant_id not in group_chat_assistant_ids:
                raise BadRequestException(
                    "The specified assistant is not part of this group chat"
                )

            assistant_to_ask = tool_assistant_id
        else:
            # select the best assistant based on the question using the completion model
            # including conversation history
            selection_result = await self._select_assistant_with_completion_model(
                question, group_chat.assistants, session
            )
            assert selection_result is not None
            response_from_selector = selection_result.response_str
            if selection_result.assistant:
                assistant_to_ask = selection_result.assistant.assistant.id
            else:
                assistant_to_ask = None

        if assistant_to_ask is None:
            assert selection_result is not None
            assert (
                response_from_selector is not None
            )  # set above whenever selection_result is set
            first_completion_model = group_chat.assistants[0].assistant.completion_model
            assert (
                first_completion_model is not None
            )  # assistant must have a model to be usable
            # Persist a placeholder Question row before the selector echo streams out, so
            # the user's question survives even if the stream is aborted.
            question_id = await self.session_service.create_question_placeholder(
                question=question,
                session=session,
                files=[],
                assistant_id=None,
                completion_model=first_completion_model,  # pyright: ignore[reportArgumentType]  # domain.CompletionModel vs ai_models.CompletionModel; structurally compatible at runtime
            )
            final_response = await self._handle_response(
                response=response_from_selector,
                question=question,
                completion_model=first_completion_model,  # pyright: ignore[reportArgumentType]  # domain.CompletionModel vs ai_models.CompletionModel; structurally compatible at runtime
                session=session,
                stream=stream,
                question_id=question_id,
                assistant_selector_tokens=selection_result.assistant_selector_tokens,
            )
            response = AssistantResponse(
                question=question,
                files=[],
                session=session,
                answer=final_response,
                info_blobs=[],
                completion_model=first_completion_model,  # pyright: ignore[reportArgumentType]  # domain.CompletionModel vs ai_models.CompletionModel; structurally compatible at runtime
                tools=UseTools(assistants=[]),
                description=None,
                web_search_results=[],
                question_id=question_id,
            )
        else:
            response = await self.assistant_service.ask(
                question=question,
                assistant_id=assistant_to_ask,
                group_chat_id=group_chat_id,
                session_id=session_id,
                file_ids=file_ids or [],
                stream=stream,
                version=version,
                assistant_selector_tokens=selection_result.assistant_selector_tokens
                if selection_result is not None
                else 0,
            )

            # ensure the response tools contain which assistant answered
            # get the assistant name for the handle
            selected_assistant = group_chat.get_assistant_by_id(assistant_to_ask)
            assert selected_assistant is not None
            assistant_name = selected_assistant.assistant.name

            # set assistant info in tools
            response.tools.assistants = [
                ToolAssistant(id=assistant_to_ask, handle=assistant_name)
            ]

        return response

    async def publish_group_chat(self, group_chat_id: "UUID", publish: bool):
        space = await self.space_repo.get_space_by_group_chat(
            group_chat_id=group_chat_id
        )
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_publish_group_chats():
            raise UnauthorizedException(
                "Publishing group chats is not allowed for your current space role.",
                code="forbidden_action",
                context={
                    "resource_type": "group_chat",
                    "action": "publish",
                    "auth_layer": "domain_policy",
                },
            )

        group_chat = space.get_group_chat(group_chat_id=group_chat_id)

        # Use the update method to change the published status
        group_chat.update(published=publish)

        # Pass the updated group chat to the repository
        updated_space = await self.space_repo.update(space=space)
        updated_group_chat = updated_space.get_group_chat(group_chat_id=group_chat_id)
        updated_group_chat.permissions = actor.get_group_chat_permissions(
            group_chat=updated_group_chat
        )

        return updated_group_chat
