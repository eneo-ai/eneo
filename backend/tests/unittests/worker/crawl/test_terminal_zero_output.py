"""Terminal-zero-output ownership.

When a crawl completes with no usable output (no pages returned,
sitemap empty, files-only past the limit, timeout before any pages),
the worker must:

  1. Log the "Crawl produced no usable output" warning with the full
     diagnostics shape operators rely on.
  2. Commit one `TerminalEvent(outcome_code=...)` through
     `execute_with_recovery(...)` so retries are bounded to the same
     recovery budget the rest of `crawl_task(...)` enjoys.
  3. Apply post-terminal effects (audit + circuit-breaker + slot
     release) with a `CrawlAuditPayload` whose counters are all zero
     (because nothing was processed) except the too-large skip
     counter, which already captured the only successful-ish work the
     crawler did before terminating.
  4. Acknowledge the terminal commit on the `TaskManager` so the
     no-op orchestration doesn't subsequently flip the job status.

The inline implementation lived in `worker/crawl_tasks.py:1005-1094`
and tangled the crawl-task orchestration with the no-output terminator
policy. These tests pin the contract for the new
`worker/crawl/terminal_zero_output.py` boundary so the orchestration
can call a single typed function instead of inlining the recovery
plumbing + audit payload construction + acknowledgement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Coroutine
from uuid import UUID, uuid4

import pytest

from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_run import CrawlFileTooLargeSample, CrawlType
from intric.worker.crawl.terminal_zero_output import (
    CommitZeroOutputTerminalInput,
    commit_zero_output_terminal,
)


@dataclass
class _RecordedTerminalCommit:
    crawl_run_id: UUID
    job_id: UUID
    outcome_code: CrawlOutcomeCode
    result_location: str
    crawl_run_update_pages: int
    crawl_run_update_files_too_large: int


@dataclass
class _RecordedPostEffects:
    audit_payload_outcome: CrawlOutcomeCode
    audit_payload_files_too_large: int
    audit_payload_successful: bool
    circuit_breaker_operation_name: str


class _FakeTaskManager:
    def __init__(self) -> None:
        self.ack_calls: list[bool] = []

    def acknowledge_terminal_commit(self, *, successful: bool) -> None:
        self.ack_calls.append(successful)


class _FakeAuditService:
    """Stand-in audit service — the function only forwards it through
    to `apply_post_terminal_effects`, which is monkey-patched in tests.
    """


def _make_input(
    *,
    outcome_code: CrawlOutcomeCode = CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
    failure_message: str = "Crawl produced no pages",
    files_too_large_skipped: int = 0,
    files_too_large_download_limit_bytes: int | None = None,
    files_too_large_samples: tuple[CrawlFileTooLargeSample, ...] = (),
) -> CommitZeroOutputTerminalInput:
    return CommitZeroOutputTerminalInput(
        crawl_run_id=uuid4(),
        job_id=uuid4(),
        website_id=uuid4(),
        website_url="https://example.com",
        website_name="Example",
        website_owner_id=uuid4(),
        tenant_id=uuid4(),
        crawl_type=CrawlType.CRAWL,
        outcome_code=outcome_code,
        failure_message=failure_message,
        crawl_termination_reason="completed",
        diagnostics_log_fields={"items_count": 0},
        files_too_large_skipped=files_too_large_skipped,
        files_too_large_download_limit_bytes=files_too_large_download_limit_bytes,
        files_too_large_samples=files_too_large_samples,
    )


@pytest.fixture
def _patch_recovery_and_post_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[_RecordedTerminalCommit], list[_RecordedPostEffects]]:
    """Wire the module's two outbound seams to controllable fakes.

    `execute_with_recovery` and `apply_post_terminal_effects` are both
    module-level imports in `terminal_zero_output.py` — patching them
    here lets the test assert exactly what TerminalEvent + audit
    payload combination the function would commit, without spinning up
    a real DB session or the audit service.
    """
    from intric.worker.crawl import terminal_zero_output

    terminal_commits: list[_RecordedTerminalCommit] = []
    post_effects_calls: list[_RecordedPostEffects] = []

    async def fake_execute_with_recovery(
        *,
        operation_name: str,
        operation: Callable[[Any], Coroutine[Any, Any, None]],
        **_: Any,
    ) -> None:
        # The operation closes over a TerminalEvent — invoke it with a
        # fake session so the closure runs and the test can inspect the
        # event the function constructed.
        del operation_name  # operator log only

        class _CapturingSession:
            captured_event: Any = None

        captured: dict[str, Any] = {"event": None}

        async def fake_commit_terminal(_session: Any, event: Any) -> Any:
            captured["event"] = event

            class _Result:
                crawl_run_rows_updated = 1
                job_rows_updated = 1

            return _Result()

        monkeypatch.setattr(
            terminal_zero_output, "commit_terminal", fake_commit_terminal
        )
        await operation(_CapturingSession())
        event = captured["event"]
        assert event is not None
        terminal_commits.append(
            _RecordedTerminalCommit(
                crawl_run_id=event.crawl_run_id,
                job_id=event.job_id,
                outcome_code=event.outcome_code,
                result_location=event.result_location,
                crawl_run_update_pages=event.crawl_run_update.pages_crawled,
                crawl_run_update_files_too_large=(
                    event.crawl_run_update.files_too_large_skipped
                ),
            )
        )

    async def fake_apply_post_terminal_effects(input: Any) -> None:
        post_effects_calls.append(
            _RecordedPostEffects(
                audit_payload_outcome=input.audit_payload.outcome_code,
                audit_payload_files_too_large=(
                    input.audit_payload.files_too_large_skipped
                ),
                audit_payload_successful=input.audit_payload.successful,
                circuit_breaker_operation_name=input.circuit_breaker_operation_name,
            )
        )

    monkeypatch.setattr(
        terminal_zero_output,
        "execute_with_recovery",
        fake_execute_with_recovery,
    )
    monkeypatch.setattr(
        terminal_zero_output,
        "apply_post_terminal_effects",
        fake_apply_post_terminal_effects,
    )

    return terminal_commits, post_effects_calls


@pytest.mark.asyncio
async def test_commit_zero_output_terminal_records_failed_status_and_acks(
    _patch_recovery_and_post_effects: tuple[
        list[_RecordedTerminalCommit], list[_RecordedPostEffects]
    ],
) -> None:
    terminal_commits, post_effects_calls = _patch_recovery_and_post_effects
    input = _make_input()
    task_manager = _FakeTaskManager()

    result = await commit_zero_output_terminal(
        input,
        audit_service=_FakeAuditService(),  # type: ignore[arg-type]
        task_manager=task_manager,  # type: ignore[arg-type]
    )

    # The status dict crawl_task returns to ARQ — operators see this in
    # the job result. The outcome_code must round-trip the value
    # operators picked via `classify_crawl_outcome`.
    assert result == {
        "status": "failed",
        "outcome_code": CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED.value,
    }

    # The TaskManager ack happens exactly once with successful=False so
    # the no-output terminator doesn't double-write the job status via
    # the orchestration's outer exception handler.
    assert task_manager.ack_calls == [False]

    # One terminal commit, with all-zero counters EXCEPT the
    # too-large-skip pass-through (zero here because input default).
    assert len(terminal_commits) == 1
    commit = terminal_commits[0]
    assert commit.outcome_code == CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED
    assert commit.result_location == "Crawl produced no pages"
    assert commit.crawl_run_update_pages == 0
    assert commit.crawl_run_update_files_too_large == 0

    # One post-effects call, with the same outcome and the
    # files_too_large counter mirrored into the audit payload.
    assert len(post_effects_calls) == 1
    effects = post_effects_calls[0]
    assert effects.audit_payload_outcome == CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED
    assert effects.audit_payload_files_too_large == 0
    assert effects.audit_payload_successful is False
    assert effects.circuit_breaker_operation_name == "terminal_circuit_breaker_update"


@pytest.mark.asyncio
async def test_files_too_large_counter_propagates_to_terminal_and_audit(
    _patch_recovery_and_post_effects: tuple[
        list[_RecordedTerminalCommit], list[_RecordedPostEffects]
    ],
) -> None:
    """A "files-only over the size limit" crawl is still zero-output
    from the indexing perspective, but the files_too_large_skipped
    counter is the operator's signal that the limit was exercised.
    The terminal commit's `crawl_run_update` and the audit payload
    must both carry the counter so the admin retention drift signal
    + alert wiring stay accurate."""
    terminal_commits, post_effects_calls = _patch_recovery_and_post_effects
    input = _make_input(
        outcome_code=CrawlOutcomeCode.CRAWL_FILES_TOO_LARGE_ONLY,
        failure_message="Crawl found files, but they exceeded the download size limit",
        files_too_large_skipped=7,
        files_too_large_download_limit_bytes=1_048_576,
    )
    task_manager = _FakeTaskManager()

    result = await commit_zero_output_terminal(
        input,
        audit_service=_FakeAuditService(),  # type: ignore[arg-type]
        task_manager=task_manager,  # type: ignore[arg-type]
    )

    assert result["outcome_code"] == CrawlOutcomeCode.CRAWL_FILES_TOO_LARGE_ONLY.value
    assert terminal_commits[0].crawl_run_update_files_too_large == 7
    assert post_effects_calls[0].audit_payload_files_too_large == 7
