from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from eneo.flows.application.flow_run_evidence import omit_passages_beyond_view_budget
from eneo.flows.domain.flow import (
    FlowStepAttempt,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from eneo.flows.domain.rag_evidence import (
    MAPPED_CALLS_COMPLETE_KEY,
    RetrievedKnowledgeEvidence,
    apply_passage_disclosure,
    recompute_mapped_aggregates,
)
from eneo.flows.domain.rag_evidence_policy import FlowRagEvidencePolicy
from eneo.flows.domain.runtime import StepExecutionOutput
from eneo.flows.domain.runtime_invariant_exceptions import MappedEvidenceNestingError
from eneo.flows.runtime.rag_metadata import build_retrieved_knowledge_evidence
from eneo.flows.runtime.step_handlers.mapped_outputs import (
    MappedCallEvidence,
    carry_call_evidence,
)
from tests.fixtures import retrieved_info_blob_chunk


def _call_output(
    *, passage_text: str, policy: FlowRagEvidencePolicy
) -> StepExecutionOutput:
    evidence = build_retrieved_knowledge_evidence(
        [
            retrieved_info_blob_chunk(
                info_blob_id=uuid4(),
                info_blob_title="Källa",
                chunk_no=1,
                text=passage_text,
                score=0.9,
            )
        ],
        policy=policy,
    )
    rag_metadata: dict[str, Any] = evidence.write_into(
        {"status": "success", "unique_sources": len(evidence.sources)}
    )
    return StepExecutionOutput(
        input_text="",
        source_text="",
        input_source="flow_input",
        used_question_binding=False,
        full_text="",
        persisted_text="",
        generated_file_ids=[],
        tool_calls_metadata=None,
        num_tokens_input=None,
        num_tokens_output=None,
        effective_prompt="",
        model_parameters_json={},
        rag_metadata=rag_metadata,
    )


def _collector(
    policy: FlowRagEvidencePolicy,
    *,
    execution_mode: str = "per_item",
    collection_key: str = "items",
) -> MappedCallEvidence:
    return MappedCallEvidence(
        policy=policy,
        execution_mode=execution_mode,
        collection_key=collection_key,
    )


def test_mapped_step_without_retrieval_records_nothing() -> None:
    collector = _collector(FlowRagEvidencePolicy())

    assert collector.payload() is None
    assert collector.partial_payload() is None


def _run_mapped_step(
    *,
    policy: FlowRagEvidencePolicy,
    passage_texts: list[str],
    execution_mode: str = "per_item",
    collection_key: str = "items",
) -> dict[str, Any]:
    """Drive the real admission order: each call is bounded as it completes."""
    collector = _collector(
        policy, execution_mode=execution_mode, collection_key=collection_key
    )
    for passage_text in passage_texts:
        output = _call_output(passage_text=passage_text, policy=policy)
        collector.admit(output.rag_metadata)
    metadata = collector.payload()
    assert metadata is not None
    return metadata


def _assert_mapped_counters_agree(
    metadata: dict[str, Any], collection_key: str
) -> None:
    calls = metadata[collection_key]
    nested = [RetrievedKnowledgeEvidence.from_payload(call) for call in calls]
    assert metadata["sources_total"] == sum(len(call.sources) for call in nested)
    assert metadata["sources_with_recorded_passages"] == sum(
        call.sources_with_recorded_passages for call in nested
    )
    assert metadata["passages_recorded"] == sum(
        call.passages_recorded for call in nested
    )
    assert metadata["passages_truncated"] == sum(
        call.passages_truncated for call in nested
    )
    assert metadata["recorded_passage_bytes"] == sum(
        call.recorded_passage_bytes for call in nested
    )
    for call in calls:
        call_evidence = RetrievedKnowledgeEvidence.from_payload(call)
        assert call["passages_recorded"] == call_evidence.passages_recorded
        assert call["recorded_passage_bytes"] == call_evidence.recorded_passage_bytes
        assert (
            call["sources_with_recorded_passages"]
            == call_evidence.sources_with_recorded_passages
        )
        for reference in call["references"]:
            assert reference["recorded_passage_count"] == len(reference["passages"])


def test_mapped_calls_within_the_step_budget_keep_every_passage() -> None:
    policy = FlowRagEvidencePolicy(
        max_recorded_passage_bytes=200,
        max_recorded_passage_bytes_per_step=1000,
    )

    metadata = _run_mapped_step(policy=policy, passage_texts=["a" * 100] * 3)

    assert metadata["execution_mode"] == "per_item"
    assert metadata["sources_with_recorded_passages"] == 3
    assert metadata["passages_recorded"] == 3
    assert metadata["recorded_passage_bytes"] == 300
    assert metadata["passages_released_to_step_budget"] == 0
    assert len(metadata["items"]) == 3
    assert all(
        call["references"][0]["passages"][0]["text"] == "a" * 100
        for call in metadata["items"]
    )
    _assert_mapped_counters_agree(metadata, "items")


def test_mapped_fan_out_releases_passage_text_but_keeps_source_identity() -> None:
    policy = FlowRagEvidencePolicy(
        max_recorded_passage_bytes=200,
        max_recorded_passage_bytes_per_step=250,
    )

    metadata = _run_mapped_step(
        policy=policy,
        passage_texts=["a" * 100] * 4,
        execution_mode="per_source",
        collection_key="sources",
    )

    assert metadata["sources_with_recorded_passages"] == 2
    assert metadata["recorded_passage_bytes"] == 200
    assert metadata["passages_released_to_step_budget"] == 2
    assert metadata["passage_bytes_released_to_step_budget"] == 200

    calls = metadata["sources"]
    assert len(calls) == 4
    assert metadata["sources_total"] == 4
    assert [len(call["references"]) for call in calls] == [1, 1, 1, 1]
    assert all(call["references"][0]["id"] for call in calls)
    assert [len(call["references"][0]["passages"]) for call in calls] == [1, 1, 0, 0]
    assert all(call["references"][0]["matched_chunk_count"] == 1 for call in calls)
    _assert_mapped_counters_agree(metadata, "sources")


def test_a_failed_mapped_step_keeps_evidence_from_completed_calls() -> None:
    """Calls 1..N-1 really retrieved; a later failure must not erase them."""
    policy = FlowRagEvidencePolicy()
    collector = _collector(policy)
    for passage_text in ("first call passage", "second call passage"):
        collector.admit(
            _call_output(passage_text=passage_text, policy=policy).rag_metadata
        )

    failure = RuntimeError("mapped call 3 failed after retrieval")
    carry_call_evidence(
        failure,
        _call_output(passage_text="third call passage", policy=policy).rag_metadata,
    )
    collector.admit(getattr(failure, "rag_metadata", None))
    partial = collector.partial_payload()

    assert partial is not None
    assert partial[MAPPED_CALLS_COMPLETE_KEY] is False
    assert len(partial["items"]) == 3
    assert partial["sources_total"] == 3
    assert partial["passages_recorded"] == 3
    assert [
        call["references"][0]["passages"][0]["text"] for call in partial["items"]
    ] == ["first call passage", "second call passage", "third call passage"]
    _assert_mapped_counters_agree(partial, "items")


def test_a_completed_mapped_step_marks_its_calls_complete() -> None:
    metadata = _run_mapped_step(
        policy=FlowRagEvidencePolicy(), passage_texts=["only call"]
    )

    assert metadata[MAPPED_CALLS_COMPLETE_KEY] is True


def test_carry_call_evidence_never_overwrites_evidence_already_on_the_error() -> None:
    policy = FlowRagEvidencePolicy()
    original = _call_output(passage_text="original", policy=policy).rag_metadata
    later = _call_output(passage_text="later", policy=policy).rag_metadata
    failure = RuntimeError("boom")

    carry_call_evidence(failure, original)
    carry_call_evidence(failure, later)

    assert getattr(failure, "rag_metadata") is original


def test_withholding_recomputes_the_mapped_root_aggregates() -> None:
    """A mapped root has no references of its own, so its totals must re-derive."""
    metadata = _run_mapped_step(
        policy=FlowRagEvidencePolicy(), passage_texts=["a" * 40, "b" * 40]
    )
    assert metadata["passages_withheld"] == 0
    assert metadata["recorded_passage_bytes"] == 80

    withheld = apply_passage_disclosure(
        metadata, disclosure="text_withheld_sensitive_flow"
    )

    assert withheld["passages_withheld"] == 2
    assert withheld["passages_recorded"] == 2
    assert withheld["sources_total"] == 2
    assert withheld["recorded_passage_bytes"] == 80
    for call in withheld["items"]:
        assert call["passages_withheld"] == 1
        assert call["references"][0]["passages"][0]["text"] is None
    _assert_mapped_counters_agree(withheld, "items")


def test_a_mapped_call_containing_mapped_calls_is_rejected() -> None:
    """Mapped evidence nests one level; deeper structure fails closed."""
    policy = FlowRagEvidencePolicy()
    inner = _run_mapped_step(policy=policy, passage_texts=["inner passage"])

    with pytest.raises(MappedEvidenceNestingError):
        recompute_mapped_aggregates(
            {"execution_mode": "per_source", "sources": [inner]}
        )


def _attempt_with_passage(
    *,
    step_order: int,
    attempt_no: int,
    passage_text: str,
    policy: FlowRagEvidencePolicy,
) -> FlowStepAttempt:
    rag = _call_output(passage_text=passage_text, policy=policy).rag_metadata
    now = datetime.now(timezone.utc)
    return FlowStepAttempt(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        attempt_no=attempt_no,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        provenance_json={"rag": rag},
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )


def _step_result(*, step_order: int, current_attempt_no: int) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        current_attempt_no=current_attempt_no,
        status=FlowStepResultStatus.COMPLETED,
        created_at=now,
        updated_at=now,
    )


def test_a_run_view_bounds_total_passage_bytes_across_attempts() -> None:
    """Every attempt satisfies its own budget; the run must still be bounded."""
    policy = FlowRagEvidencePolicy()
    attempts = [
        _attempt_with_passage(
            step_order=1, attempt_no=attempt_no, passage_text="x" * 100, policy=policy
        )
        for attempt_no in (1, 2, 3)
    ]

    bounded, summary = omit_passages_beyond_view_budget(
        attempts,
        step_results=[_step_result(step_order=1, current_attempt_no=3)],
        byte_budget=150,
        count_truncated=False,
    )

    assert summary.byte_budget == 150
    assert summary.returned_passage_bytes == 100
    assert summary.passages_omitted == 2
    assert summary.passage_bytes_omitted == 200
    assert summary.attempts_with_omitted_passages == 2
    assert summary.count_truncated is False
    # The step view renders the current attempt, so that is the one admitted.
    current = next(item for item in bounded if item.attempt_no == 3)
    assert current.provenance_json is not None
    current_rag = current.provenance_json["rag"]
    assert current_rag["references"][0]["passages"][0]["text"] == "x" * 100
    for superseded in (item for item in bounded if item.attempt_no != 3):
        assert superseded.provenance_json is not None
        rag = superseded.provenance_json["rag"]
        # Source identity survives; only the passage text was released.
        assert rag["references"][0]["id"]
        assert rag["references"][0]["matched_chunk_count"] == 1
        assert rag["references"][0]["passages"] == []
        # A view omission is counted separately from what the runtime never recorded.
        assert rag["passages_omitted_from_view"] == 1
        assert rag["passages_released_to_step_budget"] == 0


def test_a_run_view_within_budget_releases_nothing() -> None:
    policy = FlowRagEvidencePolicy()
    attempts = [
        _attempt_with_passage(
            step_order=1, attempt_no=1, passage_text="y" * 50, policy=policy
        )
    ]

    bounded, summary = omit_passages_beyond_view_budget(
        attempts,
        step_results=[_step_result(step_order=1, current_attempt_no=1)],
        byte_budget=1024,
        count_truncated=False,
    )

    assert summary.omitted_any is False
    assert summary.passages_omitted == 0
    assert bounded[0].provenance_json is not None
    assert bounded[0].provenance_json["rag"]["references"][0]["passages"][0][
        "text"
    ] == ("y" * 50)
