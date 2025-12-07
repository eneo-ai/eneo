"""Unit tests for rate limiting infrastructure."""

import pytest
from unittest.mock import AsyncMock
from uuid import uuid4

import redis.exceptions

from intric.audit.infrastructure.rate_limiting import (
    RATE_LIMIT_SCRIPT,
    RateLimitConfig,
    RateLimitResult,
    RateLimitExceededError,
    RateLimitServiceUnavailableError,
    build_rate_limit_key,
    check_rate_limit,
    enforce_rate_limit,
)


class TestRateLimitConfig:
    """Test RateLimitConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = RateLimitConfig()
        assert config.max_requests == 5
        assert config.window_seconds == 3600
        assert config.key_prefix == "rate_limit:audit_session"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = RateLimitConfig(
            max_requests=10,
            window_seconds=60,
            key_prefix="custom:prefix",
        )
        assert config.max_requests == 10
        assert config.window_seconds == 60
        assert config.key_prefix == "custom:prefix"


class TestRateLimitResult:
    """Test RateLimitResult dataclass."""

    def test_allowed_result(self):
        """Test result when under limit."""
        result = RateLimitResult(
            allowed=True,
            current_count=3,
            max_requests=5,
            window_seconds=3600,
        )
        assert result.allowed is True
        assert result.current_count == 3
        assert result.remaining == 2

    def test_exceeded_result(self):
        """Test result when over limit."""
        result = RateLimitResult(
            allowed=False,
            current_count=6,
            max_requests=5,
            window_seconds=3600,
        )
        assert result.allowed is False
        assert result.current_count == 6
        assert result.remaining == 0

    def test_remaining_never_negative(self):
        """Test remaining is never negative."""
        result = RateLimitResult(
            allowed=False,
            current_count=100,
            max_requests=5,
            window_seconds=3600,
        )
        assert result.remaining == 0


class TestBuildRateLimitKey:
    """Test build_rate_limit_key function."""

    def test_default_prefix(self):
        """Test key building with default prefix."""
        user_id = uuid4()
        tenant_id = uuid4()
        key = build_rate_limit_key(user_id, tenant_id)
        assert key == f"rate_limit:audit_session:{user_id}:{tenant_id}"

    def test_custom_prefix(self):
        """Test key building with custom prefix."""
        user_id = uuid4()
        tenant_id = uuid4()
        key = build_rate_limit_key(user_id, tenant_id, prefix="custom:rate_limit")
        assert key == f"custom:rate_limit:{user_id}:{tenant_id}"


class TestCheckRateLimit:
    """Test check_rate_limit function."""

    @pytest.mark.asyncio
    async def test_first_request_allowed(self):
        """Test first request is allowed."""
        redis_client = AsyncMock()
        redis_client.eval = AsyncMock(return_value=1)

        result = await check_rate_limit(redis_client, "test:key")

        assert result.allowed is True
        assert result.current_count == 1
        assert result.remaining == 4
        redis_client.eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_under_limit_allowed(self):
        """Test requests under limit are allowed."""
        redis_client = AsyncMock()
        redis_client.eval = AsyncMock(return_value=3)

        result = await check_rate_limit(redis_client, "test:key")

        assert result.allowed is True
        assert result.current_count == 3

    @pytest.mark.asyncio
    async def test_at_limit_allowed(self):
        """Test request at exact limit is allowed."""
        redis_client = AsyncMock()
        redis_client.eval = AsyncMock(return_value=5)

        result = await check_rate_limit(redis_client, "test:key")

        assert result.allowed is True
        assert result.current_count == 5
        assert result.remaining == 0

    @pytest.mark.asyncio
    async def test_over_limit_denied(self):
        """Test request over limit is denied."""
        redis_client = AsyncMock()
        redis_client.eval = AsyncMock(return_value=6)

        result = await check_rate_limit(redis_client, "test:key")

        assert result.allowed is False
        assert result.current_count == 6

    @pytest.mark.asyncio
    async def test_custom_config(self):
        """Test with custom configuration."""
        redis_client = AsyncMock()
        redis_client.eval = AsyncMock(return_value=8)
        config = RateLimitConfig(max_requests=10, window_seconds=60)

        result = await check_rate_limit(redis_client, "test:key", config)

        assert result.allowed is True
        assert result.max_requests == 10
        assert result.window_seconds == 60
        # Verify script called with custom window
        redis_client.eval.assert_called_once_with(
            RATE_LIMIT_SCRIPT,
            1,
            "test:key",
            60,
        )

    @pytest.mark.asyncio
    async def test_redis_error_raises_service_unavailable(self):
        """Test Redis error raises RateLimitServiceUnavailableError."""
        redis_client = AsyncMock()
        redis_client.eval = AsyncMock(
            side_effect=redis.exceptions.ConnectionError("Connection refused")
        )

        with pytest.raises(RateLimitServiceUnavailableError) as exc_info:
            await check_rate_limit(redis_client, "test:key")

        assert "Connection refused" in str(exc_info.value.original_error)


class TestEnforceRateLimit:
    """Test enforce_rate_limit function."""

    @pytest.mark.asyncio
    async def test_allowed_returns_result(self):
        """Test allowed request returns result."""
        redis_client = AsyncMock()
        redis_client.eval = AsyncMock(return_value=1)
        user_id = uuid4()
        tenant_id = uuid4()

        result = await enforce_rate_limit(redis_client, user_id, tenant_id)

        assert result.allowed is True
        assert result.current_count == 1

    @pytest.mark.asyncio
    async def test_exceeded_raises_error(self):
        """Test exceeded limit raises RateLimitExceededError."""
        redis_client = AsyncMock()
        redis_client.eval = AsyncMock(return_value=6)
        user_id = uuid4()
        tenant_id = uuid4()

        with pytest.raises(RateLimitExceededError) as exc_info:
            await enforce_rate_limit(redis_client, user_id, tenant_id)

        assert exc_info.value.result.current_count == 6
        assert exc_info.value.result.max_requests == 5

    @pytest.mark.asyncio
    async def test_builds_correct_key(self):
        """Test correct key is built."""
        redis_client = AsyncMock()
        redis_client.eval = AsyncMock(return_value=1)
        user_id = uuid4()
        tenant_id = uuid4()

        await enforce_rate_limit(redis_client, user_id, tenant_id)

        expected_key = f"rate_limit:audit_session:{user_id}:{tenant_id}"
        call_args = redis_client.eval.call_args
        assert call_args[0][2] == expected_key

    @pytest.mark.asyncio
    async def test_redis_error_propagates(self):
        """Test Redis errors propagate as RateLimitServiceUnavailableError."""
        redis_client = AsyncMock()
        redis_client.eval = AsyncMock(
            side_effect=redis.exceptions.TimeoutError("Timeout")
        )
        user_id = uuid4()
        tenant_id = uuid4()

        with pytest.raises(RateLimitServiceUnavailableError):
            await enforce_rate_limit(redis_client, user_id, tenant_id)


class TestRateLimitExceededError:
    """Test RateLimitExceededError exception."""

    def test_error_message(self):
        """Test error message contains useful info."""
        result = RateLimitResult(
            allowed=False,
            current_count=6,
            max_requests=5,
            window_seconds=3600,
        )
        error = RateLimitExceededError(result)

        assert "6/5" in str(error)
        assert "3600" in str(error)
        assert error.result == result


class TestRateLimitServiceUnavailableError:
    """Test RateLimitServiceUnavailableError exception."""

    def test_preserves_original_error(self):
        """Test original error is preserved."""
        original = redis.exceptions.ConnectionError("Connection refused")
        error = RateLimitServiceUnavailableError(original)

        assert error.original_error == original
        assert "Connection refused" in str(error)


class TestLuaScript:
    """Test the Lua script behavior through integration-like tests."""

    def test_script_is_valid_lua(self):
        """Test script contains expected Lua commands."""
        assert "redis.call('INCR'" in RATE_LIMIT_SCRIPT
        assert "redis.call('EXPIRE'" in RATE_LIMIT_SCRIPT
        assert "KEYS[1]" in RATE_LIMIT_SCRIPT
        assert "ARGV[1]" in RATE_LIMIT_SCRIPT

    def test_script_sets_expire_only_on_first_call(self):
        """Test script logic: EXPIRE only when count == 1."""
        # The Lua script should only set EXPIRE when count is 1
        assert "if count == 1 then" in RATE_LIMIT_SCRIPT
