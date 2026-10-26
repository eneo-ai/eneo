from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from eneo.database.tables.ai_models_table import ForecastModels
from eneo.database.tables.mcp_server_table import MCPServers
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from eneo.forecast_models.domain.forecast_model import (
    ForecastModel,
    ForecastModelUsage,
)
from eneo.main.exceptions import NotFoundException

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from eneo.database.database import AsyncSession
    from eneo.users.user import UserInDB


class ForecastModelRepository:
    """The tenant's live forecast models, with their provider and usage."""

    def __init__(self, session: "AsyncSession", user: "UserInDB") -> None:
        super().__init__()
        self.session = session
        self.user = user

    def _base_query(self) -> Any:
        return (
            sa.select(ForecastModels, ModelProviders.name, ModelProviders.provider_type)
            .join(ModelProviders, ForecastModels.provider_id == ModelProviders.id)
            .options(
                selectinload(ForecastModels.security_classification).selectinload(
                    SecurityClassificationDBModel.tenant
                ),
            )
            .where(
                ForecastModels.tenant_id == self.user.tenant_id,
                ForecastModels.deleted_at.is_(None),
            )
        )

    async def all(self) -> list[ForecastModel]:
        stmt = self._base_query().order_by(ForecastModels.created_at, ForecastModels.id)
        result = await self.session.execute(stmt)
        models = [
            ForecastModel.create_from_db(
                forecast_model_db=model,
                user=self.user,
                provider_name=provider_name,
                provider_type=provider_type,
            )
            for model, provider_name, provider_type in result.all()
        ]
        await self._attach_usage(models)
        return models

    async def one(self, model_id: "UUID", *, for_update: bool = False) -> ForecastModel:
        stmt = self._base_query().where(ForecastModels.id == model_id)
        if for_update:
            # Locked until commit and read afresh, so an update builds on the
            # row as it is now, never on a state a concurrent one replaced.
            stmt = stmt.with_for_update(of=ForecastModels).execution_options(
                populate_existing=True
            )
        row = (await self.session.execute(stmt)).one_or_none()
        if row is None:
            raise NotFoundException()
        model, provider_name, provider_type = row
        forecast_model = ForecastModel.create_from_db(
            forecast_model_db=model,
            user=self.user,
            provider_name=provider_name,
            provider_type=provider_type,
        )
        await self._attach_usage([forecast_model])
        return forecast_model

    async def _attach_usage(self, models: list[ForecastModel]) -> None:
        """Record the tenant's Forecast sources that run on each model."""
        if not models:
            return
        by_id = {model.id: model for model in models}
        stmt = (
            sa.select(
                MCPServers.forecast_model_id,
                MCPServers.id,
                MCPServers.name,
                MCPServers.purpose,
            )
            .where(
                MCPServers.tenant_id == self.user.tenant_id,
                MCPServers.forecast_model_id.in_(by_id.keys()),
            )
            .order_by(MCPServers.created_at, MCPServers.id)
        )
        result = await self.session.execute(stmt)
        for forecast_model_id, server_id, name, purpose in result.all():
            by_id[forecast_model_id].used_by_mcp_servers.append(
                ForecastModelUsage(id=server_id, name=name, purpose=purpose)
            )

    async def update(self, model_id: "UUID", values: "Mapping[str, object]") -> None:
        """Write only the given columns of one of the tenant's models."""
        await self.session.execute(
            sa.update(ForecastModels)
            .values(dict(values))
            .where(
                ForecastModels.id == model_id,
                ForecastModels.tenant_id == self.user.tenant_id,
            )
        )
