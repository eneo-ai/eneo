import gzip
import traceback
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aiohttp import web
from aiohttp.client_reqrep import RequestInfo
from aiohttp.test_utils import TestServer
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    IncompleteDownloadError,
    SharePointContentClient,
)
from eneo.integration.infrastructure.content_service.utils import (
    EMPTY_CONTENT_REASON,
    ExtractionResult,
)
from tests.unittests.integration.sharepoint_fixtures import OCTET, docx_bytes


def _unauthorized() -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(
        request_info=MagicMock(), history=(), status=401, message="expired"
    )


@pytest.mark.asyncio
async def test_401_is_retried_with_a_token_from_the_access_token_provider():
    client = SharePointContentClient(
        base_url="https://graph.microsoft.com",
        api_token="stale",
        access_token_provider=AsyncMock(return_value="fresh"),
        max_download_bytes=1,
    )
    client.client = MagicMock()
    client.client.get = AsyncMock(
        side_effect=[_unauthorized(), {"value": [{"id": "1"}]}]
    )

    items = await client.get_folder_items(site_id="s", drive_id="d", folder_id="f")

    assert [item["id"] for item in items] == ["1"]
    assert client.headers["Authorization"] == "Bearer fresh"
    retry_headers = client.client.get.await_args_list[1].kwargs["headers"]
    assert retry_headers["Authorization"] == "Bearer fresh"


@pytest.mark.asyncio
async def test_401_without_any_refresh_path_propagates():
    client = SharePointContentClient(
        base_url="https://graph.microsoft.com",
        api_token="stale",
        max_download_bytes=1,
    )
    client.client = MagicMock()
    client.client.get = AsyncMock(side_effect=[_unauthorized()])

    with pytest.raises(aiohttp.ClientResponseError):
        await client.get_folder_items(site_id="s", drive_id="d", folder_id="f")
    assert client.client.get.await_count == 1


@pytest.mark.asyncio
async def test_delta_pages_ask_graph_to_leave_out_the_parent_chain():
    """Parent folders of changed items are not changes; above a folder scope
    they would read as having left it."""
    client = SharePointContentClient(
        base_url="https://graph.microsoft.com",
        api_token="mock-token",
        max_download_bytes=1,
    )
    client.client = MagicMock()
    client.client.get = AsyncMock(
        side_effect=[
            {
                "value": [{"id": "1"}],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/drives/d/root/delta?token=page-2",
            },
            {
                "value": [{"id": "2"}],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/drives/d/root/delta?token=next",
            },
        ]
    )

    changes, token = await client.get_delta_changes("d", "first")

    assert ([change["id"] for change in changes], token) == (["1", "2"], "next")
    assert client.client.get.await_count == 2
    for call in client.client.get.await_args_list:
        assert call.kwargs["headers"]["Prefer"] == "deltaExcludeParent"
        assert call.kwargs["headers"]["Authorization"] == "Bearer mock-token"
    assert "Prefer" not in client.headers


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

    @pytest.mark.parametrize("encoding", [None, "identity"])
    async def test_truncated_download_is_a_failure_not_an_empty_file(
        self, client: SharePointContentClient, encoding: str | None
    ):
        """Still cut off after its retries, it fails the item, which keeps its
        copy and is tried again later, instead of being parsed or skipped."""
        payload = docx_bytes("Downloaded body")
        headers = {"Content-Length": str(len(payload))}
        if encoding:
            headers["Content-Encoding"] = encoding
        _serve(client, [payload[: len(payload) // 2]], **headers)

        with patch("asyncio.sleep", new=AsyncMock()):
            with pytest.raises(
                IncompleteDownloadError,
                match=(
                    f"Incomplete download of 'report.docx' "
                    rf"\({len(payload) // 2} of {len(payload)} bytes\)"
                ),
            ):
                await client.get_file_extraction_by_id("drive", "item")

        assert client.client.client.get.call_count == 5

    async def test_a_cut_off_download_is_fetched_again(
        self, client: SharePointContentClient
    ):
        payload = docx_bytes("Whole body")
        length = {"Content-Type": OCTET, "Content-Length": str(len(payload))}
        client.client.client.get = MagicMock(
            side_effect=[
                _FakeResponse([payload[:10]], length),
                _FailedRequest(
                    aiohttp.ClientPayloadError("Response payload is not completed")
                ),
                _FakeResponse([payload], length),
            ]
        )

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await client.get_file_extraction_by_id("drive", "item")

        assert result.text is not None and "Whole body" in result.text
        assert client.client.client.get.call_count == 3
        for call in client.client.client.get.call_args_list:
            assert "headers" not in call.kwargs

    @pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "GZIP"])
    async def test_decompressed_body_is_not_measured_against_the_wire_length(
        self, client: SharePointContentClient, encoding: str
    ):
        payload = docx_bytes("Compressed on the wire")
        wire_length = len(gzip.compress(payload))
        assert wire_length != len(payload)
        _serve(
            client,
            [payload],
            **{"Content-Length": str(wire_length), "Content-Encoding": encoding},
        )

        result = await client.get_file_extraction_by_id("drive", "item")

        assert result.failed is False
        assert result.text is not None and "Compressed on the wire" in result.text

    async def test_download_without_content_length_is_trusted(
        self, client: SharePointContentClient
    ):
        payload = docx_bytes("No length header")
        _serve(client, [payload])

        result = await client.get_file_extraction_by_id("drive", "item")

        assert result.text is not None and "No length header" in result.text

    async def test_empty_document_is_a_no_text_result(
        self, client: SharePointContentClient
    ):
        payload = docx_bytes()
        _serve(client, [payload], **{"Content-Length": str(len(payload))})

        result = await client.get_file_extraction_by_id("drive", "item")

        assert result == ExtractionResult.no_text(EMPTY_CONTENT_REASON, OCTET)

    async def test_office_bytes_are_parsed_in_the_upload_sandbox(
        self, client: SharePointContentClient
    ):
        payload = docx_bytes("Sandboxed")
        _serve(client, [payload], **{"Content-Length": str(len(payload))})

        with patch(
            "eneo.integration.infrastructure.content_service.utils.extract_in_process",
            AsyncMock(return_value="From the child process"),
        ) as sandbox:
            result = await client.get_file_extraction_by_id("drive", "item")

        assert result == ExtractionResult.ok("From the child process", OCTET)
        sandbox.assert_awaited_once()

    async def test_parse_failure_is_a_failed_result(
        self, client: SharePointContentClient
    ):
        _serve(client, [b"not a zip"], **{"Content-Length": "9"})

        result = await client.get_file_extraction_by_id("drive", "item")

        assert result == ExtractionResult.error("Corrupt or malformed file", OCTET)

    async def test_oversized_download_still_raises_value_error(
        self, client: SharePointContentClient
    ):
        client.max_download_bytes = 10
        _serve(client, [b"x" * 11])

        with pytest.raises(ValueError, match="exceeds max download size"):
            await client.get_file_extraction_by_id("drive", "item")


_SIGNED_DOWNLOAD_URL = (
    "https://contoso.sharepoint.com/sites/KS/_layouts/15/download.aspx"
    "?UniqueId=abc&Translate=false&tempauth=v1.eyJzaWduZWQiOiJ0b2tlbiJ9.c2lnbmF0dXJl"
    "&ApiVersion=2.0"
)


def _signed_request_info() -> RequestInfo:
    url = URL(_SIGNED_DOWNLOAD_URL)
    return RequestInfo(
        url,
        "GET",
        CIMultiDictProxy(CIMultiDict({"Authorization": "Bearer mock-token"})),
        url,
    )


class _FailedRequest(_FakeResponse):
    """A download aiohttp gives up on before it hands back a response."""

    def __init__(self, error: Exception):
        super().__init__([], {})
        self._error = error

    async def __aenter__(self):
        raise self._error


class _RefusedResponse(_FakeResponse):
    """A download answered with an error status, as aiohttp reports it."""

    def __init__(self, status: int, reason: str, headers: dict[str, str]):
        super().__init__([], headers)
        self.status = status
        self.reason = reason

    def raise_for_status(self) -> None:
        url = URL(_SIGNED_DOWNLOAD_URL)
        raise aiohttp.ClientResponseError(
            RequestInfo(
                url,
                "GET",
                CIMultiDictProxy(CIMultiDict({"Authorization": "Bearer mock-token"})),
                url,
            ),
            (),
            status=self.status,
            message=self.reason,
            headers=CIMultiDictProxy(CIMultiDict(self.headers)),
        )


class TestRefusedDownloads:
    """A download URL carries a bearer token in its query; errors must not."""

    @pytest.fixture
    def signed_client(self, client: SharePointContentClient):
        client.get_file_metadata = AsyncMock(
            return_value={
                "name": "report.docx",
                "@microsoft.graph.downloadUrl": _SIGNED_DOWNLOAD_URL,
            }
        )
        return client

    async def test_the_error_names_the_status_without_the_url_query_or_token(
        self, signed_client: SharePointContentClient
    ):
        signed_client.client.client.get = MagicMock(
            return_value=_RefusedResponse(403, "Forbidden", {})
        )

        with pytest.raises(aiohttp.ClientResponseError) as caught:
            await signed_client.get_file_extraction_by_id("drive", "item")

        error = caught.value
        assert error.status == 403
        logged = "".join(traceback.format_exception(error))
        for text in (str(error), repr(error), logged):
            assert "tempauth" not in text
            assert "eyJ" not in text
            assert "mock-token" not in text
        assert str(error.request_info.real_url) == _SIGNED_DOWNLOAD_URL.split("?")[0]

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(
                aiohttp.TooManyRedirects(
                    _signed_request_info(),
                    # aiohttp keeps every redirect, each with the signed URL.
                    (MagicMock(__repr__=lambda _: _SIGNED_DOWNLOAD_URL),),
                    status=302,
                    message="Found",
                ),
                id="too-many-redirects",
            ),
            pytest.param(
                aiohttp.InvalidUrlRedirectClientError(
                    _SIGNED_DOWNLOAD_URL, "Invalid redirect URL"
                ),
                id="invalid-redirect",
            ),
        ],
    )
    async def test_a_request_that_fails_before_a_response_drops_the_token_too(
        self, signed_client: SharePointContentClient, error: aiohttp.ClientError
    ):
        signed_client.client.client.get = MagicMock(return_value=_FailedRequest(error))

        with pytest.raises(aiohttp.ClientError) as caught:
            await signed_client.get_file_extraction_by_id("drive", "item")

        logged = "".join(traceback.format_exception(caught.value))
        for text in (str(caught.value), repr(caught.value), logged):
            assert "tempauth" not in text
            assert "eyJ" not in text
            assert "mock-token" not in text

    async def test_throttled_downloads_are_still_retried(
        self, signed_client: SharePointContentClient
    ):
        payload = docx_bytes("Second attempt")
        signed_client.client.client.get = MagicMock(
            side_effect=[
                _RefusedResponse(429, "Too Many Requests", {"Retry-After": "0"}),
                _FakeResponse(
                    [payload],
                    {"Content-Type": OCTET, "Content-Length": str(len(payload))},
                ),
            ]
        )

        result = await signed_client.get_file_extraction_by_id("drive", "item")

        assert result.text is not None and "Second attempt" in result.text
        assert signed_client.client.client.get.call_count == 2

    @pytest.mark.parametrize(
        "failure",
        [
            pytest.param(lambda: _RefusedResponse(502, "Bad Gateway", {}), id="502"),
            pytest.param(
                lambda: _RefusedResponse(504, "Gateway Timeout", {}), id="504"
            ),
            pytest.param(
                lambda: _FailedRequest(
                    aiohttp.ClientOSError(104, "Connection reset by peer")
                ),
                id="connection-reset",
            ),
            pytest.param(
                lambda: _FailedRequest(aiohttp.ServerDisconnectedError()),
                id="disconnected",
            ),
            pytest.param(lambda: _FailedRequest(TimeoutError()), id="timeout"),
        ],
    )
    async def test_transient_download_failures_are_retried(
        self, signed_client: SharePointContentClient, failure
    ):
        payload = docx_bytes("After a transient failure")
        signed_client.client.client.get = MagicMock(
            side_effect=[
                failure(),
                _FakeResponse(
                    [payload],
                    {"Content-Type": OCTET, "Content-Length": str(len(payload))},
                ),
            ]
        )

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await signed_client.get_file_extraction_by_id("drive", "item")

        assert result.text is not None and "After a transient failure" in result.text
        assert signed_client.client.client.get.call_count == 2

    async def test_a_refused_download_is_not_retried(
        self, signed_client: SharePointContentClient
    ):
        signed_client.client.client.get = MagicMock(
            return_value=_RefusedResponse(403, "Forbidden", {})
        )

        with pytest.raises(aiohttp.ClientResponseError):
            await signed_client.get_file_extraction_by_id("drive", "item")
        assert signed_client.client.client.get.call_count == 1

    async def test_an_expired_token_is_still_refreshed(
        self, signed_client: SharePointContentClient
    ):
        payload = docx_bytes("After refresh")
        signed_client.access_token_provider = AsyncMock(return_value="fresh")
        signed_client.client.client.get = MagicMock(
            side_effect=[
                _RefusedResponse(401, "Unauthorized", {}),
                _FakeResponse(
                    [payload],
                    {"Content-Type": OCTET, "Content-Length": str(len(payload))},
                ),
            ]
        )

        result = await signed_client.get_file_extraction_by_id("drive", "item")

        assert result.text is not None and "After refresh" in result.text
        assert signed_client.headers["Authorization"] == "Bearer fresh"


class TestDownloadUrlGetsNoGraphToken:
    """The download URL authorizes itself; the Graph token stays with Graph."""

    async def test_no_authorization_header_reaches_the_download_host(
        self, client: SharePointContentClient
    ):
        payload = docx_bytes("Served without a token")
        seen: list[tuple[str, dict[str, str]]] = []

        async def record(request: web.Request) -> web.StreamResponse:
            seen.append((request.path, dict(request.headers)))
            if len(seen) == 1:
                return web.Response(status=503)
            if request.path == "/download.aspx":
                raise web.HTTPFound(f"/file?{request.query_string}")
            return web.Response(body=payload, content_type=OCTET)

        app = web.Application()
        app.router.add_get("/{tail:.*}", record)
        async with TestServer(app) as server:
            client.get_file_metadata = AsyncMock(
                return_value={
                    "name": "report.docx",
                    "@microsoft.graph.downloadUrl": str(
                        server.make_url("/download.aspx?tempauth=signed")
                    ),
                }
            )
            with patch("asyncio.sleep", new=AsyncMock()):
                result = await client.get_file_extraction_by_id("drive", "item")

        assert result.text is not None and "Served without a token" in result.text
        # The first answer is retried, the second is a same-host redirect.
        assert [path for path, _ in seen] == [
            "/download.aspx",
            "/download.aspx",
            "/file",
        ]
        for _, headers in seen:
            assert "Authorization" not in headers
            assert "mock-token" not in str(headers)
        assert client.headers["Authorization"] == "Bearer mock-token"


@pytest.mark.parametrize("status", [200, 403, 404, 410, 429, 503])
async def test_metadata_batch_preserves_item_level_answers(client, status):
    client.client.post = AsyncMock(
        return_value={
            "responses": [
                {
                    "id": "0",
                    "status": status,
                    "body": {"id": "a", "parentReference": {"path": "/Elsewhere"}},
                },
                {"id": "1", "status": 404},
            ]
        }
    )
    results = await client.get_item_metadata_batch("drive", ["a", "b"])
    assert results["a"].status == status
    assert (results["a"].item is not None) == (status == 200)
    assert results["b"].status == 404
    assert client.client.post.await_count == 1
    requests = client.client.post.await_args.kwargs["data"]["requests"]
    assert len(requests) == 2
    assert requests[0]["url"] == "/drives/drive/items/a?$select=id,name,parentReference"


@pytest.mark.parametrize(
    "responses",
    [
        [],
        [{"id": "0", "status": 200, "body": {"id": "wrong"}}],
        [{"id": "0", "status": 404}, {"id": "0", "status": 404}],
        [{"id": "unexpected", "status": 404}],
        [{"id": "0", "status": "404"}],
    ],
)
async def test_malformed_metadata_batch_is_not_deletion_evidence(client, responses):
    client.client.post = AsyncMock(return_value={"responses": responses})
    with pytest.raises(ValueError):
        await client.get_item_metadata_batch("drive", ["a"])


async def test_metadata_batch_refreshes_inner_unauthorized_once(client):
    client.access_token_provider = AsyncMock(return_value="fresh")
    client.client.post = AsyncMock(
        side_effect=[
            {"responses": [{"id": "0", "status": 401}]},
            {"responses": [{"id": "0", "status": 404}]},
        ]
    )
    result = await client.get_item_metadata_batch("drive", ["a"])
    assert result["a"].status == 404
    assert client.client.post.await_count == 2
    assert (
        client.client.post.await_args.kwargs["headers"]["Authorization"]
        == "Bearer fresh"
    )


async def test_delta_uses_last_occurrence_across_pages(client):
    client.client.get = AsyncMock(
        side_effect=[
            {"value": [{"id": "a", "deleted": {}}], "@odata.nextLink": "v1.0/next"},
            {
                "value": [{"id": "a", "name": "restored.docx"}],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?token=next",
            },
        ]
    )
    changes, token = await client.get_delta_changes("drive", "previous")
    assert changes == [{"id": "a", "name": "restored.docx"}]
    assert token == "next"
