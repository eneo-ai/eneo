"""Unit tests for the per-turn debug capture flag.

The invariants: ``debug=True`` on an ask forces extended logging (the exact
provider payload is captured and persisted) regardless of the assistant's
``logging_enabled`` setting; ``debug=False`` leaves the setting in charge;
requesting debug capture requires the ``assistant_debug`` role permission;
group chats never accept debug capture (they have no logging persistence
path); the streamed first chunk carries the persisted question id so clients
can fetch the captured details afterwards.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import Assistant
from eneo.conversations.application.conversation_service import ConversationService
from eneo.conversations.conversation_models import ConversationRequest
from eneo.conversations.conversations_router import chat
from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.questions.question import UseTools
from eneo.roles.permissions import Permission
from eneo.sessions.session import AskChatResponse, SSEFirstChunk


def _assistant(**overrides):
    completion_model = MagicMock(vision=True, max_input_tokens=100_000)
    defaults = dict(
        id=uuid4(),
        user=MagicMock(),
        name="Test assistant",
        space_id=uuid4(),
        prompt=None,
        completion_model=completion_model,
        completion_model_kwargs=ModelKwargs(),
        logging_enabled=False,
        collections=[],
        websites=[],
        attachments=[],
        mcp_servers=[],
        published=False,
    )
    defaults.update(overrides)
    return Assistant(**defaults)


def _completion_service():
    service = MagicMock()
    service.get_response = AsyncMock(return_value=MagicMock())
    return service


def _references_service():
    service = MagicMock()
    service.get_references = AsyncMock()
    return service


class TestDebugForcesExtendedLogging:
    @pytest.mark.asyncio
    async def test_debug_forces_capture_when_logging_disabled(self):
        assistant = _assistant(logging_enabled=False)
        completion_service = _completion_service()

        await assistant.ask(
            question="Hello",
            completion_service=completion_service,
            references_service=_references_service(),
            debug=True,
        )

        kwargs = completion_service.get_response.await_args.kwargs
        assert kwargs["extended_logging"] is True

    @pytest.mark.asyncio
    async def test_no_debug_leaves_assistant_setting_in_charge(self):
        for logging_enabled in (False, True):
            assistant = _assistant(logging_enabled=logging_enabled)
            completion_service = _completion_service()

            await assistant.ask(
                question="Hello",
                completion_service=completion_service,
                references_service=_references_service(),
            )

            kwargs = completion_service.get_response.await_args.kwargs
            assert kwargs["extended_logging"] is logging_enabled


class TestDebugRequiresPermission:
    """The chat endpoint gates debug capture on the assistant_debug role
    permission before any session or service work happens."""

    class _PastPermissionCheck(Exception):
        """Sentinel raised by the first mock touched after the gate."""

    def _container(self, permissions):
        container = MagicMock()
        container.user.return_value = SimpleNamespace(permissions=permissions)
        container.session.side_effect = self._PastPermissionCheck()
        return container

    def _request(self, **overrides):
        return ConversationRequest(question="Hello", assistant_id=uuid4(), **overrides)

    @pytest.mark.asyncio
    async def test_debug_without_permission_is_unauthorized(self):
        with pytest.raises(UnauthorizedException):
            await chat(
                request=self._request(debug=True),
                http_request=MagicMock(),
                container=self._container(permissions=[]),
            )

    @pytest.mark.asyncio
    async def test_debug_with_permission_passes_the_gate(self):
        with pytest.raises(self._PastPermissionCheck):
            await chat(
                request=self._request(debug=True),
                http_request=MagicMock(),
                container=self._container(permissions=[Permission.ASSISTANT_DEBUG]),
            )

    @pytest.mark.asyncio
    async def test_no_debug_needs_no_permission(self):
        with pytest.raises(self._PastPermissionCheck):
            await chat(
                request=self._request(),
                http_request=MagicMock(),
                container=self._container(permissions=[]),
            )


class TestDebugRejectedForGroupChats:
    def _service(self, session=None):
        session_service = MagicMock()
        session_service.get_session_by_uuid = AsyncMock(return_value=session)
        return ConversationService(
            assistant_service=MagicMock(),
            group_chat_service=MagicMock(),
            session_service=session_service,
            completion_service=MagicMock(),
            space_service=MagicMock(),
            file_service=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_new_group_chat_conversation_rejects_debug(self):
        with pytest.raises(BadRequestException):
            await self._service().ask_conversation(
                question="Hello", group_chat_id=uuid4(), debug=True
            )

    @pytest.mark.asyncio
    async def test_existing_group_chat_session_rejects_debug(self):
        session = SimpleNamespace(group_chat_id=uuid4(), assistant=None)

        with pytest.raises(BadRequestException):
            await self._service(session=session).ask_conversation(
                question="Hello", session_id=uuid4(), debug=True
            )

    @pytest.mark.asyncio
    async def test_assistant_conversation_forwards_debug(self):
        service = self._service()
        service.assistant_service.ask = AsyncMock(return_value=MagicMock())

        await service.ask_conversation(
            question="Hello", assistant_id=uuid4(), debug=True
        )

        assert service.assistant_service.ask.await_args.kwargs["debug"] is True


class TestFirstChunkCarriesQuestionId:
    def _response(self, **overrides):
        defaults = dict(
            session_id=uuid4(),
            question="Hello",
            answer="",
            files=[],
            generated_files=[],
            references=[],
            tools=UseTools(assistants=[]),
        )
        defaults.update(overrides)
        return AskChatResponse(**defaults)

    def test_ask_chat_response_round_trips_id(self):
        question_id = uuid4()
        response = self._response(id=question_id)

        assert SSEFirstChunk(**response.model_dump()).id == question_id

    def test_id_defaults_to_none(self):
        assert self._response().id is None
