"""Crawl Feeder module - Pull-based queueing to prevent burst overload.

This package provides modular components for the feeder service:
- LeaderElection: Redis-based singleton lock for feeder coordination
- CapacityManager: Per-tenant slot management and settings retrieval
- PendingQueue: Redis queue operations for pending crawl jobs
- JobEnqueuer: ARQ job enqueueing with idempotency handling
- OrphanWatchdog: 4-phase orphan job cleanup with safe slot release

The CrawlFeederService orchestrates these components in the main loop.
"""

from intric.worker.feeder.capacity import CapacityManager
from intric.worker.feeder.election import LeaderElection
from intric.worker.feeder.queues import JobEnqueuer, PendingQueue
from intric.worker.feeder.watchdog import (
    CleanupMetrics,
    OrphanWatchdog,
    Phase1Result,
    Phase2Result,
    Phase3Result,
    SlotReleaseJob,
)

__all__ = [
    "CapacityManager",
    "CleanupMetrics",
    "JobEnqueuer",
    "LeaderElection",
    "OrphanWatchdog",
    "PendingQueue",
    "Phase1Result",
    "Phase2Result",
    "Phase3Result",
    "SlotReleaseJob",
]
