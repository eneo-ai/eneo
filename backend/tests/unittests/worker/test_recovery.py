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
        from intric.worker.crawl import (
            calculate_exponential_backoff,
            execute_with_recovery,
            is_invalid_transaction_error,
            is_invalid_transaction_error_msg,
            recover_session,
            reset_tenant_retry_delay,
            update_job_retry_stats,
        )

        assert callable(execute_with_recovery)
        assert callable(recover_session)
        assert callable(is_invalid_transaction_error)
        assert callable(is_invalid_transaction_error_msg)
        assert callable(calculate_exponential_backoff)
        assert callable(reset_tenant_retry_delay)
        assert callable(update_job_retry_stats)

    def test_import_directly_from_recovery_module(self):
        """Recovery functions should be importable directly from recovery module."""
        from intric.worker.crawl.recovery import (
            execute_with_recovery,
            recover_session,
        )

        assert callable(execute_with_recovery)
        assert callable(recover_session)


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

        assert is_invalid_transaction_error_msg("another operation is in progress") is True

    def test_case_insensitive(self):
        """Should be case insensitive."""
        from intric.worker.crawl.recovery import is_invalid_transaction_error_msg

        assert is_invalid_transaction_error_msg("INVALID TRANSACTION") is True
        assert is_invalid_transaction_error_msg("Pending Rollback") is True


class TestRecoverSession:
    """Tests for recover_session function.

    NOTE: sessionmanager is imported INSIDE recover_session() to avoid circular imports.
    We must patch at the source module: intric.database.database.sessionmanager
    """

    @pytest.mark.asyncio
    async def test_creates_new_session_from_sessionmanager(self):
        """Should create a fresh session via sessionmanager.create_session()."""
        from intric.worker.crawl.recovery import recover_session

        # Mock old session
        old_session = MagicMock()
        old_session.rollback = AsyncMock()
        old_session.close = AsyncMock()

        # Mock new session
        new_session = MagicMock()
        new_session.begin = AsyncMock()

        # Mock container
        mock_container = MagicMock()
        mock_container.session = MagicMock()
        mock_container.text_processor = MagicMock(return_value="new_uploader")

        # Mock sessionmanager - patch at source module where it's imported FROM
        mock_sessionmanager = MagicMock()
        mock_sessionmanager.create_session = MagicMock(return_value=new_session)

        created_sessions = []
        logger = MagicMock()

        with patch(
            "intric.database.database.sessionmanager", mock_sessionmanager
        ):
            result_session, result_uploader = await recover_session(
                container=mock_container,
                old_session=old_session,
                created_sessions=created_sessions,
                logger_instance=logger,
            )

        # Verify new session was created
        mock_sessionmanager.create_session.assert_called_once()
        assert result_session is new_session
        assert result_uploader == "new_uploader"

        # Verify session was tracked for cleanup
        assert new_session in created_sessions

        # Verify container was updated
        mock_container.session.override.assert_called_once()

        # Verify transaction was started
        new_session.begin.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleans_up_old_session_with_timeout(self):
        """Should clean up old session with rollback and close timeouts."""
        from intric.worker.crawl.recovery import recover_session

        # Mock old session
        old_session = MagicMock()
        old_session.expunge_all = MagicMock()
        old_session.rollback = AsyncMock()
        old_session.close = AsyncMock()

        # Mock new session
        new_session = MagicMock()
        new_session.begin = AsyncMock()

        # Mock container
        mock_container = MagicMock()
        mock_container.text_processor = MagicMock(return_value="uploader")

        # Mock sessionmanager - patch at source module
        mock_sessionmanager = MagicMock()
        mock_sessionmanager.create_session = MagicMock(return_value=new_session)

        created_sessions = []
        logger = MagicMock()

        with patch(
            "intric.database.database.sessionmanager", mock_sessionmanager
        ):
            await recover_session(
                container=mock_container,
                old_session=old_session,
                created_sessions=created_sessions,
                logger_instance=logger,
            )

        # Verify cleanup sequence
        old_session.expunge_all.assert_called_once()
        old_session.rollback.assert_called_once()
        old_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_none_old_session(self):
        """Should handle None old_session gracefully."""
        from intric.worker.crawl.recovery import recover_session

        # Mock new session
        new_session = MagicMock()
        new_session.begin = AsyncMock()

        # Mock container
        mock_container = MagicMock()
        mock_container.text_processor = MagicMock(return_value="uploader")

        # Mock sessionmanager - patch at source module
        mock_sessionmanager = MagicMock()
        mock_sessionmanager.create_session = MagicMock(return_value=new_session)

        created_sessions = []
        logger = MagicMock()

        with patch(
            "intric.database.database.sessionmanager", mock_sessionmanager
        ):
            result_session, _ = await recover_session(
                container=mock_container,
                old_session=None,
                created_sessions=created_sessions,
                logger_instance=logger,
            )

        # Should still create new session
        assert result_session is new_session


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

        session_holder = {"session": MagicMock(), "uploader": MagicMock()}
        container = MagicMock()
        created_sessions = []

        # Mock session for session-per-operation pattern
        mock_session = MagicMock()
        mock_session.begin = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.close = AsyncMock()

        mock_sessionmanager = MagicMock()
        mock_sessionmanager.create_session = MagicMock(return_value=mock_session)

        with patch(
            "intric.database.database.sessionmanager", mock_sessionmanager
        ):
            result = await execute_with_recovery(
                container=container,
                session_holder=session_holder,
                created_sessions=created_sessions,
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

        session_holder = {"session": MagicMock(), "uploader": MagicMock()}
        container = MagicMock()
        created_sessions = []

        # Mock session for session-per-operation pattern
        mock_session = MagicMock()
        mock_session.begin = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mock_sessionmanager = MagicMock()
        mock_sessionmanager.create_session = MagicMock(return_value=mock_session)

        with patch(
            "intric.database.database.sessionmanager", mock_sessionmanager
        ):
            with pytest.raises(ValueError, match="Not a transaction error"):
                await execute_with_recovery(
                    container=container,
                    session_holder=session_holder,
                    created_sessions=created_sessions,
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

        session_holder = {"session": MagicMock(), "uploader": MagicMock()}
        mock_container = MagicMock()
        created_sessions = []

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

        with patch(
            "intric.database.database.sessionmanager", mock_sessionmanager
        ):
            result = await execute_with_recovery(
                container=mock_container,
                session_holder=session_holder,
                created_sessions=created_sessions,
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
        result = await reset_tenant_retry_delay(
            tenant_id=uuid4(), redis_client=None
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_deletes_backoff_key(self):
        """Should delete the tenant backoff key."""
        from intric.worker.crawl.recovery import reset_tenant_retry_delay

        mock_redis = MagicMock()
        mock_redis.delete = AsyncMock()

        tenant_id = uuid4()

        await reset_tenant_retry_delay(
            tenant_id=tenant_id, redis_client=mock_redis
        )

        expected_key = f"tenant:{tenant_id}:limiter_backoff"
        mock_redis.delete.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_swallows_redis_exceptions(self):
        """Should swallow Redis exceptions (best-effort cleanup)."""
        from intric.worker.crawl.recovery import reset_tenant_retry_delay

        mock_redis = MagicMock()
        mock_redis.delete = AsyncMock(side_effect=Exception("Redis error"))

        # Should not raise
        await reset_tenant_retry_delay(
            tenant_id=uuid4(), redis_client=mock_redis
        )


class TestSessionHolderTypedDict:
    """Tests for SessionHolder TypedDict."""

    def test_session_holder_can_be_created(self):
        """SessionHolder should be creatable as a dict."""
        from intric.worker.crawl.recovery import SessionHolder

        holder: SessionHolder = {
            "session": MagicMock(),
            "uploader": MagicMock(),
        }

        assert "session" in holder
        assert "uploader" in holder

    def test_session_holder_is_mutable(self):
        """SessionHolder should be mutable for recovery updates."""
        from intric.worker.crawl.recovery import SessionHolder

        holder: SessionHolder = {
            "session": "old_session",
            "uploader": "old_uploader",
        }

        holder["session"] = "new_session"
        holder["uploader"] = "new_uploader"

        assert holder["session"] == "new_session"
        assert holder["uploader"] == "new_uploader"
