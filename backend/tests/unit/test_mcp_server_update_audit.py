"""Audit contract for the MCP server update route.

``forward_identity`` controls PII egress to a third-party server, so flipping
it must be visible in the MCP_SERVER_UPDATED audit event with old/new values,
in both directions, and must not appear when the update leaves it untouched.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.audit.domain.action_types import ActionType
from eneo.mcp_servers.presentation.mcp_server_router import update_mcp_server
from eneo.mcp_servers.presentation.models import MCPServerUpdate


def _server(forward_identity: bool) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name="srv",
        http_url="http://localhost:9000",
        http_auth_type="bearer",
        description=None,
        tags=None,
        forward_identity=forward_identity,
    )


def _make_container(old_server, updated_server):
    service = MagicMock()
    service.get_mcp_server = AsyncMock(return_value=old_server)
    service.update_mcp_server = AsyncMock(
        return_value=SimpleNamespace(server=updated_server, connection=None)
    )

    assembler = MagicMock()
    audit_service = MagicMock()
    audit_service.log_async = AsyncMock()
    user = SimpleNamespace(
        id=uuid4(),
        username="admin",
        email="admin@kommun.se",
        tenant_id=uuid4(),
    )

    container = SimpleNamespace(
        mcp_server_service=lambda: service,
        mcp_server_assembler=lambda: assembler,
        audit_service=lambda: audit_service,
        user=lambda: user,
    )
    return container, audit_service


async def _audited_changes(old: bool, new: bool | None) -> dict:
    old_server = _server(forward_identity=old)
    container, audit_service = _make_container(
        old_server, _server(new if new is not None else old)
    )

    await update_mcp_server(
        id=old_server.id,
        data=MCPServerUpdate(forward_identity=new),
        container=container,
    )

    audit_service.log_async.assert_awaited_once()
    kwargs = audit_service.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.MCP_SERVER_UPDATED
    return kwargs["metadata"].get("changes", {})


@pytest.mark.asyncio
async def test_enabling_forward_identity_is_audited_with_old_and_new():
    changes = await _audited_changes(old=False, new=True)
    assert changes["forward_identity"] == {"old": False, "new": True}


@pytest.mark.asyncio
async def test_disabling_forward_identity_is_audited_with_old_and_new():
    changes = await _audited_changes(old=True, new=False)
    assert changes["forward_identity"] == {"old": True, "new": False}


@pytest.mark.asyncio
async def test_update_without_forward_identity_records_no_change():
    changes = await _audited_changes(old=True, new=None)
    assert "forward_identity" not in changes
