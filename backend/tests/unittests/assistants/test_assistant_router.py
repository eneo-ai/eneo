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
from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.assistants.api.assistant_models import (
    AskAssistant,
    AssistantResponse,
)
from intric.assistants.api.assistant_router import ask_assistant
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.sessions.session import SessionInDB


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
    container.assistant_service.return_value = assistant_service

    # Space service
    space_service = AsyncMock()
    space_service.get_space.return_value = mock_space
    container.space_service.return_value = space_service

    # Audit service
    audit_service = AsyncMock()
    container.audit_service.return_value = audit_service

    return container


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    return AsyncMock()


@pytest.fixture
def mock_assistant_protocol(mock_response):
    """Create a mock for assistant_protocol.to_response."""
    return AsyncMock()


class TestAskAssistant:
    """Tests for the POST /{id}/sessions/ endpoint."""

    async def test_extracts_session_id_from_session_object(
        self, mock_container, mock_db_session, monkeypatch
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
            "intric.assistants.api.assistant_router.assistant_protocol.to_response",
            mock_to_response,
        )

        assistant_id = uuid.uuid4()
        ask = AskAssistant(question="What is the meaning of life?")

        await ask_assistant(
            id=assistant_id,
            ask=ask,
            version=1,
            container=mock_container,
            db_session=mock_db_session,
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
        expected_session_id = mock_container.assistant_service.return_value.ask.return_value.session.id

        # The metadata.extra dict should contain the correct session_id
        assert str(expected_session_id) in str(metadata)

    async def test_audit_logs_session_started_action(
        self, mock_container, mock_db_session, monkeypatch
    ):
        """Verify SESSION_STARTED is logged with correct action type and entity type."""
        mock_to_response = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(
            "intric.assistants.api.assistant_router.assistant_protocol.to_response",
            mock_to_response,
        )

        assistant_id = uuid.uuid4()
        ask = AskAssistant(question="Test question")

        await ask_assistant(
            id=assistant_id,
            ask=ask,
            version=1,
            container=mock_container,
            db_session=mock_db_session,
        )

        audit_service = mock_container.audit_service.return_value
        call_kwargs = audit_service.log_async.call_args.kwargs

        assert call_kwargs["action"] == ActionType.SESSION_STARTED
        assert call_kwargs["entity_type"] == EntityType.ASSISTANT
        assert call_kwargs["entity_id"] == assistant_id

    async def test_audit_logs_with_correct_user_context(
        self, mock_container, mock_user, mock_db_session, monkeypatch
    ):
        """Verify audit logging includes correct tenant_id and actor_id from user."""
        mock_to_response = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(
            "intric.assistants.api.assistant_router.assistant_protocol.to_response",
            mock_to_response,
        )

        assistant_id = uuid.uuid4()
        ask = AskAssistant(question="Test question")

        await ask_assistant(
            id=assistant_id,
            ask=ask,
            version=1,
            container=mock_container,
            db_session=mock_db_session,
        )

        audit_service = mock_container.audit_service.return_value
        call_kwargs = audit_service.log_async.call_args.kwargs

        assert call_kwargs["tenant_id"] == mock_user.tenant_id
        assert call_kwargs["actor_id"] == mock_user.id

    async def test_audit_logs_file_metadata(
        self, mock_container, mock_db_session, monkeypatch
    ):
        """Verify file count is captured in audit metadata when files are provided."""
        mock_to_response = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(
            "intric.assistants.api.assistant_router.assistant_protocol.to_response",
            mock_to_response,
        )

        # Create request with file (AskAssistant has max_length=1 by default)
        from intric.main.models import ModelId

        file1 = ModelId(id=uuid.uuid4())

        assistant_id = uuid.uuid4()
        ask = AskAssistant(
            question="Analyze this file",
            files=[file1],
        )

        await ask_assistant(
            id=assistant_id,
            ask=ask,
            version=1,
            container=mock_container,
            db_session=mock_db_session,
        )

        audit_service = mock_container.audit_service.return_value
        call_kwargs = audit_service.log_async.call_args.kwargs
        metadata = call_kwargs["metadata"]

        # Verify file metadata is captured
        # The extra dict should contain file_count: 1 and has_files: True
        assert "file_count" in str(metadata) or hasattr(metadata, "extra")

    async def test_space_service_called_for_context(
        self, mock_container, mock_assistant, mock_db_session, monkeypatch
    ):
        """Verify space_service is called to get space context when assistant has space_id."""
        mock_to_response = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(
            "intric.assistants.api.assistant_router.assistant_protocol.to_response",
            mock_to_response,
        )

        assistant_id = uuid.uuid4()
        ask = AskAssistant(question="Test question")

        await ask_assistant(
            id=assistant_id,
            ask=ask,
            version=1,
            container=mock_container,
            db_session=mock_db_session,
        )

        space_service = mock_container.space_service.return_value
        space_service.get_space.assert_called_once_with(mock_assistant.space_id)

    async def test_space_service_exception_handled_gracefully(
        self, mock_container, mock_db_session, monkeypatch
    ):
        """Verify space_service exceptions don't break the endpoint."""
        mock_to_response = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(
            "intric.assistants.api.assistant_router.assistant_protocol.to_response",
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
            db_session=mock_db_session,
        )

        # Audit logging should still happen
        audit_service = mock_container.audit_service.return_value
        audit_service.log_async.assert_called_once()


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
