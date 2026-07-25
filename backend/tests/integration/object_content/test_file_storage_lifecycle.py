from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from io import BytesIO
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi import UploadFile

import eneo.files.file_service as file_service_module
from eneo.database.database import AsyncSession, DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.database.tables.users_table import Users
from eneo.files.file_models import FileContentVariant, FileType
from eneo.files.file_protocol import (
    FileProtocol,
    PendingFileContent,
    PreparedFileUpload,
)
from eneo.files.file_repo import FileRepository
from eneo.files.file_service import FileService
from eneo.object_content.content import (
    CapturedContent,
    ContentState,
    ObjectContentUnavailableError,
    StorageKind,
)
from eneo.object_content.content_repository import ReadableContent
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot
from eneo.object_content.s3_object_store import ObjectStoreNotFoundError, S3ObjectStore
from eneo.users.user import UserInDB
from tests.integration.object_content.conftest import RealObjectStore


async def _bytes_source(payload: bytes) -> AsyncGenerator[bytes]:
    yield payload


class _PreparedFileProtocol(FileProtocol):
    def __init__(self, prepared: PreparedFileUpload) -> None:
        self._prepared = prepared
        self.seen_snapshot: UploadAdmissionSnapshot | None = None

    @asynccontextmanager
    async def prepare_upload(
        self,
        upload_file: UploadFile,
        *,
        upload_admission_snapshot: UploadAdmissionSnapshot | None = None,
        max_size: int | None = None,
        limit_name: str | None = None,
    ) -> AsyncGenerator[PreparedFileUpload]:
        del upload_file, max_size, limit_name
        self.seen_snapshot = upload_admission_snapshot
        yield self._prepared


class _ControlledObjectContentService(ObjectContentService):
    def __init__(
        self,
        *,
        database: DatabaseSessionManager,
        real_object_store: RealObjectStore,
        fail_at: int | None = None,
        pause_at: int | None = None,
        cancel_after: int | None = None,
    ) -> None:
        super().__init__(
            real_object_store.settings,
            database,
            object_store_settings=real_object_store.settings,
            object_store=real_object_store.store,
        )
        self._fail_at = fail_at
        self._pause_at = pause_at
        self._cancel_after = cancel_after
        self.store_calls = 0
        self.paused = asyncio.Event()

    async def ensure_target_ready(self, storage_kind: StorageKind) -> None:
        assert storage_kind is StorageKind.OBJECT_STORE

    async def store_and_verify(
        self,
        *,
        content_id: UUID,
        content: CapturedContent,
    ) -> ReadableContent:
        call_index = self.store_calls
        self.store_calls += 1
        if call_index == self._fail_at:
            raise ObjectContentUnavailableError("injected File upload outage")
        if call_index == self._pause_at:
            self.paused.set()
            await asyncio.Event().wait()
        readable = await super().store_and_verify(
            content_id=content_id,
            content=content,
        )
        if call_index == self._cancel_after:
            task = asyncio.current_task()
            assert task is not None
            task.cancel()
        return readable


class _SlowCompensationFileService(FileService):
    async def _compensate_new_family(self, root_file_id: UUID) -> None:
        del root_file_id
        await asyncio.sleep(0.05)


def _snapshot(storage_target: StorageKind) -> UploadAdmissionSnapshot:
    maximum = 20 * 1024 * 1024
    return UploadAdmissionSnapshot(
        policy_revision=41,
        session_storage_target=storage_target,
        session_operator_ceiling_bytes=(
            maximum if storage_target is StorageKind.POSTGRES_INLINE else None
        ),
        session_file_maximum_bytes=maximum,
        session_image_maximum_bytes=maximum,
        session_audio_maximum_bytes=maximum,
        knowledge_file_maximum_bytes=maximum,
        knowledge_audio_maximum_bytes=maximum,
    )


def _three_content_family(name: str) -> PreparedFileUpload:
    return PreparedFileUpload(
        name=f"{name}.pdf",
        file_type=FileType.TEXT,
        display_media_type="application/pdf",
        contents=(
            PendingFileContent(
                variant=FileContentVariant.ORIGINAL,
                chunks=_bytes_source(b"%PDF exact"),
                declared_media_type="application/pdf",
                verified_media_type="application/pdf",
            ),
            PendingFileContent(
                variant=FileContentVariant.EXTRACTED_TEXT,
                chunks=_bytes_source(b"extracted"),
                declared_media_type="text/plain",
                verified_media_type="text/plain",
            ),
        ),
        derivatives=(
            PreparedFileUpload(
                name=f"{name}-page-1.png",
                file_type=FileType.IMAGE,
                display_media_type="image/png",
                contents=(
                    PendingFileContent(
                        variant=FileContentVariant.DERIVED_PAGE,
                        chunks=_bytes_source(b"\x89PNG derivative"),
                        declared_media_type="image/png",
                        verified_media_type="image/png",
                        page_number=1,
                    ),
                ),
            ),
        ),
    )


async def _user(session: AsyncSession) -> UserInDB:
    statement = sa.select(Users.id, Users.tenant_id)
    if session.in_transaction():
        row = (await session.execute(statement)).first()
    else:
        async with session.begin():
            row = (await session.execute(statement)).first()
    assert row is not None
    return UserInDB.model_construct(id=row.id, tenant_id=row.tenant_id)


def _service(
    *,
    session: AsyncSession,
    user: UserInDB,
    protocol: FileProtocol,
    object_content: ObjectContentService,
    snapshot: UploadAdmissionSnapshot,
    service_type: type[FileService] = FileService,
) -> FileService:
    return service_type(
        user=user,
        repo=FileRepository(session),
        protocol=protocol,
        object_content=object_content,
        upload_admission=snapshot,
    )


def _group_contains(error: BaseExceptionGroup, expected: type[BaseException]) -> bool:
    return any(
        isinstance(nested, expected)
        or (
            isinstance(nested, BaseExceptionGroup) and _group_contains(nested, expected)
        )
        for nested in error.exceptions
    )


async def _remote_object_keys(
    database: DatabaseSessionManager,
) -> list[str]:
    async with database.session() as session, session.begin():
        return list(await session.scalars(sa.select(ObjectStoreObjects.object_key)))


async def _delete_remote_objects(
    store: S3ObjectStore,
    object_keys: list[str],
) -> None:
    for object_key in object_keys:
        try:
            await store.delete_and_confirm(object_key)
        except ObjectStoreNotFoundError:
            pass


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", [0, 1, 2])
async def test_remote_failure_compensates_the_whole_multi_content_family(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    fail_at: int,
) -> None:
    name = f"failure-{fail_at}-{uuid4().hex}"
    protocol = _PreparedFileProtocol(_three_content_family(name))
    content_service = _ControlledObjectContentService(
        database=object_content_database,
        real_object_store=real_object_store,
        fail_at=fail_at,
    )
    snapshot = _snapshot(StorageKind.OBJECT_STORE)

    try:
        async with object_content_database.session() as session:
            user = await _user(session)
            service = _service(
                session=session,
                user=user,
                protocol=protocol,
                object_content=content_service,
                snapshot=snapshot,
            )
            with pytest.raises(
                ObjectContentUnavailableError,
                match="injected File upload outage",
            ):
                await service.save_file(
                    UploadFile(
                        file=BytesIO(),
                        filename=f"{name}.pdf",
                        headers={"content-type": "application/pdf"},
                    )
                )

        assert protocol.seen_snapshot is snapshot
        async with object_content_database.session() as session, session.begin():
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(Files)
                    .where(Files.name.like(f"{name}%"))
                )
            ) == 0
            assert (
                await session.scalar(
                    sa.select(sa.func.count()).select_from(FileContentReferences)
                )
            ) == 0
            states = Counter(await session.scalars(sa.select(ObjectContents.state)))
            assert states == Counter(
                {
                    ContentState.DELETE_PENDING.value: fail_at,
                    ContentState.FAILED.value: 3 - fail_at,
                }
            )
            assert set(
                await session.scalars(sa.select(ObjectContents.reference_count))
            ) == {0}
    finally:
        await _delete_remote_objects(
            real_object_store.store,
            await _remote_object_keys(object_content_database),
        )


@pytest.mark.asyncio
async def test_remote_failure_bounds_stalled_database_compensation(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        file_service_module,
        "_FILE_COMPENSATION_TIMEOUT_SECONDS",
        0.001,
        raising=False,
    )
    name = f"stalled-compensation-{uuid4().hex}"
    content_service = _ControlledObjectContentService(
        database=object_content_database,
        real_object_store=real_object_store,
        fail_at=0,
    )

    async with object_content_database.session() as session:
        user = await _user(session)
        service = _service(
            session=session,
            user=user,
            protocol=_PreparedFileProtocol(_three_content_family(name)),
            object_content=content_service,
            snapshot=_snapshot(StorageKind.OBJECT_STORE),
            service_type=_SlowCompensationFileService,
        )

        with pytest.raises(BaseExceptionGroup) as error:
            await service.save_file(
                UploadFile(
                    file=BytesIO(),
                    filename=f"{name}.pdf",
                    headers={"content-type": "application/pdf"},
                )
            )

    assert _group_contains(error.value, ObjectContentUnavailableError)
    assert _group_contains(error.value, TimeoutError)


@pytest.mark.asyncio
async def test_cancellation_bounds_stalled_database_compensation(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        file_service_module,
        "_FILE_COMPENSATION_TIMEOUT_SECONDS",
        0.001,
        raising=False,
    )
    name = f"cancel-stalled-compensation-{uuid4().hex}"
    content_service = _ControlledObjectContentService(
        database=object_content_database,
        real_object_store=real_object_store,
        pause_at=0,
    )

    async with object_content_database.session() as session:
        user = await _user(session)
        service = _service(
            session=session,
            user=user,
            protocol=_PreparedFileProtocol(_three_content_family(name)),
            object_content=content_service,
            snapshot=_snapshot(StorageKind.OBJECT_STORE),
            service_type=_SlowCompensationFileService,
        )
        saving = asyncio.create_task(
            service.save_file(
                UploadFile(
                    file=BytesIO(),
                    filename=f"{name}.pdf",
                    headers={"content-type": "application/pdf"},
                )
            )
        )
        await asyncio.wait_for(content_service.paused.wait(), timeout=10)
        saving.cancel()
        with pytest.raises(BaseExceptionGroup) as error:
            await saving

    assert _group_contains(error.value, asyncio.CancelledError)
    assert _group_contains(error.value, TimeoutError)


@pytest.mark.asyncio
async def test_cancellation_before_final_promotion_finishes_compensation(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    name = f"cancel-before-final-{uuid4().hex}"
    content_service = _ControlledObjectContentService(
        database=object_content_database,
        real_object_store=real_object_store,
        pause_at=2,
    )

    try:
        async with object_content_database.session() as session:
            user = await _user(session)
            service = _service(
                session=session,
                user=user,
                protocol=_PreparedFileProtocol(_three_content_family(name)),
                object_content=content_service,
                snapshot=_snapshot(StorageKind.OBJECT_STORE),
            )
            saving = asyncio.create_task(
                service.save_file(
                    UploadFile(
                        file=BytesIO(),
                        filename=f"{name}.pdf",
                        headers={"content-type": "application/pdf"},
                    )
                )
            )
            await asyncio.wait_for(content_service.paused.wait(), timeout=10)
            saving.cancel()
            with pytest.raises(asyncio.CancelledError):
                await saving

        async with object_content_database.session() as session, session.begin():
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(Files)
                    .where(Files.name.like(f"{name}%"))
                )
            ) == 0
            assert (
                await session.scalar(
                    sa.select(sa.func.count()).select_from(FileContentReferences)
                )
            ) == 0
            states = Counter(await session.scalars(sa.select(ObjectContents.state)))
            assert states == Counter(
                {
                    ContentState.DELETE_PENDING.value: 2,
                    ContentState.FAILED.value: 1,
                }
            )
    finally:
        await _delete_remote_objects(
            real_object_store.store,
            await _remote_object_keys(object_content_database),
        )


@pytest.mark.asyncio
async def test_cancellation_after_final_promotion_preserves_the_visible_family(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    name = f"cancel-after-final-{uuid4().hex}"
    content_service = _ControlledObjectContentService(
        database=object_content_database,
        real_object_store=real_object_store,
        cancel_after=2,
    )

    try:
        async with object_content_database.session() as session:
            user = await _user(session)
            service = _service(
                session=session,
                user=user,
                protocol=_PreparedFileProtocol(_three_content_family(name)),
                object_content=content_service,
                snapshot=_snapshot(StorageKind.OBJECT_STORE),
            )
            saving = asyncio.create_task(
                service.save_file(
                    UploadFile(
                        file=BytesIO(),
                        filename=f"{name}.pdf",
                        headers={"content-type": "application/pdf"},
                    )
                )
            )
            with pytest.raises(asyncio.CancelledError):
                await saving

        async with object_content_database.session() as session, session.begin():
            user = await _user(session)
            roots = (
                await session.scalars(
                    sa.select(Files).where(
                        Files.name == f"{name}.pdf",
                        Files.parent_file_id.is_(None),
                    )
                )
            ).all()
            assert len(roots) == 1
            root_id = roots[0].id
            repository = FileRepository(session)
            assert (await repository.get_by_id(root_id)).id == root_id
            assert [file.id for file in await repository.get_list_by_user(user.id)] == [
                root_id
            ]
            assert set(await session.scalars(sa.select(ObjectContents.state))) == {
                ContentState.AVAILABLE.value
            }
    finally:
        await _delete_remote_objects(
            real_object_store.store,
            await _remote_object_keys(object_content_database),
        )


@pytest.mark.asyncio
async def test_inline_and_object_store_save_the_same_exact_bytes(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    payload = b"same exact audio bytes"
    snapshot_inline = _snapshot(StorageKind.POSTGRES_INLINE)
    snapshot_remote = _snapshot(StorageKind.OBJECT_STORE)

    def prepared(name: str) -> PreparedFileUpload:
        return PreparedFileUpload(
            name=name,
            file_type=FileType.AUDIO,
            display_media_type="audio/mpeg",
            contents=(
                PendingFileContent(
                    variant=FileContentVariant.ORIGINAL,
                    chunks=_bytes_source(payload),
                    declared_media_type="audio/mpeg",
                    verified_media_type="audio/mpeg",
                ),
            ),
        )

    inline_content = ObjectContentService(
        real_object_store.settings,
        object_content_database,
    )
    remote_content = _ControlledObjectContentService(
        database=object_content_database,
        real_object_store=real_object_store,
    )

    try:
        saved_ids: list[UUID] = []
        for name, snapshot, content_service in (
            ("inline.mp3", snapshot_inline, inline_content),
            ("remote.mp3", snapshot_remote, remote_content),
        ):
            async with object_content_database.session() as session:
                user = await _user(session)
                saved = await _service(
                    session=session,
                    user=user,
                    protocol=_PreparedFileProtocol(prepared(name)),
                    object_content=content_service,
                    snapshot=snapshot,
                ).save_file(
                    UploadFile(
                        file=BytesIO(),
                        filename=name,
                        headers={"content-type": "audio/mpeg"},
                    )
                )
                assert saved.size == len(payload)
                saved_ids.append(saved.id)

        downloaded: list[bytes] = []
        for file_id, content_service in zip(
            saved_ids,
            (inline_content, remote_content),
            strict=True,
        ):
            async with object_content_database.session() as session:
                async with session.begin():
                    download = await _service(
                        session=session,
                        user=await _user(session),
                        protocol=_PreparedFileProtocol(prepared("unused.mp3")),
                        object_content=content_service,
                        snapshot=snapshot_inline,
                    ).get_download_no_auth(file_id)
                downloaded.append(b"".join([chunk async for chunk in download.chunks]))

        assert downloaded == [payload, payload]
        async with object_content_database.session() as session, session.begin():
            kinds = list(
                await session.scalars(
                    sa.select(ObjectContents.storage_kind).order_by(
                        ObjectContents.storage_kind.desc()
                    )
                )
            )
            assert kinds == [
                StorageKind.POSTGRES_INLINE.value,
                StorageKind.OBJECT_STORE.value,
            ]
    finally:
        await _delete_remote_objects(
            real_object_store.store,
            await _remote_object_keys(object_content_database),
        )
