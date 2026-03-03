import time
from typing import TYPE_CHECKING, Optional

from langchain.text_splitter import RecursiveCharacterTextSplitter
from pydantic_settings import BaseSettings

from intric.completion_models.infrastructure.context_builder import count_tokens
from intric.files.chunk_embedding_list import ChunkEmbeddingList
from intric.info_blobs.info_blob import (
    InfoBlobChunk,
    InfoBlobChunkInDBWithScore,
    InfoBlobChunkWithEmbedding,
    InfoBlobInDB,
)
from intric.info_blobs.info_blob_chunk_repo import InfoBlobChunkRepo
from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from intric.main.logging import get_logger
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.collections.domain.collection import Collection
    from intric.embedding_models.domain.embedding_model import EmbeddingModel
    from intric.embedding_models.infrastructure.create_embeddings_service import (
        CreateEmbeddingsService,
    )
    from intric.websites.domain.website import Website

logger = get_logger(__name__)


class ChunkSettings(BaseSettings):
    chunk_size: int = 200
    chunk_overlap: int = 40


settings = ChunkSettings()


def autocut(
    y_values: list[float], cutoff: int = 2, cliff_threshold: float = 0.5
) -> int:
    """Cut a sorted list of scores at natural grouping boundaries.

    Finds local maxima in the normalized deviation-from-linear curve.
    Cuts at the n-th local maximum where n = cutoff.

    If a single cliff is dramatic enough (diff exceeds cliff_threshold),
    cut there immediately regardless of the cutoff count.
    """

    if len(y_values) <= 1:
        return len(y_values)

    # Handling division by zero in normalization
    if y_values[0] == y_values[-1]:
        return len(y_values)

    diff = []
    step = 1.0 / (len(y_values) - 1)

    for i, y in enumerate(y_values):
        x_value = float(i) * step
        y_value_norm = (y - y_values[0]) / (y_values[-1] - y_values[0])
        diff.append(y_value_norm - x_value)

    extrema_count = 0
    for i in range(1, len(diff)):
        is_local_max = False
        if i == len(diff) - 1:
            is_local_max = (
                len(diff) > 2 and diff[i] > diff[i - 1] and diff[i] > diff[i - 2]
            )
        else:
            is_local_max = diff[i] > diff[i - 1] and diff[i] > diff[i + 1]

        if is_local_max:
            extrema_count += 1
            if extrema_count >= cutoff or diff[i] >= cliff_threshold:
                return i

    return len(y_values)


class Datastore:
    def __init__(
        self,
        *,
        user: UserInDB,
        info_blob_chunk_repo: InfoBlobChunkRepo,
        create_embeddings_service: "CreateEmbeddingsService",
    ):
        self.user = user
        self.chunk_repo = info_blob_chunk_repo
        self.create_embeddings_service = create_embeddings_service

    def _chunk_text(self, info_blob: InfoBlobInDB):
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            length_function=count_tokens,
        )

        info_blob_chunks = [
            InfoBlobChunk(
                chunk_no=i,
                text=chunk.strip(),
                info_blob_id=info_blob.id,
                tenant_id=self.user.tenant_id,
            )
            for i, chunk in enumerate(splitter.split_text(info_blob.text))
            if chunk.strip()
        ]

        return info_blob_chunks

    async def _add(self, chunk_embedding_list: ChunkEmbeddingList, batch_size: int = 100):
        chunks = []
        for chunk, embedding in chunk_embedding_list:
            chunks.append(
                InfoBlobChunkWithEmbedding(
                    **chunk.model_dump(exclude_none=True), embedding=embedding
                )
            )

            if len(chunks) >= batch_size:
                logger.debug(f"Adding {len(chunks)} chunks to datastore.")
                await self.chunk_repo.add(chunks)

                chunks.clear()

        # Last batch
        if chunks:
            logger.debug(f"Last batch. Adding {len(chunks)} chunks to datastore.")
            await self.chunk_repo.add(chunks)

    async def add(self, info_blob: InfoBlobInDB, embedding_model: "EmbeddingModel"):
        logger.debug("Chunking text.")
        info_blob_chunks = self._chunk_text(info_blob)

        if not info_blob_chunks:
            logger.warning(f"Info Blob {info_blob.id} did not yield any chunks after splitting.")
            return

        logger.debug(f"Embedding {len(info_blob_chunks)} info-blob chunks.")
        chunk_embedding_list = await self.create_embeddings_service.get_embeddings(
            model=embedding_model, chunks=info_blob_chunks
        )

        logger.debug(f"Adding {len(info_blob_chunks)} info-blob chunks to datastore.")
        await self._add(chunk_embedding_list)

    async def semantic_search(
        self,
        search_string: str,
        embedding_model: "EmbeddingModel",
        collections: list["Collection"] = [],
        websites: list["Website"] = [],
        integration_knowledge_list: list[IntegrationKnowledge] = [],
        num_chunks: Optional[int] = 30,
        autocut_cutoff: Optional[int] = None,
    ) -> list[InfoBlobChunkInDBWithScore]:
        group_ids = [group.id for group in collections]
        website_ids = [website.id for website in websites]
        integration_knowledge_ids = [i.id for i in integration_knowledge_list]

        start = time.time()
        search_string_embedding = await self.create_embeddings_service.get_embedding_for_query(
            model=embedding_model, query=search_string
        )
        step_1 = time.time()
        semantic_results = await self.chunk_repo.semantic_search(
            search_string_embedding,
            group_ids=group_ids,
            website_ids=website_ids,
            integration_knowledge_ids=integration_knowledge_ids,
            limit=num_chunks,
        )
        end = time.time()

        logger.debug(
            f"Time to get results: Embed step: {step_1 - start},"
            f" Search step: {end - step_1}, Total: {end - start}"
        )

        scores = [res.score for res in semantic_results]

        if autocut_cutoff is not None:
            cut_point = autocut(scores, autocut_cutoff)
            logger.debug(
                "Semantic search: fetched=%d, autocut=%d/%d, "
                "scores=[%s]",
                len(semantic_results),
                cut_point,
                len(semantic_results),
                ", ".join(f"{s:.4f}" for s in scores[:10]),
            )
            return semantic_results[:cut_point]

        logger.debug(
            "Semantic search: fetched=%d (no autocut), scores=[%s]",
            len(semantic_results),
            ", ".join(f"{s:.4f}" for s in scores[:10]),
        )
        return semantic_results
