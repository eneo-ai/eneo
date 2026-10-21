from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from eneo.database.tables.ai_models_table import RerankModels
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from eneo.main.exceptions import NotFoundException
from eneo.rerank_models.domain.rerank_model import RerankModel

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.database.database import AsyncSession
    from eneo.users.user import UserInDB


class RerankModelRepository:
    def __init__(self, session: "AsyncSession", user: "UserInDB") -> None:
        super().__init__()
        self.session = session
        self.user = user

    def _base_query(self):
        return (
            sa.select(RerankModels, ModelProviders.name, ModelProviders.provider_type)
            .outerjoin(ModelProviders, RerankModels.provider_id == ModelProviders.id)
            .options(
                selectinload(RerankModels.security_classification).options(
                    selectinload(SecurityClassificationDBModel.tenant)
                ),
            )
            .where(
                # Global and tenant models alike; UI filtering happens at the
                # presentation layer.
                sa.or_(
                    RerankModels.tenant_id.is_(None),
                    RerankModels.tenant_id == self.user.tenant_id,
                ),
                # Soft-deleted models are tombstones; never surface them.
                RerankModels.deleted_at.is_(None),
            )
        )

    async def all(self, with_deprecated: bool = False) -> list[RerankModel]:
        stmt = self._base_query().order_by(
            RerankModels.org, RerankModels.created_at, RerankModels.name
        )
        if not with_deprecated:
            stmt = stmt.where(RerankModels.is_deprecated == False)  # noqa: E712

        result = await self.session.execute(stmt)
        return [
            RerankModel.create_from_db(
                rerank_model_db=rerank_model,
                user=self.user,
                provider_name=provider_name,
                provider_type=provider_type,
            )
            for rerank_model, provider_name, provider_type in result.all()
        ]

    async def one_or_none(self, model_id: "UUID") -> Optional[RerankModel]:
        stmt = self._base_query().where(RerankModels.id == model_id)
        result = await self.session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return None

        rerank_model, provider_name, provider_type = row
        return RerankModel.create_from_db(
            rerank_model_db=rerank_model,
            user=self.user,
            provider_name=provider_name,
            provider_type=provider_type,
        )

    async def one(self, model_id: "UUID") -> RerankModel:
        rerank_model = await self.one_or_none(model_id=model_id)
        if rerank_model is None:
            raise NotFoundException()
        return rerank_model

    async def update(self, rerank_model: RerankModel) -> None:
        stmt = (
            sa.update(RerankModels)
            .values(
                is_enabled=rerank_model.is_org_enabled,
                is_default=rerank_model.is_org_default,
                security_classification_id=(
                    rerank_model.security_classification.id
                    if rerank_model.security_classification
                    else None
                ),
            )
            .where(
                RerankModels.id == rerank_model.id,
                RerankModels.tenant_id == self.user.tenant_id,
            )
        )
        await self.session.execute(stmt)

        if rerank_model.is_org_default:
            stmt = (
                sa.update(RerankModels)
                .values(is_default=False)
                .where(
                    RerankModels.id != rerank_model.id,
                    RerankModels.tenant_id == self.user.tenant_id,
                )
            )
            await self.session.execute(stmt)
