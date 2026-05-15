"""Unit tests for FileNamePipeline filename truncation logic."""

from types import SimpleNamespace

import pytest
from scrapy.exceptions import StopDownload
from twisted.internet.defer import CancelledError
from twisted.python.failure import Failure

from intric.crawler.pipelines import (
    FILE_SIZE_SKIP_RECORDED_META_KEY,
    FILE_STATUS_TOO_LARGE,
    FILE_TOO_LARGE_DOWNLOAD_LIMIT_STAT,
    FILE_TOO_LARGE_SKIPPED_SAMPLES_STAT,
    FILE_TOO_LARGE_SKIPPED_STAT,
    INTRIC_FILE_DOWNLOAD_META_KEY,
    MAX_FILENAME_BYTES,
    FileNamePipeline,
    FileSizeLimitStatsExtension,
    _is_file_download_too_large_failure,
    _truncate_filename,
)


class TestTruncateFilename:
    """Test the _truncate_filename helper function."""

    def test_short_filename_unchanged(self):
        """Short filenames should pass through unchanged (but decoded)."""
        result = _truncate_filename("document.pdf")
        assert result == "document.pdf"
        assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES

    def test_url_encoded_filename_decoded(self):
        """URL-encoded filenames should be decoded."""
        # Swedish characters
        result = _truncate_filename("f%C3%B6r-att-f%C3%A5.pdf")
        assert result == "för-att-få.pdf"
        assert "%C3" not in result  # No URL encoding in result

    def test_arabic_url_encoded_filename_decoded(self):
        """Arabic URL-encoded filenames should be decoded."""
        # The actual problematic filename from production
        url_encoded = "Hit-kan-du-vanda-dig-%D9%8A%D9%85%D9%83%D9%86%D9%83-%D8%A7%D9%84%D8%AA%D9%88%D8%AC%D9%87-%D8%A7%D9%84%D9%89-%D9%87%D8%B0%D9%87-%D8%A7%D9%84%D8%A5%D8%AF%D8%A7%D8%B1%D8%A7%D8%AA-%D9%84%D9%84%D8%AD%D8%B5%D9%88%D9%84-%D8%B9%D9%84%D9%89-%D9%85%D8%B3%D8%A7%D8%B9%D8%AF%D8%A9.pdf"
        result = _truncate_filename(url_encoded)

        # Should be decoded Arabic
        assert "يمكنك" in result  # Arabic text present
        assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES
        assert result.endswith(".pdf")

    def test_farsi_url_encoded_filename_decoded(self):
        """Farsi URL-encoded filenames should be decoded."""
        # The other problematic filename (Swedish + Farsi)
        url_encoded = "Hit-kan-du-v%C3%A4nda-dig-f%C3%B6r-att-f%C3%A5-hj%C3%A4lp-%D8%A8%D8%B1%D8%A7%DB%8C-%D8%AF%D8%B1%DB%8C%D8%A7%D9%81%D8%AA-%DA%A9%D9%85%DA%A9-%D9%85%DB%8C-%D8%AA%D9%88%D8%A7%D9%86%DB%8C%D8%AF-%D8%A8%D9%87-%D8%A7%DB%8C%D9%86%D8%AC%D8%A7-%D9%85%D8%B1%D8%A7%D8%AC%D8%B9%D9%87-%DA%A9%D9%86%DB%8C%D8%AF..pdf"
        result = _truncate_filename(url_encoded)

        # Should be decoded
        assert "برای" in result  # Farsi text present
        assert "vända" in result  # Swedish text present
        assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES

    def test_very_long_filename_truncated(self):
        """Filenames exceeding max bytes should be truncated with hash."""
        long_name = "a" * 250 + ".pdf"
        result = _truncate_filename(long_name)

        assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES
        assert result.endswith(".pdf")  # Extension preserved
        assert "_" in result  # Has hash separator
        # Hash is 8 chars
        hash_part = result.split("_")[-1].replace(".pdf", "")
        assert len(hash_part) == 8

    def test_truncation_preserves_uniqueness(self):
        """Different long filenames should produce different truncated names."""
        long1 = "a" * 250 + ".pdf"
        long2 = "b" * 250 + ".pdf"

        result1 = _truncate_filename(long1)
        result2 = _truncate_filename(long2)

        assert result1 != result2  # Different hashes

    def test_empty_filename(self):
        """Empty filename should return 'unnamed_file'."""
        assert _truncate_filename("") == "unnamed_file"
        assert _truncate_filename(None) == "unnamed_file"

    def test_no_extension(self):
        """Filename without extension should work."""
        long_name = "a" * 250
        result = _truncate_filename(long_name)

        assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES
        assert "_" in result  # Has hash

    def test_multibyte_truncation_safe(self):
        """Truncation should not split multi-byte characters."""
        # Create a filename with multi-byte chars that needs truncation
        # Each Arabic char is 2-4 bytes
        arabic_name = "مستند-" * 50 + ".pdf"  # Much longer than 200 bytes
        result = _truncate_filename(arabic_name)

        # Should not raise UnicodeDecodeError
        assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES
        # Should be valid UTF-8 (no truncated chars)
        result.encode("utf-8").decode("utf-8")  # Should not raise

    def test_exact_boundary(self):
        """Filename exactly at boundary should not be truncated."""
        # Create filename exactly at MAX_FILENAME_BYTES
        extension = ".pdf"
        stem_length = MAX_FILENAME_BYTES - len(extension)
        exact_name = "a" * stem_length + extension

        assert len(exact_name.encode("utf-8")) == MAX_FILENAME_BYTES
        result = _truncate_filename(exact_name)
        assert result == exact_name  # Unchanged

    def test_one_over_boundary(self):
        """Filename one byte over boundary should be truncated."""
        extension = ".pdf"
        stem_length = MAX_FILENAME_BYTES - len(extension) + 1
        over_name = "a" * stem_length + extension

        assert len(over_name.encode("utf-8")) == MAX_FILENAME_BYTES + 1
        result = _truncate_filename(over_name)
        assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES
        assert "_" in result  # Has hash


class TestSecurityCases:
    """Security-focused tests for path traversal and injection prevention."""

    def test_directory_traversal_url_encoded(self):
        """URL-encoded directory traversal should be sanitized."""
        # %2F is URL-encoded forward slash
        result = _truncate_filename("%2Fetc%2Fpasswd")
        assert "/" not in result
        assert result == "_etc_passwd"

    def test_directory_traversal_double_dot(self):
        """Directory traversal with .. should be sanitized."""
        result = _truncate_filename("..%2F..%2Fetc%2Fpasswd")
        assert "/" not in result
        assert "\\" not in result
        assert ".._.._.." not in result or result == ".._.._.._etc_passwd"

    def test_forward_slash_sanitized(self):
        """Forward slashes should be replaced with underscores."""
        result = _truncate_filename("foo/bar/baz.pdf")
        assert "/" not in result
        assert result == "foo_bar_baz.pdf"

    def test_backslash_sanitized(self):
        """Backslashes (Windows paths) should be replaced with underscores."""
        result = _truncate_filename("foo\\bar\\baz.pdf")
        assert "\\" not in result
        assert result == "foo_bar_baz.pdf"

    def test_null_byte_removed(self):
        """Null bytes should be stripped from filenames."""
        # Null byte injection attempt
        result = _truncate_filename("file%00.pdf")
        assert "\0" not in result
        assert result == "file.pdf"

    def test_null_byte_in_middle(self):
        """Null bytes in the middle should be removed."""
        result = _truncate_filename("foo%00bar.pdf")
        assert "\0" not in result
        assert result == "foobar.pdf"

    def test_mixed_path_separators(self):
        """Mixed forward and back slashes should all be sanitized."""
        result = _truncate_filename("foo/bar\\baz/qux.pdf")
        assert "/" not in result
        assert "\\" not in result
        assert result == "foo_bar_baz_qux.pdf"


class TestEdgeCases:
    """Edge case tests for unusual inputs."""

    def test_very_long_extension(self):
        """Very long extension should be truncated."""
        # Create extension longer than 160 bytes (max_bytes - 40)
        long_ext = "." + "x" * 200
        filename = "file" + long_ext

        result = _truncate_filename(filename)
        assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES
        # Extension should be capped
        assert "_" in result  # Has hash

    def test_only_extension(self):
        """Filename that is only an extension should work."""
        result = _truncate_filename(".pdf")
        # stem is empty, so we get file_{hash}.pdf pattern
        assert result.endswith(".pdf")
        assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES

    def test_double_dots_in_filename(self):
        """Filename with double dots (like production error) should work."""
        # The Farsi filename had ".." before .pdf
        result = _truncate_filename("مراجعه-کنید..pdf")
        assert result.endswith(".pdf")
        # The ".." before extension gets treated as part of stem
        assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES

    def test_special_characters_preserved(self):
        """Non-path special characters should be preserved."""
        result = _truncate_filename("file-name_with (special) chars!.pdf")
        assert "(" in result
        assert ")" in result
        assert "!" in result

    def test_unicode_normalization_consistent(self):
        """Same logical filename should produce same result."""
        # These should all produce the same base output
        result1 = _truncate_filename("för.pdf")
        result2 = _truncate_filename("f%C3%B6r.pdf")  # URL encoded

        # Both should decode to the same result
        assert result1 == result2 == "för.pdf"

    def test_whitespace_preserved(self):
        """Whitespace in filenames should be preserved."""
        result = _truncate_filename("my file name.pdf")
        assert " " in result
        assert result == "my file name.pdf"

    def test_url_encoded_space(self):
        """URL-encoded spaces should be decoded."""
        result = _truncate_filename("my%20file.pdf")
        assert result == "my file.pdf"


class _Stats:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def inc_value(self, key: str, count: int = 1, spider: object = None) -> None:
        del spider
        current = self.values.get(key, 0)
        assert isinstance(current, int)
        self.values[key] = current + count

    def max_value(self, key: str, value: int, spider: object = None) -> None:
        del spider
        current = self.values.get(key, value)
        assert isinstance(current, int)
        self.values[key] = max(current, value)

    def get_value(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def set_value(self, key: str, value: object) -> None:
        self.values[key] = value


class TestFileSizeLimitStats:
    def test_headers_over_download_max_size_are_counted_and_stopped(self):
        stats = _Stats()
        spider = SimpleNamespace(crawler=SimpleNamespace(stats=stats))
        request = SimpleNamespace(url="https://example.com/large.pdf", meta={})
        request.meta[INTRIC_FILE_DOWNLOAD_META_KEY] = True
        extension = FileSizeLimitStatsExtension(download_max_size=10)

        with pytest.raises(StopDownload):
            extension.headers_received(
                headers=object(),
                body_length=11,
                request=request,
                spider=spider,
            )

        assert stats.values[FILE_TOO_LARGE_SKIPPED_STAT] == 1
        assert stats.values[f"file_status_count/{FILE_STATUS_TOO_LARGE}"] == 1
        assert stats.values[FILE_TOO_LARGE_DOWNLOAD_LIMIT_STAT] == 10
        assert stats.values[FILE_TOO_LARGE_SKIPPED_SAMPLES_STAT] == [
            {
                "url": "https://example.com/large.pdf",
                "observed_size_bytes": 11,
            }
        ]
        assert request.meta[FILE_SIZE_SKIP_RECORDED_META_KEY] is True

    def test_bytes_over_download_max_size_are_counted_and_stopped(self):
        stats = _Stats()
        spider = SimpleNamespace(crawler=SimpleNamespace(stats=stats))
        request = SimpleNamespace(url="https://example.com/large.pdf", meta={})
        request.meta[INTRIC_FILE_DOWNLOAD_META_KEY] = True
        extension = FileSizeLimitStatsExtension(download_max_size=10)

        extension.bytes_received(
            data=b"12345",
            request=request,
            spider=spider,
        )
        assert stats.values == {}

        with pytest.raises(StopDownload):
            extension.bytes_received(
                data=b"678901",
                request=request,
                spider=spider,
            )

        assert stats.values[FILE_TOO_LARGE_SKIPPED_STAT] == 1
        assert stats.values[f"file_status_count/{FILE_STATUS_TOO_LARGE}"] == 1
        assert stats.values[FILE_TOO_LARGE_SKIPPED_SAMPLES_STAT] == [
            {
                "url": "https://example.com/large.pdf",
                "observed_size_bytes": 11,
            }
        ]
        assert request.meta[FILE_SIZE_SKIP_RECORDED_META_KEY] is True

    def test_size_limit_signal_and_pipeline_share_status_without_double_counting(self):
        stats = _Stats()
        spider = SimpleNamespace(crawler=SimpleNamespace(stats=stats))
        request = SimpleNamespace(url="https://example.com/large.pdf", meta={})
        request.meta[INTRIC_FILE_DOWNLOAD_META_KEY] = True
        extension = FileSizeLimitStatsExtension(download_max_size=10)

        with pytest.raises(StopDownload) as stopped:
            extension.headers_received(
                headers=object(),
                body_length=11,
                request=request,
                spider=spider,
            )

        extension.bytes_received(
            data=b"still buffered",
            request=request,
            spider=spider,
        )
        pipeline = FileNamePipeline.__new__(FileNamePipeline)
        result = pipeline.media_failed(
            Failure(stopped.value),
            request,
            SimpleNamespace(spider=spider),
        )

        assert result == {
            "url": "https://example.com/large.pdf",
            "path": None,
            "checksum": None,
            "status": FILE_STATUS_TOO_LARGE,
        }
        assert stats.values[FILE_TOO_LARGE_SKIPPED_STAT] == 1
        assert stats.values[f"file_status_count/{FILE_STATUS_TOO_LARGE}"] == 1
        assert stats.values[FILE_TOO_LARGE_SKIPPED_SAMPLES_STAT] == [
            {
                "url": "https://example.com/large.pdf",
                "observed_size_bytes": 11,
            }
        ]

    def test_unmarked_requests_are_left_to_scrapy(self):
        stats = _Stats()
        spider = SimpleNamespace(crawler=SimpleNamespace(stats=stats))
        request = SimpleNamespace(url="https://example.com/large.pdf", meta={})
        extension = FileSizeLimitStatsExtension(download_max_size=10)

        extension.headers_received(
            headers=object(),
            body_length=11,
            request=request,
            spider=spider,
        )

        assert stats.values == {}

    def test_scrapy_download_max_size_failures_are_recognized(self):
        failure = Failure(
            CancelledError(
                "expected response size (11) larger than download max size (10)"
            )
        )

        assert _is_file_download_too_large_failure(failure) is True

    def test_native_scrapy_download_max_size_failure_records_sample(self):
        stats = _Stats()
        settings = SimpleNamespace(getint=lambda key: 10)
        spider = SimpleNamespace(
            crawler=SimpleNamespace(stats=stats, settings=settings)
        )
        request = SimpleNamespace(url="https://example.com/native.pdf", meta={})
        request.meta[INTRIC_FILE_DOWNLOAD_META_KEY] = True
        pipeline = FileNamePipeline.__new__(FileNamePipeline)

        result = pipeline.media_failed(
            Failure(
                CancelledError(
                    "expected response size (19) larger than download max size (10)"
                )
            ),
            request,
            SimpleNamespace(spider=spider),
        )

        assert result == {
            "url": "https://example.com/native.pdf",
            "path": None,
            "checksum": None,
            "status": FILE_STATUS_TOO_LARGE,
        }
        assert stats.values[FILE_TOO_LARGE_DOWNLOAD_LIMIT_STAT] == 10
        assert stats.values[FILE_TOO_LARGE_SKIPPED_SAMPLES_STAT] == [
            {
                "url": "https://example.com/native.pdf",
                "observed_size_bytes": 19,
            }
        ]

    def test_too_large_file_samples_keep_first_five_in_insertion_order(self):
        stats = _Stats()
        spider = SimpleNamespace(crawler=SimpleNamespace(stats=stats))
        extension = FileSizeLimitStatsExtension(download_max_size=10)

        for index in range(50):
            request = SimpleNamespace(
                url=f"https://example.com/{index}.pdf",
                meta={INTRIC_FILE_DOWNLOAD_META_KEY: True},
            )
            with pytest.raises(StopDownload):
                extension.headers_received(
                    headers=object(),
                    body_length=11 + index,
                    request=request,
                    spider=spider,
                )

        assert stats.values[FILE_TOO_LARGE_SKIPPED_STAT] == 50
        assert stats.values[FILE_TOO_LARGE_SKIPPED_SAMPLES_STAT] == [
            {
                "url": f"https://example.com/{index}.pdf",
                "observed_size_bytes": 11 + index,
            }
            for index in range(5)
        ]
