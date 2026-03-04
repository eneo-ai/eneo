from enum import Enum
from typing import TYPE_CHECKING, Optional

from intric.files.file_models import FileType
from intric.info_blobs.info_blob import InfoBlobInDBWithScore
from intric.services.service import DatastoreResult

if TYPE_CHECKING:
    from intric.collections.domain.collection import Collection
    from intric.embedding_models.infrastructure.datastore import Datastore
    from intric.files.file_models import File
    from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore, InfoBlobInDB
    from intric.info_blobs.info_blob_repo import InfoBlobRepository
    from intric.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from intric.sessions.session import SessionInDB
    from intric.websites.domain.website import Website


class EmbedMethod(str, Enum):
    LAST_QUESTION = "last question"
    CONCATENATE = "concatenate"


class ReferencesService:
    def __init__(
        self,
        info_blobs_repo: "InfoBlobRepository",
        datastore: "Datastore",
    ):
        self.info_blobs_repo = info_blobs_repo
        self.datastore = datastore

    async def _query_datastore_if_groups_or_websites(
        self,
        input_string: str,
        collections: list["Collection"],
        websites: list["Website"],
        integration_knowledge_list: list["IntegrationKnowledge"] = [],
        num_chunks: Optional[int] = None,
        autocut_cutoff: Optional[int] = None,
        version: int = 1,
    ) -> list["InfoBlobChunkInDBWithScore"]:
        if (collections or websites or integration_knowledge_list) and input_string:
            if version == 1:
                search_params = dict(autocut_cutoff=3, num_chunks=30)
            elif version == 2:
                search_params = dict(autocut_cutoff=autocut_cutoff, num_chunks=num_chunks)

            embedding_model = None
            if collections:
                embedding_model = collections[0].embedding_model
            elif websites:
                embedding_model = websites[0].embedding_model
            elif integration_knowledge_list:
                embedding_model = integration_knowledge_list[0].embedding_model

            return await self.datastore.semantic_search(
                input_string,
                embedding_model=embedding_model,
                collections=collections,
                websites=websites,
                integration_knowledge_list=integration_knowledge_list,
                **search_params,
            )

        return []

    async def _get_info_blobs_from_chunks(
        self, info_blob_chunks: list["InfoBlobChunkInDBWithScore"]
    ) -> list["InfoBlobInDBWithScore"]:
        info_blobs = []
        for chunk in info_blob_chunks:
            info_blob = await self.info_blobs_repo.get(chunk.info_blob_id)
            info_blob = InfoBlobInDBWithScore(**info_blob.model_dump(), score=chunk.score)
            info_blobs.append(info_blob)

        return info_blobs

    def _get_info_blob_chunks_without_duplicates(
        self, info_blob_chunks: list["InfoBlobChunkInDBWithScore"]
    ):
        c = {}

        for chunk in info_blob_chunks:
            if c.get(chunk.info_blob_id) is None or c[chunk.info_blob_id].score < chunk.score:
                c[chunk.info_blob_id] = chunk

        return list(c.values())

    def _remove_chunks_without_info_blob(
        self,
        info_blob_chunks: list["InfoBlobChunkInDBWithScore"],
        info_blobs: list["InfoBlobInDB"],
    ):
        info_blob_ids = {blob.id for blob in info_blobs}
        return [chunk for chunk in info_blob_chunks if chunk.info_blob_id in info_blob_ids]

    def _concatenate_conversation(
        self,
        question: str,
        session: Optional["SessionInDB"] = None,
        files: list["File"] = [],
    ):
        if files:
            files_text = (
                "\n".join(file.text for file in files if file.file_type == FileType.TEXT) + "\n"
            )
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
        files: list["File"] = [],
        collections: list["Collection"] = [],
        websites: list["Website"] = [],
        integration_knowledge_list: list["IntegrationKnowledge"] = [],
        embed_method: EmbedMethod = EmbedMethod.CONCATENATE,
        num_chunks: Optional[int] = None,
        autocut_cutoff: Optional[int] = None,
        version: int = 1,
    ) -> "DatastoreResult":
        if embed_method == EmbedMethod.CONCATENATE:
            input_string = self._concatenate_conversation(
                question=question, session=session, files=files
            )
        elif embed_method == EmbedMethod.LAST_QUESTION:
            input_string = question

        chunks = await self._query_datastore_if_groups_or_websites(
            input_string,
            collections=collections,
            websites=websites,
            integration_knowledge_list=integration_knowledge_list,
            num_chunks=num_chunks,
            autocut_cutoff=autocut_cutoff,
            version=version,
        )
        no_duplicate_chunks = self._get_info_blob_chunks_without_duplicates(chunks)
        info_blobs = await self._get_info_blobs_from_chunks(no_duplicate_chunks)

        return DatastoreResult(
            chunks=chunks,
            no_duplicate_chunks=no_duplicate_chunks,
            info_blobs=info_blobs,
        )
