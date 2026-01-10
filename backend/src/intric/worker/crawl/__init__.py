"""Crawler task utilities and components.

This package provides modular components extracted from the monolithic
crawl_tasks.py for better maintainability and testability.

Modules:
    heartbeat: Job heartbeat monitoring and preemption detection
    persistence: Two-phase batch persistence for crawled pages
    recovery: Session recovery and retry utilities
"""

from intric.worker.crawl.heartbeat import (
    HeartbeatFailedError,
    HeartbeatMonitor,
    JobPreemptedError,
)
from intric.worker.crawl.persistence import persist_batch
from intric.worker.crawl.recovery import (
    SessionHolder,
    calculate_exponential_backoff,
    execute_with_recovery,
    is_invalid_transaction_error,
    is_invalid_transaction_error_msg,
    recover_session,
    reset_tenant_retry_delay,
    update_job_retry_stats,
)

__all__ = [
    # Heartbeat
    "HeartbeatFailedError",
    "HeartbeatMonitor",
    "JobPreemptedError",
    # Persistence
    "persist_batch",
    # Recovery - Main API
    "SessionHolder",
    "calculate_exponential_backoff",
    "execute_with_recovery",
    "reset_tenant_retry_delay",
    "update_job_retry_stats",
    # Recovery - Helpers (used for inline recovery patterns)
    "is_invalid_transaction_error",
    "is_invalid_transaction_error_msg",
    "recover_session",
]
