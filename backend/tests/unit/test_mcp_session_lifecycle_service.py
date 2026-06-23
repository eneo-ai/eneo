from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.mcp_servers.application.mcp_session_lifecycle_service import (
    McpSessionLifecycleService,
)


@pytest.mark.asyncio
async def test_terminate_for_chat_session_terminates_every_persisted_session():
    chat_session_id = uuid4()
    first_server_id = uuid4()
    second_server_id = uuid4()
    state_repo = AsyncMock()
    state_repo.list_for_chat_session.return_value = [
        (first_server_id, "mcp-session-1"),
        (second_server_id, "mcp-session-2"),
    ]
    servers = {
        first_server_id: SimpleNamespace(id=first_server_id, http_url="https://one"),
        second_server_id: SimpleNamespace(id=second_server_id, http_url="https://two"),
    }
    server_repo = AsyncMock()
    server_repo.one_or_none.side_effect = lambda id: servers[id]
    proxy_factory = AsyncMock()
    service = McpSessionLifecycleService(
        state_repo=state_repo,
        mcp_server_repo=server_repo,
        proxy_factory=proxy_factory,
    )

    await service.terminate_for_chat_session(chat_session_id)

    state_repo.list_for_chat_session.assert_awaited_once_with(chat_session_id)
    assert proxy_factory.terminate.await_count == 2
    proxy_factory.terminate.assert_any_await(servers[first_server_id], "mcp-session-1")
    proxy_factory.terminate.assert_any_await(servers[second_server_id], "mcp-session-2")


@pytest.mark.asyncio
async def test_remote_failure_does_not_block_remaining_cleanup():
    chat_session_id = uuid4()
    first_server_id = uuid4()
    second_server_id = uuid4()
    state_repo = AsyncMock()
    state_repo.list_for_chat_session.return_value = [
        (first_server_id, "mcp-session-1"),
        (second_server_id, "mcp-session-2"),
    ]
    server_repo = AsyncMock()
    server_repo.one_or_none.side_effect = [
        SimpleNamespace(id=first_server_id, http_url="https://one"),
        SimpleNamespace(id=second_server_id, http_url="https://two"),
    ]
    proxy_factory = AsyncMock()
    proxy_factory.terminate.side_effect = [RuntimeError("offline"), None]
    service = McpSessionLifecycleService(
        state_repo=state_repo,
        mcp_server_repo=server_repo,
        proxy_factory=proxy_factory,
    )

    await service.terminate_for_chat_session(chat_session_id)

    assert proxy_factory.terminate.await_count == 2
