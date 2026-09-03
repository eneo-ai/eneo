from collections.abc import Sequence
from enum import Enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from eneo.files.file_models import FileType
from eneo.info_blobs.info_blob import InfoBlobInDBWithScore
from eneo.main.config import get_settings
from eneo.services.service import DatastoreResult

if TYPE_CHECKING:
    from eneo.collections.domain.collection import Collection
    from eneo.embedding_models.infrastructure.datastore import Datastore
    from eneo.files.file_models import File
    from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore, InfoBlobInDB
    from eneo.info_blobs.info_blob_repo import InfoBlobRepository
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.sessions.session import SessionInDB
    from eneo.websites.domain.website import Website


class EmbedMethod(str, Enum):
    LAST_QUESTION = "last question"
    CONCATENATE = "concatenate"


class ReferencesService:
    def __init__(
        self,
        info_blobs_repo: "InfoBlobRepository",
        datastore: "Datastore",
    ):
        super().__init__()
        self.info_blobs_repo = info_blobs_repo
        self.datastore = datastore

    async def _query_datastore_if_groups_or_websites(
        self,
        input_string: str,
        collections: list["Collection"],
        websites: list["Website"],
        integration_knowledge_list: Sequence["IntegrationKnowledge"] | None = None,
        num_chunks: Optional[int] = None,
        version: int = 1,
    ) -> list["InfoBlobChunkInDBWithScore"]:
        integration_knowledge_list = list(integration_knowledge_list or [])
        if (collections or websites or integration_knowledge_list) and input_string:
            # Named rather than splatted from a dict: a homogeneously typed
            # **kwargs would silently bind to any parameter semantic_search
            # grows later.
            if version == 1:
                autocut_cutoff, chunk_limit = 3, 30
            elif version == 2:
                autocut_cutoff, chunk_limit = None, num_chunks
            else:
                raise ValueError(f"Unsupported retrieval version: {version}")

            embedding_model = None
            if collections:
                embedding_model = collections[0].embedding_model
            elif websites:
                embedding_model = websites[0].embedding_model
            elif integration_knowledge_list:
                embedding_model = integration_knowledge_list[0].embedding_model

            # At least one knowledge source is non-empty, so embedding_model is set.
            assert embedding_model is not None, (
                "embedding_model must be set when knowledge sources are present"
            )
            return await self.datastore.semantic_search(
                input_string,
                embedding_model=embedding_model,
                collections=collections,
                websites=websites,
                integration_knowledge_list=integration_knowledge_list,
                # Deployment-wide relevance floor for injected chunks (off by
                # default; cosine-similarity scales differ per embedding model).
                min_score=get_settings().inject_knowledge_min_score,
                num_chunks=chunk_limit,
                autocut_cutoff=autocut_cutoff,
            )

        return []

    async def _get_info_blobs_from_chunks(
        self, info_blob_chunks: list["InfoBlobChunkInDBWithScore"]
    ) -> list["InfoBlobInDBWithScore"]:
        if not info_blob_chunks:
            return []

        blob_ids = [chunk.info_blob_id for chunk in info_blob_chunks]
        loaded_blobs = await self.info_blobs_repo.get_by_ids(blob_ids)
        blobs_by_id = {blob.id: blob for blob in loaded_blobs}
        info_blobs: list[InfoBlobInDBWithScore] = []
        for chunk in info_blob_chunks:
            info_blob = blobs_by_id.get(chunk.info_blob_id)
            assert info_blob is not None
            info_blobs.append(
                InfoBlobInDBWithScore(**info_blob.model_dump(), score=chunk.score)
            )

        await self.info_blobs_repo.hydrate_original_availability(info_blobs)
        return info_blobs

    def _get_info_blob_chunks_without_duplicates(
        self, info_blob_chunks: list["InfoBlobChunkInDBWithScore"]
    ) -> list["InfoBlobChunkInDBWithScore"]:
        c: dict[UUID, "InfoBlobChunkInDBWithScore"] = {}

        for chunk in info_blob_chunks:
            if (
                c.get(chunk.info_blob_id) is None
                or c[chunk.info_blob_id].score < chunk.score
            ):
                c[chunk.info_blob_id] = chunk

        return list(c.values())

    def _remove_chunks_without_info_blob(
        self,
        info_blob_chunks: list["InfoBlobChunkInDBWithScore"],
        info_blobs: list["InfoBlobInDB"],
    ):
        info_blob_ids = {blob.id for blob in info_blobs}
        return [
            chunk for chunk in info_blob_chunks if chunk.info_blob_id in info_blob_ids
        ]

    def _concatenate_conversation(
        self,
        question: str,
        session: Optional["SessionInDB"] = None,
        files: list["File"] | None = None,
    ) -> str:
        files = files or []
        if files:
            text_parts: list[str] = [
                file.text
                for file in files
                if file.file_type == FileType.TEXT and file.text is not None
            ]
            files_text: str = "\n".join(text_parts) + "\n" if text_parts else ""
        else:
            files_text = ""

        if session is not None:
            session_text = (
                "\n".join(
                    "\n".join((question.question, question.answer))
                    for question in session.questions
                )
                + "\n"
            )
        else:
            session_text = ""

        return f"{files_text}{session_text}{question}".strip()

    async def get_references(
        self,
        question: str,
        session: Optional["SessionInDB"] = None,
        files: list["File"] | None = None,
        collections: list["Collection"] | None = None,
        websites: list["Website"] | None = None,
        integration_knowledge_list: list["IntegrationKnowledge"] | None = None,
        embed_method: EmbedMethod = EmbedMethod.CONCATENATE,
        num_chunks: Optional[int] = None,
        version: int = 1,
    ) -> "DatastoreResult":
        files = files or []
        collections = collections or []
        websites = websites or []
        integration_knowledge_list = integration_knowledge_list or []

        if embed_method == EmbedMethod.CONCATENATE:
            input_string = self._concatenate_conversation(
                question=question, session=session, files=files
            )
        else:
            # EmbedMethod.LAST_QUESTION or any future variant
            input_string = question

        chunks = await self._query_datastore_if_groups_or_websites(
            input_string,
            collections=collections,
            websites=websites,
            integration_knowledge_list=integration_knowledge_list,
            num_chunks=num_chunks,
            version=version,
        )
        no_duplicate_chunks = self._get_info_blob_chunks_without_duplicates(chunks)
        info_blobs = await self._get_info_blobs_from_chunks(no_duplicate_chunks)

        return DatastoreResult(
            chunks=chunks,
            no_duplicate_chunks=no_duplicate_chunks,
            info_blobs=info_blobs,
        )
