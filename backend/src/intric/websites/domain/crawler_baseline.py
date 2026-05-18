from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from intric.websites.domain.crawl_outcome import CrawlOutcomeCode


@dataclass(frozen=True, slots=True)
class CrawlOutcomeBucket:
    code: CrawlOutcomeCode
    count: int


@dataclass(frozen=True, slots=True)
class CrawlerBaselineProcessingTotals:
    pages_crawled: int
    files_downloaded: int
    pages_hash_retained: int
    files_hash_retained: int
    pages_source_retained: int
    files_too_large_skipped: int
    pages_failed: int
    files_failed: int
    embedding_input_tokens: int | None
    embedding_total_cost_usd: Decimal | None


@dataclass(frozen=True, slots=True)
class CrawlerBaselineMetrics:
    window_days: int
    since: datetime
    until: datetime
    tenant_id: UUID | None
    total_runs: int
    terminal_runs: int
    failed_runs: int
    failed_runs_without_typed_outcome: int
    typed_failed_runs: int
    typed_unknown_failed_runs: int
    typed_unknown_failed_rate_percent: float
    legacy_null_outcome_runs: int
    unparseable_outcome_runs: int
    outcome_counts: tuple[CrawlOutcomeBucket, ...]
    processing_totals: CrawlerBaselineProcessingTotals
