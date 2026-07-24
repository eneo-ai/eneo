from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.files import file_router
from eneo.main.exceptions import NotFoundException


async def test_download_file_signed_raises_not_found_for_missing_content(monkeypatch):
    file_id = uuid4()
    payload = {"file_id": str(file_id), "content_disposition": "inline"}

    monkeypatch.setattr(file_router, "verify_signed_token", lambda _: payload)

    service = AsyncMock()
    service.get_download_no_auth.side_effect = NotFoundException(
        "File content not found"
    )

    class Container:
        @staticmethod
        def file_service(*, user):
            assert user is None
            return service

    with pytest.raises(NotFoundException, match="File content not found"):
        await file_router.download_file_signed(
            id=file_id, token="token", range=None, container=Container()
        )
