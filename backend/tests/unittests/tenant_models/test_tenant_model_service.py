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
    _snapshot_completion_capabilities,
)


@pytest.mark.asyncio
async def test_completion_model_route_changes_refresh_discovered_capabilities() -> None:
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
    discovered = {
        "temperature": {"supported": True},
        "_evidence": "provider_discovered",
    }

    with (
        patch(
            "eneo.tenant_models.application.tenant_model_service.ModelProviderRepository"
        ) as provider_repository_type,
        patch(
            "eneo.tenant_models.application.tenant_model_service.CompletionModelRepository"
        ) as completion_repository_type,
        patch(
            "eneo.tenant_models.application.tenant_model_service."
            "_snapshot_completion_capabilities",
            return_value=discovered,
        ) as snapshot_capabilities,
    ):
        provider_repository_type.return_value.get_by_id = AsyncMock(
            return_value=SimpleNamespace(provider_type="azure")
        )
        completion_repository_type.return_value.one = AsyncMock(return_value=loaded)
        service = TenantCompletionModelService(session=session, user=user)

        for payload in (
            TenantCompletionModelUpdate(name="new-model"),
            TenantCompletionModelUpdate(reasoning=True),
        ):
            model.model_kwargs_capabilities = {"temperature": {"supported": True}}
            result_model = await service.update(model.id, payload)

            assert result_model is loaded
            assert model.model_kwargs_capabilities == discovered

    assert model.name == "new-model"
    assert model.reasoning is True
    assert provider_repository_type.return_value.get_by_id.await_count == 2
    assert snapshot_capabilities.call_count == 2
    assert session.flush.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(
            TenantCompletionModelUpdate(name="moved-model"),
            False,
            id="rename-withdraws-the-declaration",
        ),
        pytest.param(
            TenantCompletionModelUpdate(name="declared-model"),
            True,
            id="resent-unchanged-name-keeps-it",
        ),
        pytest.param(
            TenantCompletionModelUpdate(description="Same route, new blurb"),
            True,
            id="unrelated-edit-keeps-it",
        ),
        pytest.param(
            TenantCompletionModelUpdate(
                name="moved-model",
                supports_strict_tool_schema=True,
            ),
            True,
            id="rename-may-redeclare-the-new-route",
        ),
    ],
)
async def test_strict_tool_schema_declaration_follows_the_model_route(
    payload: TenantCompletionModelUpdate,
    expected: bool,
) -> None:
    tenant_id = uuid4()
    model = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        provider_id=uuid4(),
        name="declared-model",
        nickname="Declared model",
        reasoning=False,
        model_kwargs_capabilities=None,
        supports_strict_tool_schema=True,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = model
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()

    with (
        patch(
            "eneo.tenant_models.application.tenant_model_service.ModelProviderRepository"
        ) as provider_repository_type,
        patch(
            "eneo.tenant_models.application.tenant_model_service.CompletionModelRepository"
        ) as completion_repository_type,
    ):
        provider_repository_type.return_value.get_by_id = AsyncMock(
            return_value=SimpleNamespace(provider_type="openai")
        )
        completion_repository_type.return_value.one = AsyncMock(
            return_value=SimpleNamespace(id=model.id, name=model.name)
        )
        service = TenantCompletionModelService(
            session=session,
            user=MagicMock(tenant_id=tenant_id),
        )

        await service.update(model.id, payload)

    assert model.supports_strict_tool_schema is expected


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
    loaded = SimpleNamespace(id=model.id, name="renamed-model")

    with (
        patch(
            "eneo.tenant_models.application.tenant_model_service.ModelProviderRepository"
        ) as provider_repository_type,
        patch(
            "eneo.tenant_models.application.tenant_model_service.CompletionModelRepository"
        ) as completion_repository_type,
    ):
        completion_repository_type.return_value.one = AsyncMock(return_value=loaded)
        service = TenantCompletionModelService(
            session=session,
            user=MagicMock(tenant_id=tenant_id),
        )

        result_model = await service.update(
            model.id,
            TenantCompletionModelUpdate(
                name="renamed-model",
                reasoning=True,
                model_kwargs_capabilities=explicit,
            ),
        )

    assert result_model is loaded
    assert model.name == "renamed-model"
    assert model.reasoning is True
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
    provider_repository_type.assert_not_called()
    session.flush.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_completion_model_update_distinguishes_omission_from_explicit_null() -> (
    None
):
    tenant_id = uuid4()
    persisted_capabilities = {
        "temperature": {"supported": True},
        "_evidence": "admin_explicit",
    }
    model = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        provider_id=uuid4(),
        name="model",
        nickname="Model",
        reasoning=False,
        max_input_tokens=4096,
        model_kwargs_capabilities=persisted_capabilities,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = model
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    loaded = SimpleNamespace(id=model.id, name=model.name)

    with patch(
        "eneo.tenant_models.application.tenant_model_service.CompletionModelRepository"
    ) as completion_repository_type:
        completion_repository_type.return_value.one = AsyncMock(return_value=loaded)
        service = TenantCompletionModelService(
            session=session,
            user=MagicMock(tenant_id=tenant_id),
        )

        omitted_result = await service.update(
            model.id,
            TenantCompletionModelUpdate(max_input_tokens=8192),
        )
        assert model.model_kwargs_capabilities is persisted_capabilities

        null_result = await service.update(
            model.id,
            TenantCompletionModelUpdate(model_kwargs_capabilities=None),
        )

    assert omitted_result is loaded
    assert null_result is loaded
    assert model.max_input_tokens == 8192
    assert model.model_kwargs_capabilities is None
    assert session.flush.await_count == 2


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


@pytest.mark.asyncio
async def test_completion_model_create_without_capabilities_persists_discovery() -> (
    None
):
    tenant_id = uuid4()
    provider_id = uuid4()
    session = MagicMock()
    session.flush = AsyncMock()
    loaded = SimpleNamespace(id=uuid4(), name="model")
    discovered = {
        "temperature": {"supported": True},
        "_evidence": "provider_discovered",
    }

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
        patch(
            "eneo.tenant_models.application.tenant_model_service."
            "_snapshot_completion_capabilities",
            return_value=discovered,
        ),
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
            )
        )

    assert result_model is loaded
    assert session.add.call_args.args[0].model_kwargs_capabilities == discovered
    session.flush.assert_awaited_once_with()


@pytest.mark.parametrize("discovery", [None, RuntimeError("metadata unavailable")])
def test_incomplete_capability_discovery_persists_no_trusted_snapshot(
    discovery: None | Exception,
) -> None:
    with patch(
        "eneo.tenant_models.application.tenant_model_service."
        "get_supported_openai_params",
        side_effect=discovery if isinstance(discovery, Exception) else None,
        return_value=discovery,
    ):
        assert _snapshot_completion_capabilities("openai", "model") is None


def test_declared_reasoning_does_not_widen_provider_discovery() -> None:
    with patch(
        "eneo.tenant_models.application.tenant_model_service."
        "get_supported_openai_params",
        return_value=[],
    ):
        persisted = _snapshot_completion_capabilities("openai", "reasoning-model")

    assert persisted is not None
    assert persisted["_evidence"] == "provider_discovered"
    assert (
        resolve_supported_model_kwargs(
            model_kwargs_capabilities=persisted,
            reasoning=True,
        ).reasoning_effort.supported
        is False
    )


def test_missing_reasoning_metadata_persists_no_reasoning_control() -> None:
    with (
        patch(
            "eneo.tenant_models.application.tenant_model_service."
            "get_supported_openai_params",
            return_value=["reasoning_effort"],
        ),
        patch(
            "eneo.tenant_models.application.tenant_model_service.get_model_info",
            side_effect=RuntimeError("value metadata unavailable"),
        ),
    ):
        persisted = _snapshot_completion_capabilities("openai", "reasoning-model")

    assert persisted is not None
    assert persisted["_evidence"] == "provider_discovered"
    assert (
        resolve_supported_model_kwargs(
            model_kwargs_capabilities=persisted,
            reasoning=True,
        ).reasoning_effort.supported
        is False
    )
