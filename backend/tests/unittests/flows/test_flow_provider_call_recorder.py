from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from eneo.flows.domain.provider_call_evidence_gap import ProviderCallEvidenceGap
from eneo.flows.infrastructure.flow_provider_call_recorder import (
    FlowProviderCallRecorder,
    ProviderCallEvidencePersistenceError,
)


def _facts() -> ProviderCallEvidenceGap:
    return ProviderCallEvidenceGap(
        call_id=None,
        provider_request_hash="b" * 64,
        outcome="started",
    )


@pytest.mark.asyncio
async def test_transient_persistence_failure_retries_with_a_fresh_operation() -> None:
    transient = OperationalError(
        "insert",
        {},
        RuntimeError("connection lost"),
        connection_invalidated=True,
    )
    operation = AsyncMock(side_effect=[transient, transient, "persisted"])

    result = await FlowProviderCallRecorder._persist_with_retry(
        operation=operation,
        facts=_facts(),
    )

    assert result == "persisted"
    assert operation.await_count == 3


@pytest.mark.asyncio
async def test_non_transient_persistence_failure_fails_closed_without_retry() -> None:
    failure = OperationalError(
        "insert",
        {},
        RuntimeError("constraint failure"),
        connection_invalidated=False,
    )
    operation = AsyncMock(side_effect=failure)

    with pytest.raises(ProviderCallEvidencePersistenceError) as exc_info:
        await FlowProviderCallRecorder._persist_with_retry(
            operation=operation,
            facts=_facts(),
        )

    assert operation.await_count == 1
    assert exc_info.value.facts == _facts()
    assert str(exc_info.value) == (
        "The provider-call outcome could not be persisted after bounded retries."
    )
