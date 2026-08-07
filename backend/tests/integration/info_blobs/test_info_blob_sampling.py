"""Postgres-level behaviour behind the query-less source overview.

The window arithmetic that picks band midpoints, the empty-``IN`` semantics of
the document scope bucket, and the active-version predicate are all decided by
Postgres rather than by SQLAlchemy compilation, so they need a real database.
"""

from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import sqlalchemy as sa

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.info_blob_chunk_table import InfoBlobChunks
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.spaces_table import Spaces


async def _seed_collection(container, *, name: str, space=None):
    """A collection, creating the owning space on first use.

    ``spaces.user_id`` is unique, so every collection in one test has to share
    the same space.
    """
    session = container.session()
    user = container.user()
    embedding_model = (await session.scalars(sa.select(EmbeddingModels).limit(1))).one()
    if space is None:
        space = Spaces(
            name=f"Sampling space {uuid4().hex[:8]}",
            tenant_id=user.tenant_id,
            user_id=user.id,
        )
        session.add(space)
        await session.flush()
    collection = CollectionsTable(
        name=name,
        size=0,
        user_id=user.id,
        tenant_id=user.tenant_id,
        embedding_model_id=embedding_model.id,
        space_id=space.id,
    )
    session.add(collection)
    await session.flush()
    return collection, embedding_model, space


async def _seed_document(
    container,
    collection,
    embedding_model,
    *,
    title: str,
    chunk_count: int,
    active: bool = True,
):
    session = container.session()
    user = container.user()
    text = f"{title} body"
    blob = InfoBlobs(
        title=title,
        text=text,
        size=len(text.encode("utf-8")),
        content_hash=sha256(text.encode("utf-8")).digest(),
        source_id=uuid4(),
        version_state=(
            InfoBlobVersionState.ACTIVE.value
            if active
            else InfoBlobVersionState.SUPERSEDED.value
        ),
        user_id=user.id,
        tenant_id=user.tenant_id,
        group_id=collection.id,
        embedding_model_id=embedding_model.id,
    )
    session.add(blob)
    await session.flush()
    for chunk_no in range(chunk_count):
        session.add(
            InfoBlobChunks(
                info_blob_id=blob.id,
                tenant_id=user.tenant_id,
                chunk_no=chunk_no,
                text=f"{title} chunk {chunk_no}",
                size=32,
                embedding=[0.1, 0.2, 0.3],
            )
        )
    await session.flush()
    return blob


async def test_sample_evenly_takes_the_midpoint_of_each_document(db_container) -> None:
    async with db_container() as container:
        collection, model, _space = await _seed_collection(container, name="Sampling")
        short = await _seed_document(
            container, collection, model, title="Short", chunk_count=1
        )
        odd = await _seed_document(
            container, collection, model, title="Odd", chunk_count=3
        )
        even = await _seed_document(
            container, collection, model, title="Even", chunk_count=4
        )

        excerpts = await container.info_blob_chunk_repo().sample_evenly(
            info_blob_ids=[short.id, odd.id, even.id]
        )

        by_blob = {excerpt.info_blob_id: excerpt for excerpt in excerpts}
        assert by_blob[short.id].chunk_no == 0
        assert by_blob[odd.id].chunk_no == 1
        assert by_blob[even.id].chunk_no == 2
        assert by_blob[odd.id].text == "Odd chunk 1"


async def test_sample_evenly_spreads_multiple_chunks_per_document(
    db_container,
) -> None:
    async with db_container() as container:
        collection, model, _space = await _seed_collection(container, name="Sampling")
        blob = await _seed_document(
            container, collection, model, title="Long", chunk_count=4
        )

        excerpts = await container.info_blob_chunk_repo().sample_evenly(
            info_blob_ids=[blob.id], per_document=2
        )

        assert [excerpt.chunk_no for excerpt in excerpts] == [1, 3]


async def test_sample_evenly_never_repeats_a_chunk_in_a_short_document(
    db_container,
) -> None:
    # Bands collapse onto the same row when a document has fewer chunks than
    # requested passages; each chunk must still come back at most once.
    async with db_container() as container:
        collection, model, _space = await _seed_collection(container, name="Sampling")
        blob = await _seed_document(
            container, collection, model, title="Tiny", chunk_count=2
        )

        excerpts = await container.info_blob_chunk_repo().sample_evenly(
            info_blob_ids=[blob.id], per_document=4
        )

        assert [excerpt.chunk_no for excerpt in excerpts] == [0, 1]


async def test_sample_evenly_ignores_superseded_versions(db_container) -> None:
    async with db_container() as container:
        collection, model, _space = await _seed_collection(container, name="Sampling")
        active = await _seed_document(
            container, collection, model, title="Active", chunk_count=2
        )
        superseded = await _seed_document(
            container,
            collection,
            model,
            title="Superseded",
            chunk_count=2,
            active=False,
        )

        excerpts = await container.info_blob_chunk_repo().sample_evenly(
            info_blob_ids=[active.id, superseded.id]
        )

        assert [excerpt.info_blob_id for excerpt in excerpts] == [active.id]


async def test_sample_evenly_without_ids_touches_no_documents(db_container) -> None:
    async with db_container() as container:
        collection, model, _space = await _seed_collection(container, name="Sampling")
        await _seed_document(
            container, collection, model, title="Present", chunk_count=2
        )

        excerpts = await container.info_blob_chunk_repo().sample_evenly(
            info_blob_ids=[]
        )

        assert excerpts == []


async def test_document_scope_returns_only_that_document(db_container) -> None:
    async with db_container() as container:
        collection, model, _space = await _seed_collection(container, name="Sampling")
        wanted = await _seed_document(
            container, collection, model, title="Wanted", chunk_count=2
        )
        await _seed_document(container, collection, model, title="Other", chunk_count=2)

        chunks = await container.info_blob_chunk_repo().semantic_search(
            [0.1, 0.2, 0.3], info_blob_ids=[wanted.id], limit=50
        )

        assert {chunk.info_blob_id for chunk in chunks} == {wanted.id}


async def test_empty_scope_buckets_match_no_chunks(db_container) -> None:
    async with db_container() as container:
        collection, model, _space = await _seed_collection(container, name="Sampling")
        await _seed_document(
            container, collection, model, title="Present", chunk_count=2
        )

        chunks = await container.info_blob_chunk_repo().semantic_search(
            [0.1, 0.2, 0.3], limit=50
        )

        assert chunks == []


async def test_listing_covers_a_source_alphabetically_and_excludes_others(
    db_container,
) -> None:
    async with db_container() as container:
        collection, model, space = await _seed_collection(container, name="Listed")
        other, other_model, _ = await _seed_collection(
            container, name="Unlisted", space=space
        )
        for title in ("Cykelplan", "Avfallsplan", "Budget"):
            await _seed_document(
                container, collection, model, title=title, chunk_count=1
            )
        await _seed_document(
            container, other, other_model, title="Annat", chunk_count=1
        )
        await _seed_document(
            container,
            collection,
            model,
            title="Gammal version",
            chunk_count=1,
            active=False,
        )

        repo = container.info_blob_repo()
        scope = dict(
            group_ids=[collection.id], website_ids=[], integration_knowledge_ids=[]
        )

        assert await repo.count_by_sources(**scope) == 3
        listings = await repo.list_by_sources(**scope, limit=10)
        assert [listing.title for listing in listings] == [
            "Avfallsplan",
            "Budget",
            "Cykelplan",
        ]


async def test_listing_pages_stably_by_offset(db_container) -> None:
    async with db_container() as container:
        collection, model, _space = await _seed_collection(container, name="Paged")
        for index in range(5):
            await _seed_document(
                container, collection, model, title=f"Dok {index}", chunk_count=1
            )

        repo = container.info_blob_repo()
        scope = dict(
            group_ids=[collection.id], website_ids=[], integration_knowledge_ids=[]
        )

        first = await repo.list_by_sources(**scope, limit=2, offset=0)
        second = await repo.list_by_sources(**scope, limit=2, offset=2)

        assert [listing.title for listing in first] == ["Dok 0", "Dok 1"]
        assert [listing.title for listing in second] == ["Dok 2", "Dok 3"]
