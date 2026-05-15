"""Crawler task utilities and lifecycle policies."""

from intric.websites.domain.crawl_terminal import (
    CrawlRunTerminalUpdate,
    TerminalBatchEvent,
    TerminalCommitResult,
    TerminalEvent,
    commit_terminal,
    commit_terminal_batch,
)
from intric.worker.crawl.audit import CrawlAuditPayload, record_crawl_audit
from intric.worker.crawl.bootstrap import (
    CrawlBootstrapResult,
    EmbeddingModelSpecError,
    HttpAuthDecryptionError,
    TenantIsolationError,
    WebsiteNotFoundError,
    bootstrap_crawl,
    build_embedding_model_spec,
    build_existing_blob_lookup,
)
from intric.worker.crawl.circuit_breaker import update_crawl_circuit_breaker
from intric.worker.crawl.cleanup import (
    CleanupDeleteCallback,
    CleanupResult,
    cleanup_stale_blobs,
)
from intric.worker.crawl.file_processing import (
    FileProcessingErrorRecorder,
    FileProcessingResult,
    MissingFileEmbeddingModelError,
    process_files,
)
from intric.worker.crawl.heartbeat import (
    HeartbeatFailedError,
    HeartbeatMonitor,
    JobPreemptedError,
)
from intric.worker.crawl.page_processing import (
    HeartbeatFailedPageProcessingAbort,
    PageProcessingAbort,
    PageProcessingAbortReason,
    PageProcessingSuccess,
    PreemptedPageProcessingAbort,
    process_pages,
)
from intric.worker.crawl.persistence import (
    ExistingBlobState,
    PersistBatchResult,
    persist_batch,
)
from intric.worker.crawl.recovery import (
    calculate_exponential_backoff,
    execute_with_recovery,
    is_invalid_transaction_error,
    is_invalid_transaction_error_msg,
    reset_tenant_retry_delay,
    update_job_retry_stats,
)
from intric.worker.crawl.slot_acquire import (
    CrawlSlotAcquirePath,
    CrawlSlotAcquireRequest,
    CrawlSlotAcquireResult,
    acquire_crawl_slot,
)
from intric.worker.crawl.slot_release import (
    CrawlSlotReleasePath,
    CrawlSlotReleaseRequest,
    CrawlSlotReleaseResult,
    release_crawl_slot_after_task,
)
from intric.worker.crawl.website_size import update_website_size_after_crawl
from intric.worker.crawl.website_timestamps import (
    update_website_timestamps_after_crawl,
)

__all__ = [
    # Audit
    "CrawlAuditPayload",
    "record_crawl_audit",
    # Bootstrap
    "CrawlBootstrapResult",
    "EmbeddingModelSpecError",
    "HttpAuthDecryptionError",
    "TenantIsolationError",
    "WebsiteNotFoundError",
    "bootstrap_crawl",
    "build_existing_blob_lookup",
    "build_embedding_model_spec",
    # Circuit breaker
    "update_crawl_circuit_breaker",
    # Cleanup
    "CleanupDeleteCallback",
    "CleanupResult",
    "cleanup_stale_blobs",
    # File processing
    "FileProcessingErrorRecorder",
    "FileProcessingResult",
    "MissingFileEmbeddingModelError",
    "process_files",
    # Heartbeat
    "HeartbeatFailedError",
    "HeartbeatMonitor",
    "JobPreemptedError",
    # Page processing
    "HeartbeatFailedPageProcessingAbort",
    "PageProcessingAbort",
    "PageProcessingAbortReason",
    "PageProcessingSuccess",
    "PreemptedPageProcessingAbort",
    "process_pages",
    # Persistence
    "ExistingBlobState",
    "PersistBatchResult",
    "persist_batch",
    # Recovery - Main API
    "calculate_exponential_backoff",
    "execute_with_recovery",
    "reset_tenant_retry_delay",
    "update_job_retry_stats",
    # Recovery - Helpers
    "is_invalid_transaction_error",
    "is_invalid_transaction_error_msg",
    # Slot release
    "CrawlSlotAcquirePath",
    "CrawlSlotAcquireRequest",
    "CrawlSlotAcquireResult",
    "acquire_crawl_slot",
    "CrawlSlotReleasePath",
    "CrawlSlotReleaseRequest",
    "CrawlSlotReleaseResult",
    "release_crawl_slot_after_task",
    # Terminal
    "CrawlRunTerminalUpdate",
    "TerminalBatchEvent",
    "TerminalCommitResult",
    "TerminalEvent",
    "commit_terminal_batch",
    "commit_terminal",
    # Website post-crawl updates
    "update_website_size_after_crawl",
    "update_website_timestamps_after_crawl",
]
