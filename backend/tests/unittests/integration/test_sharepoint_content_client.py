from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
    SharePointContentUnavailable,
)
from eneo.integration.infrastructure.content_service.utils import ExtractionResult
from tests.unittests.integration.test_sharepoint_content_extraction import (
    OCTET,
    docx_bytes,
)


@pytest.mark.asyncio
async def test_uses_settings_default_max_download_bytes_when_not_overridden():
    settings = MagicMock()
    settings.sharepoint_max_download_bytes = 12_345_678

    with patch(
        "eneo.integration.infrastructure.clients.sharepoint_content_client.get_settings",
        return_value=settings,
    ):
        client = SharePointContentClient(
            base_url="https://graph.microsoft.com",
            api_token="mock-token",
        )

    try:
        assert client.max_download_bytes == 12_345_678
    finally:
        await client.client.close()


@pytest.mark.asyncio
async def test_explicit_max_download_bytes_overrides_settings():
    settings = MagicMock()
    settings.sharepoint_max_download_bytes = 12_345_678

    with patch(
        "eneo.integration.infrastructure.clients.sharepoint_content_client.get_settings",
        return_value=settings,
    ):
        client = SharePointContentClient(
            base_url="https://graph.microsoft.com",
            api_token="mock-token",
            max_download_bytes=2_048,
        )

    try:
        assert client.max_download_bytes == 2_048
    finally:
        await client.client.close()


class _FakeResponse:
    def __init__(self, chunks: list[bytes], headers: dict[str, str]):
        self._chunks = chunks
        self.headers = headers
        self.charset = None
        self.content = self

    def raise_for_status(self) -> None:
        pass

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


@pytest.fixture
async def client():
    settings = MagicMock()
    settings.sharepoint_max_download_bytes = 1_000_000
    with patch(
        "eneo.integration.infrastructure.clients.sharepoint_content_client.get_settings",
        return_value=settings,
    ):
        client = SharePointContentClient(
            base_url="https://graph.microsoft.com", api_token="mock-token"
        )
    client.get_file_metadata = AsyncMock(
        return_value={
            "name": "report.docx",
            "@microsoft.graph.downloadUrl": "https://download.example/report.docx",
        }
    )
    try:
        yield client
    finally:
        await client.client.close()


def _serve(client: SharePointContentClient, chunks: list[bytes], **headers: str):
    client.client.client.get = MagicMock(
        return_value=_FakeResponse(chunks, {"Content-Type": OCTET, **headers})
    )


class TestFileDownloadExtraction:
    async def test_complete_download_is_extracted_with_the_upload_parsers(
        self, client: SharePointContentClient
    ):
        payload = docx_bytes("Downloaded body")
        _serve(
            client,
            [payload[:100], payload[100:]],
            **{"Content-Length": str(len(payload))},
        )

        result = await client.get_file_extraction_by_id("drive", "item")

        assert result.text is not None and "Downloaded body" in result.text
        assert result.content_type == OCTET
        assert await client.get_file_content_by_id("drive", "item") == (
            result.text,
            OCTET,
        )

    async def test_truncated_download_is_a_failure_not_an_empty_file(
        self, client: SharePointContentClient
    ):
        payload = docx_bytes("Downloaded body")
        _serve(
            client,
            [payload[: len(payload) // 2]],
            **{"Content-Length": str(len(payload))},
        )

        result = await client.get_file_extraction_by_id("drive", "item")

        assert result == ExtractionResult(
            skip_reason=(
                f"Error: Incomplete download of 'report.docx' "
                f"({len(payload) // 2} of {len(payload)} bytes)"
            ),
            failed=True,
            content_type=OCTET,
        )
        with pytest.raises(SharePointContentUnavailable) as exc_info:
            await client.get_file_content_by_id("drive", "item")
        assert str(exc_info.value).startswith("Incomplete download of 'report.docx'")

    async def test_download_without_content_length_is_trusted(
        self, client: SharePointContentClient
    ):
        payload = docx_bytes("No length header")
        _serve(client, [payload])

        result = await client.get_file_extraction_by_id("drive", "item")

        assert result.text is not None and "No length header" in result.text

    async def test_no_text_result_is_an_empty_string_for_legacy_callers(
        self, client: SharePointContentClient
    ):
        _serve(client, [docx_bytes()], **{"Content-Length": str(len(docx_bytes()))})

        assert await client.get_file_content_by_id("drive", "item") == ("", OCTET)

    async def test_parse_failure_raises_for_legacy_callers(
        self, client: SharePointContentClient
    ):
        _serve(client, [b"not a zip"], **{"Content-Length": "9"})

        result = await client.get_file_extraction_by_id("drive", "item")
        assert result.failed is True

        with pytest.raises(SharePointContentUnavailable) as exc_info:
            await client.get_file_content_by_id("drive", "item")
        assert str(exc_info.value) == "Corrupt or malformed file"
        assert exc_info.value.reason == "Error: Corrupt or malformed file"

    async def test_oversized_download_still_raises_value_error(
        self, client: SharePointContentClient
    ):
        client.max_download_bytes = 10
        _serve(client, [b"x" * 11])

        with pytest.raises(ValueError, match="exceeds max download size"):
            await client.get_file_extraction_by_id("drive", "item")
