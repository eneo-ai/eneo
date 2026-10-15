"""Postgres-level behaviour of the digest selection queries.

The active-version predicate, the source filter re-applied on an explicit id
list, ``ILIKE`` escaping and the label ordering are decided by Postgres, so
they need a real database.
"""

from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import sqlalchemy as sa

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.spaces_table import Spaces


async def _seed_collection(container, *, name: str, space=None):
    session = container.session()
    user = container.user()
    embedding_model = (await session.scalars(sa.select(EmbeddingModels).limit(1))).one()
    if space is None:
        space = Spaces(
            name=f"Digest space {uuid4().hex[:8]}",
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
    container, collection, embedding_model, *, title: str, text: str, active=True
):
    session = container.session()
    user = container.user()
    blob = InfoBlobs(
        title=title,
        text=text,
        # Storage accounting, deliberately far from the text length: the
        # digest queries must measure the text itself.
        size=40 * len(text.encode("utf-8")) + 1000,
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
    return blob


def _ids(collection):
    return {
        "group_ids": [collection.id],
        "website_ids": [],
        "integration_knowledge_ids": [],
    }


async def test_size_and_listing_follow_the_title_filter_and_active_versions(
    db_container,
) -> None:
    async with db_container() as container:
        collection, model, _space = await _seed_collection(container, name="Minutes")
        jan = await _seed_document(
            container, collection, model, title="2026-01 minutes", text="january"
        )
        feb = await _seed_document(
            container, collection, model, title="2026-02 minutes", text="february!"
        )
        await _seed_document(
            container, collection, model, title="2025-12 minutes", text="december"
        )
        await _seed_document(
            container,
            collection,
            model,
            title="2026-03 minutes",
            text="superseded",
            active=False,
        )
        repo = container.info_blob_repo()

        assert await repo.count_by_sources(**_ids(collection)) == 3
        assert (
            await repo.count_by_sources(**_ids(collection), title_contains="2026") == 2
        )
        assert await repo.size_by_sources(
            **_ids(collection), title_contains="2026"
        ) == (
            2,
            len("january") + len("february!"),
        )
        listed = await repo.list_by_sources(
            **_ids(collection), limit=10, title_contains="2026-0"
        )
        assert [listing.id for listing in listed] == [jan.id, feb.id]
        assert (
            await repo.list_by_sources(
                **_ids(collection), limit=1, title_contains="2026"
            )
            == listed[:1]
        )


async def test_title_filter_is_case_insensitive_and_escapes_wildcards(
    db_container,
) -> None:
    async with db_container() as container:
        collection, model, _space = await _seed_collection(container, name="Escapes")
        percent = await _seed_document(
            container, collection, model, title="Budget 100% final", text="a"
        )
        await _seed_document(
            container, collection, model, title="Budget 100 final", text="b"
        )
        repo = container.info_blob_repo()

        assert (
            await repo.count_by_sources(**_ids(collection), title_contains="100%") == 1
        )
        listed = await repo.list_by_sources(
            **_ids(collection), limit=10, title_contains="budget 100% FINAL"
        )
        assert [listing.id for listing in listed] == [percent.id]
        assert (
            await repo.count_by_sources(**_ids(collection), title_contains="   ") == 2
        )


async def test_texts_come_back_in_order_within_the_source_and_active_only(
    db_container,
) -> None:
    async with db_container() as container:
        mine, model, space = await _seed_collection(container, name="Mine")
        other, _model, _space = await _seed_collection(
            container, name="Other", space=space
        )
        second = await _seed_document(
            container, mine, model, title="Second", text="second text"
        )
        first = await _seed_document(
            container, mine, model, title="First", text="first text"
        )
        stale = await _seed_document(
            container, mine, model, title="Stale", text="old", active=False
        )
        foreign = await _seed_document(
            container, other, model, title="Foreign", text="not mine"
        )
        repo = container.info_blob_repo()

        texts = await repo.list_texts_by_ids(
            [second.id, foreign.id, first.id, stale.id, uuid4(), second.id],
            **_ids(mine),
        )

        assert [(t.id, t.text, t.length) for t in texts] == [
            (second.id, "second text", len("second text")),
            (first.id, "first text", len("first text")),
        ]
        assert texts[0].label == "Second"
        assert await repo.list_texts_by_ids([], **_ids(mine)) == []
