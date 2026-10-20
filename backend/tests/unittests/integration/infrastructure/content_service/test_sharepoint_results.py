"""Sync counts and how a sync's result reads (sharepoint_results)."""

import pytest

from eneo.integration.infrastructure.content_service import (
    sharepoint_results as sync_results,
)


class TestInitializeStats:
    """Tests for _initialize_stats method."""

    def test_returns_dict_with_all_stat_keys(self):
        """Returns dictionary with all required stat keys."""
        stats = sync_results.initialize_stats()

        assert "files_processed" in stats
        assert "files_deleted" in stats
        assert "out_of_scope_deleted" in stats
        assert "folders_processed" in stats
        assert "pages_processed" in stats
        assert "skipped_items" in stats

    def test_all_stats_start_at_zero(self):
        """All stats are initialized to zero."""
        stats = sync_results.initialize_stats()

        assert stats["files_processed"] == 0
        assert stats["files_deleted"] == 0
        assert stats["out_of_scope_deleted"] == 0
        assert stats["folders_processed"] == 0
        assert stats["pages_processed"] == 0
        assert stats["skipped_items"] == 0


class TestBuildSummaryStats:
    """Tests for _build_summary_stats method."""

    def test_builds_summary_from_stats(self):
        """Builds summary dictionary from stats."""
        stats = {
            "files_processed": 5,
            "files_deleted": 2,
            "out_of_scope_deleted": 1,
            "folders_processed": 3,
            "pages_processed": 1,
            "skipped_items": 4,
        }

        summary = sync_results.build_summary_stats(stats)

        assert summary["files_processed"] == 5
        assert summary["files_deleted"] == 2
        assert summary["out_of_scope_deleted"] == 1
        assert summary["folders_processed"] == 3
        assert summary["pages_processed"] == 1
        assert summary["skipped_items"] == 4

    def test_handles_missing_keys_with_defaults(self):
        """Uses 0 for missing keys."""
        stats = {"files_processed": 10}

        summary = sync_results.build_summary_stats(stats)

        assert summary["files_processed"] == 10
        assert summary["files_deleted"] == 0
        assert summary["out_of_scope_deleted"] == 0
        assert summary["folders_processed"] == 0

    @pytest.mark.parametrize(
        ("detail_count", "truncated"), [(50, False), (51, True)], ids=["cap", "over"]
    )
    def test_caps_details_but_keeps_true_skipped_count(self, detail_count, truncated):
        stats = sync_results.initialize_stats()
        stats["skipped_items"] = detail_count
        stats["skipped_details"] = [
            {"file": f"f{i}", "reason": "Unsupported"} for i in range(detail_count)
        ]

        summary = sync_results.build_summary_stats(stats)

        assert len(summary["skipped_details"]) == 50
        assert summary["skipped_total"] == detail_count
        assert summary["skipped_truncated"] is truncated

    @pytest.mark.parametrize(
        ("change_count", "truncated"), [(50, False), (51, True)], ids=["cap", "over"]
    )
    def test_caps_changed_details_but_keeps_every_change_in_the_total(
        self, change_count, truncated
    ):
        stats = sync_results.initialize_stats()
        for i in range(change_count):
            sync_results.count_outcome(stats, "added", f"f{i}.docx")

        summary = sync_results.build_summary_stats(stats)

        assert summary["changed_details"] == [
            {"file": f"f{i}.docx", "change": "added"} for i in range(50)
        ]
        assert summary["changed_total"] == change_count
        assert summary["changed_truncated"] is truncated

    def test_carries_reconcile_warning_only_when_present(self):
        stats = sync_results.initialize_stats()
        assert "reconcile_warning" not in sync_results.build_summary_stats(stats)
        stats["reconcile_warning"] = "Orphan cleanup skipped"
        assert (
            sync_results.build_summary_stats(stats)["reconcile_warning"]
            == "Orphan cleanup skipped"
        )


class TestFormatSummaryForJob:
    """Tests for _format_summary_for_job method."""

    def test_formats_files_processed(self):
        """Formats files processed count."""
        summary = {
            "files_processed": 5,
            "files_deleted": 0,
            "pages_processed": 0,
            "folders_processed": 0,
            "skipped_items": 0,
        }

        result = sync_results.format_summary_for_job(summary)

        assert "Imported 5 files" in result

    def test_formats_single_file(self):
        """Uses singular 'file' for count of 1."""
        summary = {
            "files_processed": 1,
            "files_deleted": 0,
            "pages_processed": 0,
            "folders_processed": 0,
            "skipped_items": 0,
        }

        result = sync_results.format_summary_for_job(summary)

        assert "1 file" in result
        assert "1 files" not in result

    def test_formats_deleted_files(self):
        """Formats deleted files count."""
        summary = {
            "files_processed": 0,
            "files_deleted": 3,
            "pages_processed": 0,
            "folders_processed": 0,
            "skipped_items": 0,
        }

        result = sync_results.format_summary_for_job(summary)

        assert "3 deleted files" in result

    def test_formats_pages_processed(self):
        """Formats pages processed count."""
        summary = {
            "files_processed": 0,
            "files_deleted": 0,
            "pages_processed": 2,
            "folders_processed": 0,
            "skipped_items": 0,
        }

        result = sync_results.format_summary_for_job(summary)

        assert "2 pages" in result

    def test_includes_folders_scanned(self):
        """Includes folders scanned in parentheses."""
        summary = {
            "files_processed": 5,
            "files_deleted": 0,
            "pages_processed": 0,
            "folders_processed": 10,
            "skipped_items": 0,
        }

        result = sync_results.format_summary_for_job(summary)

        assert "10 folders scanned" in result

    def test_includes_skipped_items(self):
        """Includes skipped items in parentheses."""
        summary = {
            "files_processed": 5,
            "files_deleted": 0,
            "pages_processed": 0,
            "folders_processed": 0,
            "skipped_items": 3,
        }

        result = sync_results.format_summary_for_job(summary)

        assert "3 items skipped" in result

    def test_handles_zero_files(self):
        """Shows '0 files' when nothing processed."""
        summary = {
            "files_processed": 0,
            "files_deleted": 0,
            "pages_processed": 0,
            "folders_processed": 0,
            "skipped_items": 0,
        }

        result = sync_results.format_summary_for_job(summary)

        assert "Imported 0 files" in result

    def test_handles_none_values(self):
        """Handles None values in summary."""
        summary = {
            "files_processed": None,
            "files_deleted": None,
            "pages_processed": None,
            "folders_processed": None,
            "skipped_items": None,
        }

        result = sync_results.format_summary_for_job(summary)

        assert "Imported 0 files" in result
