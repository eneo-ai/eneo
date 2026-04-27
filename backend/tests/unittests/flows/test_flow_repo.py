from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows import FlowFactory
from intric.flows.infrastructure.flow_repo import FlowRepository


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_get_assistant_snapshots_scopes_collection_query_to_tenant() -> None:
    tenant_id = uuid4()
    assistant_id = uuid4()
    kb_id = uuid4()
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _RowsResult(
                [
                    SimpleNamespace(
                        id=assistant_id,
                        completion_model_id=None,
                        instructions="Do work",
                    )
                ]
            ),
            _RowsResult(
                [
                    SimpleNamespace(
                        assistant_id=assistant_id,
                        id=kb_id,
                        name="tenant-visible-kb",
                    )
                ]
            ),
            _RowsResult([]),
            _RowsResult([]),
        ]
    )
    repo = FlowRepository(session=session, factory=FlowFactory())

    snapshots = await repo.get_assistant_snapshots(
        assistant_ids=[assistant_id],
        tenant_id=tenant_id,
    )

    assert snapshots == {
        assistant_id: {
            "instructions": "Do work",
            "model_ref": None,
            "model_label": None,
            "knowledge_refs": [str(kb_id)],
            "knowledge_labels": ["tenant-visible-kb"],
            "mcp_server_refs": [],
            "mcp_server_labels": [],
            "mcp_tool_refs": [],
            "mcp_tool_labels": [],
        }
    }
    collection_stmt = session.execute.await_args_list[1].args[0]
    compiled = str(collection_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "groups.tenant_id" in compiled
    assert tenant_id.hex in compiled
