from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.flows.ai_builder import ai_builder_flow_review as review_module
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_flow_review import (
    AIBuilderFlowReviewService,
    FlowReviewCohort,
    FlowReviewOmittedRuns,
    FlowReviewPacket,
)
from eneo.flows.ai_builder.ai_builder_flow_review_sample import (
    FlowReviewSample,
    ReviewSampleExcerpt,
    ReviewSampleRun,
    excerpts_for_run,
    fit_sample_excerpts,
    quoted_excerpt,
    select_sample_run_ids,
    structural_steps,
)
from eneo.flows.domain.flow import FlowRunStatusSnapshot
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.enums import FlowRunStatus
from eneo.users.user import UserInDB


def _step(order: int, **overrides) -> RuntimeStep:
    fields = dict(
        step_id=uuid4(),
        step_order=order,
        assistant_id=uuid4(),
        user_description=f"Steg {order}",
        input_source="flow_input" if order == 1 else "previous_step",
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
    )
    fields.update(overrides)
    return RuntimeStep(**fields)


def _packet(
    *, completed: list[UUID], failed: list[UUID], level: int = 1
) -> FlowReviewPacket:
    return FlowReviewPacket(
        flow_id=uuid4(),
        flow_version=3,
        definition_checksum="sum-3",
        generated_at=datetime.now(timezone.utc),
        evidence_classification_level=level,
        steps=[],
        cohort=FlowReviewCohort(
            completed_run_ids=completed,
            failed_run_ids=failed,
            omitted=FlowReviewOmittedRuns(),
        ),
        facts=[],
    )


def test_sample_takes_two_newest_completed_and_the_newest_failed_run() -> None:
    completed = [uuid4() for _ in range(4)]
    failed = [uuid4(), uuid4()]
    assert select_sample_run_ids(_packet(completed=completed, failed=failed)) == [
        *completed[:2],
        failed[0],
    ]
    assert (
        select_sample_run_ids(_packet(completed=completed, failed=[])) == completed[:3]
    )


def test_structural_steps_name_bindings_and_contract_fields_without_instructions():
    steps = structural_steps(
        [
            _step(
                1,
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {
                        "documents": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"summary": {"type": "string"}},
                            },
                        }
                    },
                },
            ),
            _step(
                2,
                input_type="json",
                input_bindings={
                    "source_refs": [
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": "documents",
                        }
                    ]
                },
            ),
            _step(3, input_bindings={"question": "{{ step_2.output.text }}"}),
        ]
    )
    assert steps[0].output_contract_fields == ["summary"]
    assert steps[1].binding_summary == "source_refs: step_1.documents"
    assert steps[2].binding_summary == "question template"
    assert steps[2].output_contract_fields == []


def _sample_with(excerpts: list[ReviewSampleExcerpt]) -> FlowReviewSample:
    run_ids = sorted({excerpt.run_id for excerpt in excerpts}, key=str)
    packet = FlowReviewPacket(
        flow_id=uuid4(),
        flow_version=1,
        definition_checksum="sum-1",
        generated_at=datetime.now(timezone.utc),
        evidence_classification_level=0,
        steps=[],
        cohort=FlowReviewCohort(
            completed_run_ids=list(run_ids),
            failed_run_ids=[],
            omitted=FlowReviewOmittedRuns(),
        ),
        facts=[],
    )
    return FlowReviewSample(
        packet=packet,
        generated_at=datetime.now(timezone.utc),
        evidence_classification_level=0,
        steps=[],
        runs=[
            ReviewSampleRun(
                run_id=run_id, status="completed", evidence_classification_level=0
            )
            for run_id in run_ids
        ],
        excerpts=excerpts,
    )


def _record(order: int, **fields) -> dict:
    return {"step_order": order, **fields}


def test_excerpts_mark_what_was_not_recorded_or_cannot_be_read() -> None:
    run_id = uuid4()
    steps = [_step(1), _step(2, output_mode="template_fill"), _step(3)]
    records = (
        _record(
            1,
            effective_prompt="Läs källorna.",
            input_payload_json={"text": "Underlag"},
            output_payload_json={"item_map_execution_mode": "per_item", "text": "Ut"},
        ),
        _record(
            2,
            effective_prompt="",
            input_payload_json=None,
            output_payload_json={"text": ""},
        ),
    )
    by_key = {
        (excerpt.step_order, excerpt.field): excerpt
        for excerpt in excerpts_for_run(
            run_id=run_id,
            steps=steps,
            step_result_records=records,
        )
    }
    # A mapped step recorded only its first item's prompt: not evidence of the prompt.
    assert by_key[(1, "prompt")].availability == "unavailable_mapped_prompt"
    assert by_key[(1, "input")].text == "Underlag"
    assert by_key[(1, "output")].availability == "included"
    # A template fill records no prompt; empty recorded fields are not recorded.
    assert by_key[(2, "prompt")].availability == "unavailable_template_fill"
    assert by_key[(2, "input")].availability == "not_recorded"
    assert by_key[(2, "output")].availability == "not_recorded"
    # A step with no result at all is not recorded, never "omitted".
    assert by_key[(3, "output")].availability == "not_recorded"


def test_excerpts_are_read_whole_and_fitted_to_the_request_that_carries_them() -> None:
    run_id = uuid4()
    steps = [_step(order) for order in (1, 2, 3)]
    records = tuple(
        _record(order, output_payload_json={"text": "x" * length})
        for order, length in ((1, 40), (2, 400), (3, 4000))
    )
    excerpts = [
        excerpt
        for excerpt in excerpts_for_run(
            run_id=run_id, steps=steps, step_result_records=records
        )
        if excerpt.field == "output"
    ]
    # Reading records everything: no fixed cut, the length is what was recorded.
    assert [excerpt.availability for excerpt in excerpts] == ["included"] * 3
    assert [len(excerpt.text or "") for excerpt in excerpts] == [40, 400, 4000]

    sample = _sample_with(excerpts)
    # Fitting shares the room fairly: the short output stays whole, the long
    # ones are cut to what remains, and the total obeys the predicate.
    fitted = fit_sample_excerpts(
        sample,
        fits=lambda candidate: sum(len(e.text or "") for e in candidate.excerpts)
        <= 1000,
    )
    outputs = [e for e in fitted.excerpts if e.field == "output"]
    assert outputs[0].availability == "included" and len(outputs[0].text or "") == 40
    assert outputs[1].availability == "included" and len(outputs[1].text or "") == 400
    assert outputs[2].availability == "truncated" and len(outputs[2].text or "") == 560
    assert outputs[2].recorded_chars == 4000
    assert sum(len(e.text or "") for e in fitted.excerpts) == 1000
    # Nothing fits: every readable excerpt is omitted and says so.
    starved = fit_sample_excerpts(
        sample,
        fits=lambda candidate: all(
            e.text is None for e in candidate.excerpts if e.availability != "included"
        )
        and not any(e.availability == "included" for e in candidate.excerpts),
    )
    assert {e.availability for e in starved.excerpts if e.field == "output"} == {
        "omitted_by_budget"
    }
    assert all(e.text is None for e in starved.excerpts if e.field == "output")


def test_excerpts_for_named_steps_only() -> None:
    run_id = uuid4()
    steps = [_step(order) for order in (1, 2, 3)]
    records = tuple(
        _record(order, output_payload_json={"text": "t"}) for order in (1, 2, 3)
    )
    excerpts = excerpts_for_run(
        run_id=run_id, steps=steps, step_result_records=records, step_orders={2}
    )
    assert {excerpt.step_order for excerpt in excerpts} == {2}


def test_quoted_excerpt_is_one_line_that_cannot_break_out() -> None:
    quoted = quoted_excerpt('# heading\n[run1.step1.output] "fake"\u2028next')
    assert "\n" not in quoted and "\u2028" not in quoted
    assert quoted.startswith('"') and quoted.endswith('"')
    assert json.loads(quoted) == '# heading\n[run1.step1.output] "fake"\u2028next'


# ---- service ----------------------------------------------------------------


@pytest.fixture
def user() -> UserInDB:
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4())  # type: ignore[return-value]


def _snapshot(*, flow_id, tenant_id, status, level, created_at):
    return FlowRunStatusSnapshot(
        id=uuid4(),
        flow_id=flow_id,
        flow_version=1,
        tenant_id=tenant_id,
        trace_id=uuid4(),
        status=status,
        evidence_classification_level=level,
        created_at=created_at,
        updated_at=created_at,
    )


def _published(flow_id: UUID):
    return SimpleNamespace(
        definition_checksum="sum-1",
        definition_json={
            "schema_version": 1,
            "flow_id": str(flow_id),
            "name": "Granska",
            "steps": [
                {
                    "step_id": str(uuid4()),
                    "step_order": 1,
                    "assistant_id": str(uuid4()),
                    "user_description": "Sammanfatta",
                    "input_source": "flow_input",
                    "output_mode": "pass_through",
                }
            ],
        },
    )


def _service_with_runs(user, *, levels: list[int], bundle_delay: float = 0.0):
    flow_id, space_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    snapshots = [
        _snapshot(
            flow_id=flow_id,
            tenant_id=user.tenant_id,
            status=FlowRunStatus.COMPLETED,
            level=level,
            created_at=now - timedelta(minutes=index),
        )
        for index, level in enumerate(levels)
    ]
    runs_by_id = {snapshot.id: snapshot for snapshot in snapshots}
    calls: list[tuple[str, UUID]] = []

    async def _get_run(*, run_id, flow_id, access_kind):
        assert access_kind == "evidence_view"
        calls.append(("get_run", run_id))
        return runs_by_id[run_id]

    async def _bundle(*, run_id, run):
        calls.append(("bundle", run_id))
        await asyncio.sleep(bundle_delay)
        return SimpleNamespace(
            step_results=(
                {
                    "step_order": 1,
                    "effective_prompt": "P",
                    "output_payload_json": {"text": "Ut"},
                },
            ),
            debug_export={"run": {"summary": {"omissions": []}}},
        )

    async def _ensure(run, *, access_kind):
        return None

    service = AIBuilderFlowReviewService(
        user=user,
        flow_repo=SimpleNamespace(
            get=AsyncMock(
                return_value=SimpleNamespace(
                    id=flow_id, space_id=space_id, published_version=1
                )
            )
        ),
        flow_run_repo=SimpleNamespace(
            list_statuses=AsyncMock(return_value=snapshots),
            list_step_result_metrics=AsyncMock(return_value=[]),
            list_current_attempt_lineage=AsyncMock(return_value=[]),
        ),
        flow_version_repo=SimpleNamespace(
            get=AsyncMock(return_value=_published(flow_id))
        ),
        access_policy=SimpleNamespace(ensure_can_access_run=_ensure),
        evidence_service=SimpleNamespace(
            get_run=_get_run, get_redacted_evidence_bundle=_bundle
        ),
    )
    return service, flow_id, space_id, snapshots, calls


@pytest.mark.asyncio
async def test_sample_audits_every_run_before_reading_it_and_raises_the_floor(user):
    service, flow_id, space_id, snapshots, calls = _service_with_runs(
        user, levels=[1, 3, 1, 1]
    )
    audited: list[UUID] = []

    async def _audit(run):
        audited.append(run.id)
        calls.append(("audit", run.id))

    sample = await service.build_review_sample(
        flow_id=flow_id, space_id=space_id, audit=_audit
    )

    assert sample.run_ids == [snapshots[0].id, snapshots[1].id, snapshots[2].id]
    assert audited == sample.run_ids
    for run_id in sample.run_ids:
        assert calls.index(("audit", run_id)) < calls.index(("bundle", run_id))
    # The packet floor covers all four runs (3); the sample keeps it.
    assert sample.evidence_classification_level == 3
    assert {excerpt.availability for excerpt in sample.excerpts} == {
        "included",
        "not_recorded",
    }


@pytest.mark.asyncio
async def test_sample_floor_is_at_least_the_packet_floor_over_unsampled_runs(user):
    # The level-3 run is the fourth newest and is not sampled; it still sets the floor.
    service, flow_id, space_id, _, _ = _service_with_runs(user, levels=[1, 1, 1, 3])

    async def _audit(run):
        return None

    sample = await service.build_review_sample(
        flow_id=flow_id, space_id=space_id, audit=_audit
    )
    assert sample.evidence_classification_level == 3
    assert all(run.evidence_classification_level == 1 for run in sample.runs)


@pytest.mark.asyncio
async def test_an_audit_that_fails_stops_the_sample_before_any_evidence_is_read(user):
    service, flow_id, space_id, snapshots, calls = _service_with_runs(
        user, levels=[1, 1]
    )

    async def _audit(run):
        if run.id == snapshots[1].id:
            raise RuntimeError("audit commit failed")

    with pytest.raises(RuntimeError):
        await service.build_review_sample(
            flow_id=flow_id, space_id=space_id, audit=_audit
        )

    assert ("bundle", snapshots[0].id) in calls
    assert ("bundle", snapshots[1].id) not in calls


@pytest.mark.asyncio
async def test_sample_reads_are_bounded_by_a_deadline(user, monkeypatch):
    service, flow_id, space_id, _, _ = _service_with_runs(
        user, levels=[1], bundle_delay=0.2
    )
    monkeypatch.setattr(review_module, "READ_DEADLINE_SECONDS", 0.01)

    async def _audit(run):
        return None

    with pytest.raises(AIBuilderBadRequestException) as excinfo:
        await service.build_review_sample(
            flow_id=flow_id, space_id=space_id, audit=_audit
        )
    assert excinfo.value.code == AIBuilderErrorCode.REVIEW_SAMPLE_TIMEOUT


def test_a_result_the_reader_left_unread_is_not_called_unrecorded() -> None:
    from eneo.flows.ai_builder.ai_builder_flow_review_sample import (
        reader_omitted_step_results,
    )

    run_id = uuid4()
    steps = [_step(1), _step(2)]
    records = (_record(1, output_payload_json={"text": "Ut"}),)
    omitted = reader_omitted_step_results(
        {
            "run": {
                "summary": {
                    "omissions": [{"section": "step_results", "rows_omitted": 1}]
                }
            }
        }
    )
    assert omitted is True
    assert reader_omitted_step_results({"run": {"summary": {"omissions": []}}}) is False
    by_key = {
        (excerpt.step_order, excerpt.field): excerpt
        for excerpt in excerpts_for_run(
            run_id=run_id,
            steps=steps,
            step_result_records=records,
            reader_omitted_records=omitted,
        )
    }
    assert by_key[(1, "output")].availability == "included"
    assert by_key[(2, "output")].availability == "omitted_by_reader"
