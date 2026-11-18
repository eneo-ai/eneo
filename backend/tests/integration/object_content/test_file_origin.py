"""Where a Flow file came from, as the File row records it.

The origin (space, flow and, for a file a run creates, the run) is a fact on
the row. It is written when the File is created and grants no access.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.database.database import DatabaseSessionManager
from eneo.files.file_models import FileMetadata, FileMetadataCreate, FileOwner, FileType
from eneo.files.file_repo import FileRepository
from tests.integration.object_content.test_file_storage_lifecycle import _user

ORIGIN_COLUMNS = ("origin_space_id", "origin_flow_id", "origin_flow_run_id")


def _origin(metadata: FileMetadata | None) -> dict[str, object]:
    assert metadata is not None
    return {name: getattr(metadata, name) for name in ORIGIN_COLUMNS}


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
