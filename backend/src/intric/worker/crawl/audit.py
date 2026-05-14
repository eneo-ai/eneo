from dataclasses import dataclass
from uuid import UUID

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode

CrawlAuditValue = str | int | bool | None
CrawlAuditMetadataSection = dict[str, CrawlAuditValue]
CrawlAuditMetadata = dict[str, CrawlAuditMetadataSection]


@dataclass(frozen=True, slots=True)
class CrawlAuditPayload:
    tenant_id: UUID
    website_id: UUID
    website_url: str
    website_name: str | None
    website_owner_id: UUID | None
    pages_crawled: int
    pages_failed: int
    pages_hash_retained: int
    pages_source_retained: int
    files_downloaded: int
    files_failed: int
    files_hash_retained: int
    files_too_large_skipped: int
    blobs_deleted: int
    successful: bool
    outcome_code: CrawlOutcomeCode | None

    @property
    def actor_id(self) -> UUID:
        return self.website_owner_id or self.tenant_id

    @property
    def description(self) -> str:
        status = "Success" if self.successful else "Failed"
        return f"Website crawled: {self.website_url} - {status}"

    def to_metadata(self) -> CrawlAuditMetadata:
        return {
            "target": {
                "website_id": str(self.website_id),
                "url": self.website_url,
                "name": self.website_name or self.website_url,
            },
            "crawl_stats": {
                "pages_crawled": self.pages_crawled,
                "pages_failed": self.pages_failed,
                "pages_hash_retained": self.pages_hash_retained,
                "pages_source_retained": self.pages_source_retained,
                "files_downloaded": self.files_downloaded,
                "files_failed": self.files_failed,
                "files_hash_retained": self.files_hash_retained,
                "files_too_large_skipped": self.files_too_large_skipped,
                "blobs_deleted": self.blobs_deleted,
                "successful": self.successful,
                "outcome_code": (
                    self.outcome_code.value if self.outcome_code is not None else None
                ),
            },
        }


async def record_crawl_audit(
    audit_service: AuditService,
    payload: CrawlAuditPayload,
) -> None:
    await audit_service.log_async(
        tenant_id=payload.tenant_id,
        actor_id=payload.actor_id,
        action=ActionType.WEBSITE_CRAWLED,
        entity_type=EntityType.WEBSITE,
        entity_id=payload.website_id,
        description=payload.description,
        metadata=payload.to_metadata(),
    )
