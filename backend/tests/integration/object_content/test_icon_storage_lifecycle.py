import asyncio
from collections.abc import AsyncGenerator, AsyncIterable, Sequence
from contextlib import asynccontextmanager
from io import BytesIO
from uuid import UUID

import pytest
from fastapi import UploadFile
from sqlalchemy import func, select

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.icons_table import Icons
from eneo.database.tables.object_content_table import (
    IconContentReferences,
    InlineContentPayloads,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.database.tables.users_table import Users
from eneo.files.file_size_service import FileSizeService
from eneo.icons.icon_repo import IconRepository
from eneo.icons.icon_service import IconService
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import (
    CapturedContent,
    ContentFailureCode,
    ContentState,
    ObjectContentUnavailableError,
    StorageKind,
)
from eneo.object_content.content_service import (
    ObjectContentService,
    VerifiedObjectPublication,
)
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot
from eneo.users.user import UserInDB
from tests.integration.object_content.conftest import RealObjectStore

_ICON_LIMIT_BYTES = 1024 * 1024


class _ReadyObjectStoreContentService(ObjectContentService):
    async def ensure_target_ready(self, storage_kind: StorageKind) -> None:
        assert storage_kind is StorageKind.OBJECT_STORE


class _PausingStoreContentService(ObjectContentService):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.store_started = asyncio.Event()
        self.release_store = asyncio.Event()
        self.object_key: str | None = None

    async def ensure_target_ready(self, storage_kind: StorageKind) -> None:
        del storage_kind

    @asynccontextmanager
    async def upload_for_publication(
        self,
        contents: Sequence[CapturedContent],
    ) -> AsyncGenerator[VerifiedObjectPublication]:
        async with super().upload_for_publication(contents) as publication:
            self.object_key = publication.uploads[0].object_key
            self.store_started.set()
            await self.release_store.wait()
            yield publication


class _FailingStoreContentService(ObjectContentService):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.object_key: str | None = None

    async def ensure_target_ready(self, storage_kind: StorageKind) -> None:
        del storage_kind

    @asynccontextmanager
    async def upload_for_publication(
        self,
        contents: Sequence[CapturedContent],
    ) -> AsyncGenerator[VerifiedObjectPublication]:
        async with super().upload_for_publication(contents) as publication:
            self.object_key = publication.uploads[0].object_key
            if publication.uploads:
                raise ObjectContentUnavailableError("injected object-store outage")
            yield publication


class _CancelAfterPublicationContentService(ObjectContentService):
    async def ensure_target_ready(self, storage_kind: StorageKind) -> None:
        del storage_kind

    @asynccontextmanager
    async def capture_for_target(
        self,
        source: AsyncIterable[bytes],
        *,
        storage_kind: StorageKind,
        declared_media_type: str,
        verified_media_type: str,
        business_maximum_bytes: int,
    ) -> AsyncGenerator[CapturedContent]:
        async with super().capture_for_target(
            source,
            storage_kind=storage_kind,
            declared_media_type=declared_media_type,
            verified_media_type=verified_media_type,
            business_maximum_bytes=business_maximum_bytes,
        ) as captured:
            yield captured
            raise asyncio.CancelledError


def _admission(
    target: StorageKind,
    *,
    revision: int,
    maximum_bytes: int = _ICON_LIMIT_BYTES,
) -> UploadAdmissionSnapshot:
    return UploadAdmissionSnapshot(
        policy_revision=revision,
        new_write_storage_target=target,
        session_file_maximum_bytes=maximum_bytes,
        session_image_maximum_bytes=maximum_bytes,
        session_audio_maximum_bytes=maximum_bytes,
        knowledge_file_maximum_bytes=maximum_bytes,
        knowledge_audio_maximum_bytes=maximum_bytes,
    )


def _content_service(
    database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    service_type: type[ObjectContentService] = ObjectContentService,
) -> ObjectContentService:
    return service_type(
        ObjectContentCoreSettings(
            _env_file=None,
            inline_maximum_bytes=_ICON_LIMIT_BYTES,
            inline_io_chunk_bytes=64 * 1024,
        ),
        database,
        object_store_settings=real_object_store.settings,
        object_store=real_object_store.store,
    )


async def _user(database: DatabaseSessionManager) -> UserInDB:
    async with database.session() as session, session.begin():
        row = (await session.scalars(select(Users))).first()
        assert row is not None
        return UserInDB.model_construct(id=row.id, tenant_id=row.tenant_id)


async def _read_icon_bytes(service: IconService, icon_id: UUID) -> bytes:
    opened = await service.open_icon(icon_id)
    try:
        return b"".join([chunk async for chunk in opened.chunks])
    finally:
        await opened.aclose()


async def _publication_row_counts(
    database: DatabaseSessionManager,
) -> tuple[int, int, int, int, int]:
    async with database.session() as session, session.begin():
        return (
            await session.scalar(select(func.count()).select_from(Icons)) or 0,
            await session.scalar(
                select(func.count()).select_from(IconContentReferences)
            )
            or 0,
            await session.scalar(select(func.count()).select_from(ObjectContents)) or 0,
            await session.scalar(select(func.count()).select_from(ObjectStoreObjects))
            or 0,
            await session.scalar(
                select(func.count()).select_from(InlineContentPayloads)
            )
            or 0,
        )


def _upload(payload: bytes) -> UploadFile:
    return UploadFile(
        file=BytesIO(payload),
        filename="icon.png",
        headers={"content-type": "image/png"},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inline_and_object_store_icons_are_immediately_byte_identical(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    payload = b"\x89PNG\r\n\x1a\nsame-icon"
    user = await _user(object_content_database)
    content_service = _content_service(
        object_content_database,
        real_object_store,
    )
    created: list[tuple[UUID, StorageKind]] = []
    remote_object_key: str | None = None

    try:
        for revision, target in enumerate(StorageKind, start=41):
            async with object_content_database.session() as session:
                created_icon = await IconService(
                    icon_repo=IconRepository(session),
                    file_size_service=FileSizeService(),
                    object_content=content_service,
                    upload_admission=_admission(target, revision=revision),
                ).create_icon(
                    _upload(payload),
                    tenant_id=user.tenant_id,
                    created_by_user_id=user.id,
                )
                created.append((created_icon.id, target))

            async with object_content_database.session() as session, session.begin():
                content = await session.scalar(
                    select(ObjectContents)
                    .join(
                        IconContentReferences,
                        IconContentReferences.content_id == ObjectContents.id,
                    )
                    .where(IconContentReferences.icon_id == created_icon.id)
                )
                assert content is not None
                assert content.storage_kind == target.value
                assert content.state == ContentState.AVAILABLE.value
                if target is StorageKind.OBJECT_STORE:
                    descriptor = await session.get(ObjectStoreObjects, content.id)
                    assert descriptor is not None
                    remote_object_key = descriptor.object_key

            for icon_id, _target in created:
                async with object_content_database.session() as session:
                    assert (
                        await _read_icon_bytes(
                            IconService(
                                icon_repo=IconRepository(session),
                                file_size_service=FileSizeService(),
                                object_content=content_service,
                            ),
                            icon_id,
                        )
                        == payload
                    )
    finally:
        if remote_object_key is not None:
            await real_object_store.store.delete_and_confirm(remote_object_key)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_policy_sized_object_store_icon_spools_and_streams_in_chunks(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    payload = b"\x89PNG\r\n\x1a\n" + b"x" * (8 * 1024 * 1024)
    user = await _user(object_content_database)
    content_service = _content_service(
        object_content_database,
        real_object_store,
        _ReadyObjectStoreContentService,
    )
    remote_object_key: str | None = None

    async with object_content_database.session() as session:
        created = await IconService(
            icon_repo=IconRepository(session),
            file_size_service=FileSizeService(),
            object_content=content_service,
            upload_admission=_admission(
                StorageKind.OBJECT_STORE,
                revision=45,
                maximum_bytes=len(payload),
            ),
        ).create_icon(
            _upload(payload),
            tenant_id=user.tenant_id,
            created_by_user_id=user.id,
        )

    try:
        async with object_content_database.session() as session, session.begin():
            descriptor = await session.scalar(
                select(ObjectStoreObjects)
                .join(
                    IconContentReferences,
                    IconContentReferences.content_id == ObjectStoreObjects.content_id,
                )
                .where(IconContentReferences.icon_id == created.id)
            )
            assert descriptor is not None
            remote_object_key = descriptor.object_key

        async with object_content_database.session() as session:
            opened = await IconService(
                icon_repo=IconRepository(session),
                file_size_service=FileSizeService(),
                object_content=content_service,
            ).open_icon(created.id)
            try:
                chunks = [chunk async for chunk in opened.chunks]
            finally:
                await opened.aclose()

        assert len(chunks) > 1
        assert b"".join(chunks) == payload
    finally:
        if remote_object_key is not None:
            await real_object_store.store.delete_and_confirm(remote_object_key)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_object_store_icon_is_not_published_until_remote_verification_finishes(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    payload = b"\x89PNG\r\n\x1a\npending-icon"
    user = await _user(object_content_database)
    content_service = _content_service(
        object_content_database,
        real_object_store,
        _PausingStoreContentService,
    )
    assert isinstance(content_service, _PausingStoreContentService)
    remote_object_key: str | None = None
    baseline = await _publication_row_counts(object_content_database)

    async with object_content_database.session() as create_session:
        create_task = asyncio.create_task(
            IconService(
                icon_repo=IconRepository(create_session),
                file_size_service=FileSizeService(),
                object_content=content_service,
                upload_admission=_admission(StorageKind.OBJECT_STORE, revision=51),
            ).create_icon(
                _upload(payload),
                tenant_id=user.tenant_id,
                created_by_user_id=user.id,
            )
        )
        await content_service.store_started.wait()
        assert content_service.object_key is not None

        assert await _publication_row_counts(object_content_database) == baseline

        content_service.release_store.set()
        created = await create_task

    try:
        async with object_content_database.session() as session, session.begin():
            repository = IconRepository(session)
            assert await repository.get(created.id) is not None
            descriptor = await session.scalar(
                select(ObjectStoreObjects)
                .join(
                    IconContentReferences,
                    IconContentReferences.content_id == ObjectStoreObjects.content_id,
                )
                .where(IconContentReferences.icon_id == created.id)
            )
            assert descriptor is not None
            remote_object_key = descriptor.object_key

            async with object_content_database.session() as session:
                assert (
                    await _read_icon_bytes(
                        IconService(
                            icon_repo=IconRepository(session),
                            file_size_service=FileSizeService(),
                            object_content=content_service,
                        ),
                        created.id,
                    )
                    == payload
                )
    finally:
        if remote_object_key is not None:
            await real_object_store.store.delete_and_confirm(remote_object_key)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cancelled_verified_upload_leaves_only_bounded_remote_residue(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    user = await _user(object_content_database)
    content_service = _content_service(
        object_content_database,
        real_object_store,
        _PausingStoreContentService,
    )
    assert isinstance(content_service, _PausingStoreContentService)
    baseline = await _publication_row_counts(object_content_database)

    try:
        async with object_content_database.session() as create_session:
            create_task = asyncio.create_task(
                IconService(
                    icon_repo=IconRepository(create_session),
                    file_size_service=FileSizeService(),
                    object_content=content_service,
                    upload_admission=_admission(
                        StorageKind.OBJECT_STORE,
                        revision=61,
                    ),
                ).create_icon(
                    _upload(b"\x89PNG\r\n\x1a\ncancelled-icon"),
                    tenant_id=user.tenant_id,
                    created_by_user_id=user.id,
                )
            )
            await content_service.store_started.wait()
            assert content_service.object_key is not None
            create_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await create_task

        assert await _publication_row_counts(object_content_database) == baseline
        head = await real_object_store.store.head(content_service.object_key)
        assert head.size_bytes > 0
    finally:
        if content_service.object_key is not None:
            await real_object_store.store.delete_and_confirm(content_service.object_key)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remote_failure_publishes_no_icon_or_content_rows(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    user = await _user(object_content_database)
    content_service = _content_service(
        object_content_database,
        real_object_store,
        _FailingStoreContentService,
    )
    assert isinstance(content_service, _FailingStoreContentService)
    baseline = await _publication_row_counts(object_content_database)

    try:
        async with object_content_database.session() as create_session:
            with pytest.raises(ObjectContentUnavailableError):
                await IconService(
                    icon_repo=IconRepository(create_session),
                    file_size_service=FileSizeService(),
                    object_content=content_service,
                    upload_admission=_admission(
                        StorageKind.OBJECT_STORE,
                        revision=71,
                    ),
                ).create_icon(
                    _upload(b"\x89PNG\r\n\x1a\nfailed-icon"),
                    tenant_id=user.tenant_id,
                    created_by_user_id=user.id,
                )

        assert await _publication_row_counts(object_content_database) == baseline
    finally:
        if content_service.object_key is not None:
            await real_object_store.store.delete_and_confirm(content_service.object_key)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cancellation_after_publication_preserves_visible_icon(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    payload = b"\x89PNG\r\n\x1a\npublished-icon"
    user = await _user(object_content_database)
    content_service = _content_service(
        object_content_database,
        real_object_store,
        _CancelAfterPublicationContentService,
    )
    remote_object_key: str | None = None

    async with object_content_database.session() as create_session:
        with pytest.raises(asyncio.CancelledError):
            await IconService(
                icon_repo=IconRepository(create_session),
                file_size_service=FileSizeService(),
                object_content=content_service,
                upload_admission=_admission(StorageKind.OBJECT_STORE, revision=81),
            ).create_icon(
                _upload(payload),
                tenant_id=user.tenant_id,
                created_by_user_id=user.id,
            )

    try:
        async with object_content_database.session() as session, session.begin():
            icon_id = await session.scalar(
                select(Icons.id)
                .join(
                    IconContentReferences,
                    IconContentReferences.icon_id == Icons.id,
                )
                .join(
                    ObjectContents,
                    ObjectContents.id == IconContentReferences.content_id,
                )
                .where(
                    ObjectContents.state == ContentState.AVAILABLE.value,
                    ObjectContents.storage_kind == StorageKind.OBJECT_STORE.value,
                )
            )
            assert icon_id is not None
            assert await IconRepository(session).get(icon_id) is not None
            descriptor = await session.scalar(
                select(ObjectStoreObjects).join(
                    IconContentReferences,
                    IconContentReferences.content_id == ObjectStoreObjects.content_id,
                )
            )
            assert descriptor is not None
            remote_object_key = descriptor.object_key
    finally:
        if remote_object_key is not None:
            await real_object_store.store.delete_and_confirm(remote_object_key)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_failed_icon_stays_hidden_and_tenant_deletable(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    user = await _user(object_content_database)
    content_service = _content_service(
        object_content_database,
        real_object_store,
    )
    async with object_content_database.session() as create_session:
        created = await IconService(
            icon_repo=IconRepository(create_session),
            file_size_service=FileSizeService(),
            object_content=content_service,
            upload_admission=_admission(StorageKind.POSTGRES_INLINE, revision=91),
        ).create_icon(
            _upload(b"\x89PNG\r\n\x1a\nfailed-after-create"),
            tenant_id=user.tenant_id,
            created_by_user_id=user.id,
        )

    async with object_content_database.session() as session, session.begin():
        content = await session.scalar(
            select(ObjectContents)
            .join(
                IconContentReferences,
                IconContentReferences.content_id == ObjectContents.id,
            )
            .where(IconContentReferences.icon_id == created.id)
        )
        assert content is not None
        content.state = ContentState.FAILED.value
        content.failure_code = ContentFailureCode.BACKEND_MISSING.value

    async with object_content_database.session() as session, session.begin():
        repository = IconRepository(session)
        assert await repository.get(created.id) is None
        assert await repository.get_for_lifecycle(created.id) is not None

    async with object_content_database.session() as session:
        repository = IconRepository(session)
        with pytest.raises(NotFoundException):
            await _read_icon_bytes(
                IconService(
                    icon_repo=repository,
                    file_size_service=FileSizeService(),
                    object_content=content_service,
                ),
                created.id,
            )

    other_tenant = UUID("00000000-0000-0000-0000-000000000001")
    async with object_content_database.session() as session:
        with pytest.raises(BadRequestException):
            await IconService(
                icon_repo=IconRepository(session),
                file_size_service=FileSizeService(),
                object_content=content_service,
            ).delete_icon(created.id, other_tenant)

    async with object_content_database.session() as session, session.begin():
        assert await session.get(Icons, created.id) is not None

    async with object_content_database.session() as session:
        await IconService(
            icon_repo=IconRepository(session),
            file_size_service=FileSizeService(),
            object_content=content_service,
        ).delete_icon(created.id, user.tenant_id)

    async with object_content_database.session() as session, session.begin():
        assert await session.get(Icons, created.id) is None
