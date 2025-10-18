import asyncio
from datetime import timedelta

import pytest

from intric.main.request_context import (
    clear_request_context,
    get_request_context,
    set_request_context,
)
from intric.observability import debug_toggle, redaction


class FakeRedisSuccess:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None):  # noqa: ARG002
        self.store[key] = value

    async def delete(self, key):  # noqa: ARG002
        self.store.pop(key, None)

    async def get(self, key):
        return self.store.get(key)


class FakeRedisBroken(FakeRedisSuccess):
    def __init__(self):
        super().__init__()
        self.fail = True

    async def set(self, *args, **kwargs):  # noqa: ARG002
        raise RuntimeError("redis unavailable")


@pytest.mark.asyncio
async def test_debug_toggle_fallback_on_storage_failure():
    redis = FakeRedisBroken()

    # Should not raise even though redis.set fails
    flag = await debug_toggle.set_debug_flag(
        redis,
        enabled=True,
        enabled_by="test",
        duration=timedelta(minutes=5),
        reason="unit-test",
    )

    assert not flag.enabled

    # is_debug_enabled should also remain false
    assert not await debug_toggle.is_debug_enabled(redis)


def test_request_context_isolation():
    clear_request_context()
    set_request_context(correlation_id="abc", tenant_slug="tenant-a")
    snap_one = get_request_context()

    clear_request_context()
    snap_two = get_request_context()

    assert snap_one == {"correlation_id": "abc", "tenant_slug": "tenant-a"}
    assert snap_two == {}


def test_sanitize_payload_masks_sensitive_tokens():
    payload = {
        "client_secret": "super-secret",
        "email": "user@example.com",
        "nested": {"refresh_token": "bar"},
    }

    sanitized = redaction.sanitize_payload(payload)

    assert sanitized["client_secret"] == "[REDACTED]"
    assert sanitized["email"] == "user@example.com"
    # nested dicts currently pass through (future recursion can extend this)
    assert sanitized["nested"]["refresh_token"] == "bar"
