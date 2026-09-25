from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, select, text
from sqlalchemy.exc import SQLAlchemyError

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.base_class import Base
from eneo.database.tables.files_table import Files
from eneo.database.tables.icons_table import Icons
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    IconContentReferences,
    InfoBlobContentReferences,
    InlineContentPayloads,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.object_content import deployment_policy_router
from eneo.object_content.content import ContentOwner, ContentState, StorageKind
from eneo.object_content.reconciliation_repository import (
    CONTENT_REFERENCE_OWNER_COLUMNS,
    ObjectContentReconciliationRepository,
)


async def _owner_ids(database: DatabaseSessionManager) -> tuple[UUID, UUID]:
    async with database.session() as session, session.begin():
        tenant_id = (await session.scalars(select(Tenants.id))).one()
        user_id = (await session.scalars(select(Users.id))).one()
    return tenant_id, user_id


def _content(
    *,
    tenant_id: UUID,
    user_id: UUID,
    key: str,
    payload: bytes,
    access_class: str = "private_resource",
    storage_kind: StorageKind = StorageKind.POSTGRES_INLINE,
) -> ObjectContents:
    digest = sha256(payload).digest()
    return ObjectContents(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        storage_kind=storage_kind.value,
        state=ContentState.AVAILABLE.value,
        access_class=access_class,
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        idempotency_key=key,
        request_fingerprint=digest,
        available_at=datetime.now(UTC),
    )


def _payload(content_id: UUID, payload: bytes) -> InlineContentPayloads:
    return InlineContentPayloads(
        content_id=content_id,
        storage_kind=StorageKind.POSTGRES_INLINE.value,
        payload=payload,
    )


def test_inventory_owner_registry_covers_every_content_reference_table() -> None:
    registered_tables = {
        content_id.table.name for _owner, content_id in CONTENT_REFERENCE_OWNER_COLUMNS
    }
    reference_tables = {
        table.name
        for table in Base.metadata.tables.values()
        if table.name.endswith("_content_references")
    }

    assert registered_tables == reference_tables


@pytest.mark.asyncio
async def test_inventory_groups_each_content_once_by_product_owner(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)

    async with object_content_database.session() as session, session.begin():
        file_owner = Files(
            name="file.txt",
            mimetype="text/plain",
            file_type="text",
            tenant_id=tenant_id,
            user_id=user_id,
            parent_file_id=None,
        )
        knowledge_owner = InfoBlobs(
            text="searchable knowledge",
            title="knowledge.txt",
            url=None,
            size=20,
            content_hash=sha256(b"searchable knowledge").digest(),
            source_id=uuid4(),
            version_state=InfoBlobVersionState.ACTIVE.value,
            user_id=user_id,
            tenant_id=tenant_id,
            group_id=None,
            website_id=None,
            embedding_model_id=None,
            integration_knowledge_id=None,
            sharepoint_item_id=None,
        )
        icon_owner = Icons(tenant_id=tenant_id)
        detached_owner = Files(
            name="removed.txt",
            mimetype="text/plain",
            file_type="text",
            tenant_id=tenant_id,
            user_id=user_id,
            parent_file_id=None,
        )
        session.add_all([file_owner, knowledge_owner, icon_owner, detached_owner])
        await session.flush()

        rows = [
            (
                _content(
                    tenant_id=tenant_id, user_id=user_id, key="file", payload=b"f"
                ),
                b"f",
            ),
            (
                _content(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    key="knowledge",
                    payload=b"knowledge",
                    storage_kind=StorageKind.OBJECT_STORE,
                ),
                b"knowledge",
            ),
            (
                _content(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    key="icon",
                    payload=b"icon",
                    access_class="public_immutable",
                ),
                b"icon",
            ),
            (
                _content(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    key="detached",
                    payload=b"removed",
                ),
                b"removed",
            ),
        ]
        session.add_all([content for content, _ in rows])
        await session.flush()
        file_content, knowledge_content, icon_content, detached_content = (
            content for content, _ in rows
        )
        detached_owner_id = detached_owner.id
        detached_content_id = detached_content.id
        session.add_all(
            [
                _payload(content.id, payload)
                for content, payload in rows
                if content.storage_kind == StorageKind.POSTGRES_INLINE.value
            ]
        )
        session.add(
            ObjectStoreObjects(
                content_id=knowledge_content.id,
                storage_kind=StorageKind.OBJECT_STORE.value,
                object_key="inventory/knowledge",
                verification_chunk_size_bytes=len(b"knowledge"),
                verification_chunk_sha256=sha256(b"knowledge").digest(),
            )
        )
        session.add_all(
            [
                FileContentReferences(
                    file_id=file_owner.id,
                    content_id=file_content.id,
                    variant="original",
                    ordinal=0,
                ),
                InfoBlobContentReferences(
                    info_blob_id=knowledge_owner.id,
                    content_id=knowledge_content.id,
                    original_filename="knowledge.txt",
                ),
                IconContentReferences(
                    icon_id=icon_owner.id,
                    content_id=icon_content.id,
                    variant="primary",
                ),
                FileContentReferences(
                    file_id=detached_owner.id,
                    content_id=detached_content.id,
                    variant="original",
                    ordinal=0,
                ),
            ]
        )
        file_owner_id = file_owner.id
        file_content_id = file_content.id
        knowledge_content_id = knowledge_content.id

    async with object_content_database.session() as session, session.begin():
        session.add_all(
            [
                FileContentReferences(
                    file_id=file_owner_id,
                    content_id=file_content_id,
                    variant="preview",
                    ordinal=0,
                ),
                FileContentReferences(
                    file_id=file_owner_id,
                    content_id=knowledge_content_id,
                    variant="generated_artifact",
                    ordinal=0,
                ),
            ]
        )
        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.file_id == detached_owner_id
            )
        )
        await session.execute(
            delete(InlineContentPayloads).where(
                InlineContentPayloads.content_id == detached_content_id
            )
        )
        detached = await session.get(ObjectContents, detached_content_id)
        assert detached is not None
        detached.state = ContentState.TOMBSTONED.value
        detached.payload_deleted_at = datetime.now(UTC)

    async with object_content_database.session() as session, session.begin():
        facts = await ObjectContentReconciliationRepository(session).inventory_facts()

    assert [
        (fact.owner, fact.storage_kind, fact.state, fact.count, fact.size_bytes)
        for fact in facts
    ] == [
        (
            ContentOwner.FILE_CONTENT,
            StorageKind.POSTGRES_INLINE,
            ContentState.AVAILABLE,
            1,
            1,
        ),
        (
            ContentOwner.ICON,
            StorageKind.POSTGRES_INLINE,
            ContentState.AVAILABLE,
            1,
            4,
        ),
        (
            ContentOwner.OTHER,
            StorageKind.OBJECT_STORE,
            ContentState.AVAILABLE,
            1,
            9,
        ),
        (
            ContentOwner.OTHER,
            StorageKind.POSTGRES_INLINE,
            ContentState.TOMBSTONED,
            1,
            7,
        ),
    ]


@pytest.mark.asyncio
async def test_inventory_query_stays_bounded_for_thousands_without_loading_payloads(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    row_count = 2048

    async with object_content_database.session() as session, session.begin():
        file_owner = Files(
            name="scale.txt",
            mimetype="text/plain",
            file_type="text",
            tenant_id=tenant_id,
            user_id=user_id,
            parent_file_id=None,
        )
        session.add(file_owner)
        await session.flush()
        contents = [
            _content(
                tenant_id=tenant_id,
                user_id=user_id,
                key=f"scale-{index}",
                payload=b"x",
            )
            for index in range(row_count)
        ]
        session.add_all(contents)
        await session.flush()
        session.add_all([_payload(content.id, b"x") for content in contents])
        session.add_all(
            [
                FileContentReferences(
                    file_id=file_owner.id,
                    content_id=content.id,
                    variant="generated_artifact",
                    ordinal=index,
                )
                for index, content in enumerate(contents)
            ]
        )

    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    async with object_content_database.session() as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout = '5s'"))
        connection = await session.connection()
        event.listen(
            connection.sync_connection, "before_cursor_execute", record_statement
        )
        try:
            facts = await ObjectContentReconciliationRepository(
                session
            ).inventory_facts()
        finally:
            event.remove(
                connection.sync_connection,
                "before_cursor_execute",
                record_statement,
            )

    assert len(statements) == 1
    assert "inline_content_payloads" not in statements[0].lower()
    assert sum(fact.count for fact in facts) == row_count
    assert len(facts) <= len(ContentOwner) * len(StorageKind) * len(ContentState)


@pytest.mark.asyncio
async def test_postgresql_allocation_is_complete_or_unavailable(
    object_content_database: DatabaseSessionManager,
) -> None:
    async with object_content_database.session() as session, session.begin():
        facts = await ObjectContentReconciliationRepository(
            session
        ).postgresql_allocation_facts()

    assert facts is not None
    assert facts.total_bytes > 0
    assert facts.inline_content_bytes >= 0
    assert facts.searchable_knowledge_bytes > 0
    assert facts.other_bytes >= 0
    assert (
        facts.inline_content_bytes
        + facts.searchable_knowledge_bytes
        + facts.other_bytes
        == facts.total_bytes
    )

    async with object_content_database.session() as session, session.begin():
        await session.execute(text("SET LOCAL search_path = pg_catalog"))
        unavailable = await ObjectContentReconciliationRepository(
            session
        ).postgresql_allocation_facts()

    assert unavailable is None


@pytest.mark.asyncio
async def test_inventory_remains_available_when_postgresql_allocation_fails(
    monkeypatch: pytest.MonkeyPatch,
    object_content_database: DatabaseSessionManager,
) -> None:
    async def fail_allocation(
        _repository: ObjectContentReconciliationRepository,
    ) -> None:
        raise SQLAlchemyError("catalog unavailable")

    monkeypatch.setattr(
        ObjectContentReconciliationRepository,
        "postgresql_allocation_facts",
        fail_allocation,
    )

    async with object_content_database.session() as session:
        projection = await deployment_policy_router._read_inventory(session)
        async with session.begin():
            assert await session.scalar(select(1)) == 1

    assert projection.postgresql_allocation is None
