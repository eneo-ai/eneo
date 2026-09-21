from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from eneo.flows.domain.provider_call_evidence_gap import ProviderCallEvidenceGap
from eneo.flows.infrastructure.flow_provider_call_recorder import (
    FlowProviderCallRecorder,
    ProviderCallEvidencePersistenceError,
)
from tests.unittests.flows import audio_spool_test_support

spool_contract = audio_spool_test_support.spool_contract


@pytest.fixture
def accepted_call_recorder(monkeypatch):
    from eneo.database.tables.flow_tables import FlowProviderCalls
    from eneo.flows.infrastructure import flow_provider_call_recorder as module

    now = datetime.now(timezone.utc)
    row = FlowProviderCalls(
        id=uuid4(),
        flow_step_attempt_id=uuid4(),
        ordinal=1,
        call_kind="transcription",
        status="started",
        request_schema_version=2,
        provider_request_hash="a" * 64,
        requested_model="external/test",
        provider="external",
        response_format="none",
        requested_capabilities=[],
        resolved_input_edge_indexes=[],
        call_reason="initial",
        audio_seconds=42,
        requested_at=now,
        created_at=now,
        updated_at=now,
    )
    session = AsyncMock()
    session.scalar.return_value = row
    commits = []

    @asynccontextmanager
    async def transaction():
        original_id = row.provider_response_id
        try:
            yield
        except BaseException:
            row.provider_response_id = original_id
            raise
        commits.append(row.provider_response_id)

    @asynccontextmanager
    async def connection():
        yield session

    session.begin = MagicMock(side_effect=transaction)
    monkeypatch.setattr(module.sessionmanager, "session", connection)
    recorder = FlowProviderCallRecorder(
        run_id=uuid4(),
        step_id=uuid4(),
        attempt_no=1,
        tenant_id=uuid4(),
        principal_user_id=uuid4(),
        principal_service_id=None,
        completion_model_id=None,
        mapped_call=None,
        resolved_input_edge_indexes=(),
    )
    return recorder, row, session, commits


async def _accepted_transcriber(
    recorder, row, monkeypatch, spool_contract, *, result_timeout=10
):
    from eneo.flows.runtime import remote_transcription

    monkeypatch.setattr(recorder, "started", AsyncMock(return_value=row.id))
    requests = []

    def handle(request):
        requests.append(request.method)
        assert request.method in {"POST", "DELETE"}
        return httpx.Response(202, json={"job_id": "job-1"})

    transcriber = remote_transcription.RemoteFlowTranscriber(
        remote_transcription.RemoteTranscriptionClient(
            base_url="http://transcription.test",
            api_key="test",
            submit_timeout_seconds=10,
            poll_interval_seconds=0.001,
            result_timeout_seconds=result_timeout,
            transport=httpx.MockTransport(handle),
        )
    )
    file = SimpleNamespace(
        id=uuid4(), name="audio.mp3", mimetype="audio/mpeg", blob=b"audio"
    )
    return transcriber, await spool_contract.spool(file), requests


@pytest.mark.parametrize("cancelled", [False, True])
async def test_stalled_acceptance_is_bounded_and_preserves_gap_identity(
    spool_contract, accepted_call_recorder, monkeypatch, cancelled
):
    from eneo.flows.flow_run_error import FlowRunErrorDetails

    recorder, row, session, commits = accepted_call_recorder
    transcriber, file, requests = await _accepted_transcriber(
        recorder, row, monkeypatch, spool_contract, result_timeout=0.02
    )
    accepting = asyncio.Event()
    release = asyncio.Event()

    async def flush():
        if row.status == "started":
            accepting.set()
            await release.wait()

    session.flush.side_effect = flush
    task = asyncio.create_task(
        transcriber.transcribe(
            file, SimpleNamespace(), file_id=row.id, observer=recorder
        )
    )
    try:
        await asyncio.wait_for(accepting.wait(), timeout=1)
        if cancelled:
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=0.3)
        assert task in done, "acceptance bookkeeping exceeded its cleanup deadline"
        assert requests == ["POST", "DELETE"]
        assert not release.is_set()
        with pytest.raises(ProviderCallEvidencePersistenceError) as exc_info:
            task.result()
        details = FlowRunErrorDetails(provider_call_evidence_gap=exc_info.value.facts)
        gap = details.model_dump(mode="json")["provider_call_evidence_gap"]
        assert gap["call_id"] == str(row.id)
        assert gap["provider_response_id"] == "job-1"
        assert gap["outcome"] == "started"
        assert commits == []
    finally:
        if not task.done():
            task.cancel()
        release.set()
        try:
            await task
        except (asyncio.CancelledError, ProviderCallEvidencePersistenceError):
            pass


async def test_interrupted_cancel_after_stalled_acceptance_keeps_gap_identity(
    spool_contract, accepted_call_recorder, monkeypatch
):
    """An outer deadline during the DELETE must not replace the gap error."""
    from eneo.flows.flow_run_error import FlowRunErrorDetails

    recorder, row, session, commits = accepted_call_recorder
    transcriber, file, requests = await _accepted_transcriber(
        recorder, row, monkeypatch, spool_contract, result_timeout=0.02
    )
    release = asyncio.Event()

    async def flush():
        if row.status == "started":
            await release.wait()

    session.flush.side_effect = flush
    deleting = asyncio.Event()

    async def hanging_cancel(job_id, *, client=None):
        deleting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(transcriber.client, "cancel", hanging_cancel)

    async def run():
        async with asyncio.timeout(0.3):
            await transcriber.transcribe(
                file, SimpleNamespace(), file_id=row.id, observer=recorder
            )

    try:
        with pytest.raises(ProviderCallEvidencePersistenceError) as exc_info:
            await run()
        assert deleting.is_set()
        details = FlowRunErrorDetails(provider_call_evidence_gap=exc_info.value.facts)
        gap = details.model_dump(mode="json")["provider_call_evidence_gap"]
        assert gap["provider_response_id"] == "job-1"
        assert gap["outcome"] == "started"
        assert commits == []
    finally:
        release.set()


async def test_remote_releases_spool_after_acceptance_before_polling(
    accepted_call_recorder, monkeypatch, spool_contract
):
    from eneo.main.exceptions import OpenAIException

    recorder, row, _, commits = accepted_call_recorder
    transcriber, file, requests = await _accepted_transcriber(
        recorder, row, monkeypatch, spool_contract
    )

    async def wait_for_result(*args, **kwargs):
        assert commits == ["job-1"]
        assert not file.path.exists()
        raise OpenAIException("provider failure")

    transcriber.client.wait_for_result = wait_for_result
    with pytest.raises(OpenAIException):
        await transcriber.transcribe(
            file, SimpleNamespace(), file_id=row.id, observer=recorder
        )
    assert not file.path.exists()
    assert row.provider_response_id == "job-1"
    assert row.status == "outcome_unknown"
    assert commits == ["job-1", "job-1"]
    assert requests == ["POST"]


async def test_cancellation_during_acceptance_commits_job_identity(
    spool_contract, accepted_call_recorder, monkeypatch
):
    recorder, row, session, commits = accepted_call_recorder
    transcriber, file, requests = await _accepted_transcriber(
        recorder, row, monkeypatch, spool_contract
    )
    accepting = asyncio.Event()
    release = asyncio.Event()

    async def flush():
        if row.status == "started":
            accepting.set()
            await release.wait()

    session.flush.side_effect = flush
    task = asyncio.create_task(
        transcriber.transcribe(
            file, SimpleNamespace(), file_id=row.id, observer=recorder
        )
    )
    try:
        await asyncio.wait_for(accepting.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert row.provider_response_id == "job-1"
    assert row.status == "outcome_unknown"
    assert row.outcome_reason == "request_cancelled"
    assert commits == ["job-1", "job-1"]
    assert requests == ["POST", "DELETE"]


@pytest.mark.parametrize("terminal", ["rejected", "outcome_unknown"])
async def test_accepted_receipt_commits_and_retains_identity(
    accepted_call_recorder, terminal
):
    from eneo.flows.infrastructure.flow_provider_call_repo import (
        FlowProviderCallRepository,
    )

    recorder, row, session, commits = accepted_call_recorder
    await recorder.accepted(row.id, "job-1")
    assert commits == ["job-1"]
    assert row.status == "started"
    await recorder.accepted(row.id, "job-1")
    if terminal == "rejected":
        await recorder.rejected(row.id, "provider_rejected")
    else:
        await recorder.outcome_unknown(row.id, "provider_error")
    evidence = await FlowProviderCallRepository(session).get_call(call_id=row.id)
    assert evidence.status.value == terminal
    assert evidence.provider_response_id == "job-1"


async def test_completed_receipt_cannot_replace_accepted_identity(
    accepted_call_recorder,
):
    from eneo.model_providers.domain.provider_call_observer import (
        TranscriptionCallResultFacts,
    )

    recorder, row, _, _ = accepted_call_recorder
    await recorder.accepted(row.id, "job-1")
    with pytest.raises(ProviderCallEvidencePersistenceError):
        await recorder.completed(
            row.id,
            TranscriptionCallResultFacts(
                response_model="whisper", provider_response_id="other-job"
            ),
        )
    assert row.provider_response_id == "job-1"
    assert row.status == "started"


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


async def test_release_failure_after_acceptance_preserves_receipt_and_cancels_job(
    accepted_call_recorder, monkeypatch, spool_contract
):
    from pathlib import Path

    recorder, row, _, commits = accepted_call_recorder
    transcriber, file, requests = await _accepted_transcriber(
        recorder, row, monkeypatch, spool_contract
    )
    wait_for_result = AsyncMock()
    transcriber.client.wait_for_result = wait_for_result

    def fail_unlink(*args, **kwargs):
        raise OSError("cannot remove original")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_unlink)
        with pytest.raises(OSError, match="cannot remove original"):
            await transcriber.transcribe(
                file, SimpleNamespace(), file_id=row.id, observer=recorder
            )
    wait_for_result.assert_not_awaited()
    assert row.provider_response_id == "job-1"
    assert row.status == "outcome_unknown"
    assert commits == ["job-1", "job-1"]
    assert requests == ["POST", "DELETE"]
