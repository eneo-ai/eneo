"""Unit tests for the extracted recovery module.

Tests the crawl/recovery.py module to ensure:
1. Transaction error detection works correctly
2. Session recovery creates fresh sessions
3. execute_with_recovery wraps operations with retry logic
4. Redis cleanup functions are best-effort

Run with: pytest tests/unittests/worker/test_recovery.py -v
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import InvalidRequestError, PendingRollbackError


class TestRecoveryModuleImports:
    """Tests that the recovery module can be imported from both locations."""

    def test_import_from_crawl_package(self):
        """Recovery functions should be importable from intric.worker.crawl."""
        import intric.worker.crawl as crawl_package
        from intric.worker.crawl import (
            calculate_exponential_backoff,
            execute_with_recovery,
            is_invalid_transaction_error,
            is_invalid_transaction_error_msg,
            reset_tenant_retry_delay,
            update_job_retry_stats,
        )

        assert callable(execute_with_recovery)
        assert callable(is_invalid_transaction_error)
        assert callable(is_invalid_transaction_error_msg)
        assert callable(calculate_exponential_backoff)
        assert callable(reset_tenant_retry_delay)
        assert callable(update_job_retry_stats)
        assert not hasattr(crawl_package, "recover_session")
        assert not hasattr(crawl_package, "SessionHolder")

    def test_import_directly_from_recovery_module(self):
        """Recovery functions should be importable directly from recovery module."""
        import intric.worker.crawl.recovery as recovery_module
        from intric.worker.crawl.recovery import execute_with_recovery

        assert callable(execute_with_recovery)
        assert "recover_session" not in recovery_module.__all__
        assert "SessionHolder" not in recovery_module.__all__
        assert not hasattr(recovery_module, "recover_session")
        assert not hasattr(recovery_module, "SessionHolder")


class TestIsInvalidTransactionError:
    """Tests for is_invalid_transaction_error function."""

    def test_detects_pending_rollback_error(self):
        """Should detect PendingRollbackError as invalid transaction."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error

        error = PendingRollbackError("test error")
        assert is_invalid_transaction_error(error) is True

    def test_detects_invalid_request_error(self):
        """Should detect InvalidRequestError as invalid transaction."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error

        error = InvalidRequestError("test error")
        assert is_invalid_transaction_error(error) is True

    def test_detects_invalid_transaction_in_message(self):
        """Should detect 'invalid transaction' string in error message."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error

        error = Exception("Something invalid transaction happened")
        assert is_invalid_transaction_error(error) is True

    def test_detects_cant_reconnect_in_message(self):
        """Should detect \"can't reconnect\" string in error message."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error

        error = Exception("can't reconnect to database")
        assert is_invalid_transaction_error(error) is True

    def test_detects_pending_rollback_in_message(self):
        """Should detect 'pending rollback' string in error message."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error

        error = Exception("This transaction is pending rollback")
        assert is_invalid_transaction_error(error) is True

    def test_returns_false_for_unrelated_errors(self):
        """Should return False for errors not related to transaction state."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error

        error = Exception("Connection timeout")
        assert is_invalid_transaction_error(error) is False

        error = ValueError("Invalid input")
        assert is_invalid_transaction_error(error) is False

    def test_case_insensitive_message_detection(self):
        """Should detect transaction errors case-insensitively."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error

        error = Exception("INVALID TRANSACTION in progress")
        assert is_invalid_transaction_error(error) is True


class TestIsInvalidTransactionErrorMsg:
    """Tests for is_invalid_transaction_error_msg function."""

    def test_returns_false_for_none(self):
        """Should return False for None message."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error_msg

        assert is_invalid_transaction_error_msg(None) is False

    def test_returns_false_for_empty_string(self):
        """Should return False for empty string."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error_msg

        assert is_invalid_transaction_error_msg("") is False

    def test_detects_invalid_transaction(self):
        """Should detect 'invalid transaction' in message."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error_msg

        assert is_invalid_transaction_error_msg("invalid transaction") is True

    def test_detects_cant_reconnect(self):
        """Should detect \"can't reconnect\" in message."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error_msg

        assert is_invalid_transaction_error_msg("can't reconnect") is True

    def test_detects_pending_rollback(self):
        """Should detect 'pending rollback' in message."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error_msg

        assert is_invalid_transaction_error_msg("pending rollback") is True

    def test_detects_autobegin_disabled(self):
        """Should detect 'autobegin is disabled' in message."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error_msg

        assert is_invalid_transaction_error_msg("autobegin is disabled") is True

    def test_detects_another_operation_in_progress(self):
        """Should detect 'another operation is in progress' in message."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error_msg

        assert (
            is_invalid_transaction_error_msg("another operation is in progress") is True
        )

    def test_case_insensitive(self):
        """Should be case insensitive."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error_msg

        assert is_invalid_transaction_error_msg("INVALID TRANSACTION") is True
        assert is_invalid_transaction_error_msg("Pending Rollback") is True


class TestExecuteWithRecovery:
    """Tests for execute_with_recovery wrapper function.

    NOTE: execute_with_recovery now uses session-per-operation pattern:
    1. Creates fresh session via sessionmanager.create_session()
    2. Passes session to the operation callable
    3. Commits and closes the session when done

    Operations must accept a `session` parameter.
    """

    @pytest.mark.asyncio
    async def test_successful_operation_returns_result(self):
        """Should return result when operation succeeds."""
        from intric.worker.crawl.recovery import execute_with_recovery

        async def successful_op(session):
            # Operation receives session from execute_with_recovery
            return "success"

        # Mock session for session-per-operation pattern
        mock_session = MagicMock()
        mock_session.begin = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.close = AsyncMock()

        mock_sessionmanager = MagicMock()
        mock_sessionmanager.create_session = MagicMock(return_value=mock_session)

        with patch("intric.database.database.sessionmanager", mock_sessionmanager):
            result = await execute_with_recovery(
                operation_name="test_op",
                operation=successful_op,
            )

        assert result == "success"
        # Verify session lifecycle: begin, commit, close
        mock_session.begin.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_transaction_error_is_reraised(self):
        """Should re-raise non-transaction errors without recovery."""
        from intric.worker.crawl.recovery import execute_with_recovery

        async def failing_op(session):
            raise ValueError("Not a transaction error")

        # Mock session for session-per-operation pattern
        mock_session = MagicMock()
        mock_session.begin = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mock_sessionmanager = MagicMock()
        mock_sessionmanager.create_session = MagicMock(return_value=mock_session)

        with patch("intric.database.database.sessionmanager", mock_sessionmanager):
            with pytest.raises(ValueError, match="Not a transaction error"):
                await execute_with_recovery(
                    operation_name="test_op",
                    operation=failing_op,
                )

        # Verify rollback was called on error
        mock_session.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_transaction_error_triggers_recovery(self):
        """Should trigger recovery on transaction error and retry."""
        from intric.worker.crawl.recovery import execute_with_recovery

        call_count = 0

        async def op_fails_then_succeeds(session):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PendingRollbackError("First call fails")
            return "success on retry"

        # Mock primary session (fails on first call)
        primary_session = MagicMock()
        primary_session.begin = AsyncMock()
        primary_session.rollback = AsyncMock()
        primary_session.close = AsyncMock()

        # Mock retry session (succeeds)
        retry_session = MagicMock()
        retry_session.begin = AsyncMock()
        retry_session.commit = AsyncMock()
        retry_session.close = AsyncMock()

        # Return primary first, then retry
        mock_sessionmanager = MagicMock()
        mock_sessionmanager.create_session = MagicMock(
            side_effect=[primary_session, retry_session]
        )

        with patch("intric.database.database.sessionmanager", mock_sessionmanager):
            result = await execute_with_recovery(
                operation_name="test_op",
                operation=op_fails_then_succeeds,
            )

        assert result == "success on retry"
        assert call_count == 2
        # Verify both sessions were created
        assert mock_sessionmanager.create_session.call_count == 2
        # Verify retry session was committed and closed
        retry_session.commit.assert_called_once()
        retry_session.close.assert_called_once()


class TestResetTenantRetryDelay:
    """Tests for reset_tenant_retry_delay function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_redis_is_none(self):
        """Should return None when Redis client is None."""
        from intric.worker.crawl.recovery import reset_tenant_retry_delay

        # Should not raise
        result = await reset_tenant_retry_delay(tenant_id=uuid4(), redis_client=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_deletes_backoff_key(self):
        """Should delete the tenant backoff key."""
        from intric.worker.crawl.recovery import reset_tenant_retry_delay

        mock_redis = MagicMock()
        mock_redis.delete = AsyncMock()

        tenant_id = uuid4()

        await reset_tenant_retry_delay(tenant_id=tenant_id, redis_client=mock_redis)

        expected_key = f"tenant:{tenant_id}:limiter_backoff"
        mock_redis.delete.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_swallows_redis_exceptions(self):
        """Should swallow Redis exceptions (best-effort cleanup)."""
        from intric.worker.crawl.recovery import reset_tenant_retry_delay

        mock_redis = MagicMock()
        mock_redis.delete = AsyncMock(side_effect=Exception("Redis error"))

        # Should not raise
        await reset_tenant_retry_delay(tenant_id=uuid4(), redis_client=mock_redis)
