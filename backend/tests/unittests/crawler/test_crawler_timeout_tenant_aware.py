"""Unit tests for tenant-aware crawler timeout (crawl_max_length).

Tests the crochet.run_in_reactor() + EventualResult.wait() timeout implementation
that provides runtime-configurable timeouts while properly integrating with
Twisted's reactor for Scrapy crawls.

Test categories:
- Timeout enforcement: Verifies crochet.TimeoutError triggers CrawlerException
- Tenant settings resolution: Tests get_crawler_setting() integration
- Edge cases: Very short timeouts, missing settings, error handling
"""

import asyncio
import time
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import crochet
import pytest

# Setup crochet BEFORE importing Crawler (which uses @crochet.run_in_reactor decorator)
# This initializes Twisted's reactor in a way that's compatible with our test process.
crochet.setup()

from intric.crawler.crawler import Crawler
from intric.main.exceptions import CrawlerException


class MockEventualResult:
    """Mock for crochet's EventualResult that simulates blocking wait behavior."""

    def __init__(self, delay: float = 0, should_timeout: bool = False):
        self.delay = delay
        self.should_timeout = should_timeout

    def wait(self, timeout: float = None):
        """Simulate EventualResult.wait() behavior."""
        if self.should_timeout or (timeout and self.delay > timeout):
            time.sleep(min(timeout, 0.1))  # Sleep briefly to simulate timeout
            raise crochet.TimeoutError("Crawl exceeded timeout")
        time.sleep(min(self.delay, 0.1))  # Quick sleep for fast tests
        return None


class TestCrawlerTimeoutEnforcement:
    """Tests that crawl timeout is properly enforced via EventualResult.wait()."""

    @pytest.mark.asyncio
    async def test_timeout_triggers_crawler_exception(self):
        """When crawl exceeds max_length, CrawlerException is raised.

        This is the CRITICAL test - verifies the crochet integration works.
        """
        # Mock the deferred method to return a slow EventualResult
        mock_result = MockEventualResult(delay=10, should_timeout=True)

        with patch.object(
            Crawler, "_run_crawl_deferred", return_value=mock_result
        ):
            with pytest.raises(CrawlerException) as exc_info:
                await Crawler._run_crawl_with_timeout(
                    url="https://example.com",
                    download_files=False,
                    filepath="/tmp/test.jsonl",
                    files_dir="/tmp/files",
                    http_user=None,
                    http_pass=None,
                    tenant_crawler_settings=None,
                    max_length=1,  # 1 second timeout - will trigger
                )

            assert "Crawl timeout" in str(exc_info.value)
            assert "exceeded 1 seconds" in str(exc_info.value)
            assert "https://example.com" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_sitemap_timeout_triggers_crawler_exception(self):
        """Sitemap crawl also respects timeout and raises CrawlerException."""
        mock_result = MockEventualResult(delay=10, should_timeout=True)

        with patch.object(
            Crawler, "_run_sitemap_crawl_deferred", return_value=mock_result
        ):
            with pytest.raises(CrawlerException) as exc_info:
                await Crawler._run_sitemap_crawl_with_timeout(
                    sitemap_url="https://example.com/sitemap.xml",
                    filepath="/tmp/test.jsonl",
                    files_dir="/tmp/files",
                    http_user=None,
                    http_pass=None,
                    tenant_crawler_settings=None,
                    max_length=1,
                )

            assert "Crawl timeout" in str(exc_info.value)
            assert "sitemap.xml" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_successful_crawl_within_timeout(self):
        """Crawl completes successfully when within timeout limit."""
        # Fast crawl that completes quickly
        mock_result = MockEventualResult(delay=0.01, should_timeout=False)

        with patch.object(
            Crawler, "_run_crawl_deferred", return_value=mock_result
        ) as mock_deferred:
            # Should complete without exception
            await Crawler._run_crawl_with_timeout(
                url="https://example.com",
                download_files=False,
                filepath="/tmp/test.jsonl",
                files_dir="/tmp/files",
                http_user=None,
                http_pass=None,
                tenant_crawler_settings=None,
                max_length=60,  # 60 second timeout - plenty of time
            )

            # Verify the deferred method was called
            mock_deferred.assert_called_once()


class TestCrawlerTenantSettingsResolution:
    """Tests tenant-aware timeout resolution in crawl() method."""

    @pytest.mark.asyncio
    async def test_uses_tenant_override_timeout(self):
        """When tenant has custom crawl_max_length, it's used."""
        tenant_settings = {"crawl_max_length": 120}  # 2 minutes

        with patch(
            "intric.crawler.crawler.get_crawler_setting"
        ) as mock_get_setting:
            mock_get_setting.return_value = 120

            # Mock _crawl to capture the max_length parameter
            captured_max_length = None

            @asynccontextmanager
            async def capture_crawl(func, *, max_length, **kwargs):
                nonlocal captured_max_length
                captured_max_length = max_length
                # Yield a mock result
                yield MagicMock()

            crawler = Crawler()
            crawler._crawl = capture_crawl
            async with crawler.crawl(
                url="https://example.com",
                tenant_crawler_settings=tenant_settings,
            ):
                pass

            # Verify get_crawler_setting was called with tenant settings
            mock_get_setting.assert_called_once_with(
                "crawl_max_length", tenant_settings
            )
            assert captured_max_length == 120

    @pytest.mark.asyncio
    async def test_uses_default_when_no_tenant_settings(self):
        """When no tenant settings provided, uses environment default."""
        with patch(
            "intric.crawler.crawler.get_crawler_setting"
        ) as mock_get_setting:
            mock_get_setting.return_value = 7200  # Default 2 hours

            captured_max_length = None

            @asynccontextmanager
            async def capture_crawl(func, *, max_length, **kwargs):
                nonlocal captured_max_length
                captured_max_length = max_length
                yield MagicMock()

            crawler = Crawler()
            crawler._crawl = capture_crawl
            async with crawler.crawl(
                url="https://example.com",
                tenant_crawler_settings=None,  # No tenant settings
            ):
                pass

            mock_get_setting.assert_called_once_with("crawl_max_length", None)
            assert captured_max_length == 7200

    @pytest.mark.asyncio
    async def test_sitemap_crawl_uses_tenant_timeout(self):
        """SITEMAP crawl type also uses tenant-aware timeout."""
        from intric.websites.domain.crawl_run import CrawlType

        tenant_settings = {"crawl_max_length": 300}

        with patch(
            "intric.crawler.crawler.get_crawler_setting"
        ) as mock_get_setting:
            mock_get_setting.return_value = 300

            captured_max_length = None

            @asynccontextmanager
            async def capture_crawl(func, *, max_length, **kwargs):
                nonlocal captured_max_length
                captured_max_length = max_length
                yield MagicMock()

            crawler = Crawler()
            crawler._crawl = capture_crawl
            async with crawler.crawl(
                url="https://example.com/sitemap.xml",
                crawl_type=CrawlType.SITEMAP,
                tenant_crawler_settings=tenant_settings,
            ):
                pass

            assert captured_max_length == 300


class TestCrawlerTimeoutEdgeCases:
    """Tests edge cases and error handling for timeout behavior."""

    @pytest.mark.asyncio
    async def test_very_short_timeout_still_works(self):
        """Extremely short timeout (1 second) still properly triggers."""
        mock_result = MockEventualResult(delay=5, should_timeout=True)

        with patch.object(
            Crawler, "_run_crawl_deferred", return_value=mock_result
        ):
            start_time = asyncio.get_event_loop().time()
            with pytest.raises(CrawlerException):
                await Crawler._run_crawl_with_timeout(
                    url="https://example.com",
                    filepath="/tmp/test.jsonl",
                    files_dir="/tmp/files",
                    max_length=1,  # Very short timeout
                )
            end_time = asyncio.get_event_loop().time()

            # Should timeout quickly, not wait for the full 5 seconds
            elapsed = end_time - start_time
            assert elapsed < 3, f"Timeout should trigger quickly, took {elapsed}s"

    @pytest.mark.asyncio
    async def test_timeout_message_includes_url(self):
        """Timeout exception message includes the URL for debugging."""
        mock_result = MockEventualResult(delay=10, should_timeout=True)

        with patch.object(
            Crawler, "_run_crawl_deferred", return_value=mock_result
        ):
            test_url = "https://slow-website.example.com/very/long/path"
            with pytest.raises(CrawlerException) as exc_info:
                await Crawler._run_crawl_with_timeout(
                    url=test_url,
                    filepath="/tmp/test.jsonl",
                    files_dir="/tmp/files",
                    max_length=1,
                )

            error_message = str(exc_info.value)
            assert test_url in error_message, "Error should include full URL"
            assert "exceeded 1 seconds" in error_message

    @pytest.mark.asyncio
    @pytest.mark.parametrize("timeout_value", [1, 2])
    async def test_timeout_message_includes_seconds(self, timeout_value):
        """Timeout exception message includes the max_length value."""
        mock_result = MockEventualResult(delay=10, should_timeout=True)

        with patch.object(
            Crawler, "_run_crawl_deferred", return_value=mock_result
        ):
            with pytest.raises(CrawlerException) as exc_info:
                await Crawler._run_crawl_with_timeout(
                    url="https://example.com",
                    filepath="/tmp/test.jsonl",
                    files_dir="/tmp/files",
                    max_length=timeout_value,
                )

            assert f"exceeded {timeout_value} seconds" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_crawler_passes_settings_to_deferred_method(self):
        """Tenant crawler settings are passed through to deferred method."""
        tenant_settings = {
            "download_timeout": 120,
            "retry_times": 5,
        }

        mock_result = MockEventualResult(delay=0.01, should_timeout=False)

        with patch.object(
            Crawler, "_run_crawl_deferred", return_value=mock_result
        ) as mock_deferred:
            await Crawler._run_crawl_with_timeout(
                url="https://example.com",
                download_files=True,
                filepath="/tmp/test.jsonl",
                files_dir="/tmp/files",
                http_user="user",
                http_pass="pass",
                tenant_crawler_settings=tenant_settings,
                max_length=60,
            )

            # Verify all params were passed correctly
            mock_deferred.assert_called_once()
            call_args = mock_deferred.call_args
            # Check positional args
            assert call_args[0][0] == "https://example.com"  # url
            assert call_args[0][1] is True  # download_files
            # Check keyword args
            assert call_args[1]["tenant_crawler_settings"] == tenant_settings


class TestCrawlerTimeoutIsolation:
    """Tests that different tenants get different timeouts."""

    @pytest.mark.asyncio
    async def test_different_tenants_different_timeouts(self):
        """Two consecutive crawls with different tenant settings use different timeouts."""
        tenant_a_settings = {"crawl_max_length": 60}  # 1 minute
        tenant_b_settings = {"crawl_max_length": 3600}  # 1 hour

        captured_timeouts = []

        @asynccontextmanager
        async def capture_crawl(func, *, max_length, **kwargs):
            captured_timeouts.append(max_length)
            yield MagicMock()

        def mock_get_setting(key, settings):
            if settings == tenant_a_settings:
                return 60
            elif settings == tenant_b_settings:
                return 3600
            return 7200  # Default

        with patch(
            "intric.crawler.crawler.get_crawler_setting",
            side_effect=mock_get_setting,
        ):
            crawler = Crawler()
            crawler._crawl = capture_crawl

            # Tenant A crawl
            async with crawler.crawl(
                url="https://a.example.com",
                tenant_crawler_settings=tenant_a_settings,
            ):
                pass

            # Tenant B crawl
            async with crawler.crawl(
                url="https://b.example.com",
                tenant_crawler_settings=tenant_b_settings,
            ):
                pass

        assert len(captured_timeouts) == 2
        assert captured_timeouts[0] == 60, "Tenant A should have 60s timeout"
        assert captured_timeouts[1] == 3600, "Tenant B should have 3600s timeout"


class TestCrawlerNoRegressions:
    """Tests ensuring no regressions from crochet integration."""

    @pytest.mark.asyncio
    async def test_all_parameters_still_passed_correctly(self):
        """Verify all existing parameters are still passed through correctly."""
        tenant_settings = {"download_timeout": 100}
        mock_result = MockEventualResult(delay=0.01, should_timeout=False)

        with patch.object(
            Crawler, "_run_crawl_deferred", return_value=mock_result
        ) as mock_deferred:
            await Crawler._run_crawl_with_timeout(
                url="https://example.com",
                download_files=True,
                filepath="/tmp/test.jsonl",
                files_dir="/tmp/files",
                http_user="testuser",
                http_pass="testpass",
                tenant_crawler_settings=tenant_settings,
                max_length=60,
            )

            mock_deferred.assert_called_once()
            call_args = mock_deferred.call_args
            # Check keyword args
            assert call_args[1]["filepath"] == "/tmp/test.jsonl"
            assert call_args[1]["files_dir"] == "/tmp/files"
            assert call_args[1]["http_user"] == "testuser"
            assert call_args[1]["http_pass"] == "testpass"
            assert call_args[1]["tenant_crawler_settings"] == tenant_settings

    @pytest.mark.asyncio
    async def test_download_files_flag_passed_correctly(self):
        """Ensure download_files parameter works as before."""
        mock_result = MockEventualResult(delay=0.01, should_timeout=False)

        with patch.object(
            Crawler, "_run_crawl_deferred", return_value=mock_result
        ) as mock_deferred:
            await Crawler._run_crawl_with_timeout(
                url="https://example.com",
                download_files=True,  # Should be passed through
                filepath="/tmp/test.jsonl",
                files_dir="/tmp/files",
                max_length=60,
            )

            mock_deferred.assert_called_once()
            # download_files should be second positional arg
            assert mock_deferred.call_args[0][1] is True
