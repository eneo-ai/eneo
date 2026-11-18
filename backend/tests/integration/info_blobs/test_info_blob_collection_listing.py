from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.spaces_table import SpacesUsers
from tests.integration.flows.statement_capture_support import capture_queries

pytestmark = pytest.mark.integration


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container(user=admin_user) as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def _seed_collection(
    db_container, admin_user, space_factory
) -> tuple[UUID, list[UUID]]:
    """A collection with two active documents and one superseded version.

    Creation times, insertion order and id order all differ, so only ordering
    by creation time gives ``active_ids``.
    """
    active_ids = [UUID(int=202), UUID(int=201)]
    created = datetime(2026, 10, 1, tzinfo=timezone.utc)
    async with db_container(user=admin_user) as container:
        session = container.session()
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        assert embedding_model_id is not None
        space = await space_factory(session, f"Collection listing {uuid4()}")
        session.add(SpacesUsers(space_id=space.id, user_id=admin_user.id, role="admin"))
        collection = CollectionsTable(
            name="Handbooks",
            space_id=space.id,
            tenant_id=admin_user.tenant_id,
            embedding_model_id=embedding_model_id,
            size=0,
            user_id=admin_user.id,
        )
        session.add(collection)
        await session.flush()
        for blob_id, state, position in (
            (active_ids[1], InfoBlobVersionState.ACTIVE, 2),
            (UUID(int=299), InfoBlobVersionState.SUPERSEDED, 1),
            (active_ids[0], InfoBlobVersionState.ACTIVE, 0),
        ):
            text = f"Handbook chapter {position} " * 50
            session.add(
                InfoBlobs(
                    id=blob_id,
                    title=f"Chapter {position}",
                    url=None,
                    text=text,
                    size=len(text.encode()),
                    content_hash=sha256(text.encode()).digest(),
                    source_id=uuid4(),
                    version_state=state.value,
                    user_id=admin_user.id,
                    tenant_id=admin_user.tenant_id,
                    group_id=collection.id,
                    embedding_model_id=embedding_model_id,
                    created_at=created + timedelta(hours=position),
                )
            )
        await session.flush()
        return collection.id, active_ids


async def test_collection_listing_reads_no_document_text(
    db_container, admin_user, space_factory
) -> None:
    collection_id, active_ids = await _seed_collection(
        db_container, admin_user, space_factory
    )

    async with db_container(user=admin_user) as container:
        session = container.session()
        bind = session.sync_session.bind
        assert bind is not None
        with capture_queries(bind) as queries:
            blobs = await container.info_blob_service().get_by_group(collection_id)

    assert [blob.id for blob in blobs] == active_ids
    assert all(not hasattr(blob, "text") for blob in blobs)
    assert all(blob.original_available is False for blob in blobs)
    blob_reads = [query.sql for query in queries if "FROM info_blobs" in query.sql]
    assert blob_reads
    assert all("info_blobs.text" not in sql for sql in blob_reads)


async def test_collection_listing_endpoint_keeps_its_contract(
    client, db_container, admin_user, admin_token: str, space_factory
) -> None:
    collection_id, active_ids = await _seed_collection(
        db_container, admin_user, space_factory
    )

    response = await client.get(
        f"/api/v1/groups/{collection_id}/info-blobs/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert set(page) == {"items", "count"}
    assert page["count"] == 2
    assert [item["id"] for item in page["items"]] == [str(i) for i in active_ids]
    first = page["items"][0]
    assert set(first) == {
        "id",
        "created_at",
        "updated_at",
        "metadata",
        "group_id",
        "website_id",
        "original_available",
        "source_metadata",
    }
    assert set(first["metadata"]) == {"url", "title", "embedding_model_id", "size"}
    assert first["metadata"]["title"] == "Chapter 0"
    assert first["metadata"]["size"] == len(("Handbook chapter 0 " * 50).encode())
    assert first["group_id"] == str(collection_id)
    assert first["website_id"] is None
    assert first["original_available"] is False
    assert first["source_metadata"] == []
