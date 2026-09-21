from __future__ import annotations

import json
import runpy
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.flow_run_error import FlowRunErrorDetails
from eneo.flows.flow_run_provenance import parse_attempt_provenance
from eneo.flows.runtime.step_deadline import current_step_deadline_scope
from eneo.flows.runtime.step_result_builder import build_attempt_provenance
from eneo.main.exceptions import (
    ProviderCapabilityRejectedException,
    TypedIOValidationException,
)
from eneo.model_providers.domain.provider_call_observer import (
    CompletionCallRequestFacts,
)
from tests.unittests.flows.test_text_sections import _case


async def test_summarize_fitting_material_uses_one_call_and_one_record(user):
    executor, repo, assistant, run, state, step, _, _, questions, _ = _case(
        user, text="A short municipal report."
    )
    step = replace(step, input_config={"text_processing": {"mode": "summarize"}})

    result = await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    assert result.output.structured_output == {"records": [{"value": "1"}]}
    assert len(questions) == 1
    assert assistant.get_response.call_args.kwargs["prepared_request"].fits
    assert repo.activate_step_attempt.await_count == 1


async def test_summarize_folds_section_records_in_one_fitting_call(user):
    executor, repo, _, run, state, step, _, file, questions, _ = _case(user)
    step = replace(step, input_config={"text_processing": {"mode": "summarize"}})

    result = await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    assert len(questions) > 2
    parents = json.loads(questions[-1])["records"]
    assert parents == [{"value": str(i)} for i in range(1, len(questions))]
    assert result.output.structured_output == {
        "records": [{"value": str(len(questions))}]
    }
    assert repo.activate_step_attempt.await_count == 1
    assert "summarization" not in result.output.output_payload_extensions
    lineage = result.output.summarization.model_dump(mode="json")
    assert lineage["rounds"] == 1
    assert lineage["records"][-1]["parents"] == [
        f"section:{i}" for i in range(len(parents))
    ]
    assert lineage["sources"][0]["file_id"] == str(file.id)
    assert [r["value"] for r in lineage["records"][:-1]] == parents
    assert (
        lineage["records"][-1]["value"] == result.output.structured_output["records"][0]
    )
    persisted = parse_attempt_provenance(build_attempt_provenance(output=result.output))
    assert persisted.status == "tracked"
    assert persisted.provenance.summarization.model_dump(mode="json") == lineage


def _fold_case(user, *, expands=False):
    case = _case(user, text="material " * 300)
    executor, repo, assistant, run, state, step, _, _, questions, progress = case
    step = replace(step, input_config={"text_processing": {"mode": "summarize"}})

    async def respond(**kwargs):
        scope = current_step_deadline_scope()
        progress.append((scope.completed_items, scope.total_items))
        question = kwargs["question"]
        questions.append(question)
        if question.startswith('{"records":'):
            parents = json.loads(question)["records"]
            size = sum(len(p["value"]) for p in parents) + 100 if expands else 40
        else:
            size = 190
        return SimpleNamespace(
            completion=json.dumps({"records": [{"value": "x" * size}]}),
            total_token_count=3,
        )

    assistant.get_response.side_effect = respond
    return executor, repo, assistant, run, state, step, questions, progress


async def test_summarize_groups_consecutive_records_and_reports_each_round(user):
    executor, _, assistant, run, state, step, questions, progress = _fold_case(user)

    result = await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    folds = [q for q in questions if q.startswith('{"records":')]
    assert len(folds) > 1
    lineage = result.output.summarization.model_dump(mode="json")
    assert lineage["rounds"] >= 2
    first_round = [r for r in lineage["records"] if r["round"] == 1]
    section_ids = [r["id"] for r in lineage["records"] if r["round"] == 0]
    assert [p for r in first_round for p in r["parents"]] == section_ids
    assert lineage["records"][-1]["section_indexes"] == list(range(len(section_ids)))
    assert (0, len(first_round)) in progress
    assert (len(first_round) - 1, len(first_round)) in progress
    assert progress[-1] == (0, 1)
    for call in assistant.get_response.call_args_list:
        package = call.kwargs["prepared_request"]
        assert package.fits
        assert any(
            measured.kwargs["question"] == call.kwargs["question"]
            for measured in assistant.preflight_response_context.call_args_list
        )


async def test_non_contracting_round_refuses_before_another_dispatch(user):
    executor, _, _, run, state, step, questions, _ = _fold_case(user, expands=True)

    with pytest.raises(TypedIOValidationException) as caught:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    assert caught.value.code == "flow_summarization_non_convergent"
    details = FlowRunErrorDetails.from_budget_context(caught.value.context)
    assert details.summarization_rounds == 1
    assert details.summarization_records > 1
    assert details.summarization_bytes > 0
    folds = [json.loads(q)["records"] for q in questions if q.startswith('{"records":')]
    assert folds
    assert all(len(record["value"]) == 190 for group in folds for record in group)


@pytest.mark.parametrize(
    "policy",
    [
        FlowMappedExecutionPolicy(max_provider_calls_per_mapped_step=None),
        FlowMappedExecutionPolicy(
            max_provider_calls_per_mapped_step=100,
            max_estimated_input_tokens_per_mapped_step=1,
        ),
        FlowMappedExecutionPolicy(max_provider_calls_per_mapped_step=2),
    ],
)
async def test_summarize_aggregate_limits_refuse_before_dispatch(user, policy):
    executor, _, _, run, state, step, questions, _ = _fold_case(user)
    executor.mapped_execution_policy = policy

    with pytest.raises(TypedIOValidationException) as caught:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    assert caught.value.code == "flow_summarization_non_convergent"
    assert questions == []
    assert FlowRunErrorDetails.from_budget_context(caught.value.context) is not None


@pytest.mark.parametrize("fail_fold_receipt", [False, True])
async def test_fold_inputs_commit_before_provider_dispatch(
    user, monkeypatch, fail_fold_receipt
):
    from eneo.database.tables.flow_tables import FlowProviderCalls
    from eneo.flows.infrastructure import flow_provider_call_recorder as module
    from eneo.flows.infrastructure.flow_provider_call_recorder import (
        ProviderCallEvidencePersistenceError,
    )
    from eneo.flows.infrastructure.flow_provider_call_repo import (
        FlowProviderCallRepository,
    )

    executor, repo, assistant, run, state, step, _, _, questions, _ = _case(user)
    step = replace(step, input_config={"text_processing": {"mode": "summarize"}})
    events = []
    requests = []

    @asynccontextmanager
    async def transaction():
        yield
        if fail_fold_receipt and requests[-1].summarization_input is not None:
            raise RuntimeError("Commit failed")
        events.append("commit")

    @asynccontextmanager
    async def connection():
        yield session

    async def start(**kwargs):
        requests.append(kwargs["request"])
        events.append("persist")
        return SimpleNamespace(id=uuid4(), ordinal=len(requests))

    session = SimpleNamespace(begin=transaction)
    monkeypatch.setattr(module.sessionmanager, "session", connection)
    monkeypatch.setattr(
        module,
        "FlowProviderCallRepository",
        lambda _: SimpleNamespace(start_call_for_execution=start),
    )
    respond = assistant.get_response.side_effect

    async def dispatch(**kwargs):
        await kwargs["provider_call_observer"].started(
            CompletionCallRequestFacts(
                request_schema_version=2,
                provider_request_hash="a" * 64,
                requested_model="test-model",
                provider="test",
                response_format="none",
                requested_capabilities=(),
                reason="initial",
            )
        )
        events.append("dispatch")
        response = await respond(**kwargs)
        if not kwargs["question"].startswith('{"records":'):
            response.completion = json.dumps(
                {"records": [{"value": f"å{len(questions)}"}]}
            )
        return response

    assistant.get_response.side_effect = dispatch
    if fail_fold_receipt:
        with pytest.raises(ProviderCallEvidencePersistenceError):
            await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
        assert events[-1] == "persist"
        assert len(questions) == len(requests) - 1
        assert not questions[-1].startswith('{"records":')
        return
    await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    assert events == [
        event for _ in questions for event in ("persist", "commit", "dispatch")
    ]
    assert repo.activate_step_attempt.await_count == 1
    descriptor = requests[-1].summarization_input
    assert descriptor.record_ids == tuple(
        f"section:{i}" for i in range(len(questions) - 1)
    )
    composed = questions[-1].encode("utf-8")
    assert len(composed) > len(questions[-1])
    assert descriptor.input_bytes == len(composed)
    assert descriptor.input_sha256 == sha256(composed).hexdigest()
    assert requests[-1].summarization_input.max_provider_calls > 0
    assert requests[-1].summarization_input.max_input_tokens > 0

    async def scalar(statement):
        if isinstance(statement, sa.sql.Select):
            return 0
        persisted = statement.compile().params["summarization_input"]
        assert set(persisted) == {
            "round",
            "group_index",
            "record_ids",
            "input_bytes",
            "input_sha256",
            "reserved_calls",
            "reserved_input_tokens",
            "max_provider_calls",
            "max_input_tokens",
        }
        assert "å" not in json.dumps(persisted, ensure_ascii=False)
        return FlowProviderCalls(
            id=uuid4(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            **statement.compile().params,
        )

    stored = await FlowProviderCallRepository(
        SimpleNamespace(scalar=scalar)
    )._insert_started_call(
        attempt_id=uuid4(),
        resolved_inputs_attempt_id=uuid4(),
        request=requests[-1],
        resolved_input_edge_indexes=(),
    )
    assert stored.summarization_input == requests[-1].summarization_input


async def test_fold_cannot_spend_the_section_stage_budget_twice(user):
    executor, _, _, run, state, step, section_questions, _ = _fold_case(user)
    await executor._execute_step(
        step=replace(
            step, input_config={"text_processing": {"mode": "process_each_section"}}
        ),
        run=run,
        state=state,
        attempt_no=1,
    )
    executor, _, _, run, state, step, questions, _ = _fold_case(user)
    executor.mapped_execution_policy = FlowMappedExecutionPolicy(
        max_provider_calls_per_mapped_step=len(section_questions) + 1
    )
    with pytest.raises(TypedIOValidationException) as caught:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    assert caught.value.code == "flow_summarization_non_convergent"
    assert len(questions) == len(section_questions)
    assert not any(q.startswith('{"records":') for q in questions)


async def test_fold_has_no_retrieval_and_inherits_parent_citations(user, monkeypatch):
    from eneo.flows.runtime.step_handlers import mapped_completion

    executor, _, assistant, run, state, step, _, _, questions, _ = _case(user)
    step = replace(step, input_config={"text_processing": {"mode": "summarize"}})
    source_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    make_records = mapped_completion.section_records

    def cited_records(records, outputs):
        return [
            record.model_copy(update={"citations": (source_id,)})
            for record in make_records(records, outputs)
        ]

    monkeypatch.setattr(mapped_completion, "section_records", cited_records)
    retrieval = executor._retrieve_rag_chunks

    async def checked_retrieval(**kwargs):
        assert not kwargs["question"].startswith('{"records":')
        return await retrieval(**kwargs)

    executor._retrieve_rag_chunks = checked_retrieval
    result = await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    assert questions[-1].startswith('{"records":')
    assert result.output.citation_sidecar["cited_source_ids"] == [source_id]
    assert result.output.citation_sidecar["direct_cited_source_ids"] == []
    assert result.output.summarization.records[-1].citations == (source_id,)


async def test_fold_uses_the_original_attempt_deadline(user, monkeypatch):
    from eneo.flows.runtime import step_deadline

    clock = [0.0]
    monkeypatch.setattr(step_deadline, "_now", lambda: clock[0])
    executor, _, assistant, run, state, step, questions, _ = _fold_case(user)
    executor._step_deadline_seconds = lambda step: 1.5
    respond = assistant.get_response.side_effect

    async def delayed(**kwargs):
        response = await respond(**kwargs)
        if kwargs["question"].startswith('{"records":'):
            clock[0] += 2
        return response

    assistant.get_response.side_effect = delayed
    with pytest.raises(TypedIOValidationException) as caught:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    assert caught.value.code == "flow_step_timeout"
    assert sum(q.startswith('{"records":') for q in questions) == 1


async def test_fallback_attempts_share_the_finite_call_and_token_budget(user):
    executor, _, assistant, run, state, step, _, _, questions, _ = _case(user)
    step = replace(step, input_config={"text_processing": {"mode": "summarize"}})
    respond = assistant.get_response.side_effect
    attempts = []

    async def reject_once(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise ProviderCapabilityRejectedException(
                "JSON format rejected",
                capability="response_format",
                retry_without_capability_safe=True,
                code="provider_capability_rejected",
            )
        return await respond(**kwargs)

    assistant.get_response.side_effect = reject_once
    await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    assert len(attempts) == len(questions) + 1
    assert attempts[1]["provider_call_reason"] == "capability_fallback"
    receipt = attempts[-1]["provider_call_observer"].summarization_input
    assert receipt.reserved_calls == len(attempts)
    assert receipt.reserved_input_tokens == sum(
        call["prepared_request"].input_reserve.tokens for call in attempts
    )


async def test_fold_failure_reports_progress_within_the_current_round(user):
    executor, _, assistant, run, state, step, questions, progress = _fold_case(user)
    respond = assistant.get_response.side_effect

    async def reject_fold(**kwargs):
        if kwargs["question"].startswith('{"records":'):
            raise TypedIOValidationException(
                "Rejected", code="typed_io_contract_violation"
            )
        return await respond(**kwargs)

    assistant.get_response.side_effect = reject_fold
    with pytest.raises(TypedIOValidationException) as caught:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    assert caught.value.completed_items == 0
    assert 0 < caught.value.total_items < len(questions)


@pytest.mark.parametrize("retained", [False, True])
def test_summarization_receipt_migration_preserves_existing_evidence(
    monkeypatch, retained
):
    from sqlalchemy.dialects.postgresql import dialect

    from eneo.database.tables.flow_tables import FlowProviderCalls

    migration = runpy.run_path(
        str(
            Path(__file__).parents[3]
            / "alembic/versions/202609211100_summarization_input.py"
        )
    )
    assert migration["revision"] == "202609211100"
    assert migration["down_revision"] == "202609201300"
    operations = MagicMock()
    for name in ("execute", "add_column", "drop_column", "get_bind"):
        monkeypatch.setattr(
            migration["upgrade"].__globals__["op"], name, getattr(operations, name)
        )
    migration["upgrade"]()
    table, column = operations.add_column.call_args.args
    assert table == "flow_provider_calls"
    assert column.name == "summarization_input"
    assert column.nullable and column.server_default is None
    assert type(column.type) is type(
        FlowProviderCalls.__table__.c.summarization_input.type
    )
    bind = FlowProviderCalls.__table__.c.summarization_input.type.bind_processor(
        dialect()
    )
    assert bind(None) is None
    operations.get_bind.return_value.execute.return_value.scalar_one.return_value = (
        retained
    )
    if retained:
        with pytest.raises(RuntimeError, match="Refusing to downgrade"):
            migration["downgrade"]()
        operations.drop_column.assert_not_called()
    else:
        migration["downgrade"]()
        operations.drop_column.assert_called_once_with(
            "flow_provider_calls", "summarization_input"
        )
