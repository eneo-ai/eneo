from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import AsyncSession, DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.database.tables.users_table import Users
from eneo.files.file_models import FileContentVariant, FileType
from eneo.files.file_repo import FileRepository
from eneo.files.file_service import FileService
from eneo.main.exceptions import NotFoundException
from eneo.object_content.content import ContentFailureCode, ContentState, StorageKind
from eneo.users.user import UserInDB


async def _owner_ids(session: AsyncSession) -> tuple[UUID, UUID]:
    row = (await session.execute(sa.select(Users.tenant_id, Users.id))).one()
    return row.tenant_id, row.id


async def _add_file(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    name: str,
    parent_file_id: UUID | None = None,
) -> Files:
    file = Files(
        name=name,
        mimetype="application/pdf",
        file_type=FileType.TEXT.value,
        tenant_id=tenant_id,
        user_id=user_id,
        parent_file_id=parent_file_id,
    )
    session.add(file)
    await session.flush()
    return file


async def _add_pending_reference(
    session: AsyncSession,
    *,
    file_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    variant: FileContentVariant,
    ordinal: int = 0,
) -> UUID:
    payload = f"{file_id}:{variant.value}:{ordinal}".encode()
    content = ObjectContents(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        storage_kind=StorageKind.OBJECT_STORE.value,
        state=ContentState.PENDING.value,
        access_class="private_resource",
        sha256=sha256(payload).digest(),
        size_bytes=len(payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        idempotency_key=uuid4().hex,
        request_fingerprint=sha256(uuid4().bytes).digest(),
    )
    session.add(content)
    await session.flush()
    session.add(
        ObjectStoreObjects(
            content_id=content.id,
            storage_kind=StorageKind.OBJECT_STORE.value,
            object_key=f"visibility-test/{uuid4().hex}",
        )
    )
    session.add(
        FileContentReferences(
            file_id=file_id,
            content_id=content.id,
            variant=variant.value,
            ordinal=ordinal,
        )
    )
    await session.flush()
    return content.id


async def _set_content_state(
    session: AsyncSession,
    content_id: UUID,
    state: ContentState,
) -> None:
    values: dict[str, object] = {"state": state.value}
    if state is ContentState.AVAILABLE:
        values.update(
            available_at=datetime.now(UTC),
            failure_code=None,
            failure_detail=None,
        )
    elif state is ContentState.FAILED:
        values.update(
            failure_code=ContentFailureCode.BACKEND_MISSING.value,
            failure_detail="injected visibility failure",
        )
    await session.execute(
        sa.update(ObjectContents)
        .where(ObjectContents.id == content_id)
        .values(**values)
    )


async def _assert_family_hidden(
    session: AsyncSession,
    *,
    root_id: UUID,
    derivative_id: UUID,
    user_id: UUID,
) -> None:
    repository = FileRepository(session)
    assert (
        await repository.get_list_by_id_and_user(
            [root_id, derivative_id],
            user_id,
        )
        == []
    )
    assert await repository.get_by_ids([root_id, derivative_id]) == []
    assert await repository.get_by_parent_ids([root_id], user_id) == []
    assert await repository.get_list_by_user(user_id) == []
    assert await repository.get_infos_by_ids([root_id, derivative_id]) == []
    with pytest.raises(NotFoundException):
        await repository.get_by_id(root_id)
    with pytest.raises(NotFoundException):
        await repository.get_by_id(derivative_id)
    with pytest.raises(NotFoundException):
        await repository.get_by_id_for_update(root_id)


@pytest.mark.asyncio
async def test_file_family_appears_only_after_its_final_content_promotion(
    object_content_database: DatabaseSessionManager,
) -> None:
    async with object_content_database.session() as session, session.begin():
        tenant_id, user_id = await _owner_ids(session)
        root = await _add_file(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            name="pending-family.pdf",
        )
        derivative = await _add_file(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            name="page-1.png",
            parent_file_id=root.id,
        )
        content_ids = (
            await _add_pending_reference(
                session,
                file_id=root.id,
                tenant_id=tenant_id,
                user_id=user_id,
                variant=FileContentVariant.ORIGINAL,
            ),
            await _add_pending_reference(
                session,
                file_id=root.id,
                tenant_id=tenant_id,
                user_id=user_id,
                variant=FileContentVariant.EXTRACTED_TEXT,
            ),
            await _add_pending_reference(
                session,
                file_id=derivative.id,
                tenant_id=tenant_id,
                user_id=user_id,
                variant=FileContentVariant.DERIVED_PAGE,
            ),
        )
        root_id = root.id
        derivative_id = derivative.id

    async with object_content_database.session() as session, session.begin():
        await _assert_family_hidden(
            session,
            root_id=root_id,
            derivative_id=derivative_id,
            user_id=user_id,
        )
        references = await FileRepository(session).get_content_references(
            [root_id, derivative_id]
        )
        assert {reference.content_id for reference in references} == set(content_ids)
        assert (
            await FileRepository(session).get_by_id_for_lifecycle(root_id)
        ) is not None
        assert (
            await FileRepository(session).get_by_id_and_owner_for_lifecycle(
                file_id=root_id,
                user_id=user_id,
                tenant_id=tenant_id,
            )
        ) is not None

    for content_id in content_ids[:-1]:
        async with object_content_database.session() as session, session.begin():
            await _set_content_state(session, content_id, ContentState.AVAILABLE)
        async with object_content_database.session() as session, session.begin():
            await _assert_family_hidden(
                session,
                root_id=root_id,
                derivative_id=derivative_id,
                user_id=user_id,
            )

    async with object_content_database.session() as session, session.begin():
        await _set_content_state(
            session,
            content_ids[-1],
            ContentState.AVAILABLE,
        )

    async with object_content_database.session() as session, session.begin():
        repository = FileRepository(session)
        assert [file.id for file in await repository.get_list_by_user(user_id)] == [
            root_id
        ]
        assert {
            file.id for file in await repository.get_by_ids([root_id, derivative_id])
        } == {root_id, derivative_id}
        assert [
            file.id for file in await repository.get_by_parent_ids([root_id], user_id)
        ] == [derivative_id]
        assert (await repository.get_by_id(root_id)).id == root_id
        assert (await repository.get_by_id(derivative_id)).id == derivative_id
        assert {
            info.id
            for info in await repository.get_infos_by_ids([root_id, derivative_id])
        } == {root_id, derivative_id}


@pytest.mark.asyncio
async def test_failed_family_disappears_but_lifecycle_and_references_remain(
    object_content_database: DatabaseSessionManager,
) -> None:
    async with object_content_database.session() as session, session.begin():
        tenant_id, user_id = await _owner_ids(session)
        healthy = await _add_file(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            name="healthy.pdf",
        )
        healthy_content_id = await _add_pending_reference(
            session,
            file_id=healthy.id,
            tenant_id=tenant_id,
            user_id=user_id,
            variant=FileContentVariant.ORIGINAL,
        )
        await _set_content_state(
            session,
            healthy_content_id,
            ContentState.AVAILABLE,
        )
        failed = await _add_file(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            name="failed.pdf",
        )
        failed_content_id = await _add_pending_reference(
            session,
            file_id=failed.id,
            tenant_id=tenant_id,
            user_id=user_id,
            variant=FileContentVariant.ORIGINAL,
        )
        await _set_content_state(
            session,
            failed_content_id,
            ContentState.AVAILABLE,
        )
        healthy_id = healthy.id
        failed_id = failed.id

    async with object_content_database.session() as session, session.begin():
        repository = FileRepository(session)
        assert {file.id for file in await repository.get_list_by_user(user_id)} == {
            healthy_id,
            failed_id,
        }
        await _set_content_state(
            session,
            failed_content_id,
            ContentState.FAILED,
        )

    async with object_content_database.session() as session, session.begin():
        repository = FileRepository(session)
        assert [file.id for file in await repository.get_list_by_user(user_id)] == [
            healthy_id
        ]
        with pytest.raises(NotFoundException):
            await repository.get_by_id(failed_id)
        lifecycle = await repository.get_by_id_and_owner_for_lifecycle(
            file_id=failed_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        assert lifecycle is not None
        assert [
            reference.content_id
            for reference in await repository.get_content_references([failed_id])
        ] == [failed_content_id]
        service = FileService(
            user=UserInDB.model_construct(id=user_id, tenant_id=tenant_id),
            repo=repository,
            protocol=AsyncMock(),
            object_content=AsyncMock(),
        )
        assert (await service.delete_file(failed_id)).id == failed_id

    async with object_content_database.session() as session, session.begin():
        assert await session.get(Files, failed_id) is None
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(FileContentReferences)
                .where(FileContentReferences.file_id == failed_id)
            )
        ) == 0
        failed_content = await session.get(ObjectContents, failed_content_id)
        assert failed_content is not None
        assert failed_content.state == ContentState.FAILED.value
        assert failed_content.reference_count == 0
        assert failed_content.delete_requested_at is not None


def _explain_nodes(plan: dict[str, object]):
    yield plan
    for child in plan.get("Plans", []):
        assert isinstance(child, dict)
        yield from _explain_nodes(child)


@pytest.mark.asyncio
async def test_family_visibility_is_one_query_with_indexed_content_lookups(
    object_content_database: DatabaseSessionManager,
) -> None:
    root_ids: list[UUID] = []
    representative_root_id: UUID | None = None
    async with object_content_database.session() as session, session.begin():
        tenant_id, user_id = await _owner_ids(session)
        content_ids: list[UUID] = []
        for index in range(96):
            root = await _add_file(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                name=f"family-{index}.pdf",
            )
            derivative = await _add_file(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                name=f"family-{index}-page.png",
                parent_file_id=root.id,
            )
            root_ids.append(root.id)
            representative_root_id = root.id
            content_ids.extend(
                [
                    await _add_pending_reference(
                        session,
                        file_id=root.id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        variant=FileContentVariant.ORIGINAL,
                    ),
                    await _add_pending_reference(
                        session,
                        file_id=derivative.id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        variant=FileContentVariant.DERIVED_PAGE,
                    ),
                ]
            )

        await session.execute(
            sa.update(ObjectContents)
            .where(ObjectContents.id.in_(content_ids))
            .values(
                state=ContentState.AVAILABLE.value,
                available_at=datetime.now(UTC),
            )
        )
        await session.execute(
            sa.text("ANALYZE files, file_content_references, object_contents")
        )

        statements: list[str] = []

        def capture_statement(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            statements.append(statement)

        assert session.bind is not None
        engine = session.bind.sync_engine
        sa.event.listen(engine, "before_cursor_execute", capture_statement)
        try:
            files = await FileRepository(session).get_by_ids(root_ids)
        finally:
            sa.event.remove(engine, "before_cursor_execute", capture_statement)

        assert {file.id for file in files} == set(root_ids)
        assert len(statements) == 1

        assert representative_root_id is not None
        statement = sa.select(Files.id).where(
            Files.id == representative_root_id,
            FileRepository._visible_family(),
        )
        sql = str(
            statement.compile(
                dialect=session.bind.dialect,
                compile_kwargs={"literal_binds": True},
            )
        )
        explained = (
            await session.execute(
                sa.text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
            )
        ).scalar_one()

        assert isinstance(explained, list)
        plan = explained[0]["Plan"]
        assert isinstance(plan, dict)
        nodes = list(_explain_nodes(plan))
        assert not any(
            node.get("Node Type") == "Seq Scan"
            and node.get("Relation Name") == "object_contents"
            for node in nodes
        )
        assert any(
            node.get("Relation Name") == "object_contents"
            and node.get("Node Type") in {"Index Scan", "Index Only Scan"}
            for node in nodes
        )
