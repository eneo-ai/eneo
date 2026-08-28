from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.object_content.file_icon_backfill import (
    _FileIconBackfillRepository,
    _WorkItem,
)


class _SingleRowResult:
    def __init__(self, row: object) -> None:
        self._row = row

    def one_or_none(self) -> object:
        return self._row


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_user_id", [uuid4(), None])
async def test_legacy_file_source_uses_the_canonical_user_owner(
    owner_user_id: UUID | None,
) -> None:
    tenant_id = uuid4()
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = _SingleRowResult(
        SimpleNamespace(
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            mimetype="application/pdf",
            sha256=b"digest",
            size_bytes=7,
        )
    )
    repository = _FileIconBackfillRepository(session)

    source = await repository.legacy_source(
        _WorkItem(
            id=1,
            owner_kind="file",
            owner_id=uuid4(),
            variant="original",
            ordinal=0,
            tenant_id=tenant_id,
            payload_size_estimate=7,
            lease_owner="test-worker",
        )
    )

    assert source.created_by_user_id == owner_user_id
