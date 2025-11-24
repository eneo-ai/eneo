from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.tables.ai_models_table import (
    TranscriptionModels,
    TranscriptionModelSettings,
)
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
        from intric.main.config import get_settings
        app_settings = get_settings()
        tenant_models_enabled = app_settings.tenant_models_enabled

        stmt = (
            sa.select(TranscriptionModels, TranscriptionModelSettings)
            .outerjoin(
                TranscriptionModelSettings,
                sa.and_(
                    TranscriptionModelSettings.transcription_model_id
                    == TranscriptionModels.id,
                    TranscriptionModelSettings.tenant_id == self.user.tenant_id,
                ),
            )
            .options(
                selectinload(TranscriptionModelSettings.security_classification),
                selectinload(
                    TranscriptionModelSettings.security_classification
                ).options(selectinload(SecurityClassificationDBModel.tenant)),
            )
            .where(
                # When tenant_models_enabled, return both global and tenant models
                # This allows existing apps with global models to continue working
                # UI filtering happens at the presentation layer
                sa.or_(
                    TranscriptionModels.tenant_id.is_(None),
                    TranscriptionModels.tenant_id == self.user.tenant_id
                ) if tenant_models_enabled
                else TranscriptionModels.tenant_id.is_(None)
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
        transcription_models = result.all()

        return [
            TranscriptionModel.create_from_db(
                transcription_model_db=transcription_model,
                transcription_model_settings=transcription_model_settings,
                user=self.user,
            )
            for transcription_model, transcription_model_settings in transcription_models
        ]

    async def one_or_none(self, model_id: "UUID") -> Optional["TranscriptionModel"]:
        # When fetching by ID, return ANY model (global or tenant) that the user can access
        stmt = (
            sa.select(TranscriptionModels, TranscriptionModelSettings)
            .outerjoin(
                TranscriptionModelSettings,
                sa.and_(
                    TranscriptionModelSettings.transcription_model_id
                    == TranscriptionModels.id,
                    TranscriptionModelSettings.tenant_id == self.user.tenant_id,
                ),
            )
            .options(
                selectinload(TranscriptionModelSettings.security_classification),
                selectinload(
                    TranscriptionModelSettings.security_classification
                ).options(selectinload(SecurityClassificationDBModel.tenant)),
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
        one_or_none = result.one_or_none()

        if one_or_none is None:
            return None

        transcription_model, transcription_model_settings = one_or_none

        return TranscriptionModel.create_from_db(
            transcription_model_db=transcription_model,
            transcription_model_settings=transcription_model_settings,
            user=self.user,
        )

    async def one(self, model_id: "UUID") -> "TranscriptionModel":
        transcription_model = await self.one_or_none(model_id=model_id)

        if transcription_model is None:
            raise NotFoundException()

        return transcription_model

    async def update(self, transcription_model: "TranscriptionModel"):
        stmt = sa.select(TranscriptionModelSettings).where(
            TranscriptionModelSettings.transcription_model_id == transcription_model.id,
            TranscriptionModelSettings.tenant_id == self.user.tenant_id,
        )
        result = await self.session.execute(stmt)
        existing_settings = result.scalars().one_or_none()

        if existing_settings is None:
            # For new settings, insert all required fields
            stmt = sa.insert(TranscriptionModelSettings).values(
                transcription_model_id=transcription_model.id,
                tenant_id=self.user.tenant_id,
                is_org_enabled=transcription_model.is_org_enabled,
                is_org_default=transcription_model.is_org_default,
                security_classification_id=(
                    transcription_model.security_classification.id
                    if transcription_model.security_classification
                    else None
                ),
            )
            await self.session.execute(stmt)

        else:
            stmt = (
                sa.update(TranscriptionModelSettings)
                .values(
                    is_org_enabled=transcription_model.is_org_enabled,
                    is_org_default=transcription_model.is_org_default,
                    security_classification_id=(
                        transcription_model.security_classification.id
                        if transcription_model.security_classification
                        else None
                    ),
                )
                .where(
                    TranscriptionModelSettings.transcription_model_id
                    == transcription_model.id,
                    TranscriptionModelSettings.tenant_id == self.user.tenant_id,
                )
            )
            await self.session.execute(stmt)

        if transcription_model.is_org_default:
            # Set all other models to not default
            stmt = (
                sa.update(TranscriptionModelSettings)
                .values(is_org_default=False)
                .where(
                    TranscriptionModelSettings.transcription_model_id
                    != transcription_model.id,
                    TranscriptionModelSettings.tenant_id == self.user.tenant_id,
                )
            )
            await self.session.execute(stmt)
