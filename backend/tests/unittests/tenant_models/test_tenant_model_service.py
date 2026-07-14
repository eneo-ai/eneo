from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.completion_models.presentation.tenant_completion_models_router import (
    TenantCompletionModelUpdate,
)
from eneo.tenant_models.application.tenant_model_service import (
    TenantCompletionModelService,
)


@pytest.mark.asyncio
async def test_completion_model_route_change_refreshes_persisted_capabilities() -> None:
    tenant_id = uuid4()
    provider_id = uuid4()
    model = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        provider_id=provider_id,
        name="old-model",
        nickname="Old model",
        reasoning=False,
        model_kwargs_capabilities={"temperature": {"supported": True}},
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = model
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    user = MagicMock(tenant_id=tenant_id)
    refreshed = {"temperature": {"supported": False}}
    loaded = SimpleNamespace(id=model.id, name="new-model")

    with (
        patch(
            "eneo.tenant_models.application.tenant_model_service.ModelProviderRepository"
        ) as provider_repository_type,
        patch(
            "eneo.tenant_models.application.tenant_model_service._snapshot_completion_capabilities",
            return_value=refreshed,
        ) as snapshot_capabilities,
        patch(
            "eneo.tenant_models.application.tenant_model_service.CompletionModelRepository"
        ) as completion_repository_type,
    ):
        provider_repository_type.return_value.get_by_id = AsyncMock(
            return_value=SimpleNamespace(provider_type="azure")
        )
        completion_repository_type.return_value.one = AsyncMock(return_value=loaded)
        service = TenantCompletionModelService(session=session, user=user)

        result_model = await service.update(
            model.id,
            TenantCompletionModelUpdate(name="new-model"),
        )

    assert result_model is loaded
    assert model.name == "new-model"
    assert model.model_kwargs_capabilities == refreshed
    snapshot_capabilities.assert_called_once_with(
        "azure",
        "new-model",
        reasoning=False,
    )
    session.flush.assert_awaited_once_with()
