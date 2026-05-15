from collections.abc import Awaitable, Callable
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import intric.worker.crawl.post_terminal_effects as post_terminal_effects_module
from intric.audit.application.audit_service import AuditService
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.worker.crawl.audit import CrawlAuditPayload
from intric.worker.crawl.post_terminal_effects import (
    PostTerminalEffectInput,
    apply_post_terminal_effects,
)


class _FakeAuditService:
    pass


class _Recorder:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.circuit_breaker_success_values: list[bool] = []
        self.audit_services: list[AuditService] = []
        self.audit_payloads: list[CrawlAuditPayload] = []

    async def execute_with_recovery(
        self,
        *,
        operation_name: str,
        operation: Callable[[AsyncSession], Awaitable[None]],
    ) -> None:
        assert operation_name == "circuit_breaker_update"
        self.events.append("circuit-breaker")
        await operation(cast(AsyncSession, object()))


def _payload(*, successful: bool, outcome_code: CrawlOutcomeCode) -> CrawlAuditPayload:
    return CrawlAuditPayload(
        tenant_id=uuid4(),
        website_id=uuid4(),
        website_url="https://example.com",
        website_name="Example",
        website_owner_id=uuid4(),
        pages_crawled=3 if successful else 0,
        pages_failed=0,
        pages_hash_retained=2,
        pages_source_retained=1,
        files_downloaded=1,
        files_failed=0,
        files_hash_retained=1,
        files_too_large_skipped=0,
        blobs_deleted=0,
        successful=successful,
        outcome_code=outcome_code,
    )


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    calls = _Recorder()

    async def fake_update_crawl_circuit_breaker(
        sess: object,
        *,
        website_id: object,
        tenant_id: object,
        website_url: str,
        crawl_successful: bool,
    ) -> None:
        calls.circuit_breaker_success_values.append(crawl_successful)

    async def fake_record_crawl_audit(
        audit_service: AuditService,
        payload: CrawlAuditPayload,
    ) -> None:
        calls.events.append("audit")
        calls.audit_services.append(audit_service)
        calls.audit_payloads.append(payload)

    monkeypatch.setattr(
        post_terminal_effects_module,
        "update_crawl_circuit_breaker",
        fake_update_crawl_circuit_breaker,
    )
    monkeypatch.setattr(
        post_terminal_effects_module,
        "record_crawl_audit",
        fake_record_crawl_audit,
    )

    return calls


@pytest.mark.asyncio
async def test_apply_post_terminal_effects_records_success_before_audit(
    recorder: _Recorder,
) -> None:
    audit_service = _FakeAuditService()
    payload = _payload(
        successful=True,
        outcome_code=CrawlOutcomeCode.CRAWL_ALL_UNCHANGED,
    )

    await apply_post_terminal_effects(
        PostTerminalEffectInput(
            recovery_executor=recorder.execute_with_recovery,
            audit_service=audit_service,
            audit_payload=payload,
            circuit_breaker_operation_name="circuit_breaker_update",
        )
    )

    assert recorder.events == ["circuit-breaker", "audit"]
    assert recorder.circuit_breaker_success_values == [True]
    assert recorder.audit_services == [audit_service]
    assert recorder.audit_payloads == [payload]
    assert (
        recorder.audit_payloads[0].outcome_code == CrawlOutcomeCode.CRAWL_ALL_UNCHANGED
    )
    assert recorder.audit_payloads[0].successful is True


@pytest.mark.asyncio
async def test_apply_post_terminal_effects_records_failure_before_audit(
    recorder: _Recorder,
) -> None:
    audit_service = _FakeAuditService()
    payload = _payload(
        successful=False,
        outcome_code=CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
    )

    await apply_post_terminal_effects(
        PostTerminalEffectInput(
            recovery_executor=recorder.execute_with_recovery,
            audit_service=audit_service,
            audit_payload=payload,
            circuit_breaker_operation_name="circuit_breaker_update",
        )
    )

    assert recorder.events == ["circuit-breaker", "audit"]
    assert recorder.circuit_breaker_success_values == [False]
    assert recorder.audit_services == [audit_service]
    assert recorder.audit_payloads == [payload]
    assert recorder.audit_payloads[0].outcome_code == (
        CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED
    )
    assert recorder.audit_payloads[0].successful is False


@pytest.mark.asyncio
async def test_apply_post_terminal_effects_propagates_circuit_breaker_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _Recorder()

    async def failing_execute_with_recovery(
        *,
        operation_name: str,
        operation: Callable[[AsyncSession], Awaitable[None]],
    ) -> None:
        calls.events.append("circuit-breaker")
        raise RuntimeError("circuit breaker failed")

    async def fake_record_crawl_audit(
        audit_service: AuditService,
        payload: CrawlAuditPayload,
    ) -> None:
        calls.events.append("audit")

    monkeypatch.setattr(
        post_terminal_effects_module,
        "record_crawl_audit",
        fake_record_crawl_audit,
    )

    with pytest.raises(RuntimeError, match="circuit breaker failed"):
        await apply_post_terminal_effects(
            PostTerminalEffectInput(
                recovery_executor=failing_execute_with_recovery,
                audit_service=_FakeAuditService(),
                audit_payload=_payload(
                    successful=False,
                    outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
                ),
                circuit_breaker_operation_name="circuit_breaker_update",
            )
        )

    assert calls.events == ["circuit-breaker"]
