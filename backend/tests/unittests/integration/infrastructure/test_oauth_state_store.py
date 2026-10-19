"""Single-use OAuth state bound in Redis, sealed when the caller asks for it."""

import json

import pytest
from cryptography.fernet import Fernet

from eneo.integration.infrastructure.oauth_state_store import OauthStateStore
from eneo.settings.encryption_service import EncryptionService


class _FakeRedis:
    """Dict-backed Redis exposing only GETDEL for reads, so a non-atomic
    GET+DEL pop fails loudly."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def getdel(self, key: str) -> str | None:
        return self.store.pop(key, None)

    async def get(self, key: str) -> None:
        raise AssertionError("pop must use GETDEL, not GET")

    async def delete(self, key: str) -> None:
        raise AssertionError("pop must use GETDEL, not DEL")


def _encryption_service() -> EncryptionService:
    return EncryptionService(Fernet.generate_key().decode())


async def test_sealed_state_is_encrypted_at_rest_and_single_use():
    redis = _FakeRedis()
    encryption = _encryption_service()
    store = OauthStateStore(redis, prefix="p:", encryption_service=encryption)
    data = {"client_secret": "super-secret", "tenant_id": "t", "user_id": "u"}

    await store.store("state-1", data)

    stored = redis.store["p:state-1"]
    assert "super-secret" not in stored
    assert encryption.decrypt(stored) == json.dumps(data)
    assert await store.pop("state-1") == data
    assert await store.pop("state-1") is None


async def test_plain_state_round_trips_under_its_prefix_and_is_single_use():
    redis = _FakeRedis()
    store = OauthStateStore(redis, prefix="integration:oauth_state:")

    await store.store("state-1", {"user_id": "u"})

    assert json.loads(redis.store["integration:oauth_state:state-1"]) == {
        "user_id": "u"
    }
    assert await store.pop("state-1") == {"user_id": "u"}
    assert await store.pop("state-1") is None


@pytest.mark.parametrize("payload", ["not-json", '"a string"', "[1]"])
async def test_unreadable_states_are_invalid_not_errors(payload):
    redis = _FakeRedis()
    redis.store["p:state-1"] = payload

    assert await OauthStateStore(redis, prefix="p:").pop("state-1") is None
    assert redis.store == {}


async def test_a_blob_sealed_with_another_key_is_discarded():
    redis = _FakeRedis()
    await OauthStateStore(
        redis, prefix="p:", encryption_service=_encryption_service()
    ).store("state-1", {"a": "b"})

    assert (
        await OauthStateStore(
            redis, prefix="p:", encryption_service=_encryption_service()
        ).pop("state-1")
        is None
    )
