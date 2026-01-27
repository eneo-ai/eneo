"""Tests for SyncLog entity and its computed properties."""

import unittest
from datetime import datetime, timedelta
from uuid import uuid4

from intric.integration.domain.entities.sync_log import SyncLog


class TestSyncLog(unittest.TestCase):
    """Test SyncLog entity properties and computed fields."""

    def setUp(self):
        """Set up test fixtures."""
        self.integration_knowledge_id = uuid4()
        self.sync_log_id = uuid4()
        self.now = datetime.utcnow()

    def test_sync_log_creation(self):
        """Test creating a SyncLog entity."""
        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="full",
            status="success",
            started_at=self.now,
            completed_at=self.now + timedelta(seconds=300),
            created_at=self.now,
        )

        self.assertEqual(log.id, self.sync_log_id)
        self.assertEqual(log.integration_knowledge_id, self.integration_knowledge_id)
        self.assertEqual(log.sync_type, "full")
        self.assertEqual(log.status, "success")

    def test_sync_log_with_metadata(self):
        """Test SyncLog with metadata."""
        metadata = {
            "files_processed": 25,
            "files_deleted": 3,
            "pages_processed": 5,
            "folders_processed": 2,
            "skipped_items": 1,
        }
        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="delta",
            status="success",
            metadata=metadata,
            started_at=self.now,
            completed_at=self.now + timedelta(seconds=120),
            created_at=self.now,
        )

        self.assertEqual(log.files_processed, 25)
        self.assertEqual(log.files_deleted, 3)
        self.assertEqual(log.pages_processed, 5)
        self.assertEqual(log.folders_processed, 2)
        self.assertEqual(log.skipped_items, 1)

    def test_files_processed_defaults_to_zero(self):
        """Test that files_processed defaults to 0 when not in metadata."""
        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="full",
            status="success",
            metadata={},
            started_at=self.now,
            created_at=self.now,
        )

        self.assertEqual(log.files_processed, 0)

    def test_files_deleted_defaults_to_zero(self):
        """Test that files_deleted defaults to 0 when not in metadata."""
        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="full",
            status="success",
            metadata=None,
            started_at=self.now,
            created_at=self.now,
        )

        self.assertEqual(log.files_deleted, 0)

    def test_duration_seconds_calculation(self):
        """Test duration_seconds computed field."""
        started = self.now
        completed = self.now + timedelta(seconds=300)

        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="full",
            status="success",
            started_at=started,
            completed_at=completed,
            created_at=self.now,
        )

        self.assertEqual(log.duration_seconds, 300.0)

    def test_duration_seconds_is_none_when_not_completed(self):
        """Test duration_seconds is None when sync is still in progress."""
        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="full",
            status="in_progress",
            started_at=self.now,
            completed_at=None,
            created_at=self.now,
        )

        self.assertIsNone(log.duration_seconds)

    def test_total_items_processed_sum(self):
        """Test total_items_processed sums all item types."""
        metadata = {
            "files_processed": 10,
            "pages_processed": 5,
            "folders_processed": 3,
            "files_deleted": 2,  # Not counted in total
            "skipped_items": 1,  # Not counted in total
        }
        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="delta",
            status="success",
            metadata=metadata,
            started_at=self.now,
            completed_at=self.now + timedelta(seconds=60),
            created_at=self.now,
        )

        # Should sum: files_processed + pages_processed + folders_processed
        self.assertEqual(log.total_items_processed, 18)

    def test_total_items_processed_with_missing_fields(self):
        """Test total_items_processed when some metadata fields are missing."""
        metadata = {
            "files_processed": 10,
            # pages_processed missing
            "folders_processed": 3,
        }
        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="full",
            status="success",
            metadata=metadata,
            started_at=self.now,
            completed_at=self.now + timedelta(seconds=120),
            created_at=self.now,
        )

        # Should sum what's available: 10 + 0 + 3
        self.assertEqual(log.total_items_processed, 13)

    def test_sync_log_with_error(self):
        """Test SyncLog with error status and message."""
        error_msg = "SharePoint API returned 401 Unauthorized"
        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="delta",
            status="error",
            error_message=error_msg,
            started_at=self.now,
            completed_at=self.now + timedelta(seconds=30),
            created_at=self.now,
        )

        self.assertEqual(log.status, "error")
        self.assertEqual(log.error_message, error_msg)

    def test_sync_log_in_progress_status(self):
        """Test SyncLog with in_progress status."""
        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="full",
            status="in_progress",
            started_at=self.now,
            completed_at=None,
            created_at=self.now,
        )

        self.assertEqual(log.status, "in_progress")
        self.assertIsNone(log.completed_at)
        self.assertIsNone(log.duration_seconds)

    def test_pages_processed_defaults_to_zero(self):
        """Test pages_processed defaults to 0."""
        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="full",
            status="success",
            metadata={},
            started_at=self.now,
            created_at=self.now,
        )

        self.assertEqual(log.pages_processed, 0)

    def test_folders_processed_defaults_to_zero(self):
        """Test folders_processed defaults to 0."""
        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="full",
            status="success",
            metadata=None,
            started_at=self.now,
            created_at=self.now,
        )

        self.assertEqual(log.folders_processed, 0)

    def test_skipped_items_defaults_to_zero(self):
        """Test skipped_items defaults to 0."""
        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="delta",
            status="success",
            metadata={"files_processed": 5},
            started_at=self.now,
            created_at=self.now,
        )

        self.assertEqual(log.skipped_items, 0)

    def test_duration_seconds_with_fractional_seconds(self):
        """Test duration_seconds preserves fractional seconds."""
        started = self.now
        completed = self.now + timedelta(seconds=123, milliseconds=456)

        log = SyncLog(
            id=self.sync_log_id,
            integration_knowledge_id=self.integration_knowledge_id,
            sync_type="full",
            status="success",
            started_at=started,
            completed_at=completed,
            created_at=self.now,
        )

        # Should be ~123.456 seconds
        self.assertGreater(log.duration_seconds, 123)
        self.assertLess(log.duration_seconds, 124)


if __name__ == "__main__":
    unittest.main()
