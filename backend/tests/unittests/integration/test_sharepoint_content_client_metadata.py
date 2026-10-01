"""List item column expansion in the Graph content client."""

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
    _strip_query_param,
)

EXPAND = "$expand=listItem($expand=fields)"


def _bad_request(message: str = "Invalid $expand") -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(
        request_info=MagicMock(), history=(), status=400, message=message
    )


def _client(*, include: bool, responses) -> SharePointContentClient:
    client = SharePointContentClient(
        base_url="https://graph.microsoft.com",
        api_token="token",
        include_list_item_fields=include,
        max_download_bytes=1,
    )
    client.client = MagicMock()
    client.client.get = AsyncMock(side_effect=responses)
    client.client.close = AsyncMock()
    return client


def _urls(client: SharePointContentClient) -> list[str]:
    return [call.args[0] for call in client.client.get.await_args_list]


class TestStripQueryParam:
    def test_removes_plain_and_encoded_spellings(self):
        assert _strip_query_param("a/delta?token=x&$expand=y", "$expand") == (
            "a/delta?token=x"
        )
        assert _strip_query_param("a/delta?%24expand=y&token=x", "$expand") == (
            "a/delta?token=x"
        )
        assert _strip_query_param("a/delta?$expand=y", "$expand") == "a/delta"
        assert _strip_query_param("a/delta", "$expand") == "a/delta"


class TestListingExpansion:
    async def test_listings_carry_the_expansion_when_enabled(self):
        client = _client(include=True, responses=[{"value": [{"id": "1"}]}])

        items = await client.get_drive_folder_items("d1", "f1")

        assert items == [{"id": "1"}]
        assert _urls(client) == [f"v1.0/drives/d1/items/f1/children?{EXPAND}"]

    async def test_listings_are_plain_when_disabled(self):
        client = _client(include=False, responses=[{"value": []}])

        await client.get_drive_root_children("d1")

        assert _urls(client) == ["v1.0/drives/d1/root/children"]
        assert client.list_item_fields_enabled is False

    async def test_rejected_expansion_falls_back_for_the_rest_of_the_client(self):
        client = _client(
            include=True,
            responses=[_bad_request(), {"value": [{"id": "1"}]}, {"value": []}],
        )

        items = await client.get_drive_root_children("d1")
        await client.get_drive_folder_items("d1", "f1")

        assert items == [{"id": "1"}]
        assert _urls(client) == [
            f"v1.0/drives/d1/root/children?{EXPAND}",
            "v1.0/drives/d1/root/children",
            "v1.0/drives/d1/items/f1/children",
        ]
        assert client.list_item_fields_enabled is False

    async def test_other_errors_still_propagate(self):
        forbidden = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=403, message="no"
        )
        client = _client(include=True, responses=[forbidden])

        with pytest.raises(aiohttp.ClientResponseError):
            await client.get_drive_root_children("d1")
        assert client.list_item_fields_enabled is True

    async def test_single_item_lookup_is_expanded_too(self):
        client = _client(include=True, responses=[{"id": "f1", "folder": {}}])

        await client.get_file_metadata("d1", "f1")

        assert _urls(client) == [f"v1.0/drives/d1/items/f1?{EXPAND}"]


class TestDeltaExpansion:
    async def test_delta_requests_carry_the_expansion(self):
        client = _client(
            include=True,
            responses=[
                {
                    "value": [{"id": "1"}],
                    "@odata.nextLink": (
                        "https://graph.microsoft.com/v1.0/drives/d1/root/delta"
                        "?token=p2&%24expand=listItem(%24expand%3Dfields)"
                    ),
                },
                {
                    "value": [{"id": "2"}],
                    "@odata.deltaLink": (
                        "https://graph.microsoft.com/v1.0/drives/d1/root/delta"
                        "?token=final"
                    ),
                },
            ],
        )

        changes, token = await client.get_delta_changes("d1", "start")

        assert [c["id"] for c in changes] == ["1", "2"]
        assert token == "final"
        urls = _urls(client)
        assert urls[0] == f"v1.0/drives/d1/root/delta?token=start&{EXPAND}"
        # Graph builds the next link from the accepted options; we follow it as is.
        assert urls[1].startswith("v1.0/drives/d1/root/delta?token=p2")

    async def test_delta_retries_the_page_without_expansion_on_400(self):
        client = _client(
            include=True,
            responses=[
                _bad_request(),
                {"value": [], "@odata.deltaLink": "x/delta?token=t1"},
            ],
        )

        token = await client.initialize_delta_token("d1")

        assert token == "t1"
        assert _urls(client) == [
            f"v1.0/drives/d1/root/delta?{EXPAND}",
            "v1.0/drives/d1/root/delta",
        ]


class TestListColumns:
    async def test_follows_pagination(self):
        client = _client(
            include=True,
            responses=[
                {
                    "value": [{"name": "A"}],
                    "@odata.nextLink": (
                        "https://g/v1.0/drives/d1/list/columns?$skiptoken=1"
                    ),
                },
                {"value": [{"name": "B"}]},
            ],
        )

        columns = await client.get_list_columns("d1")

        assert [c["name"] for c in columns] == ["A", "B"]
        assert _urls(client)[0] == "v1.0/drives/d1/list/columns"
