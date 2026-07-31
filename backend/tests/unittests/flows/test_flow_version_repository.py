from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.flows.infrastructure.flow_version_repo import (
    audit_flow_version_template_identity_readiness,
)


@pytest.mark.asyncio
async def test_template_identity_audit_bounds_file_projection_queries() -> None:
    driver_argument_limit = 32_767
    tenant_id = uuid4()
    flow_id = uuid4()
    file_ids = [uuid4() for _index in range(driver_argument_limit + 1)]
    asset_relationships = [
        (tenant_id, flow_id, uuid4(), file_id) for file_id in file_ids
    ]
    asset_relationships.append((tenant_id, flow_id, uuid4(), file_ids[0]))
    definition_result = MagicMock()
    definition_result.tuples.return_value.all.return_value = []
    asset_result = MagicMock()
    asset_result.tuples.return_value.all.return_value = asset_relationships
    session = AsyncMock()
    session.execute.side_effect = [definition_result, asset_result]
    file_repo = AsyncMock()
    file_repo.get_infos_by_ids.return_value = []

    with patch(
        "eneo.flows.infrastructure.flow_version_repo.FileRepository",
        return_value=file_repo,
    ):
        await audit_flow_version_template_identity_readiness(session)

    requested_batches = [
        call.args[0] for call in file_repo.get_infos_by_ids.await_args_list
    ]
    assert requested_batches
    assert all(len(batch) <= driver_argument_limit for batch in requested_batches)
    assert [file_id for batch in requested_batches for file_id in batch] == file_ids
