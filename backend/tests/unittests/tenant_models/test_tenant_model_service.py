from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
    resolve_supported_model_kwargs,
)
from eneo.completion_models.presentation.tenant_completion_models_router import (
    TenantCompletionModelCreate,
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
    loaded = SimpleNamespace(id=model.id, name="new-model")

    with (
        patch(
            "eneo.tenant_models.application.tenant_model_service.ModelProviderRepository"
        ) as provider_repository_type,
        patch(
            "eneo.tenant_models.application.tenant_model_service.get_supported_openai_params",
            return_value=["temperature"],
        ) as discover_parameters,
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
    assert model.model_kwargs_capabilities["_evidence"] == "parameter_presence"
    assert (
        resolve_supported_model_kwargs(
            model_kwargs_capabilities=model.model_kwargs_capabilities,
            reasoning=False,
        )
        == SupportedModelKwargs()
    )
    discover_parameters.assert_called_once_with("azure/new-model")
    session.flush.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_completion_model_update_tags_explicit_admin_capabilities() -> None:
    tenant_id = uuid4()
    model = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        provider_id=uuid4(),
        name="model",
        nickname="Model",
        reasoning=False,
        model_kwargs_capabilities=None,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = model
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    explicit = SupportedModelKwargs(temperature=ModelKwargCapability(supported=True))
    loaded = SimpleNamespace(id=model.id, name=model.name)

    with patch(
        "eneo.tenant_models.application.tenant_model_service.CompletionModelRepository"
    ) as completion_repository_type:
        completion_repository_type.return_value.one = AsyncMock(return_value=loaded)
        service = TenantCompletionModelService(
            session=session,
            user=MagicMock(tenant_id=tenant_id),
        )

        result_model = await service.update(
            model.id,
            TenantCompletionModelUpdate(model_kwargs_capabilities=explicit),
        )

    assert result_model is loaded
    assert model.model_kwargs_capabilities["_evidence"] == "admin_explicit"
    assert (
        resolve_supported_model_kwargs(
            model_kwargs_capabilities=model.model_kwargs_capabilities,
            reasoning=False,
        )
        == explicit
    )
    assert (
        SupportedModelKwargs.model_validate(model.model_kwargs_capabilities) == explicit
    )
    session.flush.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_completion_model_create_tags_explicit_admin_capabilities() -> None:
    tenant_id = uuid4()
    provider_id = uuid4()
    session = MagicMock()
    session.flush = AsyncMock()
    explicit = SupportedModelKwargs(temperature=ModelKwargCapability(supported=True))
    loaded = SimpleNamespace(id=uuid4(), name="model")

    with (
        patch(
            "eneo.tenant_models.application.tenant_model_service._validate_active_provider",
            new=AsyncMock(return_value=SimpleNamespace(provider_type="openai")),
        ),
        patch(
            "eneo.tenant_models.application.tenant_model_service._validate_unique_display_name",
            new=AsyncMock(),
        ),
        patch(
            "eneo.tenant_models.application.tenant_model_service.resolve_tenant_security_classification",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "eneo.tenant_models.application.tenant_model_service.CompletionModelRepository"
        ) as completion_repository_type,
    ):
        completion_repository_type.return_value.one = AsyncMock(return_value=loaded)
        service = TenantCompletionModelService(
            session=session,
            user=MagicMock(tenant_id=tenant_id, tenant=MagicMock()),
        )

        result_model = await service.create(
            TenantCompletionModelCreate(
                provider_id=provider_id,
                name="model",
                display_name="Model",
                max_input_tokens=4096,
                max_output_tokens=1024,
                model_kwargs_capabilities=explicit,
            )
        )

    assert result_model is loaded
    persisted = session.add.call_args.args[0].model_kwargs_capabilities
    assert persisted["_evidence"] == "admin_explicit"
    assert (
        resolve_supported_model_kwargs(
            model_kwargs_capabilities=persisted,
            reasoning=False,
        )
        == explicit
    )
    session.flush.assert_awaited_once_with()
