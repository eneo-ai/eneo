"""Unit test for help-assistant MCP forwarding.

The invariant: a help assistant's MCP servers reach the completion call even
when the assistant also has knowledge attached; knowledge does not suppress
tools.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.help_assistants.application import helper_run_service as hrs
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.services.service import DatastoreResult


@pytest.mark.asyncio
async def test_helper_mcp_servers_forwarded_despite_knowledge(monkeypatch):
    mcp_server = MagicMock()
    helper_assistant = MagicMock()
    helper_assistant.id = uuid4()
    helper_assistant.collections = [MagicMock()]
    helper_assistant.websites = []
    helper_assistant.integration_knowledge_list = []
    helper_assistant.mcp_servers = [mcp_server]
    assert helper_assistant.has_knowledge()

    service = hrs.HelperRunService(
        user=MagicMock(id=uuid4(), tenant_id=uuid4()),
        helper_run_repo=MagicMock(add=AsyncMock(return_value=MagicMock())),
        role_service=MagicMock(
            get_active=AsyncMock(
                return_value=MagicMock(
                    is_enabled=True,
                    is_visible_to_users=True,
                    assistant_id=uuid4(),
                    org_space_id=uuid4(),
                )
            )
        ),
        assistant_service=MagicMock(),
        session_repo=MagicMock(),
        question_repo=MagicMock(),
        completion_service=MagicMock(get_response=AsyncMock(return_value=MagicMock())),
        references_service=MagicMock(
            get_references=AsyncMock(
                return_value=DatastoreResult(
                    chunks=[], no_duplicate_chunks=[], info_blobs=[]
                )
            )
        ),
        factory=MagicMock(),
        audit_service=MagicMock(),
    )

    monkeypatch.setattr(
        service,
        "_load_target_with_edit_permission",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        service, "_load_helper_assistant", AsyncMock(return_value=helper_assistant)
    )
    monkeypatch.setattr(service, "_check_helper_completion_model", MagicMock())
    monkeypatch.setattr(
        service, "_create_helper_session", AsyncMock(return_value=MagicMock())
    )
    monkeypatch.setattr(service, "_stream_and_persist", MagicMock())
    monkeypatch.setattr(
        hrs, "HelperRunResponse", lambda **kwargs: SimpleNamespace(**kwargs)
    )

    await service.run(
        kind=HelperKind.PROMPT_GUIDE,
        target_type="assistant",
        target_id=uuid4(),
        question="Improve my prompt",
        stream=True,
    )

    kwargs = service.completion_service.get_response.await_args.kwargs
    assert kwargs["mcp_servers"] == [mcp_server]
