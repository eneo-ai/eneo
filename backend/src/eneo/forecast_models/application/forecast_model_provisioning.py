"""Gives a tenant the forecast model its deployment's tool service runs."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa

from eneo.database.tables.ai_models_table import ForecastModels
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.mcp_servers.application.runtime_status import runtime_status
from eneo.model_providers.domain.model_provider import (
    ENEO_TOOL_SERVICE_PROVIDER_TYPE,
    ModelProvider,
)
from eneo.model_providers.infrastructure.model_provider_repository import (
    ModelProviderRepository,
)

if TYPE_CHECKING:
    from eneo.database.database import AsyncSession

# The key of the checkpoint the deployment's tool service runs
# (FORECAST_MODEL_PATH): the one forecast model a tool service has today.
DEFAULT_FORECAST_MODEL = "default"
# The tool service endpoint that runs it, as its diagnostics name it.
_FORECAST_ENDPOINT = "forecast"
# A tenant's own provider may already carry the first name.
_PROVIDER_NAMES = ("Eneo tool service", "Eneo tool service (built in)")


async def ensure_default_forecast_model(
    session: "AsyncSession", tenant_id: UUID
) -> UUID:
    """The id of the tenant's default forecast model, created the first time
    with the tool service's provider.

    Idempotent. Never loads weights or calls a tool: the display name is the
    one the runtime's (cached) diagnostics report, else "Timestral".
    """
    # Concurrent first uses run one after the other: a row lock cannot cover
    # rows that do not exist yet, so the tenant is locked by name until the
    # transaction ends. The unique constraints stay the backstop.
    await session.execute(
        sa.select(
            sa.func.pg_advisory_xact_lock(
                sa.func.hashtextextended(f"forecast_model_provisioning:{tenant_id}", 0)
            )
        )
    )
    provider_id = await _tool_service_provider(session, tenant_id)
    model_id = await session.scalar(
        sa.select(ForecastModels.id).where(
            ForecastModels.tenant_id == tenant_id,
            ForecastModels.provider_id == provider_id,
            ForecastModels.name == DEFAULT_FORECAST_MODEL,
            ForecastModels.deleted_at.is_(None),
        )
    )
    if model_id is not None:
        return model_id

    status = await runtime_status()
    model = ForecastModels(
        **dict(  # type: ignore[call-arg]
            tenant_id=tenant_id,
            provider_id=provider_id,
            name=DEFAULT_FORECAST_MODEL,
            nickname=status.model_name(_FORECAST_ENDPOINT, DEFAULT_FORECAST_MODEL)
            or "Timestral",
            org="Mistral AI",
            open_source=True,
            is_enabled=True,
        )
    )
    session.add(model)
    await session.flush()
    return model.id


async def _tool_service_provider(session: "AsyncSession", tenant_id: UUID) -> UUID:
    """The tenant's provider for the tool service, created on first use.

    Seeded through the repository: the service's create path would ask an
    unknown provider type for an API key, and this one has no credentials.
    Its URL and token stay in the deployment's settings.
    """
    provider_id = await session.scalar(
        sa.select(ModelProviders.id)
        .where(
            ModelProviders.tenant_id == tenant_id,
            ModelProviders.provider_type == ENEO_TOOL_SERVICE_PROVIDER_TYPE,
        )
        .order_by(ModelProviders.created_at, ModelProviders.id)
        .limit(1)
    )
    if provider_id is not None:
        return provider_id

    taken = set(
        await session.scalars(
            sa.select(ModelProviders.name).where(
                ModelProviders.tenant_id == tenant_id,
                ModelProviders.name.in_(_PROVIDER_NAMES),
            )
        )
    )
    name = next(
        (name for name in _PROVIDER_NAMES if name not in taken),
        f"{_PROVIDER_NAMES[-1]} {uuid4().hex[:8]}",
    )
    now = datetime.now(timezone.utc)
    provider = await ModelProviderRepository(session, tenant_id).create(
        ModelProvider(
            id=uuid4(),
            tenant_id=tenant_id,
            name=name,
            provider_type=ENEO_TOOL_SERVICE_PROVIDER_TYPE,
            credentials={},
            config={},
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )
    return provider.id
