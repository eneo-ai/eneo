from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from eneo.completion_models.domain.completion_model import CompletionModel
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.tenants.tenant import TenantInDB


def _load_model(
    output_tokens: int | None, window: int | None = None
) -> CompletionModel:
    now = datetime.now(timezone.utc)
    row = CompletionModels(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="custom-deployment",
        nickname="Custom deployment",
        litellm_model_name="openai/custom-deployment",
        tenant_id=uuid4(),
        provider_id=uuid4(),
        max_input_tokens=1_000_000,
        max_output_tokens=output_tokens,
        context_window_tokens=window,
        open_source=False,
        is_deprecated=False,
        is_enabled=True,
        is_default=False,
        vision=False,
        reasoning=False,
        supports_tool_calling=True,
        supports_strict_tool_schema=False,
    )
    return CompletionModel.create_from_db(
        row,
        tenant=TenantInDB.model_construct(id=row.tenant_id, name="Test tenant"),
        provider_type="openai",
    )


def test_unknown_output_limit_is_not_inferred_from_the_context_window() -> None:
    with patch(
        "eneo.model_providers.domain.model_defaults._get_model_cost", return_value={}
    ):
        with pytest.raises(ValueError, match="missing max_output_tokens"):
            _load_model(None)


@pytest.mark.parametrize(
    ("configured_output", "expected_output"), [(None, 128_000), (32_000, 32_000)]
)
def test_model_limits_use_configured_values_or_known_provider_metadata(
    configured_output: int | None, expected_output: int
) -> None:
    with patch(
        "eneo.model_providers.domain.model_defaults._get_model_cost",
        return_value={
            "openai/custom-deployment": {
                "max_input_tokens": 1_000_000,
                "max_output_tokens": 128_000,
            }
        },
    ):
        model = _load_model(configured_output)

    assert model.max_input_tokens == 1_000_000
    assert model.max_output_tokens == expected_output


@pytest.mark.parametrize("window", [None, 1_128_000])
def test_shared_window_survives_hydration_and_public_projection(window) -> None:
    from eneo.ai_models.completion_models.completion_model import CompletionModelPublic
    from eneo.completion_models.domain.model_capacity import ModelCapacity
    from eneo.completion_models.presentation.completion_model_assembler import (
        CompletionModelAssembler,
    )

    model = _load_model(128_000, window)
    assert model.capacity == ModelCapacity(1_000_000, 128_000, window)
    assert CompletionModelPublic.from_domain(model).context_window_tokens == window
    assembler = CompletionModelAssembler()
    assert (
        assembler.from_completion_model_to_model(model).context_window_tokens == window
    )


@pytest.mark.parametrize("value", [0, -1])
def test_admin_window_declarations_must_be_positive(value) -> None:
    from pydantic import ValidationError

    from eneo.completion_models.presentation.tenant_completion_models_router import (
        TenantCompletionModelCreate,
        TenantCompletionModelUpdate,
    )

    with pytest.raises(ValidationError):
        TenantCompletionModelUpdate(context_window_tokens=value)
    with pytest.raises(ValidationError):
        TenantCompletionModelCreate(
            provider_id=uuid4(),
            name="custom",
            display_name="Custom",
            max_input_tokens=100,
            max_output_tokens=80,
            context_window_tokens=value,
        )


async def test_admin_window_create_read_declare_keep_clear_and_route_move() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from eneo.completion_models.presentation.tenant_completion_models_router import (
        TenantCompletionModelCreate,
        TenantCompletionModelUpdate,
    )
    from eneo.database.tables.model_providers_table import ModelProviders
    from eneo.tenant_models.application.tenant_model_service import (
        TenantCompletionModelService,
    )
    from eneo.users.user import UserInDB

    tenant = TenantInDB.model_construct(id=uuid4(), name="Test tenant")
    user = UserInDB.model_construct(id=uuid4(), tenant_id=tenant.id, tenant=tenant)
    provider = ModelProviders(
        id=uuid4(), tenant_id=tenant.id, provider_type="openai", is_active=True
    )
    session = MagicMock()
    session.flush = AsyncMock()
    rows = []

    def add(row):
        row.id = uuid4()
        row.created_at = row.updated_at = datetime.now(timezone.utc)
        rows.append(row)

    async def read(*, model_id):
        return CompletionModel.create_from_db(rows[0], tenant, provider_type="openai")

    session.add.side_effect = add
    result = MagicMock()
    result.scalar_one_or_none.side_effect = lambda: rows[0]
    session.execute = AsyncMock(return_value=result)
    owner = "eneo.tenant_models.application.tenant_model_service."
    with (
        patch(owner + "_validate_active_provider", AsyncMock(return_value=provider)),
        patch(owner + "_validate_unique_display_name", AsyncMock()),
        patch(
            owner + "resolve_tenant_security_classification",
            AsyncMock(return_value=None),
        ),
        patch(owner + "_snapshot_completion_capabilities", return_value=None),
        patch(owner + "CompletionModelRepository") as repo,
        patch(owner + "ModelProviderRepository") as providers,
    ):
        repo.return_value.one = AsyncMock(side_effect=read)
        providers.return_value.get_by_id = AsyncMock(return_value=provider)
        service = TenantCompletionModelService(session, user)
        model = await service.create(
            TenantCompletionModelCreate(
                provider_id=provider.id,
                name="custom",
                display_name="Custom",
                max_input_tokens=100,
                max_output_tokens=80,
                context_window_tokens=120,
            )
        )
        assert model.context_window_tokens == 120
        for payload, expected in (
            (TenantCompletionModelUpdate(context_window_tokens=140), 140),
            (TenantCompletionModelUpdate(description="Updated"), 140),
            (TenantCompletionModelUpdate(context_window_tokens=None), None),
            (TenantCompletionModelUpdate(context_window_tokens=120), 120),
            (TenantCompletionModelUpdate(name="renamed"), None),
            (
                TenantCompletionModelUpdate(
                    name="redeclared", context_window_tokens=160
                ),
                160,
            ),
            (TenantCompletionModelUpdate(name="redeclared"), 160),
        ):
            model = await service.update(model.id, payload)
            assert model.context_window_tokens == expected
            assert (model.max_input_tokens, model.max_output_tokens) == (100, 80)


@pytest.mark.parametrize("redeclare", [False, True])
async def test_metadata_route_update_withdraws_only_omitted_declarations(
    redeclare,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from eneo.ai_models.completion_models.completion_model import (
        COMPLETION_MODEL_ROUTE_FIELDS,
        CompletionModelUpdate,
    )
    from eneo.ai_models.completion_models.completion_models_repo import (
        CompletionModelsRepository,
    )

    row = CompletionModels(name="old", provider_id=uuid4())
    result = MagicMock()
    result.one_or_none.return_value = (
        *[getattr(row, name) for name in COMPLETION_MODEL_ROUTE_FIELDS],
        "openai",
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    repo = CompletionModelsRepository(session)
    repo.delegate = MagicMock()
    repo.delegate.update = AsyncMock()
    payload = CompletionModelUpdate(
        id=uuid4(),
        name="new",
        supports_strict_tool_schema=True,
        **({"context_window_tokens": 120} if redeclare else {}),
    )
    await repo.update_model(payload)
    written = repo.delegate.update.call_args.args[0].model_dump(exclude_unset=True)
    assert written["context_window_tokens"] == (120 if redeclare else None)
    assert written["supports_strict_tool_schema"] is True


@pytest.mark.parametrize("request_type", ["create", "update"])
@pytest.mark.parametrize("value", [0, -1])
def test_sysadmin_window_declarations_must_be_positive(request_type, value) -> None:
    from pydantic import ValidationError

    from eneo.ai_models.completion_models.completion_model import (
        CompletionModelCreate,
        CompletionModelUpdate,
    )

    schema = (
        CompletionModelCreate if request_type == "create" else CompletionModelUpdate
    )
    with pytest.raises(ValidationError) as error:
        schema.model_validate(
            {
                "id": uuid4(),
                "name": "custom",
                "max_input_tokens": 100,
                "max_output_tokens": 80,
                "vision": False,
                "reasoning": False,
                "is_deprecated": False,
                "context_window_tokens": value,
            }
        )
    assert [(item["loc"], item["type"]) for item in error.value.errors()] == [
        (("context_window_tokens",), "greater_than")
    ]


@pytest.mark.parametrize("request_type", ["create", "update"])
@pytest.mark.parametrize(
    "declaration", [{}, {"context_window_tokens": None}, {"context_window_tokens": 120}]
)
def test_sysadmin_window_preserves_optional_declarations(
    request_type, declaration
) -> None:
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModelCreate,
        CompletionModelUpdate,
    )

    schema = (
        CompletionModelCreate if request_type == "create" else CompletionModelUpdate
    )
    payload = schema.model_validate(
        {
            "id": uuid4(),
            "name": "custom",
            "max_input_tokens": 100,
            "max_output_tokens": 80,
            "vision": False,
            "reasoning": False,
            "is_deprecated": False,
            **declaration,
        }
    )
    assert payload.context_window_tokens == declaration.get("context_window_tokens")
    assert ("context_window_tokens" in payload.model_fields_set) == (
        "context_window_tokens" in declaration
    )
