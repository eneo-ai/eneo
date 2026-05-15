import logging
from typing import TypedDict

from intric.websites.crawl_dependencies.crawl_models import CrawlRunProcessingSummary
from intric.websites.domain.crawl_outcome import CrawlTerminationReason


class CrawlCompletionTimings(TypedDict):
    fetch_existing_titles: float
    crawl_and_parse: float
    process_pages: float
    process_files: float
    cleanup_deleted: float
    update_size: float


def emit_crawl_completion_logs(
    *,
    logger: logging.Logger,
    url: str,
    processing_summary: CrawlRunProcessingSummary,
    blobs_deleted: int,
    timings: CrawlCompletionTimings,
    crawl_termination_reason: CrawlTerminationReason | None,
) -> None:
    page_retention_rate = _page_retention_rate_percent(processing_summary)
    file_retention_rate = _file_retention_rate_percent(processing_summary)

    logger.info(
        _completion_summary_message(
            url=url,
            processing_summary=processing_summary,
            blobs_deleted=blobs_deleted,
            page_retention_rate=page_retention_rate,
            file_retention_rate=file_retention_rate,
            crawl_termination_reason=crawl_termination_reason,
        )
    )

    total_time = (
        timings["fetch_existing_titles"]
        + timings["crawl_and_parse"]
        + timings["process_pages"]
        + timings["process_files"]
        + timings["cleanup_deleted"]
        + timings["update_size"]
    )
    logger.info(
        f"Performance breakdown: "
        f"fetch_existing={timings['fetch_existing_titles']:.2f}s, "
        f"crawl_parse={timings['crawl_and_parse']:.2f}s, "
        f"process_pages={timings['process_pages']:.2f}s, "
        f"process_files={timings['process_files']:.2f}s, "
        f"cleanup={timings['cleanup_deleted']:.2f}s, "
        f"update_size={timings['update_size']:.2f}s, "
        f"total_measured={total_time:.2f}s",
        extra={
            "timings": timings,
            "pages_crawled": processing_summary.pages_fetched,
            "pages_source_retained": processing_summary.pages_source_retained,
            "pages_failed": processing_summary.pages_failed,
            "pages_hash_retained": processing_summary.pages_hash_retained,
            # Existing log metric names; values are retained/avoided-work rates.
            "page_skip_rate_percent": page_retention_rate,
            "files_crawled": processing_summary.files_downloaded,
            "files_failed": processing_summary.files_failed,
            "files_hash_retained": processing_summary.files_hash_retained,
            "files_too_large_skipped": processing_summary.files_too_large_skipped,
            "file_skip_rate_percent": file_retention_rate,
            "blobs_deleted": blobs_deleted,
        },
    )


def _completion_summary_message(
    *,
    url: str,
    processing_summary: CrawlRunProcessingSummary,
    blobs_deleted: int,
    page_retention_rate: float,
    file_retention_rate: float,
    crawl_termination_reason: CrawlTerminationReason | None,
) -> str:
    status_label = (
        f"CRAWL PARTIAL ({crawl_termination_reason})"
        if crawl_termination_reason is not None
        else "CRAWL FINISHED"
    )
    summary = [
        "=" * 60,
        f"{status_label}: {url}",
        "-" * 60,
        (
            f"Pages:   {processing_summary.pages_fetched} fetched, "
            f"{processing_summary.pages_source_retained} source-retained, "
            f"{processing_summary.pages_failed} failed, "
            f"{processing_summary.pages_hash_retained} hash-retained "
            f"({page_retention_rate:.1f}% retained)"
        ),
        (
            f"Files:   {processing_summary.files_downloaded} downloaded, "
            f"{processing_summary.files_failed} failed, "
            f"{processing_summary.files_hash_retained} hash-retained, "
            f"{processing_summary.files_too_large_skipped} too-large skipped "
            f"({file_retention_rate:.1f}% retained)"
        ),
        f"Cleanup: {blobs_deleted} stale entries removed",
    ]
    if crawl_termination_reason is not None:
        summary.append(f"Partial completion due to: {crawl_termination_reason}")
    summary.append("=" * 60)
    return "\n".join(summary)


def _page_retention_rate_percent(
    processing_summary: CrawlRunProcessingSummary,
) -> float:
    total_page_source_count = (
        processing_summary.pages_fetched + processing_summary.pages_source_retained
    )
    total_retained_pages = (
        processing_summary.pages_hash_retained
        + processing_summary.pages_source_retained
    )
    if total_page_source_count == 0:
        return 0.0
    return total_retained_pages / total_page_source_count * 100


def _file_retention_rate_percent(
    processing_summary: CrawlRunProcessingSummary,
) -> float:
    total_file_source_count = (
        processing_summary.files_downloaded + processing_summary.files_too_large_skipped
    )
    total_retained_files = (
        processing_summary.files_hash_retained
        + processing_summary.files_too_large_skipped
    )
    if total_file_source_count == 0:
        return 0.0
    return total_retained_files / total_file_source_count * 100
