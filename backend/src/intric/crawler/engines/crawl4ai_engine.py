"""Crawl4ai engine implementation using AsyncWebCrawler."""

import logging
from pathlib import Path
from typing import AsyncIterator

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from crawl4ai.content_filter_strategy import PruningContentFilter

from intric.crawler.engines.base import CrawlerEngineAbstraction
from intric.crawler.parse_html import CrawledPage
from intric.main.config import SETTINGS
from intric.main.exceptions import CrawlerException
from intric.websites.domain.crawl_run import CrawlType

logger = logging.getLogger(__name__)


class Crawl4aiEngine(CrawlerEngineAbstraction):
    """Crawl4ai engine implementation using AsyncWebCrawler.

    This engine provides modern web crawling capabilities with JavaScript support,
    AI-optimized content extraction, and enhanced markdown generation.
    """

    def __init__(self):
        """Initialize the Crawl4ai engine."""
        # Default browser config for regular crawling
        self._browser_config = BrowserConfig(
            browser_type="chromium",
            headless=True,
            verbose=False,
            # Optimize for server environments
            text_mode=False,  # Keep images for better content understanding
            extra_args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
            ]
        )

        # Browser config for file downloads
        import tempfile
        self._download_dir = tempfile.mkdtemp(prefix="crawl4ai_downloads_")

        self._download_browser_config = BrowserConfig(
            browser_type="chromium",
            headless=True,
            verbose=False,
            accept_downloads=True,      # Enable actual file downloads
            downloads_path=self._download_dir,  # Use temp directory for downloads
            text_mode=False,
            extra_args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
            ]
        )

    async def crawl(
        self,
        url: str,
        download_files: bool = False,
        crawl_type: CrawlType = CrawlType.CRAWL,
    ) -> AsyncIterator[CrawledPage]:
        """Execute crawl using crawl4ai AsyncWebCrawler.

        Args:
            url: The URL to crawl
            download_files: Whether to download files during crawling
            crawl_type: The type of crawl to perform (CRAWL or SITEMAP)

        Yields:
            CrawledPage objects containing crawled data
        """
        logger.info(f"Starting crawl4ai crawl for URL: {url}")

        try:
            # Configure crawl settings based on existing Scrapy patterns
            run_config = self._create_run_config(download_files, crawl_type)

            async with AsyncWebCrawler(config=self._browser_config) as crawler:
                if crawl_type == CrawlType.SITEMAP:
                    # For sitemap crawling, we need to handle multiple URLs
                    async for page in self._crawl_sitemap(crawler, url, run_config):
                        yield page
                else:
                    # Single page crawl
                    result = await crawler.arun(url=url, config=run_config)

                    if result.success and result.markdown:
                        # Convert crawl4ai result to CrawledPage format
                        page = self._convert_result_to_crawled_page(result)
                        yield page
                    else:
                        error_msg = result.error_message or "Unknown crawl error"
                        logger.error(f"Crawl4ai crawl failed: {error_msg}")
                        raise CrawlerException(f"Crawl failed: {error_msg}")

        except Exception as e:
            logger.error(f"Crawl4ai engine error: {str(e)}")
            raise CrawlerException(f"Crawl4ai engine error: {str(e)}")

    async def crawl_files(self, url: str) -> AsyncIterator[Path]:
        """Execute crawl and yield downloaded file paths using crawl4ai native capabilities.

        Args:
            url: The URL to crawl for files

        Yields:
            Path objects to downloaded files
        """
        logger.info(f"Starting file download crawl for URL: {url}")

        try:
            # Configure for actual file downloads from page links
            run_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                word_count_threshold=10,

                # JavaScript to trigger document downloads (production version)
                js_code="""
                    const selectors = [
                        'a[href$=".pdf"]', 'a[href*=".pdf"]',     // PDF files
                        'a[href$=".doc"]', 'a[href*=".doc"]',     // Word documents
                        'a[href$=".docx"]', 'a[href*=".docx"]',   // Modern Word documents
                        'a[href$=".xls"]', 'a[href*=".xls"]',     // Excel files
                        'a[href$=".xlsx"]', 'a[href*=".xlsx"]',   // Modern Excel files
                        'a[href$=".csv"]', 'a[href*=".csv"]',     // CSV files
                        'a[href$=".txt"]', 'a[href*=".txt"]',     // Text files
                        'a[download]'                             // Explicit download links
                    ];

                    let downloadLinks = [];
                    selectors.forEach(sel => {
                        downloadLinks.push(...document.querySelectorAll(sel));
                    });

                    // Remove duplicates by href
                    const uniqueLinks = [...new Map(downloadLinks.map(link => [link.href, link])).values()];

                    if (uniqueLinks.length > 0) {
                        for (const link of uniqueLinks) {
                            try {
                                link.click();
                                await new Promise(r => setTimeout(r, 2000));
                            } catch (e) {
                                // Silent failure - don't clutter logs
                            }
                        }
                    }
                """,

                # Wait longer for downloads
                delay_before_return_html=15.0,  # Wait 15 seconds for downloads

                # Use timeout equivalent to Scrapy settings
                page_timeout=int(SETTINGS.crawl_max_length * 1000),

                # DON'T generate page captures - only download actual files
                screenshot=False,
                pdf=False,
                capture_mhtml=False,
            )

            # Execute file download crawl
            async with AsyncWebCrawler(config=self._download_browser_config) as crawler:
                result = await crawler.arun(url=url, config=run_config)

                # Check download results
                downloaded_count = len(result.downloaded_files or [])
                logger.info(f"File download completed: {downloaded_count} files found")

                if downloaded_count > 0:
                    logger.debug(f"Downloaded files: {result.downloaded_files}")
                elif logger.isEnabledFor(logging.DEBUG):
                    # Only check directory contents in debug mode to avoid performance impact
                    dir_after = list(Path(self._download_dir).iterdir()) if Path(self._download_dir).exists() else []
                    logger.debug(f"No files tracked by crawl4ai, directory has {len(dir_after)} files")

                if result.success and result.downloaded_files:
                    # Process downloaded files
                    for file_path_str in result.downloaded_files:
                        file_path = Path(file_path_str)
                        logger.debug(f"Processing downloaded file: {file_path}")

                        # Validate file exists and is text-extractable
                        if file_path.exists():
                            # Check file extension - only allow document types
                            allowed_extensions = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt'}
                            file_extension = file_path.suffix.lower()

                            if file_extension not in allowed_extensions:
                                logger.debug(f"Skipping unsupported file extension: {file_extension}")
                                continue

                            try:
                                import magic
                                mimetype = magic.from_file(str(file_path), mime=True)
                                from intric.files.text import TextMimeTypes

                                # Only process files that TextExtractor can handle
                                if not TextMimeTypes.has_value(mimetype):
                                    logger.debug(f"Skipping unsupported mimetype: {mimetype}")
                                    continue

                                file_size = file_path.stat().st_size

                                # Skip extremely large files
                                if file_size > 50 * 1024 * 1024:  # 50MB limit
                                    logger.warning(f"Skipping oversized file: {file_size / 1024 / 1024:.1f}MB")
                                    continue

                                # Handle binary document files (PDFs, Word, Excel) that TextExtractor can process
                                binary_document_types = {
                                    "application/pdf",
                                    "application/msword",
                                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    "application/vnd.ms-excel",
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                                }

                                if mimetype in binary_document_types:
                                    logger.info(f"Processing binary document: {file_path.name} ({file_size / 1024:.1f}KB)")
                                    yield file_path
                                else:
                                    # For text files (CSV, TXT), validate UTF-8 encoding
                                    try:
                                        with open(file_path, 'r', encoding='utf-8') as f:
                                            sample_text = f.read(1024)

                                        if len(sample_text.strip()) >= 10:
                                            logger.info(f"Processing text file: {file_path.name} ({file_size / 1024:.1f}KB)")
                                            yield file_path
                                        else:
                                            logger.debug("Skipping file with minimal content")

                                    except UnicodeDecodeError:
                                        logger.warning(f"Skipping text file with encoding issues: {file_path.name}")
                                    except Exception as e:
                                        logger.debug(f"Could not validate text file: {str(e)}")

                            except Exception as e:
                                logger.warning(f"Could not process file {file_path.name}: {str(e)}")
                        else:
                            logger.warning(f"Downloaded file not found: {file_path_str}")

                elif not result.success:
                    logger.warning(f"File download crawl failed: {result.error_message or 'Unknown error'}")
                    # Graceful degradation - don't break content crawling

        except Exception as e:
            logger.error(f"File download engine error: {str(e)}")
            # Graceful degradation - continue with content crawling even if file downloads fail

    def validate_config(self) -> bool:
        """Validate crawl4ai engine configuration.

        Returns:
            True if configuration is valid
        """
        try:
            # Basic validation - check if we can create the configs
            self._create_run_config(False, CrawlType.CRAWL)

            # Validate required settings exist
            if not hasattr(SETTINGS, 'crawl_max_length'):
                logger.error("Missing required setting: crawl_max_length")
                return False

            if not hasattr(SETTINGS, 'closespider_itemcount'):
                logger.error("Missing required setting: closespider_itemcount")
                return False

            logger.info("Crawl4ai engine configuration is valid")
            return True

        except Exception as e:
            logger.error(f"Crawl4ai configuration validation failed: {str(e)}")
            return False

    def _create_run_config(self, download_files: bool, crawl_type: CrawlType) -> CrawlerRunConfig:
        """Create CrawlerRunConfig based on settings and parameters.

        Args:
            download_files: Whether to enable file downloads
            crawl_type: The type of crawl to perform

        Returns:
            Configured CrawlerRunConfig object
        """
        # Map Scrapy settings to crawl4ai configuration
        config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,  # Always bypass cache for fresh data
            markdown_generator=DefaultMarkdownGenerator(
                content_source="cleaned_html",   # Pre-cleaning removes structural noise
                content_filter=PruningContentFilter(
                    threshold=0.2,               # Very mild - only obvious junk removal
                    threshold_type="dynamic",    # Adapt to different website patterns
                    min_word_threshold=5         # Preserve short valuable content and links
                ),
                options={
                    "ignore_links": False,       # Preserve all links for references/sources
                    "include_sup_sub": True,     # Better footnote and citation handling
                    "body_width": 0,            # No line wrapping for LLMs
                    "escape_html": False,       # Cleaner text output
                    "citations": True           # Generate citations for references
                }
            ),
            word_count_threshold=10,  # Minimum word count for content

            # Performance settings based on Scrapy configuration
            page_timeout=int(SETTINGS.crawl_max_length * 1000),  # Convert to milliseconds

            # Content filtering
            excluded_tags=["script", "style", "noscript"],
            remove_overlay_elements=True,

            # Link filtering for cleaner references
            exclude_social_media_links=True,    # Remove Facebook, Twitter, LinkedIn noise
            exclude_external_links=False,       # Keep external links for references (can be valuable)

            # Image filtering for performance and quality
            exclude_external_images=True,       # Skip third-party ads/tracking images
            wait_for_images=True,              # Ensure complete image loading
            image_score_threshold=2,           # Remove tiny icons/pixels, keep content images

            # Respect robots.txt if configured
            check_robots_txt=SETTINGS.obey_robots,

            # Wait for content to load
            wait_for="body",

            # Enable table extraction for structured data
            table_score_threshold=5,  # Lower threshold to capture more tables

            # Only generate useful captures when downloading files
            screenshot=False,           # Never capture screenshots (binary image data)
            pdf=download_files,         # Generate PDF render only when downloading files
            capture_mhtml=False,        # Never capture MHTML (huge files with binary data)

            # Handle large pages efficiently
            scan_full_page=False,  # Don't auto-scroll entire page for performance
        )

        # Adjust configuration based on crawl type
        if crawl_type == CrawlType.SITEMAP:
            # For sitemap crawls, we want minimal processing per page
            config.word_count_threshold = 5
            config.scan_full_page = False

        return config

    def _convert_result_to_crawled_page(self, result) -> CrawledPage:
        """Convert crawl4ai CrawlResult to CrawledPage format.

        Args:
            result: crawl4ai CrawlResult object

        Returns:
            CrawledPage object compatible with existing system
        """
        # Extract title from metadata or HTML
        title = ""
        if result.metadata and "title" in result.metadata:
            title = result.metadata["title"]
        elif result.markdown and hasattr(result.markdown, 'raw_markdown'):
            # Try to extract title from markdown
            lines = result.markdown.raw_markdown.split('\n')
            for line in lines[:10]:  # Check first 10 lines
                if line.startswith('# '):
                    title = line[2:].strip()
                    break

        # Use the best available markdown content (prioritize filtered content)
        content = ""
        if result.markdown:
            # Handle MarkdownGenerationResult object (modern format)
            if hasattr(result.markdown, 'fit_markdown') and result.markdown.fit_markdown:
                # Use filtered/cleaned markdown when available (from content filter)
                content = result.markdown.fit_markdown
                logger.debug("Using fit_markdown (filtered content)")
            elif hasattr(result.markdown, 'markdown_with_citations') and result.markdown.markdown_with_citations:
                # Use markdown with citations for better reference handling
                content = result.markdown.markdown_with_citations
                logger.debug("Using markdown_with_citations")
            elif hasattr(result.markdown, 'raw_markdown'):
                # Fall back to raw markdown
                content = result.markdown.raw_markdown
                logger.debug("Using raw_markdown")
            else:
                # Fallback for older string format
                content = str(result.markdown)
                logger.debug("Using legacy string markdown format")

        # Add table data to content if available
        if result.tables:
            table_content = self._extract_table_content(result.tables)
            if table_content:
                content += "\n\n## Extracted Tables\n\n" + table_content

        # Create CrawledPage object
        return CrawledPage(
            url=result.url,
            title=title,
            content=content,
        )

    async def _crawl_sitemap(self, crawler, sitemap_url: str, run_config: CrawlerRunConfig) -> AsyncIterator[CrawledPage]:
        """Handle sitemap crawling by processing sitemap URLs.

        Args:
            crawler: AsyncWebCrawler instance
            sitemap_url: URL of the sitemap
            run_config: Crawler run configuration

        Yields:
            CrawledPage objects for each URL in the sitemap
        """
        try:
            # First, fetch the sitemap
            sitemap_result = await crawler.arun(url=sitemap_url, config=run_config)

            if not sitemap_result.success:
                raise CrawlerException(f"Failed to fetch sitemap: {sitemap_result.error_message}")

            # Parse URLs from sitemap
            # This is a simplified implementation - in production, you'd want a proper sitemap parser
            import xml.etree.ElementTree as ET

            try:
                root = ET.fromstring(sitemap_result.html)
                # Handle XML namespaces
                namespaces = {
                    'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'
                }

                urls = []
                for url_elem in root.findall('.//sm:url', namespaces):
                    loc_elem = url_elem.find('sm:loc', namespaces)
                    if loc_elem is not None and loc_elem.text:
                        urls.append(loc_elem.text)

                # Limit URLs based on settings (equivalent to CLOSESPIDER_ITEMCOUNT)
                max_urls = min(len(urls), SETTINGS.closespider_itemcount)
                urls = urls[:max_urls]

                logger.info(f"Found {len(urls)} URLs in sitemap, crawling {max_urls}")

                # Crawl each URL
                for url in urls:
                    try:
                        result = await crawler.arun(url=url, config=run_config)
                        if result.success and result.markdown:
                            page = self._convert_result_to_crawled_page(result)
                            yield page
                        else:
                            logger.warning(f"Failed to crawl URL from sitemap: {url}")
                    except Exception as e:
                        logger.warning(f"Error crawling URL {url}: {str(e)}")
                        continue

            except ET.ParseError as e:
                logger.error(f"Failed to parse sitemap XML: {str(e)}")
                # Fallback: treat as regular page crawl
                result = await crawler.arun(url=sitemap_url, config=run_config)
                if result.success and result.markdown:
                    page = self._convert_result_to_crawled_page(result)
                    yield page

        except Exception as e:
            logger.error(f"Sitemap crawl error: {str(e)}")
            raise CrawlerException(f"Sitemap crawl error: {str(e)}")

    def _extract_table_content(self, tables: list) -> str:
        """Extract table data as markdown format.

        Args:
            tables: List of table dictionaries from crawl4ai

        Returns:
            Formatted markdown string with table data
        """
        if not tables:
            return ""

        table_markdown = []
        valid_table_count = 0

        for i, table in enumerate(tables):
            # Validate table structure
            if not isinstance(table, dict):
                continue

            rows = table.get('rows', [])
            if not rows:
                continue  # Skip empty tables

            valid_table_count += 1

            # Add table caption if available
            caption = table.get('caption', f'Table {valid_table_count}')
            table_markdown.append(f"### {caption}")

            # Extract headers
            headers = table.get('headers', [])
            if headers and len(headers) > 0:
                # Clean headers (remove empty strings, strip whitespace)
                clean_headers = [str(h).strip() or f"Col {j+1}" for j, h in enumerate(headers)]
                header_row = "| " + " | ".join(clean_headers) + " |"
                separator_row = "| " + " | ".join(["---"] * len(clean_headers)) + " |"
                table_markdown.append(header_row)
                table_markdown.append(separator_row)

                # Extract rows with header count validation
                for row in rows[:10]:  # Limit to first 10 rows to avoid huge content
                    if isinstance(row, list) and len(row) >= len(clean_headers):
                        # Clean cells and pad if necessary
                        clean_row = [str(cell).strip() if cell is not None else "" for cell in row[:len(clean_headers)]]
                        row_markdown = "| " + " | ".join(clean_row) + " |"
                        table_markdown.append(row_markdown)
            else:
                # Handle tables without headers
                table_markdown.append("*Table without headers*")
                for row in rows[:5]:  # Show fewer rows for headerless tables
                    if isinstance(row, list):
                        clean_row = [str(cell).strip() if cell is not None else "" for cell in row]
                        row_markdown = "| " + " | ".join(clean_row) + " |"
                        table_markdown.append(row_markdown)

            if len(rows) > 10:
                table_markdown.append(f"*... ({len(rows) - 10} more rows)*")

            # Add table metadata if available
            metadata = table.get('metadata', {})
            if metadata:
                table_markdown.append(f"*Rows: {metadata.get('row_count', len(rows))}, Columns: {metadata.get('column_count', len(headers))}*")

            table_markdown.append("")  # Add spacing between tables

        return "\n".join(table_markdown) if table_markdown else ""