from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.files.text import TextExtractor
from eneo.info_blobs.info_blob import InfoBlobAdd
from eneo.info_blobs.info_blob_service import InfoBlobService
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.embedding_models.domain.embedding_model import EmbeddingModel


class TextProcessor:
    def __init__(
        self,
        user: UserInDB,
        extractor: TextExtractor,
        info_blob_service: InfoBlobService,
    ):
        super().__init__()
        self.user = user
        self.extractor = extractor
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
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ):
        text = self.extractor.extract(filepath, mimetype)

        return await self.process_text(
            text=text,
            title=filename,
            embedding_model=embedding_model,
            group_id=group_id,
            website_id=website_id,
            content_hash=content_hash,  # Pass hash for files too
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
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
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
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

        return await self.info_blob_service.publish_info_blob_without_validation(
            info_blob_add,
            embedding_model=embedding_model,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
