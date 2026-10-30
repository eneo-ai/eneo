from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.flows.application.feature_gate import require_flows_enabled
from eneo.main.exceptions import NotFoundException


async def test_the_gate_checks_the_callers_tenant_and_refuses_as_not_found():
    service = SimpleNamespace(check_is_feature_enabled=AsyncMock(return_value=False))
    tenant_id = uuid4()

    with pytest.raises(NotFoundException):
        await require_flows_enabled(service, tenant_id)

    service.check_is_feature_enabled.assert_awaited_once_with(
        "flows_core", tenant_id=tenant_id
    )


async def test_an_enabled_tenant_passes():
    service = SimpleNamespace(check_is_feature_enabled=AsyncMock(return_value=True))

    await require_flows_enabled(service, uuid4())
