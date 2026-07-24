from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from eneo.roles.permissions import Permission
from eneo.settings.settings import (
    FlowMappedExecutionPolicyPublic,
    FlowMappedExecutionPolicyUpdate,
)
from eneo.settings.settings_router import (
    get_mapped_execution_policy,
    settings_admin_router,
    update_mapped_execution_policy,
)


def _container(service: AsyncMock) -> MagicMock:
    container = MagicMock()
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )
    return container


@pytest.mark.asyncio
async def test_get_mapped_execution_policy_delegates_to_service() -> None:
    service = AsyncMock()
    service.get_mapped_execution_policy.return_value = FlowMappedExecutionPolicyPublic(
        version=1,
        max_provider_calls_per_mapped_step=8,
        max_estimated_input_tokens_per_mapped_step=None,
    )

    response = await get_mapped_execution_policy(container=_container(service))

    assert response.max_provider_calls_per_mapped_step == 8
    service.get_mapped_execution_policy.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_patch_mapped_execution_policy_preserves_null_clear_intent() -> None:
    service = AsyncMock()
    service.update_mapped_execution_policy.return_value = (
        FlowMappedExecutionPolicyPublic(
            version=1,
            max_provider_calls_per_mapped_step=None,
            max_estimated_input_tokens_per_mapped_step=90_000,
        )
    )
    payload = FlowMappedExecutionPolicyUpdate(max_provider_calls_per_mapped_step=None)

    response = await update_mapped_execution_policy(
        payload=payload,
        container=_container(service),
    )

    assert response.max_provider_calls_per_mapped_step is None
    assert payload.model_dump(exclude_unset=True) == {
        "max_provider_calls_per_mapped_step": None
    }
    service.update_mapped_execution_policy.assert_awaited_once_with(payload)


def test_mapped_execution_policy_openapi_is_complete_for_admin_clients() -> None:
    app = FastAPI()
    app.include_router(settings_admin_router, prefix="/api/v1/settings")
    schema = app.openapi()
    path = schema["paths"]["/api/v1/settings/flow-mapped-execution-policy"]

    assert path["get"]["operationId"] == "get_mapped_execution_policy"
    assert path["patch"]["operationId"] == "update_mapped_execution_policy"
    assert set(path["get"]["responses"]) >= {"200", "403"}
    assert set(path["patch"]["responses"]) >= {"200", "400", "403", "422"}

    schemas = schema["components"]["schemas"]
    for schema_name in (
        "FlowMappedExecutionPolicyPublic",
        "FlowMappedExecutionPolicyUpdate",
    ):
        policy_schema = schemas[schema_name]
        assert policy_schema["example"]
        for field_name in (
            "max_provider_calls_per_mapped_step",
            "max_estimated_input_tokens_per_mapped_step",
        ):
            assert policy_schema["properties"][field_name]["description"]
