from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from eneo.completion_models.domain.completion_model import CompletionModel
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.tenants.tenant import TenantInDB


def _load_model(
    output_tokens: int | None,
    window: int | None = None,
    input_tokens: int | None = 1_000_000,
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
        max_input_tokens=input_tokens,
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
        assert _load_model(None).max_output_tokens is None


@pytest.mark.parametrize(
    ("configured_output", "expected_output"), [(None, None), (32_000, 32_000)]
)
def test_model_limits_preserve_only_configured_values(
    configured_output: int | None, expected_output: int | None
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


@pytest.mark.parametrize(
    "dimension", ["max_input_tokens", "max_output_tokens", "context_window_tokens"]
)
async def test_admin_window_create_read_declare_keep_clear_and_route_move(
    dimension,
) -> None:
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
        initial = {
            "max_input_tokens": 100,
            "max_output_tokens": 80,
            "context_window_tokens": 120,
        }
        assert getattr(model, dimension) == initial[dimension]
        for payload, expected in (
            (TenantCompletionModelUpdate(**{dimension: 140}), 140),
            (TenantCompletionModelUpdate(description="Updated"), 140),
            (TenantCompletionModelUpdate(**{dimension: None}), None),
            (TenantCompletionModelUpdate(**{dimension: 120}), 120),
            (TenantCompletionModelUpdate(name="renamed"), None),
            (TenantCompletionModelUpdate(name="custom"), None),
            (TenantCompletionModelUpdate(name="redeclared", **{dimension: 160}), 160),
            (TenantCompletionModelUpdate(name="redeclared"), 160),
        ):
            model = await service.update(model.id, payload)
            assert getattr(model, dimension) == expected


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
        **(
            {
                "context_window_tokens": 120,
                "max_input_tokens": 100,
                "max_output_tokens": 80,
            }
            if redeclare
            else {}
        ),
    )
    await repo.update_model(payload)
    written = repo.delegate.update.call_args.args[0].model_dump(exclude_unset=True)
    assert written["context_window_tokens"] == (120 if redeclare else None)
    assert written["max_input_tokens"] == (100 if redeclare else None)
    assert written["max_output_tokens"] == (80 if redeclare else None)
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


@pytest.mark.parametrize(
    "input_tokens,output_tokens", [(None, 80), (100, None), (None, None), (100, 80)]
)
def test_stored_limits_survive_hydration_and_projections(input_tokens, output_tokens):
    from eneo.ai_models.completion_models.completion_model import CompletionModelPublic
    from eneo.completion_models.presentation.completion_model_assembler import (
        CompletionModelAssembler,
    )

    model = _load_model(output_tokens, input_tokens=input_tokens)
    assert model.token_limit == input_tokens
    assert model.capacity.max_input_tokens == input_tokens
    for public in (
        CompletionModelPublic.from_domain(model),
        CompletionModelAssembler().from_completion_model_to_model(model),
    ):
        assert public.max_input_tokens == input_tokens
        assert public.max_output_tokens == output_tokens
        assert public.context_window_tokens is None


@pytest.mark.parametrize("dimension", ["max_input_tokens", "max_output_tokens"])
@pytest.mark.parametrize("value", [0, -1])
def test_tenant_capacity_declarations_must_be_positive(dimension, value):
    from pydantic import ValidationError

    from eneo.completion_models.presentation.tenant_completion_models_router import (
        TenantCompletionModelCreate,
        TenantCompletionModelUpdate,
    )

    with pytest.raises(ValidationError):
        TenantCompletionModelUpdate(**{dimension: value})
    values = dict(
        provider_id=uuid4(),
        name="custom",
        display_name="Custom",
        max_input_tokens=100,
        max_output_tokens=80,
    )
    values[dimension] = value
    with pytest.raises(ValidationError):
        TenantCompletionModelCreate(**values)


@pytest.mark.parametrize("dimension", ["max_input_tokens", "max_output_tokens"])
def test_tenant_creation_requires_declared_ceiling(dimension):
    from pydantic import ValidationError

    from eneo.completion_models.presentation.tenant_completion_models_router import (
        TenantCompletionModelCreate,
    )

    values = dict(
        provider_id=uuid4(),
        name="custom",
        display_name="Custom",
        max_input_tokens=100,
        max_output_tokens=80,
    )
    values[dimension] = None
    with pytest.raises(ValidationError):
        TenantCompletionModelCreate(**values)
    del values[dimension]
    with pytest.raises(ValidationError):
        TenantCompletionModelCreate(**values)


async def test_sysadmin_route_move_does_not_redeclare_omitted_output():
    from unittest.mock import AsyncMock, MagicMock

    from eneo.ai_models.completion_models.completion_model import (
        CompletionModelSparse,
        CompletionModelUpdate,
    )
    from eneo.sysadmin.sysadmin_router import update_completion_model_metadata

    model = _load_model(80, input_tokens=100)
    session = MagicMock()
    session.begin.return_value = AsyncMock()
    container = MagicMock()
    container.session.return_value = session
    with (
        patch(
            "eneo.sysadmin.sysadmin_router.validate_unique_display_name", AsyncMock()
        ),
        patch("eneo.sysadmin.sysadmin_router.CompletionModelsRepository") as repo,
    ):
        repo.return_value.delegate.get_by = AsyncMock(return_value=model)
        repo.return_value.update_model = AsyncMock(
            return_value=CompletionModelSparse.model_validate(
                model, from_attributes=True
            )
        )
        await update_completion_model_metadata(
            model.id,
            CompletionModelUpdate(id=model.id, name="moved", max_input_tokens=120),
            container,
        )
        written = repo.return_value.update_model.call_args.args[0]
        assert "max_output_tokens" not in written.model_fields_set


@pytest.mark.parametrize("other_tenant,deleted", [(True, False), (False, True)])
async def test_reads_preserve_tenant_and_soft_deletion_boundaries(
    other_tenant, deleted
):
    from unittest.mock import AsyncMock, MagicMock

    import sqlalchemy as sa

    from eneo.completion_models.domain.completion_model_repo import (
        CompletionModelRepository,
    )
    from eneo.main.exceptions import NotFoundException

    tenant = TenantInDB.model_construct(id=uuid4(), name="Tenant")
    table = CompletionModels.__table__
    metadata = sa.MetaData()
    visible = sa.Table(
        table.name,
        metadata,
        *(
            sa.Column(name, table.c[name].type)
            for name in ("id", "tenant_id", "deleted_at")
        ),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    model_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            visible.insert().values(
                id=model_id,
                tenant_id=uuid4() if other_tenant else tenant.id,
                deleted_at=datetime.now(timezone.utc) if deleted else None,
            )
        )
        session = MagicMock()
        session.execute = AsyncMock(
            side_effect=lambda stmt: connection.execute(
                sa.select(table.c.id).where(stmt.whereclause)
            )
        )
        repo = CompletionModelRepository(session=session, tenant=tenant)
        with pytest.raises(NotFoundException):
            await repo.one(model_id)
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(visible)
            ).scalar_one()
            == 1
        )


async def test_update_cannot_clear_another_tenants_capacity():
    from unittest.mock import AsyncMock, MagicMock

    import sqlalchemy as sa

    from eneo.completion_models.presentation.tenant_completion_models_router import (
        TenantCompletionModelUpdate,
    )
    from eneo.main.exceptions import NotFoundException
    from eneo.tenant_models.application.tenant_model_service import (
        TenantCompletionModelService,
    )

    table = CompletionModels.__table__
    metadata = sa.MetaData()
    stored = sa.Table(
        table.name,
        metadata,
        *(
            sa.Column(name, table.c[name].type)
            for name in ("id", "tenant_id", "max_input_tokens")
        ),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    model_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            stored.insert().values(id=model_id, tenant_id=uuid4(), max_input_tokens=100)
        )
        session = MagicMock()
        session.execute = AsyncMock(
            side_effect=lambda stmt: connection.execute(
                sa.select(table.c.id).where(stmt.whereclause)
            )
        )
        service = TenantCompletionModelService(session, MagicMock(tenant_id=uuid4()))
        with pytest.raises(NotFoundException):
            await service.update(
                model_id, TenantCompletionModelUpdate(max_input_tokens=None)
            )
        assert (
            connection.execute(sa.select(stored.c.max_input_tokens)).scalar_one() == 100
        )
        session.flush.assert_not_called()
