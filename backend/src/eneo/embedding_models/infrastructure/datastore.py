import asyncio
import time
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from eneo.embedding_models.domain.chunking import (
    build_text_splitter,
    effective_chunk_config,
)
from eneo.embedding_models.infrastructure.adapters.base import (
    PartialEmbeddingBatchError,
)
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.info_blobs.info_blob import (
    InfoBlobChunk,
    InfoBlobChunkInDBWithScore,
    InfoBlobChunkWithEmbedding,
    InfoBlobInDB,
)
from eneo.info_blobs.info_blob_chunk_repo import InfoBlobChunkRepo
from eneo.info_blobs.source_metadata import build_source_header
from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from eneo.main.logging import get_logger
from eneo.tokens.token_utils import count_tokens

if TYPE_CHECKING:
    from eneo.collections.domain.collection import Collection
    from eneo.embedding_models.domain.embedding_model import EmbeddingModel
    from eneo.embedding_models.infrastructure.create_embeddings_service import (
        CreateEmbeddingsService,
    )
    from eneo.websites.domain.website import Website

logger = get_logger(__name__)


# Share of a chunk's token budget the source metadata header may take when it
# is prepended for embedding. The rest stays for the chunk's own text.
SOURCE_HEADER_BUDGET_SHARE = 0.25


def autocut(y_values: list[float], cutoff: int = 2) -> int:
    # Written by GPT-4, fact-checked by GPT-4

    if len(y_values) <= 1:
        return len(y_values)

    # Handling division by zero in normalization
    if y_values[0] == y_values[-1]:
        return len(y_values)

    diff: list[float] = []
    step = 1.0 / (len(y_values) - 1)

    for i, y in enumerate(y_values):
        x_value = float(i) * step
        y_value_norm = (y - y_values[0]) / (y_values[-1] - y_values[0])
        diff.append(y_value_norm - x_value)

    extrema_count = 0
    for i in range(1, len(diff)):
        if i == len(diff) - 1:
            if len(diff) > 2 and diff[i] > diff[i - 1] and diff[i] > diff[i - 2]:
                extrema_count += 1
                if extrema_count >= cutoff:
                    return i
        elif diff[i] > diff[i - 1] and len(diff) > i + 1 and diff[i] > diff[i + 1]:
            extrema_count += 1
            if extrema_count >= cutoff:
                return i

    return len(y_values)


class Datastore:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        info_blob_chunk_repo: InfoBlobChunkRepo,
        create_embeddings_service: "CreateEmbeddingsService",
    ) -> None:
        super().__init__()
        self.tenant_id = tenant_id
        self.chunk_repo = info_blob_chunk_repo
        self.create_embeddings_service = create_embeddings_service

    @staticmethod
    def _source_header(
        info_blob: InfoBlobInDB, embedding_model: "EmbeddingModel"
    ) -> str:
        """Title and source properties prepended to every chunk for embedding.

        Stored chunk text stays the document's own words: the header is only
        part of what the embedding model sees, so a query about a document's
        kind or subject area can find it, while excerpts shown to people and
        the model remain clean. Empty for documents without source metadata.
        """
        if not info_blob.source_metadata:
            return ""
        config = effective_chunk_config(embedding_model)
        return build_source_header(
            title=info_blob.title,
            entries=info_blob.source_metadata,
            token_budget=int(config.chunk_size * SOURCE_HEADER_BUDGET_SHARE),
            count_tokens=count_tokens,
        )

    def _chunk_text(
        self, info_blob: InfoBlobInDB, embedding_model: "EmbeddingModel"
    ) -> list[InfoBlobChunk]:
        header = self._source_header(info_blob, embedding_model)
        splitter = build_text_splitter(
            embedding_model, reserved_tokens=count_tokens(header) if header else 0
        )

        info_blob_chunks = [
            InfoBlobChunk(
                chunk_no=i,
                text=chunk.strip(),
                info_blob_id=info_blob.id,
                tenant_id=self.tenant_id,
            )
            for i, chunk in enumerate(splitter.split_text(info_blob.text))
            if chunk.strip()
        ]

        return info_blob_chunks

    async def _add(
        self, chunk_embedding_list: ChunkEmbeddingList, batch_size: int = 100
    ) -> None:
        chunks: list[InfoBlobChunkWithEmbedding] = []
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
        header = self._source_header(info_blob, embedding_model)
        info_blob_chunks = await asyncio.to_thread(
            self._chunk_text, info_blob, embedding_model
        )

        if not info_blob_chunks:
            raise ValueError(
                f"InfoBlob {info_blob.id} did not yield searchable content"
            )

        logger.debug(f"Embedding {len(info_blob_chunks)} info-blob chunks.")
        embedding_inputs = (
            [
                chunk.model_copy(update={"text": header + chunk.text})
                for chunk in info_blob_chunks
            ]
            if header
            else info_blob_chunks
        )
        try:
            chunk_embedding_list = await self.create_embeddings_service.get_embeddings(
                model=embedding_model, chunks=embedding_inputs
            )
        except PartialEmbeddingBatchError as error:
            error.completed.close()
            raise error.cause from None

        if header:
            # Pair each embedding back with the chunk whose text we store: the
            # header belongs to the vector, not to the excerpt.
            by_chunk_no = {chunk.chunk_no: chunk for chunk in info_blob_chunks}
            stored = ChunkEmbeddingList()
            for embedded, embedding in chunk_embedding_list:
                stored.add([by_chunk_no[embedded.chunk_no]], [embedding])
            chunk_embedding_list = stored

        logger.debug(f"Adding {len(info_blob_chunks)} info-blob chunks to datastore.")
        await self._add(chunk_embedding_list)

    async def semantic_search(
        self,
        search_string: str,
        embedding_model: "EmbeddingModel",
        collections: Optional[list["Collection"]] = None,
        websites: Optional[list["Website"]] = None,
        integration_knowledge_list: Optional[list[IntegrationKnowledge]] = None,
        info_blob_ids: Optional[list[UUID]] = None,
        num_chunks: Optional[int] = 30,
        autocut_cutoff: Optional[int] = None,
        min_score: Optional[float] = None,
    ) -> list[InfoBlobChunkInDBWithScore]:
        group_ids = [group.id for group in (collections or [])]
        website_ids = [website.id for website in (websites or [])]
        integration_knowledge_ids = [i.id for i in (integration_knowledge_list or [])]

        # The scope buckets are OR-ed in SQL, so combining a document with its
        # own sources would widen the search back out to those sources instead
        # of narrowing it to the document. On an authorization-adjacent
        # predicate that footgun is worth making unconstructible.
        if info_blob_ids and (group_ids or website_ids or integration_knowledge_ids):
            raise ValueError(
                "info_blob_ids narrows a search to single documents and cannot be "
                "combined with collection, website or integration scopes."
            )

        start = time.time()
        search_string_embedding = (
            await self.create_embeddings_service.get_embedding_for_query(
                model=embedding_model, query=search_string
            )
        )
        step_1 = time.time()
        semantic_results = await self.chunk_repo.semantic_search(
            search_string_embedding,
            group_ids=group_ids,
            website_ids=website_ids,
            integration_knowledge_ids=integration_knowledge_ids,
            info_blob_ids=info_blob_ids,
            limit=num_chunks if num_chunks is not None else 30,
        )
        end = time.time()

        logger.debug(
            f"Time to get results: Embed step: {step_1 - start},"
            f" Search step: {end - step_1}, Total: {end - start}"
        )

        # Vector search returns nearest neighbors unconditionally; a relevance
        # floor lets callers drop chunks that merely happen to be the least
        # distant (e.g. retrieval triggered by an off-topic message). Score
        # scales are embedding-model-dependent, so there is no global default.
        if min_score is not None:
            semantic_results = [
                res for res in semantic_results if res.score >= min_score
            ]

        scores = [res.score for res in semantic_results]

        if autocut_cutoff is not None:
            cut_point = autocut(scores, autocut_cutoff)
            return semantic_results[:cut_point]

        return semantic_results
