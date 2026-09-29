from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)

SETTINGS_PATCH = (
    "eneo.integration.infrastructure.clients.sharepoint_content_client.get_settings"
)


def _sub_response(gid: str, status: int, headers: dict | None = None) -> dict:
    body = (
        {"id": f"site-{gid}", "webUrl": f"https://contoso.sharepoint.com/sites/{gid}"}
        if status == 200
        else {}
    )
    return {"id": gid, "status": status, "headers": headers or {}, "body": body}


async def _make_client() -> SharePointContentClient:
    with patch(
        SETTINGS_PATCH,
        return_value=MagicMock(sharepoint_max_download_bytes=1024),
    ):
        return SharePointContentClient(
            base_url="https://graph.microsoft.com",
            api_token="token",
        )


@pytest.mark.asyncio
async def test_batched_lookup_maps_group_ids_and_chunks_requests():
    client = await _make_client()
    try:
        group_ids = [f"g{i}" for i in range(25)]

        async def post(endpoint, data=None, headers=None, **kwargs):
            assert endpoint == "v1.0/$batch"
            assert len(data["requests"]) <= SharePointContentClient.BATCH_SIZE
            return {
                "responses": [_sub_response(req["id"], 200) for req in data["requests"]]
            }

        client.client.post = AsyncMock(side_effect=post)

        result = await client.get_group_root_sites_batched(group_ids)

        assert len(result) == 25
        assert result["g0"] == {
            "id": "site-g0",
            "webUrl": "https://contoso.sharepoint.com/sites/g0",
        }
        assert client.client.post.await_count == 2  # 25 ids -> chunks of 20 + 5
    finally:
        await client.client.close()


@pytest.mark.asyncio
async def test_batched_lookup_skips_forbidden_and_missing_sites():
    client = await _make_client()
    try:
        client.client.post = AsyncMock(
            return_value={
                "responses": [
                    _sub_response("g-ok", 200),
                    _sub_response("g-forbidden", 403),
                    _sub_response("g-missing", 404),
                ]
            }
        )

        result = await client.get_group_root_sites_batched(
            ["g-ok", "g-forbidden", "g-missing"]
        )

        assert set(result) == {"g-ok"}
        assert client.client.post.await_count == 1
    finally:
        await client.client.close()


@pytest.mark.asyncio
async def test_batched_lookup_retries_throttled_subrequests_with_retry_after():
    client = await _make_client()
    try:
        envelopes = [
            {
                "responses": [
                    _sub_response("g1", 200),
                    _sub_response("g2", 429, headers={"Retry-After": "7"}),
                ]
            },
            {"responses": [_sub_response("g2", 200)]},
        ]
        client.client.post = AsyncMock(side_effect=envelopes)

        with patch("asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await client.get_group_root_sites_batched(["g1", "g2"])

        assert set(result) == {"g1", "g2"}
        assert client.client.post.await_count == 2
        sleep.assert_awaited_once_with(7.0)
        # Second round only re-requests the throttled id
        retried_body = (
            client.client.post.await_args_list[1].kwargs.get("data")
            or client.client.post.await_args_list[1].args[1]
        )
        assert [req["id"] for req in retried_body["requests"]] == ["g2"]
    finally:
        await client.client.close()


@pytest.mark.asyncio
async def test_batched_lookup_gives_up_after_retry_round_cap():
    client = await _make_client()
    try:
        client.client.post = AsyncMock(
            return_value={
                "responses": [
                    _sub_response("g1", 429, headers={"Retry-After": "1"}),
                ]
            }
        )

        with patch("asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await client.get_group_root_sites_batched(["g1"])

        assert result == {}
        assert (
            client.client.post.await_count
            == SharePointContentClient.BATCH_MAX_RETRY_ROUNDS + 1
        )
        assert sleep.await_count == SharePointContentClient.BATCH_MAX_RETRY_ROUNDS
        # Retry-After below the floor sleeps the minimum instead
        sleep.assert_awaited_with(SharePointContentClient.BATCH_MIN_RETRY_SLEEP_SECONDS)
    finally:
        await client.client.close()


@pytest.mark.asyncio
async def test_batched_lookup_dedupes_input_ids():
    client = await _make_client()
    try:
        client.client.post = AsyncMock(
            return_value={"responses": [_sub_response("g1", 200)]}
        )

        result = await client.get_group_root_sites_batched(["g1", "g1", "", "g1"])

        assert set(result) == {"g1"}
        body = (
            client.client.post.await_args.kwargs.get("data")
            or client.client.post.await_args.args[1]
        )
        assert [req["id"] for req in body["requests"]] == ["g1"]
    finally:
        await client.client.close()
