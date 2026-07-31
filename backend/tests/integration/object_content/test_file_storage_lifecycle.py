from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from io import BytesIO
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi import UploadFile

from eneo.database.database import AsyncSession, DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContentOrphanCandidates,
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
from eneo.object_content.content_service import (
    ObjectContentService,
    VerifiedObjectPublication,
)
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot
from eneo.object_content.lease import OperationCheckpoint
from eneo.object_content.s3_object_store import (
    MultipartStarted,
    ObjectHead,
    ObjectStoreNotFoundError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
)
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
        pause_before_publication: bool = False,
        cancel_after_publication: bool = False,
    ) -> None:
        super().__init__(
            real_object_store.settings,
            database,
            object_store_settings=real_object_store.settings,
            object_store=real_object_store.store,
        )
        self._pause_before_publication = pause_before_publication
        self._cancel_after_publication = cancel_after_publication
        self.store_calls = 0
        self.object_keys: tuple[str, ...] = ()
        self.paused = asyncio.Event()

    async def ensure_target_ready(self, storage_kind: StorageKind) -> None:
        assert storage_kind is StorageKind.OBJECT_STORE

    @asynccontextmanager
    async def upload_for_publication(
        self,
        contents: Sequence[CapturedContent],
    ) -> AsyncGenerator[VerifiedObjectPublication]:
        async with super().upload_for_publication(contents) as publication:
            self.store_calls = len(publication.uploads)
            self.object_keys = tuple(
                upload.object_key for upload in publication.uploads
            )
            if self._pause_before_publication:
                self.paused.set()
                await asyncio.Event().wait()
            yield publication
            if self._cancel_after_publication:
                task = asyncio.current_task()
                assert task is not None
                task.cancel()


def _snapshot(storage_target: StorageKind) -> UploadAdmissionSnapshot:
    maximum = 20 * 1024 * 1024
    return UploadAdmissionSnapshot(
        policy_revision=41,
        new_write_storage_target=storage_target,
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
) -> FileService:
    return FileService(
        user=user,
        repo=FileRepository(session),
        protocol=protocol,
        object_content=object_content,
        upload_admission=snapshot,
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
@pytest.mark.parametrize("fail_on_upload", [1, 2, 3])
async def test_remote_failure_publishes_no_multi_content_family_rows(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
    fail_on_upload: int,
) -> None:
    name = f"failure-{uuid4().hex}"
    protocol = _PreparedFileProtocol(_three_content_family(name))
    content_service = _ControlledObjectContentService(
        database=object_content_database,
        real_object_store=real_object_store,
    )
    snapshot = _snapshot(StorageKind.OBJECT_STORE)
    upload_calls = 0
    uploaded_object_keys: list[str] = []
    upload = real_object_store.store.upload

    async def fail_during_family_upload(
        key: str,
        content: CapturedContent,
        *,
        multipart_started: MultipartStarted | None = None,
        operation_checkpoint: OperationCheckpoint | None = None,
    ) -> ObjectHead:
        nonlocal upload_calls
        upload_calls += 1
        if upload_calls == fail_on_upload:
            raise ObjectStoreUnavailableError("injected File upload outage")
        head = await upload(
            key,
            content,
            multipart_started=multipart_started,
            operation_checkpoint=operation_checkpoint,
        )
        uploaded_object_keys.append(key)
        return head

    monkeypatch.setattr(real_object_store.store, "upload", fail_during_family_upload)

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
                match="temporarily unavailable",
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
            assert await session.scalar(sa.select(ObjectContents.id)) is None
            assert (
                await session.scalar(sa.select(ObjectStoreObjects.content_id)) is None
            )
        assert upload_calls == fail_on_upload
        assert len(uploaded_object_keys) == fail_on_upload - 1
        for object_key in uploaded_object_keys:
            assert (await real_object_store.store.head(object_key)).size_bytes > 0
    finally:
        await _delete_remote_objects(
            real_object_store.store,
            uploaded_object_keys,
        )


@pytest.mark.asyncio
async def test_cancellation_before_publication_leaves_no_file_family_rows(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    name = f"cancel-before-final-{uuid4().hex}"
    content_service = _ControlledObjectContentService(
        database=object_content_database,
        real_object_store=real_object_store,
        pause_before_publication=True,
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
            assert await session.scalar(sa.select(ObjectContents.id)) is None
            assert (
                await session.scalar(sa.select(ObjectStoreObjects.content_id)) is None
            )
        assert content_service.store_calls == 3
        assert len(content_service.object_keys) == 3
        for object_key in content_service.object_keys:
            assert (await real_object_store.store.head(object_key)).size_bytes > 0
    finally:
        await _delete_remote_objects(
            real_object_store.store,
            list(content_service.object_keys),
        )


@pytest.mark.asyncio
async def test_database_rollback_after_verified_uploads_publishes_no_family_rows(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    name = f"rollback-before-commit-{uuid4().hex}"
    content_service = _ControlledObjectContentService(
        database=object_content_database,
        real_object_store=real_object_store,
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

            def reject_commit(_session: object) -> None:
                raise RuntimeError("injected publication commit failure")

            sa.event.listen(
                session.sync_session,
                "before_commit",
                reject_commit,
                once=True,
            )
            with pytest.raises(
                RuntimeError,
                match="injected publication commit failure",
            ):
                await service.save_file(
                    UploadFile(
                        file=BytesIO(),
                        filename=f"{name}.pdf",
                        headers={"content-type": "application/pdf"},
                    )
                )

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
            assert await session.scalar(sa.select(ObjectContents.id)) is None
            assert (
                await session.scalar(sa.select(ObjectStoreObjects.content_id)) is None
            )
            assert set(
                await session.scalars(
                    sa.select(ObjectContentOrphanCandidates.object_key).where(
                        ObjectContentOrphanCandidates.object_key.in_(
                            content_service.object_keys
                        )
                    )
                )
            ) == set(content_service.object_keys)

        assert content_service.store_calls == 3
        assert len(content_service.object_keys) == 3
        for object_key in content_service.object_keys:
            assert (await real_object_store.store.head(object_key)).size_bytes > 0
    finally:
        await _delete_remote_objects(
            real_object_store.store,
            list(content_service.object_keys),
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
        cancel_after_publication=True,
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
                    user = await _user(session)
                download = await _service(
                    session=session,
                    user=user,
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


@pytest.mark.asyncio
async def test_generated_file_family_content_uses_operator_not_source_business_limit(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    original = b"%PDF-1"
    extracted = b"expanded text"
    page = b"\x89PNG page data"
    source_business_maximum = len(original)

    def prepared(name: str) -> PreparedFileUpload:
        return PreparedFileUpload(
            name=f"{name}.pdf",
            file_type=FileType.TEXT,
            display_media_type="application/pdf",
            contents=(
                PendingFileContent(
                    variant=FileContentVariant.ORIGINAL,
                    chunks=_bytes_source(original),
                    declared_media_type="application/pdf",
                    verified_media_type="application/pdf",
                ),
                PendingFileContent(
                    variant=FileContentVariant.EXTRACTED_TEXT,
                    chunks=_bytes_source(extracted),
                    declared_media_type="text/plain",
                    verified_media_type="text/plain",
                ),
            ),
            derivatives=(
                PreparedFileUpload(
                    name=f"{name}-page.png",
                    file_type=FileType.IMAGE,
                    display_media_type="image/png",
                    contents=(
                        PendingFileContent(
                            variant=FileContentVariant.DERIVED_PAGE,
                            chunks=_bytes_source(page),
                            declared_media_type="image/png",
                            verified_media_type="image/png",
                        ),
                    ),
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
        for name, target, content_service in (
            ("inline-generated", StorageKind.POSTGRES_INLINE, inline_content),
            ("remote-generated", StorageKind.OBJECT_STORE, remote_content),
        ):
            snapshot = UploadAdmissionSnapshot(
                policy_revision=42,
                new_write_storage_target=target,
                session_file_maximum_bytes=source_business_maximum,
                session_image_maximum_bytes=source_business_maximum,
                session_audio_maximum_bytes=source_business_maximum,
                knowledge_file_maximum_bytes=source_business_maximum,
                knowledge_audio_maximum_bytes=source_business_maximum,
            )
            async with object_content_database.session() as session:
                user = await _user(session)
                await _service(
                    session=session,
                    user=user,
                    protocol=_PreparedFileProtocol(prepared(name)),
                    object_content=content_service,
                    snapshot=snapshot,
                ).save_file(
                    UploadFile(
                        file=BytesIO(original),
                        filename=f"{name}.pdf",
                        headers={"content-type": "application/pdf"},
                    )
                )

        async with object_content_database.session() as session, session.begin():
            controls = (
                await session.execute(
                    sa.select(
                        ObjectContents.size_bytes,
                        ObjectContents.state,
                        ObjectContents.storage_kind,
                    )
                    .join(
                        FileContentReferences,
                        FileContentReferences.content_id == ObjectContents.id,
                    )
                    .order_by(ObjectContents.storage_kind, ObjectContents.size_bytes)
                )
            ).all()

        assert sorted(
            size_bytes for size_bytes, _state, _storage_kind in controls
        ) == sorted([len(original), len(extracted), len(page)] * 2)
        assert {state for _size_bytes, state, _storage_kind in controls} == {
            ContentState.AVAILABLE.value
        }
        assert {storage_kind for _size_bytes, _state, storage_kind in controls} == {
            StorageKind.POSTGRES_INLINE.value,
            StorageKind.OBJECT_STORE.value,
        }
    finally:
        await _delete_remote_objects(
            real_object_store.store,
            await _remote_object_keys(object_content_database),
        )
