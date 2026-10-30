"""A completion model's token limits are required and survive a route change.

Renaming a model (or any other route move) once withdrew both limits, and the
save was allowed, so every chat and app on that model failed until an admin
entered them again. On develop the limits are required integers: a route
change keeps them and a save that leaves one blank is refused.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.completion_models.domain.completion_model import CompletionModel
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.main.exceptions import ValidationException
from eneo.tenants.tenant import TenantInDB

LIMITS = ("max_input_tokens", "max_output_tokens")


def _tenant_service(row: CompletionModels):
    from eneo.database.tables.model_providers_table import ModelProviders
    from eneo.tenant_models.application.tenant_model_service import (
        TenantCompletionModelService,
    )
    from eneo.users.user import UserInDB

    tenant = TenantInDB.model_construct(id=row.tenant_id, name="Test tenant")
    user = UserInDB.model_construct(id=uuid4(), tenant_id=tenant.id, tenant=tenant)
    provider = ModelProviders(
        id=row.provider_id, tenant_id=tenant.id, provider_type="openai"
    )
    session = MagicMock()
    session.flush = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result)

    async def read(*, model_id):
        return CompletionModel.create_from_db(row, tenant, provider_type="openai")

    owner = "eneo.tenant_models.application.tenant_model_service."
    patches = (
        patch(owner + "_validate_unique_display_name", AsyncMock()),
        patch(owner + "_snapshot_completion_capabilities", return_value=None),
        patch(owner + "_audit", AsyncMock()),
        patch(owner + "CompletionModelRepository"),
        patch(owner + "ModelProviderRepository"),
    )
    return TenantCompletionModelService(session, user), provider, read, patches


def _row(*, max_input_tokens: int | None, max_output_tokens: int | None):
    now = datetime.now(timezone.utc)
    return CompletionModels(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="gpt-5.4-mini",
        nickname="Mini",
        tenant_id=uuid4(),
        provider_id=uuid4(),
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        open_source=False,
        is_deprecated=False,
        is_enabled=True,
        is_default=False,
        vision=False,
        reasoning=False,
        supports_tool_calling=True,
        supports_strict_tool_schema=True,
    )


async def _update(row: CompletionModels, **fields):
    from eneo.completion_models.presentation.tenant_completion_models_router import (
        TenantCompletionModelUpdate,
    )

    service, provider, read, patches = _tenant_service(row)
    with patches[0], patches[1], patches[2], patches[3] as repo, patches[4] as prov:
        repo.return_value.one = AsyncMock(side_effect=read)
        prov.return_value.get_by_id = AsyncMock(return_value=provider)
        return await service.update(row.id, TenantCompletionModelUpdate(**fields))


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "gpt-5.4-mini-2026"},
        {"name": "gpt-5.4-mini-2026", "display_name": "Renamed"},
        {"display_name": "Renamed"},
        {"description": "Unrelated edit"},
    ],
)
async def test_a_tenant_rename_or_edit_keeps_both_token_limits(fields) -> None:
    row = _row(max_input_tokens=272_000, max_output_tokens=128_000)

    model = await _update(row, **fields)

    assert (model.max_input_tokens, model.max_output_tokens) == (272_000, 128_000)
    assert (row.max_input_tokens, row.max_output_tokens) == (272_000, 128_000)


async def test_a_tenant_rename_still_withdraws_the_strict_schema_declaration() -> None:
    row = _row(max_input_tokens=272_000, max_output_tokens=128_000)

    model = await _update(row, name="gpt-5.4-mini-2026")

    assert model.supports_strict_tool_schema is False


async def test_a_rename_with_new_limits_stores_the_new_limits() -> None:
    row = _row(max_input_tokens=272_000, max_output_tokens=128_000)

    model = await _update(
        row, name="other", max_input_tokens=100_000, max_output_tokens=8_000
    )

    assert (model.max_input_tokens, model.max_output_tokens) == (100_000, 8_000)


@pytest.mark.parametrize("dimension", LIMITS)
def test_a_tenant_update_refuses_a_blank_token_limit(dimension) -> None:
    from eneo.completion_models.presentation.tenant_completion_models_router import (
        TenantCompletionModelUpdate,
    )

    with pytest.raises(ValidationError, match=dimension):
        TenantCompletionModelUpdate.model_validate({dimension: None})


@pytest.mark.parametrize("dimension", LIMITS)
async def test_saving_a_model_whose_stored_limit_is_missing_is_refused(
    dimension,
) -> None:
    limits = {"max_input_tokens": 272_000, "max_output_tokens": 128_000}
    limits[dimension] = None
    row = _row(**limits)

    with pytest.raises(ValidationException, match=dimension):
        await _update(row, description="Unrelated edit")


async def test_saving_a_model_that_declares_its_missing_limit_is_allowed() -> None:
    row = _row(max_input_tokens=None, max_output_tokens=None)

    model = await _update(row, max_input_tokens=100_000, max_output_tokens=8_000)

    assert (model.max_input_tokens, model.max_output_tokens) == (100_000, 8_000)


@pytest.mark.parametrize("redeclare", [False, True])
async def test_a_sysadmin_route_move_keeps_the_stored_limits(redeclare) -> None:
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
    stored_limits = MagicMock()
    stored_limits.one_or_none.return_value = (100, 80)
    # The stored limits the partial save keeps, then the stored route.
    session.execute = AsyncMock(
        side_effect=[result] if redeclare else [stored_limits, result]
    )
    repo = CompletionModelsRepository(session)
    repo.delegate = MagicMock()
    repo.delegate.update = AsyncMock()

    await repo.update_model(
        CompletionModelUpdate(
            id=uuid4(),
            name="new",
            **({"max_input_tokens": 100, "max_output_tokens": 80} if redeclare else {}),
        )
    )

    written = repo.delegate.update.call_args.args[0].model_dump(exclude_unset=True)
    assert written["supports_strict_tool_schema"] is False
    if redeclare:
        assert (written["max_input_tokens"], written["max_output_tokens"]) == (100, 80)
    else:
        assert not set(LIMITS) & written.keys()


@pytest.mark.parametrize("request_type", ["create", "update"])
@pytest.mark.parametrize("dimension", LIMITS)
def test_sysadmin_requests_refuse_a_blank_token_limit(request_type, dimension) -> None:
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModelCreate,
        CompletionModelUpdate,
    )

    schema = (
        CompletionModelCreate if request_type == "create" else CompletionModelUpdate
    )
    payload = {
        "id": uuid4(),
        "name": "custom",
        "max_input_tokens": 100,
        "max_output_tokens": 80,
        "vision": False,
        "reasoning": False,
        "is_deprecated": False,
    }
    payload[dimension] = None
    with pytest.raises(ValidationError, match=dimension):
        schema.model_validate(payload)
    if request_type == "create":
        del payload[dimension]
        with pytest.raises(ValidationError, match=dimension):
            schema.model_validate(payload)


def _sysadmin_repo(stored_limits: tuple[int | None, int | None] | None):
    from eneo.ai_models.completion_models.completion_models_repo import (
        CompletionModelsRepository,
    )

    result = MagicMock()
    result.one_or_none.return_value = stored_limits
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    repo = CompletionModelsRepository(session)
    repo.delegate = MagicMock()
    repo.delegate.update = AsyncMock()
    return repo


@pytest.mark.parametrize("dimension", LIMITS)
async def test_a_sysadmin_save_of_a_model_missing_a_stored_limit_is_refused(
    dimension,
) -> None:
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModelUpdate,
    )

    stored = (None, 80) if dimension == "max_input_tokens" else (100, None)
    repo = _sysadmin_repo(stored)

    with pytest.raises(ValidationException, match=dimension):
        await repo.update_model(
            CompletionModelUpdate(id=uuid4(), description="Unrelated edit")
        )
    repo.delegate.update.assert_not_awaited()


async def test_a_sysadmin_save_that_declares_the_missing_limits_is_allowed() -> None:
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModelUpdate,
    )

    repo = _sysadmin_repo((None, None))

    await repo.update_model(
        CompletionModelUpdate(id=uuid4(), max_input_tokens=100, max_output_tokens=80)
    )

    repo.delegate.update.assert_awaited_once()


async def test_a_sysadmin_save_of_a_model_with_both_limits_is_allowed() -> None:
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModelUpdate,
    )

    repo = _sysadmin_repo((100, 80))

    await repo.update_model(CompletionModelUpdate(id=uuid4(), description="Edit"))

    repo.delegate.update.assert_awaited_once()
