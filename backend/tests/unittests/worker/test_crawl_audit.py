from typing import cast
from uuid import UUID, uuid4

import pytest

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.worker.crawl.audit import CrawlAuditPayload, record_crawl_audit


class _RecordingAuditService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def log_async(
        self,
        tenant_id: UUID,
        actor_id: UUID | None,
        action: ActionType,
        entity_type: EntityType,
        entity_id: UUID,
        description: str,
        metadata: dict[str, object],
        outcome: Outcome = Outcome.SUCCESS,
        actor_type: ActorType = ActorType.USER,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: UUID | None = None,
        error_message: str | None = None,
    ) -> UUID | None:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "actor_id": actor_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "description": description,
                "metadata": metadata,
                "outcome": outcome,
                "actor_type": actor_type,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "request_id": request_id,
                "error_message": error_message,
            }
        )
        return None


def test_crawl_audit_payload_serializes_bounded_metadata_with_outcome_code() -> None:
    tenant_id = uuid4()
    website_id = uuid4()
    owner_id = uuid4()

    payload = CrawlAuditPayload(
        tenant_id=tenant_id,
        website_id=website_id,
        website_url="https://example.com",
        website_name=None,
        website_owner_id=owner_id,
        pages_crawled=3,
        pages_failed=1,
        pages_hash_retained=2,
        pages_source_retained=4,
        files_downloaded=5,
        files_failed=6,
        files_hash_retained=7,
        files_too_large_skipped=8,
        blobs_deleted=9,
        successful=False,
        outcome_code=CrawlOutcomeCode.CRAWL_PARTIAL_TIMEOUT,
    )

    assert payload.actor_id == owner_id
    assert payload.description == "Website crawled: https://example.com - Failed"
    assert payload.to_metadata() == {
        "target": {
            "website_id": str(website_id),
            "url": "https://example.com",
            "name": "https://example.com",
        },
        "crawl_stats": {
            "pages_crawled": 3,
            "pages_failed": 1,
            "pages_hash_retained": 2,
            "pages_source_retained": 4,
            "files_downloaded": 5,
            "files_failed": 6,
            "files_hash_retained": 7,
            "files_too_large_skipped": 8,
            "blobs_deleted": 9,
            "successful": False,
            "outcome_code": CrawlOutcomeCode.CRAWL_PARTIAL_TIMEOUT.value,
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("successful", "has_website_owner", "expected_description_suffix"),
    [
        (True, True, "Success"),
        (True, False, "Success"),
        (False, False, "Failed"),
    ],
)
async def test_record_crawl_audit_passes_full_audit_kwargs(
    successful: bool,
    has_website_owner: bool,
    expected_description_suffix: str,
) -> None:
    tenant_id = uuid4()
    website_id = uuid4()
    owner_id = uuid4() if has_website_owner else None
    payload = CrawlAuditPayload(
        tenant_id=tenant_id,
        website_id=website_id,
        website_url="https://example.com",
        website_name="Example",
        website_owner_id=owner_id,
        pages_crawled=1,
        pages_failed=0,
        pages_hash_retained=0,
        pages_source_retained=0,
        files_downloaded=0,
        files_failed=0,
        files_hash_retained=0,
        files_too_large_skipped=0,
        blobs_deleted=0,
        successful=successful,
        outcome_code=None,
    )
    audit_service = _RecordingAuditService()

    await record_crawl_audit(cast(AuditService, audit_service), payload)

    assert audit_service.calls == [
        {
            "tenant_id": tenant_id,
            "actor_id": owner_id or tenant_id,
            "action": ActionType.WEBSITE_CRAWLED,
            "entity_type": EntityType.WEBSITE,
            "entity_id": website_id,
            "description": (
                f"Website crawled: https://example.com - {expected_description_suffix}"
            ),
            "metadata": payload.to_metadata(),
            "outcome": Outcome.SUCCESS,
            "actor_type": ActorType.USER,
            "ip_address": None,
            "user_agent": None,
            "request_id": None,
            "error_message": None,
        }
    ]
