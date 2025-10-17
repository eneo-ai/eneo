from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from intric.embedding_models.infrastructure.datastore import Datastore
from intric.files.text import TextExtractor
from intric.info_blobs.info_blob import InfoBlobAdd
from intric.info_blobs.info_blob_service import InfoBlobService
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.embedding_models.domain.embedding_model import EmbeddingModel


class TextProcessor:
    def __init__(
        self,
        user: UserInDB,
        extractor: TextExtractor,
        datastore: Datastore,
        info_blob_service: InfoBlobService,
    ):
        self.user = user
        self.extractor = extractor
        self.datastore = datastore
        self.info_blob_service = info_blob_service

    async def process_file(
        self,
        *,
        filepath: Path,
        filename: str,
        embedding_model: "EmbeddingModel",
        mimetype: str | None = None,
        group_id: UUID | None = None,
        website_id: UUID | None = None,
        content_hash: bytes | None = None,
    ):
        text = self.extractor.extract(filepath, mimetype)

        return await self.process_text(
            text=text,
            title=filename,
            embedding_model=embedding_model,
            group_id=group_id,
            website_id=website_id,
            content_hash=content_hash,  # Pass hash for files too
        )

    async def process_text(
        self,
        *,
        text: str,
        title: str,
        embedding_model: "EmbeddingModel",
        group_id: UUID | None = None,
        website_id: UUID | None = None,
        url: str | None = None,
        content_hash: bytes | None = None,
    ):
        info_blob_add = InfoBlobAdd(
            title=title,
            user_id=self.user.id,
            text=text,
            group_id=group_id,
            url=url,
            website_id=website_id,
            tenant_id=self.user.tenant_id,
            content_hash=content_hash,  # Used by files for hash checking
        )

        info_blob = await self.info_blob_service.add_info_blob_without_validation(
            info_blob_add
        )
        await self.datastore.add(info_blob=info_blob, embedding_model=embedding_model)
        info_blob_updated = await self.info_blob_service.update_info_blob_size(
            info_blob.id
        )

        return info_blob_updated
