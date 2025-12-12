"""Tests for OfficeChangeKeyService (Redis-based webhook deduplication)."""

import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.integration.infrastructure.office_change_key_service import (
    OfficeChangeKeyService,
)


class TestOfficeChangeKeyService(unittest.TestCase):
    """Test OfficeChangeKeyService for ChangeKey deduplication."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_redis = AsyncMock()
        self.service = OfficeChangeKeyService(self.mock_redis)
        self.integration_id = uuid4()
        self.item_id = "file123"
        self.change_key = "abc123def456"

    @pytest.mark.asyncio
    async def test_should_process_first_time_no_cache(self):
        """Test should_process returns True when no cached ChangeKey exists."""
        # Arrange
        self.mock_redis.get = AsyncMock(return_value=None)

        # Act
        result = await self.service.should_process(
            self.integration_id, self.item_id, self.change_key
        )

        # Assert
        self.assertTrue(result)
        self.mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_process_duplicate_changekey(self):
        """Test should_process returns False when ChangeKey matches cached value."""
        # Arrange
        cached_key = b"abc123def456"
        self.mock_redis.get = AsyncMock(return_value=cached_key)

        # Act
        result = await self.service.should_process(
            self.integration_id, self.item_id, "abc123def456"
        )

        # Assert
        self.assertFalse(result)

    @pytest.mark.asyncio
    async def test_should_process_changed_changekey(self):
        """Test should_process returns True when ChangeKey is different."""
        # Arrange
        old_key = b"old_key_123"
        self.mock_redis.get = AsyncMock(return_value=old_key)

        # Act
        result = await self.service.should_process(
            self.integration_id, self.item_id, "new_key_456"
        )

        # Assert
        self.assertTrue(result)

    @pytest.mark.asyncio
    async def test_should_process_with_string_cached_key(self):
        """Test should_process handles string cached values (not just bytes)."""
        # Arrange
        cached_key = "abc123def456"  # String, not bytes
        self.mock_redis.get = AsyncMock(return_value=cached_key)

        # Act
        result = await self.service.should_process(
            self.integration_id, self.item_id, "abc123def456"
        )

        # Assert
        self.assertFalse(result)

    @pytest.mark.asyncio
    async def test_update_change_key(self):
        """Test update_change_key stores ChangeKey in Redis with TTL."""
        # Arrange
        self.mock_redis.setex = AsyncMock()

        # Act
        await self.service.update_change_key(
            self.integration_id, self.item_id, self.change_key
        )

        # Assert
        self.mock_redis.setex.assert_called_once()
        call_args = self.mock_redis.setex.call_args

        # Verify the call signature
        redis_key = call_args[0][0]
        ttl = call_args[0][1]
        value = call_args[0][2]

        self.assertIn(str(self.integration_id), redis_key)
        self.assertIn(self.item_id, redis_key)
        self.assertEqual(value, self.change_key)
        # TTL should be 7 days in seconds
        self.assertEqual(ttl, 7 * 24 * 60 * 60)

    @pytest.mark.asyncio
    async def test_invalidate_change_key(self):
        """Test invalidate_change_key removes ChangeKey from cache."""
        # Arrange
        self.mock_redis.delete = AsyncMock()

        # Act
        await self.service.invalidate_change_key(
            self.integration_id, self.item_id
        )

        # Assert
        self.mock_redis.delete.assert_called_once()
        call_args = self.mock_redis.delete.call_args
        redis_key = call_args[0][0]

        self.assertIn(str(self.integration_id), redis_key)
        self.assertIn(self.item_id, redis_key)

    @pytest.mark.asyncio
    async def test_clear_integration_cache(self):
        """Test clear_integration_cache removes all ChangeKeys for an integration."""
        # Arrange
        self.mock_redis.eval = AsyncMock(return_value=42)  # Return number of deleted keys

        # Act
        deleted_count = await self.service.clear_integration_cache(
            self.integration_id
        )

        # Assert
        self.mock_redis.eval.assert_called_once()
        self.assertEqual(deleted_count, 42)

    def test_get_changekey_key_format(self):
        """Test _get_changekey_key generates correct Redis key format."""
        # Act
        key = self.service._get_changekey_key(self.integration_id, self.item_id)

        # Assert
        self.assertEqual(
            key, f"office_change_key:{self.integration_id}:{self.item_id}"
        )

    def test_get_changekey_key_with_special_characters(self):
        """Test _get_changekey_key handles special characters in item_id."""
        # Arrange
        special_item_id = "file-123/folder/document.docx"

        # Act
        key = self.service._get_changekey_key(self.integration_id, special_item_id)

        # Assert
        self.assertIn(special_item_id, key)
        self.assertIn("office_change_key:", key)

    @pytest.mark.asyncio
    async def test_should_process_redis_key_includes_integration_id(self):
        """Test that should_process uses correct Redis key with integration_id."""
        # Arrange
        self.mock_redis.get = AsyncMock(return_value=None)

        # Act
        await self.service.should_process(
            self.integration_id, self.item_id, self.change_key
        )

        # Assert
        call_args = self.mock_redis.get.call_args[0][0]
        self.assertIn(str(self.integration_id), call_args)

    @pytest.mark.asyncio
    async def test_should_process_redis_key_includes_item_id(self):
        """Test that should_process uses correct Redis key with item_id."""
        # Arrange
        self.mock_redis.get = AsyncMock(return_value=None)

        # Act
        await self.service.should_process(
            self.integration_id, self.item_id, self.change_key
        )

        # Assert
        call_args = self.mock_redis.get.call_args[0][0]
        self.assertIn(self.item_id, call_args)

    @pytest.mark.asyncio
    async def test_changekey_ttl_is_7_days(self):
        """Test that ChangeKey TTL is set to exactly 7 days."""
        # Arrange
        self.mock_redis.setex = AsyncMock()
        expected_ttl_seconds = 7 * 24 * 60 * 60  # 604800 seconds

        # Act
        await self.service.update_change_key(
            self.integration_id, self.item_id, self.change_key
        )

        # Assert
        call_args = self.mock_redis.setex.call_args[0]
        actual_ttl = call_args[1]
        self.assertEqual(actual_ttl, expected_ttl_seconds)

    @pytest.mark.asyncio
    async def test_should_process_handles_empty_cached_value(self):
        """Test should_process handles empty string from Redis."""
        # Arrange
        self.mock_redis.get = AsyncMock(return_value=b"")

        # Act
        result = await self.service.should_process(
            self.integration_id, self.item_id, ""
        )

        # Assert
        self.assertFalse(result)  # Empty matches empty

    @pytest.mark.asyncio
    async def test_should_process_case_sensitive_comparison(self):
        """Test ChangeKey comparison is case-sensitive."""
        # Arrange
        self.mock_redis.get = AsyncMock(return_value=b"ABC123")

        # Act
        result = await self.service.should_process(
            self.integration_id, self.item_id, "abc123"
        )

        # Assert
        # Different case should be treated as different ChangeKey
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
