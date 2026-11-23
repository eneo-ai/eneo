"""Where a Flow file came from, as the File row records it.

The origin (space, flow and, for a file a run creates, the run) is a fact on
the row. It is written when the File is created and grants no access.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from io import BytesIO
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi import UploadFile

from eneo.authentication.principal_types import PrincipalType
from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.files.file_models import (
    FileMetadata,
    FileMetadataCreate,
    FileOrigin,
    FileOwner,
    FileType,
)
from eneo.files.file_protocol import FileProtocol, PreparedFileUpload
from eneo.files.file_repo import FileRepository
from eneo.files.file_service import FileService
from eneo.object_content.content import StorageKind
from eneo.object_content.content_service import ObjectContentService
from tests.integration.object_content.conftest import RealObjectStore
from tests.integration.object_content.test_file_storage_lifecycle import (
    _ControlledObjectContentService,
    _delete_remote_objects,
    _remote_object_keys,
    _service,
    _snapshot,
    _three_content_family,
    _user,
)

ORIGIN_COLUMNS = ("origin_space_id", "origin_flow_id", "origin_flow_run_id")


def _origin(metadata: FileMetadata | None) -> dict[str, object]:
    assert metadata is not None
    return {name: getattr(metadata, name) for name in ORIGIN_COLUMNS}


def _columns(origin: FileOrigin | None) -> dict[str, object]:
    if origin is None:
        return dict.fromkeys(ORIGIN_COLUMNS)
    return {
        "origin_space_id": origin.space_id,
        "origin_flow_id": origin.flow_id,
        "origin_flow_run_id": origin.flow_run_id,
    }


class _FamilyProtocol(FileProtocol):
    """Prepares a fresh root with one derived page image for every upload."""

    def __init__(self) -> None:
        pass

    @asynccontextmanager
    async def prepare_upload(
        self, upload_file: UploadFile, **_kwargs: object
    ) -> AsyncGenerator[PreparedFileUpload]:
        yield _three_content_family(upload_file.filename or "upload")


def _upload(name: str) -> UploadFile:
    return UploadFile(
        file=BytesIO(), filename=name, headers={"content-type": "application/pdf"}
    )


async def _family(
    database: DatabaseSessionManager, root_id: UUID
) -> list[FileMetadata | None]:
    async with database.session() as session, session.begin():
        repo = FileRepository(session)
        child_ids = list(
            await session.scalars(
                sa.select(Files.id).where(Files.parent_file_id == root_id)
            )
        )
        assert len(child_ids) == 1
        return [
            await repo.get_by_id_for_lifecycle(file_id)
            for file_id in (root_id, *child_ids)
        ]


@pytest.mark.asyncio
async def test_the_repository_returns_the_origin_it_writes_and_deletes(
    object_content_database: DatabaseSessionManager,
) -> None:
    origin = {name: uuid4() for name in ORIGIN_COLUMNS}
    async with object_content_database.session() as session, session.begin():
        user = await _user(session)
        repo = FileRepository(session)
        created = await repo.add_metadata(
            FileMetadataCreate(
                name="origin.txt",
                file_type=FileType.TEXT,
                owner_type=PrincipalType.USER,
                owner_user_id=user.id,
                tenant_id=user.tenant_id,
                **origin,
            )
        )
        assert _origin(created) == origin
        assert _origin(await repo.get_by_id_for_lifecycle(created.id)) == origin
        deleted = await repo.delete_by_owner_for_lifecycle(
            created.id,
            FileOwner(
                tenant_id=user.tenant_id,
                owner_type=PrincipalType.USER,
                owner_user_id=user.id,
            ),
        )
        assert _origin(deleted) == origin


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "storage_kind", [StorageKind.POSTGRES_INLINE, StorageKind.OBJECT_STORE]
)
async def test_a_derived_file_records_its_roots_origin(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    storage_kind: StorageKind,
) -> None:
    # A PDF upload to a published step stores its page images as derived
    # Files; both storage paths write the root's origin on each of them.
    origin = FileOrigin(space_id=uuid4(), flow_id=uuid4())
    content: ObjectContentService = (
        ObjectContentService(real_object_store.settings, object_content_database)
        if storage_kind is StorageKind.POSTGRES_INLINE
        else _ControlledObjectContentService(
            database=object_content_database, real_object_store=real_object_store
        )
    )
    try:
        async with object_content_database.session() as session:
            user = await _user(session)
            saved = await (
                _service(
                    session=session,
                    user=user,
                    protocol=_FamilyProtocol(),
                    object_content=content,
                    snapshot=_snapshot(storage_kind),
                )
                .with_origin(origin)
                .save_file(_upload("report"))
            )

        family = await _family(object_content_database, saved.id)
        assert [_origin(file) for file in family] == [_columns(origin)] * 2
    finally:
        await _delete_remote_objects(
            real_object_store.store,
            await _remote_object_keys(object_content_database),
        )


@pytest.mark.asyncio
async def test_each_service_records_only_its_own_origin(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    first_origin = FileOrigin(space_id=uuid4(), flow_id=uuid4())
    second_origin = FileOrigin(space_id=uuid4(), flow_id=uuid4(), flow_run_id=uuid4())
    content = ObjectContentService(real_object_store.settings, object_content_database)
    async with object_content_database.session() as session:
        user = await _user(session)
        plain: FileService = _service(
            session=session,
            user=user,
            protocol=_FamilyProtocol(),
            object_content=content,
            snapshot=_snapshot(StorageKind.POSTGRES_INLINE),
        )
        first = plain.with_origin(first_origin)
        second = plain.with_origin(second_origin)

        async def refuse(_file: object, _seconds: float | None) -> None:
            raise RuntimeError("dependent write refused")

        with pytest.raises(RuntimeError, match="dependent write refused"):
            await first.save_file(_upload("refused"), before_commit=refuse)
        saved = {
            "second": await second.save_file(_upload("second")),
            "first": await first.save_file(_upload("first")),
            "plain": await plain.save_file(_upload("plain")),
        }

    async with object_content_database.session() as session, session.begin():
        names = set(await session.scalars(sa.select(Files.name)))
    # The refused family left no row behind.
    assert not any(name.startswith("refused") for name in names)
    expected = {
        "second": _columns(second_origin),
        "first": _columns(first_origin),
        # The service the bound ones came from still records no origin.
        "plain": _columns(None),
    }
    for key, file in saved.items():
        family = await _family(object_content_database, file.id)
        assert [_origin(member) for member in family] == [expected[key]] * 2, key
