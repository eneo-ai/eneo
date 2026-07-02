"""Tests for OfficeChangeKeyService (Redis-based webhook deduplication)."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.integration.infrastructure.office_change_key_service import (
    OfficeChangeKeyService,
)


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(mock_redis: AsyncMock) -> OfficeChangeKeyService:
    return OfficeChangeKeyService(mock_redis)


@pytest.fixture
def integration_id():
    return uuid4()


@pytest.fixture
def item_id() -> str:
    return "file123"


@pytest.fixture
def change_key() -> str:
    return "abc123def456"


async def test_should_process_first_time_no_cache(
    service, mock_redis, integration_id, item_id, change_key
):
    """Test should_process returns True when no cached ChangeKey exists."""
    mock_redis.get = AsyncMock(return_value=None)

    result = await service.should_process(integration_id, item_id, change_key)

    assert result is True
    mock_redis.get.assert_called_once()


async def test_should_process_duplicate_changekey(
    service, mock_redis, integration_id, item_id
):
    """Test should_process returns False when ChangeKey matches cached value."""
    mock_redis.get = AsyncMock(return_value=b"abc123def456")

    result = await service.should_process(integration_id, item_id, "abc123def456")

    assert result is False


async def test_should_process_changed_changekey(
    service, mock_redis, integration_id, item_id
):
    """Test should_process returns True when ChangeKey is different."""
    mock_redis.get = AsyncMock(return_value=b"old_key_123")

    result = await service.should_process(integration_id, item_id, "new_key_456")

    assert result is True


async def test_should_process_with_string_cached_key(
    service, mock_redis, integration_id, item_id
):
    """Test should_process handles string cached values (not just bytes)."""
    mock_redis.get = AsyncMock(return_value="abc123def456")

    result = await service.should_process(integration_id, item_id, "abc123def456")

    assert result is False


async def test_update_change_key(
    service, mock_redis, integration_id, item_id, change_key
):
    """Test update_change_key stores ChangeKey in Redis with TTL."""
    mock_redis.setex = AsyncMock()

    await service.update_change_key(integration_id, item_id, change_key)

    mock_redis.setex.assert_called_once()
    call_args = mock_redis.setex.call_args
    redis_key = call_args[0][0]
    ttl = call_args[0][1]
    value = call_args[0][2]

    assert str(integration_id) in redis_key
    assert item_id in redis_key
    assert value == change_key
    assert ttl == 7 * 24 * 60 * 60


async def test_invalidate_change_key(service, mock_redis, integration_id, item_id):
    """Test invalidate_change_key removes ChangeKey from cache."""
    mock_redis.delete = AsyncMock()

    await service.invalidate_change_key(integration_id, item_id)

    mock_redis.delete.assert_called_once()
    redis_key = mock_redis.delete.call_args[0][0]
    assert str(integration_id) in redis_key
    assert item_id in redis_key


async def test_clear_integration_cache(service, mock_redis, integration_id):
    """Test clear_integration_cache removes all ChangeKeys for an integration."""
    matching_keys = [
        f"office_change_key:{integration_id}:file1",
        f"office_change_key:{integration_id}:file2",
    ]
    mock_redis.keys = AsyncMock(return_value=matching_keys)
    mock_redis.delete = AsyncMock()

    await service.clear_integration_cache(integration_id)

    mock_redis.keys.assert_called_once_with(f"office_change_key:{integration_id}:*")
    mock_redis.delete.assert_called_once_with(*matching_keys)


async def test_clear_integration_cache_noop_when_empty(
    service, mock_redis, integration_id
):
    """Test clear_integration_cache does not call delete when no keys match."""
    mock_redis.keys = AsyncMock(return_value=[])
    mock_redis.delete = AsyncMock()

    await service.clear_integration_cache(integration_id)

    mock_redis.delete.assert_not_called()


def test_get_changekey_key_format(service, integration_id, item_id):
    """Test _get_changekey_key generates correct Redis key format."""
    key = service._get_changekey_key(integration_id, item_id)

    assert key == f"office_change_key:{integration_id}:{item_id}"


def test_get_changekey_key_with_special_characters(service, integration_id):
    """Test _get_changekey_key handles special characters in item_id."""
    special_item_id = "file-123/folder/document.docx"

    key = service._get_changekey_key(integration_id, special_item_id)

    assert special_item_id in key
    assert "office_change_key:" in key


async def test_should_process_redis_key_includes_integration_id(
    service, mock_redis, integration_id, item_id, change_key
):
    """Test that should_process uses correct Redis key with integration_id."""
    mock_redis.get = AsyncMock(return_value=None)

    await service.should_process(integration_id, item_id, change_key)

    call_args = mock_redis.get.call_args[0][0]
    assert str(integration_id) in call_args


async def test_should_process_redis_key_includes_item_id(
    service, mock_redis, integration_id, item_id, change_key
):
    """Test that should_process uses correct Redis key with item_id."""
    mock_redis.get = AsyncMock(return_value=None)

    await service.should_process(integration_id, item_id, change_key)

    call_args = mock_redis.get.call_args[0][0]
    assert item_id in call_args


async def test_changekey_ttl_is_7_days(
    service, mock_redis, integration_id, item_id, change_key
):
    """Test that ChangeKey TTL is set to exactly 7 days."""
    mock_redis.setex = AsyncMock()
    expected_ttl_seconds = 7 * 24 * 60 * 60

    await service.update_change_key(integration_id, item_id, change_key)

    actual_ttl = mock_redis.setex.call_args[0][1]
    assert actual_ttl == expected_ttl_seconds


async def test_should_process_handles_empty_cached_value(
    service, mock_redis, integration_id, item_id
):
    """Test should_process handles empty string from Redis."""
    mock_redis.get = AsyncMock(return_value=b"")

    result = await service.should_process(integration_id, item_id, "")

    assert result is False


async def test_should_process_case_sensitive_comparison(
    service, mock_redis, integration_id, item_id
):
    """Test ChangeKey comparison is case-sensitive."""
    mock_redis.get = AsyncMock(return_value=b"ABC123")

    result = await service.should_process(integration_id, item_id, "abc123")

    assert result is True
