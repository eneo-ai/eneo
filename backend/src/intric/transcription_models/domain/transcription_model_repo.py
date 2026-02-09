from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.tables.ai_models_table import TranscriptionModels
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from intric.main.exceptions import NotFoundException
from intric.transcription_models.domain.transcription_model import (
    TranscriptionModel,
)

if TYPE_CHECKING:
    from uuid import UUID

    from intric.database.database import AsyncSession
    from intric.users.user import UserInDB


class TranscriptionModelRepository:
    def __init__(self, session: "AsyncSession", user: "UserInDB"):
        self.session = session
        self.user = user

    async def all(self, with_deprecated: bool = False):
        stmt = (
            sa.select(TranscriptionModels, ModelProviders.name, ModelProviders.provider_type)
            .outerjoin(ModelProviders, TranscriptionModels.provider_id == ModelProviders.id)
            .options(
                selectinload(TranscriptionModels.security_classification),
                selectinload(TranscriptionModels.security_classification).options(
                    selectinload(SecurityClassificationDBModel.tenant)
                ),
            )
            .where(
                # Return both global and tenant models
                # This allows existing apps with global models to continue working
                # UI filtering happens at the presentation layer
                sa.or_(
                    TranscriptionModels.tenant_id.is_(None),
                    TranscriptionModels.tenant_id == self.user.tenant_id
                )
            )
            .order_by(
                TranscriptionModels.org,
                TranscriptionModels.created_at,
                TranscriptionModels.name,
            )
        )

        if not with_deprecated:
            stmt = stmt.where(TranscriptionModels.is_deprecated == False)  # noqa

        result = await self.session.execute(stmt)
        rows = result.all()

        return [
            TranscriptionModel.create_from_db(
                transcription_model_db=transcription_model,
                user=self.user,
                provider_name=provider_name,
                provider_type=provider_type,
            )
            for transcription_model, provider_name, provider_type in rows
        ]

    async def one_or_none(self, model_id: "UUID") -> Optional["TranscriptionModel"]:
        # When fetching by ID, return ANY model (global or tenant) that the user can access
        stmt = (
            sa.select(TranscriptionModels, ModelProviders.name, ModelProviders.provider_type)
            .outerjoin(ModelProviders, TranscriptionModels.provider_id == ModelProviders.id)
            .options(
                selectinload(TranscriptionModels.security_classification),
                selectinload(TranscriptionModels.security_classification).options(
                    selectinload(SecurityClassificationDBModel.tenant)
                ),
            )
            .where(
                TranscriptionModels.id == model_id,
                # Allow both global models (tenant_id IS NULL) and tenant models (tenant_id = user.tenant_id)
                sa.or_(
                    TranscriptionModels.tenant_id.is_(None),
                    TranscriptionModels.tenant_id == self.user.tenant_id
                )
            )
        )

        result = await self.session.execute(stmt)
        row = result.one_or_none()

        if row is None:
            return None

        transcription_model, provider_name, provider_type = row
        return TranscriptionModel.create_from_db(
            transcription_model_db=transcription_model,
            user=self.user,
            provider_name=provider_name,
            provider_type=provider_type,
        )

    async def one(self, model_id: "UUID") -> "TranscriptionModel":
        transcription_model = await self.one_or_none(model_id=model_id)

        if transcription_model is None:
            raise NotFoundException()

        return transcription_model

    async def update(self, transcription_model: "TranscriptionModel"):
        # Update settings directly on the model table
        stmt = (
            sa.update(TranscriptionModels)
            .values(
                is_enabled=transcription_model.is_org_enabled,
                is_default=transcription_model.is_org_default,
                security_classification_id=(
                    transcription_model.security_classification.id
                    if transcription_model.security_classification
                    else None
                ),
            )
            .where(
                TranscriptionModels.id == transcription_model.id,
                TranscriptionModels.tenant_id == self.user.tenant_id,
            )
        )
        await self.session.execute(stmt)

        if transcription_model.is_org_default:
            # Set all other models to not default (for this tenant)
            stmt = (
                sa.update(TranscriptionModels)
                .values(is_default=False)
                .where(
                    TranscriptionModels.id != transcription_model.id,
                    TranscriptionModels.tenant_id == self.user.tenant_id,
                )
            )
            await self.session.execute(stmt)
