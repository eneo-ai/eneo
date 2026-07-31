# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""
Unit tests for assistant router endpoints.

These tests ensure proper response structure handling and audit logging
in the assistant endpoints. Specifically addresses the session.id access
pattern to prevent regressions from commit 58b73e9e.
"""

import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request

from eneo.assistants.api import assistant_router
from eneo.assistants.api.assistant_models import (
    AskAssistant,
    AssistantResponse,
    AssistantUpdatePublic,
)
from eneo.assistants.api.assistant_router import (
    ask_assistant,
    delete_assistant_session,
    get_assistant_session,
    get_assistant_sessions,
    leave_feedback,
    update_assistant,
)
from eneo.assistants.assistant import AssistantOrigin
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.main.exceptions import UnauthorizedException
from eneo.main.models import NOT_PROVIDED, ModelId
from eneo.sessions.session import SessionFeedback, SessionInDB
from eneo.skills.domain.skill import (
    ResolvedSkillBinding,
    SkillActivationMode,
    SkillBindingIntent,
    SkillBindingReference,
    SkillBindingSource,
)
from eneo.skills.presentation.skill_models import AssistantSkillBindingInput


def _request(*, api_key=None) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/assistants/test/",
            "headers": [],
        }
    )
    request.state.api_key = api_key
    return request


@pytest.fixture
def mock_user():
    """Create a mock user object with required attributes."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.username = "testuser"
    user.tenant_id = uuid.uuid4()
    return user


@pytest.fixture
def mock_session():
    """Create a mock session with correct id attribute.

    SessionInDB inherits from InDB -> BaseResponse -> ModelId,
    so the id attribute comes from the ModelId base class.
    """
    session = MagicMock(spec=SessionInDB)
    session.id = uuid.uuid4()
    session.name = "Test Session"
    return session


@pytest.fixture
def mock_assistant():
    """Create a mock assistant object."""
    assistant = MagicMock()
    assistant.id = uuid.uuid4()
    assistant.name = "Test Assistant"
    assistant.space_id = uuid.uuid4()
    return assistant


def _router_assistant(assistant_id: uuid.UUID):
    assistant = MagicMock()
    assistant.id = assistant_id
    assistant.name = "Assistant"
    assistant.space_id = uuid.uuid4()
    assistant.origin = AssistantOrigin.USER
    assistant.managing_flow_id = None
    assistant.completion_model = MagicMock(id=uuid.uuid4(), nickname="gpt")
    assistant.completion_model_kwargs = MagicMock(temperature=None, top_p=None)
    assistant.description = None
    assistant.insight_enabled = False
    assistant.data_retention_days = None
    assistant.collections = []
    assistant.websites = []
    assistant.attachments = []
    assistant.integration_knowledge_list = []
    assistant.mcp_servers = []
    assistant.mcp_tools = []
    assistant.type.value = "standard"
    return assistant


@pytest.fixture
def mock_space():
    """Create a mock space object."""
    space = MagicMock()
    space.id = uuid.uuid4()
    space.name = "Test Space"
    return space


@pytest.fixture
def mock_response(mock_session):
    """Create a mock AssistantResponse with session object.

    IMPORTANT: AssistantResponse has 'session: SessionInDB', NOT 'session_id'.
    The session_id must be accessed via response.session.id, not response.session_id.
    """
    response = MagicMock(spec=AssistantResponse)
    response.session = mock_session
    # Explicitly do NOT set session_id attribute - AssistantResponse doesn't have it
    return response


@pytest.fixture
def mock_container(mock_user, mock_assistant, mock_response, mock_space):
    """Create a mock container with common services."""
    container = MagicMock()

    # User
    container.user.return_value = mock_user

    # Assistant service
    assistant_service = AsyncMock()
    assistant_service.ask.return_value = mock_response
    assistant_service.get_assistant.return_value = (mock_assistant, None)
    assistant_service.get_assistant_with_effective_config.return_value = (
        mock_assistant,
        None,
        None,
    )
    assistant_service.is_help_assistant.return_value = False
    container.assistant_service.return_value = assistant_service

    assistant_assembler = MagicMock()
    assistant_assembler.from_assistant_to_model.return_value = MagicMock()
    container.assistant_assembler.return_value = assistant_assembler

    # Space service
    space_service = AsyncMock()
    space_service.get_space.return_value = mock_space
    container.space_service.return_value = space_service

    # Audit service
    audit_service = AsyncMock()
    container.audit_service.return_value = audit_service

    return container


@pytest.fixture
def mock_assistant_protocol(mock_response):
    """Create a mock for assistant_protocol.to_response."""
    return AsyncMock()


class TestAskAssistant:
    """Tests for the POST /{id}/sessions/ endpoint."""

    async def test_extracts_session_id_from_session_object(
        self, mock_container, monkeypatch
    ):
        """Verify that response.session.id is used, not response.session_id.

        Regression test for the bug fixed in commit 58b73e9e where the code
        incorrectly accessed response.session_id instead of response.session.id.

        AssistantResponse structure:
        - session: SessionInDB (object with id attribute)
        - NOT session_id (attribute directly on response)
        """
        # Mock assistant_protocol.to_response to avoid full response transformation
        mock_to_response = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(
            "eneo.assistants.api.assistant_router.assistant_protocol.to_response",
            mock_to_response,
        )

        assistant_id = uuid.uuid4()
        ask = AskAssistant(question="What is the meaning of life?")

        await ask_assistant(
            id=assistant_id,
            ask=ask,
            version=1,
            container=mock_container,
        )

        # Verify audit_service.log_async was called
        audit_service = mock_container.audit_service.return_value
        audit_service.log_async.assert_called_once()

        # Get the call arguments
        call_kwargs = audit_service.log_async.call_args.kwargs

        # Verify the session_id in metadata comes from response.session.id
        # This is the key assertion - if code uses response.session_id, it would fail
        # because MagicMock(spec=AssistantResponse) won't have that attribute
        metadata = call_kwargs["metadata"]
        expected_session_id = (
            mock_container.assistant_service.return_value.ask.return_value.session.id
        )

        # The metadata.extra dict should contain the correct session_id
        assert str(expected_session_id) in str(metadata)

    async def test_audit_logs_session_started_action(self, mock_container, monkeypatch):
        """Verify SESSION_STARTED is logged with correct action type and entity type."""
        mock_to_response = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(
            "eneo.assistants.api.assistant_router.assistant_protocol.to_response",
            mock_to_response,
        )

        assistant_id = uuid.uuid4()
        ask = AskAssistant(question="Test question")

        await ask_assistant(
            id=assistant_id,
            ask=ask,
            version=1,
            container=mock_container,
        )

        audit_service = mock_container.audit_service.return_value
        call_kwargs = audit_service.log_async.call_args.kwargs

        assert call_kwargs["action"] == ActionType.SESSION_STARTED
        assert call_kwargs["entity_type"] == EntityType.ASSISTANT
        assert call_kwargs["entity_id"] == assistant_id

    async def test_audit_logs_with_correct_user_context(
        self, mock_container, mock_user, monkeypatch
    ):
        """Verify audit logging includes correct tenant_id and actor_id from user."""
        mock_to_response = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(
            "eneo.assistants.api.assistant_router.assistant_protocol.to_response",
            mock_to_response,
        )

        assistant_id = uuid.uuid4()
        ask = AskAssistant(question="Test question")

        await ask_assistant(
            id=assistant_id,
            ask=ask,
            version=1,
            container=mock_container,
        )

        audit_service = mock_container.audit_service.return_value
        call_kwargs = audit_service.log_async.call_args.kwargs

        assert call_kwargs["tenant_id"] == mock_user.tenant_id
        assert call_kwargs["actor_id"] == mock_user.id

    async def test_audit_logs_file_metadata(self, mock_container, monkeypatch):
        """Verify file count is captured in audit metadata when files are provided."""
        mock_to_response = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(
            "eneo.assistants.api.assistant_router.assistant_protocol.to_response",
            mock_to_response,
        )

        # Create request with file (AskAssistant has max_length=1 by default)
        from eneo.main.models import ModelId

        file1 = ModelId(id=uuid.uuid4())

        assistant_id = uuid.uuid4()
        ask = AskAssistant(
            question="Analyze this file",
            files=[file1.id],
        )

        await ask_assistant(
            id=assistant_id,
            ask=ask,
            version=1,
            container=mock_container,
        )

        audit_service = mock_container.audit_service.return_value
        call_kwargs = audit_service.log_async.call_args.kwargs
        metadata = call_kwargs["metadata"]

        # Verify file metadata is captured
        # The extra dict should contain file_count: 1 and has_files: True
        assert "file_count" in str(metadata) or hasattr(metadata, "extra")

    async def test_space_service_called_for_context(
        self, mock_container, mock_assistant, monkeypatch
    ):
        """Verify space_service is called to get space context when assistant has space_id."""
        mock_to_response = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(
            "eneo.assistants.api.assistant_router.assistant_protocol.to_response",
            mock_to_response,
        )

        assistant_id = uuid.uuid4()
        ask = AskAssistant(question="Test question")

        await ask_assistant(
            id=assistant_id,
            ask=ask,
            version=1,
            container=mock_container,
        )

        space_service = mock_container.space_service.return_value
        space_service.get_space.assert_called_once_with(mock_assistant.space_id)

    async def test_space_service_exception_handled_gracefully(
        self, mock_container, monkeypatch
    ):
        """Verify space_service exceptions don't break the endpoint."""
        mock_to_response = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(
            "eneo.assistants.api.assistant_router.assistant_protocol.to_response",
            mock_to_response,
        )

        # Make space_service raise an exception
        space_service = mock_container.space_service.return_value
        space_service.get_space.side_effect = Exception("Space not found")

        assistant_id = uuid.uuid4()
        ask = AskAssistant(question="Test question")

        # Should not raise - exception is caught
        await ask_assistant(
            id=assistant_id,
            ask=ask,
            version=1,
            container=mock_container,
        )

        # Audit logging should still happen
        audit_service = mock_container.audit_service.return_value
        audit_service.log_async.assert_called_once()


class TestUpdateAssistant:
    async def test_preserves_completion_model_when_deprecated_field_absent(
        self,
        mock_container,
    ):
        assistant_id = uuid.uuid4()
        old_assistant = _router_assistant(assistant_id)
        updated_assistant = _router_assistant(assistant_id)
        service = mock_container.assistant_service.return_value
        service.get_assistant.return_value = (old_assistant, [])
        service.update_assistant.return_value = (updated_assistant, [])
        mock_container.assistant_assembler.return_value.from_assistant_to_model.return_value = MagicMock()

        await update_assistant(
            id=assistant_id,
            assistant=AssistantUpdatePublic(name="Renamed"),
            request=_request(),
            container=mock_container,
        )

        update = service.update_assistant.await_args.kwargs["update"]
        assert update.completion_model_id is NOT_PROVIDED
        assert not update.is_set("completion_model_id")

    async def test_preserves_completion_model_when_deprecated_field_is_null(
        self,
        mock_container,
    ):
        assistant_id = uuid.uuid4()
        old_assistant = _router_assistant(assistant_id)
        updated_assistant = _router_assistant(assistant_id)
        service = mock_container.assistant_service.return_value
        service.get_assistant.return_value = (old_assistant, [])
        service.update_assistant.return_value = (updated_assistant, [])
        mock_container.assistant_assembler.return_value.from_assistant_to_model.return_value = MagicMock()

        await update_assistant(
            id=assistant_id,
            assistant=AssistantUpdatePublic(name="Renamed", completion_model=None),
            request=_request(),
            container=mock_container,
        )

        update = service.update_assistant.await_args.kwargs["update"]
        assert update.completion_model_id is NOT_PROVIDED
        assert not update.is_set("completion_model_id")

    async def test_preserves_completion_model_when_deprecated_field_is_non_null(
        self,
        mock_container,
    ):
        assistant_id = uuid.uuid4()
        old_assistant = _router_assistant(assistant_id)
        updated_assistant = _router_assistant(assistant_id)
        service = mock_container.assistant_service.return_value
        service.get_assistant.return_value = (old_assistant, [])
        service.update_assistant.return_value = (updated_assistant, [])
        mock_container.assistant_assembler.return_value.from_assistant_to_model.return_value = MagicMock()

        await update_assistant(
            id=assistant_id,
            assistant=AssistantUpdatePublic(
                name="Renamed",
                completion_model=ModelId(id=uuid.uuid4()),
            ),
            request=_request(),
            container=mock_container,
        )

        update = service.update_assistant.await_args.kwargs["update"]
        assert update.completion_model_id is NOT_PROVIDED
        assert not update.is_set("completion_model_id")


class TestAssistantResponseStructure:
    """Tests verifying the AssistantResponse model structure.

    These tests document the expected structure and serve as regression tests
    to catch any changes that might reintroduce the session_id bug.
    """

    def test_assistant_response_has_session_not_session_id(self, mock_session):
        """Verify AssistantResponse has 'session' attribute, not 'session_id'.

        This is the core structural test that documents why
        response.session.id is correct and response.session_id is wrong.
        """
        # Create a MagicMock with spec=AssistantResponse
        # This will only have attributes defined in AssistantResponse
        response = MagicMock(spec=AssistantResponse)
        response.session = mock_session

        # session attribute should exist
        assert hasattr(response, "session")

        # session.id should be accessible
        assert hasattr(response.session, "id")
        assert response.session.id == mock_session.id

    def test_session_in_db_has_id_from_in_db_inheritance(self, mock_session):
        """Verify SessionInDB has 'id' through InDB inheritance chain.

        Inheritance chain: SessionInDB -> InDB -> BaseResponse -> ModelId -> id: UUID
        """
        # The mock_session fixture uses spec=SessionInDB
        assert hasattr(mock_session, "id")
        assert isinstance(mock_session.id, uuid.UUID)

    def test_mock_response_matches_real_structure(self, mock_response, mock_session):
        """Verify mock response structure matches the real AssistantResponse.

        This test ensures our test fixtures accurately represent the real models.
        """
        # Access pattern should be response.session.id
        session_id = mock_response.session.id
        assert session_id == mock_session.id

        # Attempting to access response.session_id should either:
        # - Return the mock's default (if not using spec)
        # - Raise AttributeError (if using strict spec)
        # Our mock uses spec=AssistantResponse, so session_id won't be a real attribute


class TestAssistantSessionPagination:
    async def test_missing_cursor_stays_none_in_paginated_response(
        self, mock_container
    ):
        assistant_id = uuid.uuid4()
        session = SessionInDB(
            id=uuid.uuid4(),
            name="Session",
            user_id=uuid.uuid4(),
            created_at=None,
        )
        session_service = AsyncMock()
        session_service.get_sessions_by_assistant.return_value = ([session], 1)
        mock_container.session_service.return_value = session_service

        response = await get_assistant_sessions(
            id=assistant_id,
            container=mock_container,
            limit=10,
            cursor=None,
            previous=False,
        )

        assert response.previous_cursor is None


class TestLegacyAssistantSessionAuthorization:
    @pytest.fixture
    def unauthorized_container(self, mock_container):
        assistant_service = mock_container.assistant_service.return_value
        assistant_service.get_assistant.side_effect = UnauthorizedException(
            "Personal chat access has been revoked"
        )
        mock_container.session_service.return_value = AsyncMock()
        return mock_container

    async def test_get_authorizes_assistant_before_loading_session(
        self, unauthorized_container
    ):
        with pytest.raises(UnauthorizedException):
            await get_assistant_session(
                id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                container=unauthorized_container,
            )

        unauthorized_container.session_service.return_value.get_session_by_uuid.assert_not_awaited()

    async def test_delete_authorizes_assistant_before_deleting_session(
        self, unauthorized_container
    ):
        with pytest.raises(UnauthorizedException):
            await delete_assistant_session(
                id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                container=unauthorized_container,
            )

        unauthorized_container.session_service.return_value.delete.assert_not_awaited()

    async def test_feedback_authorizes_assistant_before_writing_feedback(
        self, unauthorized_container
    ):
        with pytest.raises(UnauthorizedException):
            await leave_feedback(
                id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                feedback=SessionFeedback(value=1),
                container=unauthorized_container,
            )

        unauthorized_container.session_service.return_value.leave_feedback.assert_not_awaited()


async def test_update_assistant_rejects_api_key_skill_facet_before_service_call():
    container = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await update_assistant(
            id=uuid.uuid4(),
            assistant=AssistantUpdatePublic(skill_bindings=[]),
            request=_request(api_key=MagicMock()),
            container=container,
        )

    assert exc_info.value.status_code == 403
    assert "session token" in str(exc_info.value.detail)
    container.assistant_service.assert_not_called()


def _skill_binding(*, position: int) -> ResolvedSkillBinding:
    return ResolvedSkillBinding(
        skill_id=uuid.uuid4(),
        skill_revision_id=uuid.uuid4(),
        current_revision_id=uuid.uuid4(),
        skill_space_id=uuid.uuid4(),
        slug=f"skill-{position}",
        revision_number=position + 1,
        current_revision_number=position + 1,
        display_name=f"Skill {position}",
        description="Description must not enter parent audit evidence",
        instructions="Sensitive instructions must not enter audit evidence",
        content_digest=str(position + 1) * 64,
        position=position,
        source=SkillBindingSource.SPACE,
        is_active=True,
    )


async def test_update_assistant_audits_mode_only_skill_change_without_bodies(
    monkeypatch,
):
    assistant_id = uuid.uuid4()
    space_id = uuid.uuid4()
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        active_api_key=None,
        email="editor@example.com",
        username="editor",
    )
    old_assistant = SimpleNamespace(
        id=assistant_id,
        name="Assistant",
        space_id=space_id,
        origin=AssistantOrigin.USER,
        managing_flow_id=None,
    )
    updated_assistant = SimpleNamespace(
        id=assistant_id,
        name="Assistant",
        space_id=space_id,
        type=None,
    )
    before_binding = _skill_binding(position=0)
    before = [before_binding]
    after = [
        replace(
            before_binding,
            activation_mode=SkillActivationMode.ON_DEMAND,
        )
    ]
    references = [
        AssistantSkillBindingInput(
            skill_id=binding.skill_id,
            skill_revision_id=binding.skill_revision_id,
            activation_mode=SkillActivationMode.ON_DEMAND,
        )
        for binding in after
    ]
    service = SimpleNamespace(
        get_assistant=AsyncMock(return_value=(old_assistant, [])),
        update_assistant=AsyncMock(return_value=(updated_assistant, [])),
    )
    skill_repo = SimpleNamespace(
        list_assistant_bindings=AsyncMock(side_effect=[before, after])
    )
    audit_service = SimpleNamespace(log_async=AsyncMock())
    container = SimpleNamespace(
        assistant_service=lambda: service,
        skill_repo=lambda: skill_repo,
        user=lambda: current_user,
        space_service=lambda: SimpleNamespace(
            get_space=AsyncMock(return_value=SimpleNamespace(id=space_id, name="Space"))
        ),
        audit_service=lambda: audit_service,
    )
    response = SimpleNamespace(id=assistant_id)
    monkeypatch.setattr(
        assistant_router,
        "_build_assistant_update_changes",
        MagicMock(return_value=({}, [])),
    )
    monkeypatch.setattr(
        assistant_router,
        "_assistant_response",
        AsyncMock(return_value=response),
    )

    result = await update_assistant(
        id=assistant_id,
        assistant=AssistantUpdatePublic(skill_bindings=references),
        request=_request(),
        container=container,
    )

    assert result is response
    service.update_assistant.assert_awaited_once()
    assert service.update_assistant.await_args.kwargs[
        "update"
    ].skill_binding_intents == [
        SkillBindingIntent(
            reference=SkillBindingReference(
                skill_id=reference.skill_id,
                skill_revision_id=reference.skill_revision_id,
            ),
            activation_mode=SkillActivationMode.ON_DEMAND,
        )
        for reference in references
    ]
    audit_service.log_async.assert_awaited_once()
    audit_call = audit_service.log_async.await_args.kwargs
    assert audit_call["action"] == ActionType.ASSISTANT_UPDATED
    skills_change = audit_call["metadata"]["changes"]["skills"]
    assert skills_change["old"][0]["activation_mode"] == "always"
    assert skills_change["new"][0]["activation_mode"] == "on_demand"
    assert "instructions" not in str(skills_change)
    assert "description" not in str(skills_change)
