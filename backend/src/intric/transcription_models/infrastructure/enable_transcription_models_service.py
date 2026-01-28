from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from intric.database.database import AsyncSession
from intric.database.tables.ai_models_table import TranscriptionModels
from intric.main.exceptions import UniqueException

if TYPE_CHECKING:
    from intric.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )


class TranscriptionModelEnableService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_model_id_by_name(self, model_name: str) -> "TranscriptionModel":
        """Get a transcription model by name."""
        query = sa.select(TranscriptionModels).where(
            TranscriptionModels.model_name == model_name
        )
        result = await self.session.scalar(query)

        if not result:
            raise ValueError(f"Transcription model with name '{model_name}' not found")

        return result.id

    async def enable_transcription_model(
        self,
        transcription_model_id: UUID,
        tenant_id: UUID,
        is_org_enabled: bool = True,
        is_org_default: bool = False,
    ):
        """Enable or disable a transcription model for a tenant.

        Args:
            is_org_enabled: Whether the model should be enabled for the organization
            transcription_model_id: The ID of the transcription model
            tenant_id: The ID of the tenant

        Returns:
            The updated TranscriptionModel

        Raises:
            UniqueException: If there's a conflict when updating
        """
        try:
            # Settings are now stored directly on the model table
            query = (
                sa.update(TranscriptionModels)
                .values(
                    is_enabled=is_org_enabled,
                    is_default=is_org_default,
                )
                .where(
                    TranscriptionModels.id == transcription_model_id,
                    TranscriptionModels.tenant_id == tenant_id,
                )
                .returning(TranscriptionModels)
            )
            return await self.session.scalar(query)
        except IntegrityError as e:
            raise UniqueException("Default transcription model already exists.") from e
