# MIT License

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa

from intric.database.tables.model_providers_table import ModelProviders
from intric.files import audio
from intric.files.audio import AudioMimeTypes
from intric.files.file_models import File
from intric.main.config import SETTINGS, Settings
from intric.main.logging import get_logger
from intric.model_providers.infrastructure.tenant_model_credential_resolver import (
    TenantModelCredentialResolver,
)
from intric.transcription_models.infrastructure.adapters.litellm_transcription import (
    LiteLLMTranscriptionAdapter,
)

if TYPE_CHECKING:
    from intric.database.database import AsyncSession
    from intric.files.file_repo import FileRepository
    from intric.settings.encryption_service import EncryptionService
    from intric.tenants.tenant import TenantInDB
    from intric.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )

logger = get_logger(__name__)


class Transcriber:
    def __init__(
        self,
        file_repo: "FileRepository",
        tenant: Optional["TenantInDB"] = None,
        config: Optional[Settings] = None,
        encryption_service: Optional["EncryptionService"] = None,
        session: Optional["AsyncSession"] = None,
    ):
        self.file_repo = file_repo
        self.tenant = tenant
        self.config = config or SETTINGS
        self.encryption_service = encryption_service
        self.session = session

    async def transcribe(self, file: File, transcription_model: "TranscriptionModel"):
        if file.blob is None or not AudioMimeTypes.has_value(file.mimetype):
            raise ValueError("File needs to be an audio file")

        # If file already has a transcription, return it
        if file.transcription:
            return file.transcription

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
                temp_file.write(file.blob)
                temp_file_path = Path(temp_file.name)

            result = await self.transcribe_from_filepath(
                filepath=temp_file_path, transcription_model=transcription_model
            )

            # Store the transcription in the file object
            file.transcription = result

            # If we have a repository, update the file in the database
            if self.file_repo:
                await self.file_repo.update(file)
        finally:
            temp_file_path.unlink()  # Clean up the temporary file

        return result

    async def _get_adapter(
        self, model: "TranscriptionModel"
    ) -> LiteLLMTranscriptionAdapter:
        """
        Get the LiteLLM adapter for the given transcription model.

        All transcription models must have a provider_id linking to a ModelProvider.
        """
        # All models must have provider_id
        if not hasattr(model, "provider_id") or not model.provider_id:
            raise ValueError(
                f"Transcription model '{model.name}' is missing required provider_id. "
                "All models must be associated with a ModelProvider."
            )

        # Check if session is available
        if not self.session:
            logger.error(
                "Model requires database session but none available",
                extra={
                    "model_id": str(model.id) if hasattr(model, "id") else None,
                    "model_name": model.name,
                    "provider_id": str(model.provider_id),
                    "tenant_id": str(self.tenant.id) if self.tenant else None,
                },
            )
            raise ValueError(
                f"Transcription model '{model.name}' requires database session to load provider credentials. "
                "Please ensure the Transcriber is initialized with a database session."
            )

        # Load provider data from database
        stmt = sa.select(ModelProviders).where(ModelProviders.id == model.provider_id)
        result = await self.session.execute(stmt)
        provider_db = result.scalar_one_or_none()

        if provider_db is None:
            raise ValueError(f"Model provider {model.provider_id} not found")

        if not provider_db.is_active:
            raise ValueError(f"Model provider {model.provider_id} is not active")

        # Create credential resolver
        credential_resolver = TenantModelCredentialResolver(
            provider_id=provider_db.id,
            provider_type=provider_db.provider_type,
            credentials=provider_db.credentials,
            config=provider_db.config,
            encryption_service=self.encryption_service,
        )

        logger.info(
            f"Using LiteLLMTranscriptionAdapter for model '{model.name}'",
            extra={
                "model_id": str(model.id) if hasattr(model, "id") else None,
                "model_name": model.name,
                "provider_id": str(model.provider_id),
                "provider_type": provider_db.provider_type,
                "tenant_id": str(self.tenant.id) if self.tenant else None,
            },
        )

        return LiteLLMTranscriptionAdapter(
            model=model,
            credential_resolver=credential_resolver,
            provider_type=provider_db.provider_type,
        )

    async def transcribe_from_filepath(
        self, *, filepath: Path, transcription_model: "TranscriptionModel"
    ):
        adapter = await self._get_adapter(transcription_model)

        async with audio.to_wav(filepath) as wav_file:
            return await adapter.get_text_from_file(wav_file)
