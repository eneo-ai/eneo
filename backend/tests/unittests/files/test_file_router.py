from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.files import file_router
from intric.main.exceptions import NotFoundException


async def test_download_file_signed_raises_not_found_for_missing_content(monkeypatch):
    file_id = uuid4()
    payload = {"file_id": str(file_id), "content_disposition": "inline"}

    monkeypatch.setattr(file_router, "verify_signed_token", lambda _: payload)

    file_repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=SimpleNamespace(text=None, blob=None))
    )
    container = SimpleNamespace(file_repo=lambda: file_repo)

    with pytest.raises(NotFoundException, match="File content not found"):
        await file_router.download_file_signed(
            id=file_id, token="token", range=None, container=container
        )
