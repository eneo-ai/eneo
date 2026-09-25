from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.main.exceptions import NotFoundException


@pytest.mark.asyncio
async def test_get_raises_explicit_not_found_for_missing_record():
    repo = InfoBlobRepository(AsyncMock())
    repo.delegate.get = AsyncMock(return_value=None)

    with pytest.raises(NotFoundException):
        await repo.get(uuid4())
