from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import defer

from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.info_blob_chunk_table import InfoBlobChunks
from eneo.database.tables.info_blobs_table import InfoBlobs, active_info_blob_version
from eneo.info_blobs.info_blob import (
    InfoBlobChunkInDB,
    InfoBlobChunkInDBWithScore,
    InfoBlobChunkWithEmbedding,
)


@dataclass(frozen=True, slots=True)
class InfoBlobChunkExcerpt:
    """A chunk read for its text alone.

    Distinct from ``InfoBlobChunkInDB``, which inherits an ``embedding`` field:
    sampling has no use for the vectors and hydrating them would move kilobytes
    per row for nothing.
    """

    info_blob_id: UUID
    chunk_no: int
    text: str


class InfoBlobChunkRepo:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.delegate: BaseRepositoryDelegate[InfoBlobChunkInDB] = (
            BaseRepositoryDelegate(
                session=session, table=InfoBlobChunks, in_db_model=InfoBlobChunkInDB
            )
        )
        self.session = session

    @staticmethod
    def _filter_on_sources(
        stmt: sa.Select[Any],
        group_ids: list[UUID],
        website_ids: list[UUID],
        integration_knowledge_ids: list[UUID],
        info_blob_ids: list[UUID] | None = None,
    ) -> sa.Select[Any]:
        # A single document is just a narrower scope handle than a collection,
        # so it joins the same OR: no branch, no scope-kind discriminator.
        # Every bucket widens the match; callers that need one scope alone pass
        # empty lists for the rest (``.in_([])`` renders false-y).
        return stmt.where(
            sa.or_(
                InfoBlobs.group_id.in_(group_ids),
                InfoBlobs.website_id.in_(website_ids),
                InfoBlobs.integration_knowledge_id.in_(integration_knowledge_ids),
                InfoBlobs.id.in_(info_blob_ids or []),
            )
        )

    async def add(
        self, chunks: list[InfoBlobChunkWithEmbedding]
    ) -> list[InfoBlobChunkInDB]:
        stmt = (
            sa.insert(InfoBlobChunks)
            .values([chunk.model_dump() for chunk in chunks])
            .returning(InfoBlobChunks)
        )

        return await self.delegate.get_models_from_query(
            stmt  # pyright: ignore[reportArgumentType]  # ReturningInsert is structurally compatible with Select at runtime
        )

    async def delete_by_info_blob(self, info_blob_id: UUID) -> list[InfoBlobChunkInDB]:
        stmt = (
            sa.delete(InfoBlobChunks)
            .where(InfoBlobChunks.info_blob_id == info_blob_id)
            .returning(InfoBlobChunks)
        )

        return await self.delegate.get_models_from_query(
            stmt  # pyright: ignore[reportArgumentType]  # ReturningDelete is structurally compatible with Select at runtime
        )

    async def semantic_search(
        self,
        embedding: list[float],
        *,
        group_ids: list[UUID] | None = None,
        website_ids: list[UUID] | None = None,
        integration_knowledge_ids: list[UUID] | None = None,
        info_blob_ids: list[UUID] | None = None,
        limit: int = 30,
    ) -> list[InfoBlobChunkInDBWithScore]:
        # Postgres will sometimes think that a sequential scan of the whole table is
        # preferable to an index scan, when it is not. This is because this particular
        # table has a lot of data in TOAST tables, which postgres apparently fails
        # to account for when planning the query.
        #
        # The solution below is a crude one, and we should revisit this at some point
        # in the future. This should also be the first place we look at if something
        # is slow. Note the "LOCAL", ensuring that we only punish sequential scans for
        # this particular session. This might make all future queries in this transaction
        # not be able to run sequential, but we will see if that is an issue.
        #
        # Reference: https://github.com/pgvector/pgvector/issues/662
        # TODO: Solve this issue in a more elegant way.

        await self.session.execute(sa.text("SET LOCAL enable_seqscan = off;"))

        stmt = (
            sa.select(
                InfoBlobChunks,
                InfoBlobChunks.embedding.cosine_distance(embedding),
                InfoBlobs.title,
            )
            .join(InfoBlobs)
            .where(active_info_blob_version())
            .options(defer(InfoBlobChunks.embedding))
            .order_by(InfoBlobChunks.embedding.cosine_distance(embedding))
            .limit(limit)
        )

        stmt = self._filter_on_sources(
            stmt,
            group_ids or [],
            website_ids or [],
            integration_knowledge_ids=integration_knowledge_ids or [],
            info_blob_ids=info_blob_ids or [],
        )

        chunks_in_db = await self.session.execute(stmt)

        chunks_with_score = [
            InfoBlobChunkInDBWithScore(
                **chunk[0].to_dict(exclude="embedding"),
                score=1 - chunk[1],
                info_blob_title=chunk[2],
            )
            for chunk in chunks_in_db
        ]

        return chunks_with_score

    async def sample_evenly(
        self,
        *,
        info_blob_ids: Sequence[UUID],
        per_document: int = 1,
    ) -> list[InfoBlobChunkExcerpt]:
        """Chunks spread evenly through each of the given documents.

        Position-based, not similarity-based: this backs questions about what a
        source contains, which have no content query to embed. Chunks are taken
        at the midpoints of ``per_document`` equal bands, so a single sample
        lands mid-document rather than on the opening chunk, which for uploaded
        PDFs is usually a title page.
        """
        if not info_blob_ids or per_document < 1:
            return []

        ranked = (
            sa.select(
                InfoBlobChunks.info_blob_id,
                InfoBlobChunks.chunk_no,
                InfoBlobChunks.text,
                sa.func.row_number()
                .over(
                    partition_by=InfoBlobChunks.info_blob_id,
                    order_by=InfoBlobChunks.chunk_no,
                )
                .label("rn"),
                sa.func.count()
                .over(partition_by=InfoBlobChunks.info_blob_id)
                .label("total"),
            )
            .join(InfoBlobs, InfoBlobs.id == InfoBlobChunks.info_blob_id)
            # Without this a superseded version's chunks could be sampled while
            # the title list beside them only shows active documents.
            .where(
                InfoBlobChunks.info_blob_id.in_(info_blob_ids),
                active_info_blob_version(),
            )
            .subquery()
        )

        band_midpoints = [
            sa.cast(
                sa.func.floor(ranked.c.total * (2 * k + 1) / (2.0 * per_document)) + 1,
                sa.Integer,
            )
            for k in range(per_document)
        ]
        stmt = (
            sa.select(ranked.c.info_blob_id, ranked.c.chunk_no, ranked.c.text)
            .where(sa.or_(*[ranked.c.rn == midpoint for midpoint in band_midpoints]))
            .order_by(ranked.c.info_blob_id, ranked.c.rn)
        )

        rows = await self.session.execute(stmt)
        return [
            InfoBlobChunkExcerpt(
                info_blob_id=row.info_blob_id, chunk_no=row.chunk_no, text=row.text
            )
            for row in rows.all()
        ]

    async def get_adjacent_chunks(
        self,
        *,
        info_blob_id: UUID,
        chunk_no: int,
        radius: int = 1,
    ) -> list[InfoBlobChunkExcerpt]:
        """Read the active document chunks immediately around one anchor."""
        if radius < 1:
            return []

        stmt = (
            sa.select(
                InfoBlobChunks.info_blob_id,
                InfoBlobChunks.chunk_no,
                InfoBlobChunks.text,
            )
            .join(InfoBlobs, InfoBlobs.id == InfoBlobChunks.info_blob_id)
            .where(
                InfoBlobChunks.info_blob_id == info_blob_id,
                InfoBlobChunks.chunk_no.between(
                    max(0, chunk_no - radius), chunk_no + radius
                ),
                InfoBlobChunks.chunk_no != chunk_no,
                active_info_blob_version(),
            )
            .order_by(InfoBlobChunks.chunk_no)
        )

        rows = await self.session.execute(stmt)
        return [
            InfoBlobChunkExcerpt(
                info_blob_id=row.info_blob_id, chunk_no=row.chunk_no, text=row.text
            )
            for row in rows.all()
        ]

    async def keyword_search(
        self,
        search_string: str,
        *,
        group_ids: Optional[list[UUID]] = None,
        limit: int = 30,
    ):
        stmt = (
            sa.select(InfoBlobChunks)
            .join(InfoBlobs)
            .filter(InfoBlobChunks.text.match(search_string))
            .where(active_info_blob_version())
            .limit(limit)
        )

        if group_ids is not None:
            stmt = self._filter_on_sources(
                stmt, group_ids, [], integration_knowledge_ids=[]
            )

        return await self.delegate.get_models_from_query(stmt)
