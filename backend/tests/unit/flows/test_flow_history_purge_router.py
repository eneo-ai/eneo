from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.settings.settings import FlowRunHistoryPurgeRequest
from eneo.settings.settings_router import (
    purge_flow_run_history,
    purge_organization_flow_run_history,
    purge_space_flow_run_history,
)


@pytest.mark.parametrize(
    "endpoint,scope_key",
    [
        (purge_organization_flow_run_history, None),
        (purge_space_flow_run_history, "space_id"),
        (purge_flow_run_history, "flow_id"),
    ],
)
async def test_purge_router_passes_only_resolved_scope_and_validated_request(
    endpoint, scope_key
):
    service = AsyncMock()
    container = MagicMock()
    container.flow_run_retention_policy_service.return_value = service
    scope = {} if scope_key is None else {scope_key: uuid4()}
    result = await endpoint(
        container=container, payload=FlowRunHistoryPurgeRequest(), **scope
    )
    service.purge_due_history.assert_awaited_once_with(dry_run=True, limit=100, **scope)
    assert result is service.purge_due_history.return_value


@pytest.mark.parametrize(
    "payload",
    [
        {"limit": 0},
        {"limit": 501},
        {"limit": True},
        {"limit": "1"},
        {"dry_run": "false"},
        {"tenant_id": str(uuid4())},
    ],
)
def test_purge_request_rejects_invalid_or_untrusted_options(payload):
    with pytest.raises(ValidationError):
        FlowRunHistoryPurgeRequest.model_validate(payload)
