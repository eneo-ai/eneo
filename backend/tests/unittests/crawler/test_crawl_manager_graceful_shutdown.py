"""Unit tests for CrawlManager graceful shutdown and heartbeat during crawl.

Tests the CrawlManager pattern that ensures:
1. Scrapy crawlers are explicitly stopped on timeout (no resource leak)
2. wait_for_completion() ensures crawler has flushed writes before file read
3. Heartbeat runs concurrently during Scrapy crawl (not just page processing)
4. CrawlShutdownError is raised if shutdown fails

Run with: pytest tests/unittests/crawler/test_crawl_manager_graceful_shutdown.py -v
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import crochet
import pytest

# Setup crochet BEFORE importing Crawler
crochet.setup()

from intric.crawler.crawler import (
    Crawler,
    CrawlManager,
    CrawlShutdownError,
)
from intric.main.exceptions import CrawlTimeoutError


class TestCrawlManagerLifecycle:
    """Tests for CrawlManager start/stop/wait_for_completion lifecycle."""

    def test_crawl_manager_initializes_clean_state(self):
        """CrawlManager initializes with None crawler and event not set."""
        manager = CrawlManager()
        assert manager._crawler is None
        assert manager._crawl_deferred is None
        assert manager._runner is None
        assert not manager._completion_event.is_set()

    def test_wait_for_completion_returns_true_when_event_set(self):
        """wait_for_completion returns True when completion event is set."""
        manager = CrawlManager()
        manager._completion_event.set()

        result = manager.wait_for_completion(timeout=1.0)
        assert result is True

    def test_wait_for_completion_returns_false_on_timeout(self):
        """wait_for_completion returns False when timeout expires."""
        manager = CrawlManager()
        # Event not set - should timeout

        start = time.time()
        result = manager.wait_for_completion(timeout=0.1)
        elapsed = time.time() - start

        assert result is False
        assert elapsed >= 0.1
        assert elapsed < 0.5  # Should not take much longer than timeout

    def test_stop_crawl_is_noop_when_no_crawler(self):
        """stop_crawl() is safe to call when no crawler exists."""
        manager = CrawlManager()
        # Should not raise
        manager.stop_crawl()


class TestCrawlManagerStopBehavior:
    """Tests for CrawlManager.stop_crawl() behavior."""

    def test_stop_crawl_calls_crawler_stop_when_crawling(self):
        """stop_crawl() calls crawler.stop() when crawler is actively crawling."""
        manager = CrawlManager()

        # Mock a crawler that's actively crawling
        mock_crawler = MagicMock()
        mock_crawler.crawling = True
        manager._crawler = mock_crawler

        # Call stop_crawl (runs in reactor via crochet)
        manager.stop_crawl()

        # Give reactor time to process
        time.sleep(0.1)

        # Verify stop was called
        mock_crawler.stop.assert_called_once()

    def test_stop_crawl_noop_when_not_crawling(self):
        """stop_crawl() is noop when crawler.crawling is False."""
        manager = CrawlManager()

        mock_crawler = MagicMock()
        mock_crawler.crawling = False
        manager._crawler = mock_crawler

        manager.stop_crawl()
        time.sleep(0.1)

        # stop() should NOT be called when not crawling
        mock_crawler.stop.assert_not_called()


class TestCrawlShutdownError:
    """Tests for CrawlShutdownError exception."""

    def test_shutdown_error_contains_url_and_timeout(self):
        """CrawlShutdownError message includes URL and shutdown timeout."""
        error = CrawlShutdownError(
            url="https://example.com/test",
            shutdown_timeout=10.0,
        )

        assert "https://example.com/test" in str(error)
        assert "10.0s" in str(error)
        assert "failed to shut down" in str(error).lower()

    def test_shutdown_error_attributes(self):
        """CrawlShutdownError stores url and timeout as attributes."""
        error = CrawlShutdownError(
            url="https://example.com",
            shutdown_timeout=5.0,
        )

        assert error.url == "https://example.com"
        assert error.shutdown_timeout == 5.0


class TestRunCrawlWithTimeoutGracefulShutdown:
    """Tests for _run_crawl_with_timeout graceful shutdown behavior."""

    @pytest.mark.asyncio
    async def test_timeout_triggers_stop_crawl(self):
        """When timeout occurs, stop_crawl() is called on CrawlManager."""
        stop_crawl_called = threading.Event()
        wait_for_completion_called = threading.Event()

        class MockCrawlManager:
            def __init__(self):
                self._crawler = None
                self._completion_event = threading.Event()

            def start_crawl(self, *args, **kwargs):
                # Return a mock EventualResult that will timeout
                mock_result = MagicMock()
                mock_result.wait = MagicMock(side_effect=crochet.TimeoutError("timeout"))
                return mock_result

            def stop_crawl(self, reason="timeout"):
                stop_crawl_called.set()

            def wait_for_completion(self, timeout=10.0):
                wait_for_completion_called.set()
                return True  # Simulate successful shutdown

        with patch("intric.crawler.crawler.CrawlManager", MockCrawlManager):
            with pytest.raises(CrawlTimeoutError):
                await Crawler._run_crawl_with_timeout(
                    url="https://example.com",
                    download_files=False,
                    filepath="/tmp/test.jsonl",
                    files_dir="/tmp/files",
                    max_length=1,
                )

        assert stop_crawl_called.is_set(), "stop_crawl() should be called on timeout"
        assert wait_for_completion_called.is_set(), "wait_for_completion() should be called"

    @pytest.mark.asyncio
    async def test_shutdown_failure_raises_error(self):
        """When wait_for_completion returns False, CrawlShutdownError is raised."""

        class MockCrawlManager:
            def __init__(self):
                self._crawler = None
                self._completion_event = threading.Event()

            def start_crawl(self, *args, **kwargs):
                mock_result = MagicMock()
                mock_result.wait = MagicMock(side_effect=crochet.TimeoutError("timeout"))
                return mock_result

            def stop_crawl(self, reason="timeout"):
                pass

            def wait_for_completion(self, timeout=10.0):
                return False  # Simulate shutdown failure

        with patch("intric.crawler.crawler.CrawlManager", MockCrawlManager):
            with pytest.raises(CrawlShutdownError) as exc_info:
                await Crawler._run_crawl_with_timeout(
                    url="https://example.com",
                    download_files=False,
                    filepath="/tmp/test.jsonl",
                    files_dir="/tmp/files",
                    max_length=1,
                )

        assert "https://example.com" in str(exc_info.value)


class TestHeartbeatDuringCrawl:
    """Tests for concurrent heartbeat during Scrapy crawl phase."""

    @pytest.mark.asyncio
    async def test_heartbeat_callback_called_during_crawl(self):
        """heartbeat_callback is invoked during the crawl execution."""
        heartbeat_calls = []

        async def mock_heartbeat():
            heartbeat_calls.append(time.time())

        class MockCrawlManager:
            def __init__(self):
                self._crawler = None
                self._completion_event = threading.Event()

            def start_crawl(self, *args, **kwargs):
                # Simulate a 0.5 second crawl
                mock_result = MagicMock()

                def slow_wait(timeout):
                    time.sleep(0.3)  # Simulate crawl taking some time
                    return None

                mock_result.wait = slow_wait
                return mock_result

            def stop_crawl(self, reason="timeout"):
                pass

            def wait_for_completion(self, timeout=10.0):
                return True

        with patch("intric.crawler.crawler.CrawlManager", MockCrawlManager):
            await Crawler._run_crawl_with_timeout(
                url="https://example.com",
                download_files=False,
                filepath="/tmp/test.jsonl",
                files_dir="/tmp/files",
                max_length=60,  # Long timeout so we don't trigger CrawlTimeoutError
                heartbeat_callback=mock_heartbeat,
                heartbeat_interval=0.1,  # 100ms heartbeat for fast test
            )

        # With 0.3s crawl and 0.1s interval, expect 2-3 heartbeat calls
        assert len(heartbeat_calls) >= 1, f"Expected heartbeat calls, got {len(heartbeat_calls)}"

    @pytest.mark.asyncio
    async def test_heartbeat_stops_when_crawl_completes(self):
        """Heartbeat loop terminates when crawl completes normally."""
        heartbeat_calls = []
        crawl_start = None

        async def mock_heartbeat():
            heartbeat_calls.append(time.time())

        class MockCrawlManager:
            def __init__(self):
                self._crawler = None
                self._completion_event = threading.Event()

            def start_crawl(self, *args, **kwargs):
                nonlocal crawl_start
                crawl_start = time.time()
                mock_result = MagicMock()
                mock_result.wait = lambda timeout: time.sleep(0.15)  # 150ms crawl
                return mock_result

            def stop_crawl(self, reason="timeout"):
                pass

            def wait_for_completion(self, timeout=10.0):
                return True

        with patch("intric.crawler.crawler.CrawlManager", MockCrawlManager):
            await Crawler._run_crawl_with_timeout(
                url="https://example.com",
                download_files=False,
                filepath="/tmp/test.jsonl",
                files_dir="/tmp/files",
                max_length=60,
                heartbeat_callback=mock_heartbeat,
                heartbeat_interval=0.05,  # 50ms interval
            )

        # Heartbeat should stop after crawl - wait a bit and verify no more calls
        initial_count = len(heartbeat_calls)
        await asyncio.sleep(0.2)  # Wait 200ms (4 intervals)
        final_count = len(heartbeat_calls)

        assert final_count == initial_count, (
            f"Heartbeat should stop after crawl. "
            f"Got {final_count - initial_count} extra calls"
        )

    @pytest.mark.asyncio
    async def test_heartbeat_stops_on_timeout(self):
        """Heartbeat loop terminates when crawl times out."""
        heartbeat_calls = []

        async def mock_heartbeat():
            heartbeat_calls.append(time.time())

        class MockCrawlManager:
            def __init__(self):
                self._crawler = None
                self._completion_event = threading.Event()

            def start_crawl(self, *args, **kwargs):
                mock_result = MagicMock()
                mock_result.wait = MagicMock(side_effect=crochet.TimeoutError("timeout"))
                return mock_result

            def stop_crawl(self, reason="timeout"):
                pass

            def wait_for_completion(self, timeout=10.0):
                return True

        with patch("intric.crawler.crawler.CrawlManager", MockCrawlManager):
            with pytest.raises(CrawlTimeoutError):
                await Crawler._run_crawl_with_timeout(
                    url="https://example.com",
                    download_files=False,
                    filepath="/tmp/test.jsonl",
                    files_dir="/tmp/files",
                    max_length=1,
                    heartbeat_callback=mock_heartbeat,
                    heartbeat_interval=0.05,
                )

        # Wait and verify heartbeat has stopped
        initial_count = len(heartbeat_calls)
        await asyncio.sleep(0.2)
        final_count = len(heartbeat_calls)

        assert final_count == initial_count, "Heartbeat should stop after timeout"


class TestHeartbeatCallbackParameter:
    """Tests for heartbeat_callback parameter passing through layers."""

    @pytest.mark.asyncio
    async def test_crawl_method_passes_heartbeat_to_internal(self):
        """crawl() method passes heartbeat_callback to _crawl()."""
        captured_heartbeat = None
        captured_interval = None

        async def mock_heartbeat():
            pass

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def capture_crawl(
            func,
            *,
            max_length,
            heartbeat_callback=None,
            heartbeat_interval=60.0,
            **kwargs,
        ):
            nonlocal captured_heartbeat, captured_interval
            captured_heartbeat = heartbeat_callback
            captured_interval = heartbeat_interval
            yield MagicMock()

        with patch(
            "intric.crawler.crawler.get_crawler_setting", return_value=60
        ):
            crawler = Crawler()
            crawler._crawl = capture_crawl

            async with crawler.crawl(
                url="https://example.com",
                heartbeat_callback=mock_heartbeat,
                heartbeat_interval=30.0,
            ):
                pass

        assert captured_heartbeat is mock_heartbeat
        assert captured_interval == 30.0

    @pytest.mark.asyncio
    async def test_crawl_method_defaults_heartbeat_to_none(self):
        """crawl() method defaults heartbeat_callback to None."""
        captured_heartbeat = "not_set"

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def capture_crawl(
            func,
            *,
            max_length,
            heartbeat_callback=None,
            heartbeat_interval=60.0,
            **kwargs,
        ):
            nonlocal captured_heartbeat
            captured_heartbeat = heartbeat_callback
            yield MagicMock()

        with patch(
            "intric.crawler.crawler.get_crawler_setting", return_value=60
        ):
            crawler = Crawler()
            crawler._crawl = capture_crawl

            async with crawler.crawl(
                url="https://example.com",
                # No heartbeat_callback specified
            ):
                pass

        assert captured_heartbeat is None


class TestSitemapCrawlGracefulShutdown:
    """Tests for sitemap crawl graceful shutdown (same pattern as regular crawl)."""

    @pytest.mark.asyncio
    async def test_sitemap_timeout_triggers_stop_crawl(self):
        """Sitemap crawl timeout also triggers stop_crawl()."""
        stop_crawl_called = threading.Event()

        class MockCrawlManager:
            def __init__(self):
                self._crawler = None
                self._completion_event = threading.Event()

            def start_crawl(self, *args, **kwargs):
                mock_result = MagicMock()
                mock_result.wait = MagicMock(side_effect=crochet.TimeoutError("timeout"))
                return mock_result

            def stop_crawl(self, reason="timeout"):
                stop_crawl_called.set()

            def wait_for_completion(self, timeout=10.0):
                return True

        with patch("intric.crawler.crawler.CrawlManager", MockCrawlManager):
            with pytest.raises(CrawlTimeoutError):
                await Crawler._run_sitemap_crawl_with_timeout(
                    sitemap_url="https://example.com/sitemap.xml",
                    filepath="/tmp/test.jsonl",
                    files_dir="/tmp/files",
                    max_length=1,
                )

        assert stop_crawl_called.is_set(), "stop_crawl() should be called for sitemap timeout"


class TestNoResourceLeakOnTimeout:
    """Integration-style tests verifying no resource leak on timeout."""

    @pytest.mark.asyncio
    async def test_completion_event_set_before_file_read(self):
        """Verify completion event is checked before file can be read.

        This test validates the fix for the race condition where the JSONL file
        was being read before Scrapy had finished writing to it.
        """
        completion_waited = threading.Event()

        class MockCrawlManager:
            def __init__(self):
                self._crawler = None
                self._completion_event = threading.Event()

            def start_crawl(self, *args, **kwargs):
                mock_result = MagicMock()
                mock_result.wait = MagicMock(side_effect=crochet.TimeoutError("timeout"))
                return mock_result

            def stop_crawl(self, reason="timeout"):
                pass

            def wait_for_completion(self, timeout=10.0):
                completion_waited.set()
                return True

        with patch("intric.crawler.crawler.CrawlManager", MockCrawlManager):
            with pytest.raises(CrawlTimeoutError):
                await Crawler._run_crawl_with_timeout(
                    url="https://example.com",
                    filepath="/tmp/test.jsonl",
                    files_dir="/tmp/files",
                    max_length=1,
                )

        # Verify wait_for_completion was called (which ensures file is ready)
        assert completion_waited.is_set(), (
            "wait_for_completion() must be called before file read to prevent race condition"
        )
