from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.files import file_router
from eneo.files.file_models import ContentDisposition
from eneo.files.file_service import FileDownload
from eneo.main.exceptions import UnauthorizedException


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "validator,ranged,status",
    [
        ('"' + "78" * 32 + '"', False, 304),
        ('W/"' + "78" * 32 + '"', False, 304),
        ('"different"', False, 200),
        (None, False, 200),
        ('"' + "78" * 32 + '"', True, 206),
    ],
)
async def test_conditional_download_authorizes_audits_and_closes(
    validator, ranged, status
):
    file_id, tenant_id = uuid4(), uuid4()

    async def chunks():
        yield b"bytes"

    close = AsyncMock()
    download = FileDownload(
        file_id=file_id,
        tenant_id=tenant_id,
        chunks=chunks(),
        content_length=5,
        media_type="audio/wav",
        filename="file.wav",
        sha256=b"x" * 32,
        content_range="bytes 0-4/5" if ranged else None,
        range_supported=True,
        _close=close,
    )
    service = AsyncMock()
    service.get_original_download_no_auth.return_value = download
    audit = AsyncMock()

    class Session:
        @asynccontextmanager
        async def begin(self):
            yield

    class Container:
        def file_service(self, **_):
            return service

        def audit_service(self):
            return audit

        def session(self):
            return Session()

    response = await file_router.download_original_file_signed(
        id=file_id,
        access=(ContentDisposition.ATTACHMENT, tenant_id),
        container=Container(),
        range="bytes=0-4" if ranged else None,
        if_none_match=validator,
    )
    assert response.status_code == status
    service.get_original_download_no_auth.assert_awaited_once_with(
        file_id,
        range_header="bytes=0-4" if ranged else None,
        expected_tenant_id=tenant_id,
    )
    audit.log_async.assert_awaited_once()
    metadata = audit.log_async.call_args.kwargs["metadata"]
    assert metadata["extra"]["cache_revalidated"] == (status == 304)
    if status == 304:
        close.assert_awaited_once()
        assert not response.body
    else:
        await download.aclose()


@pytest.mark.asyncio
async def test_matching_etag_never_bypasses_denied_access():
    service = AsyncMock()
    service.get_original_download_no_auth.side_effect = UnauthorizedException("denied")

    class Container:
        def file_service(self, **_):
            return service

    with pytest.raises(UnauthorizedException):
        await file_router.download_original_file_signed(
            id=uuid4(),
            access=(ContentDisposition.ATTACHMENT, uuid4()),
            container=Container(),
            range=None,
            if_none_match="*",
        )
