import pytest

from eneo.worker.redis.lua_scripts import LuaScripts


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lease_lua_enforces_owner_for_refresh_and_release(redis_client) -> None:
    key = "test:owner-checked-lease"
    await redis_client.set(key, "owner-a", ex=30)

    assert not await LuaScripts.refresh_owned_lock(
        redis_client, key, "owner-b", ttl_seconds=60
    )
    assert not await LuaScripts.release_owned_lock(redis_client, key, "owner-b")
    assert await redis_client.get(key) == b"owner-a"

    assert await LuaScripts.refresh_owned_lock(
        redis_client, key, "owner-a", ttl_seconds=60
    )
    assert await redis_client.ttl(key) > 30
    assert await LuaScripts.release_owned_lock(redis_client, key, "owner-a")
    assert await redis_client.get(key) is None
