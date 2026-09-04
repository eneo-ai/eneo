from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_flow_review import (
    COHORT_COMPLETED_LIMIT,
    AIBuilderFlowReviewService,
    EvidenceCompletenessFact,
    OutputNotObservedConsumedFact,
    RepeatedErrorCodeFact,
    StepShareFact,
    review_facts,
)
from eneo.flows.domain.flow import FlowRunStatusSnapshot
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.enums import FlowRunStatus
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdge,
    FlowResolvedInputEdges,
    FlowResolvedInputHashedSelection,
    FlowResolvedInputJsonPath,
    FlowResolvedInputStepResultSource,
    parse_resolved_input_edges,
)
from eneo.flows.infrastructure.flow_run_repo import (
    FlowStepLineage,
    FlowStepResultMetrics,
)
from eneo.main.exceptions import UnauthorizedException

_T0 = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _step(order: int, *, input_source: str = "previous_step") -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=order,
        assistant_id=uuid4(),
        user_description=f"Steg {order}",
        input_source="flow_input" if order == 1 else input_source,
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
    )


def _metric(
    run_id: UUID,
    step: RuntimeStep,
    *,
    status: str = "completed",
    error_code: str | None = None,
    tokens: int = 100,
    seconds: float = 1.0,
) -> FlowStepResultMetrics:
    return FlowStepResultMetrics(
        flow_run_id=run_id,
        step_id=step.step_id,
        step_order=step.step_order,
        status=status,
        error_code=error_code,
        num_tokens_input=tokens,
        num_tokens_output=0,
        started_at=_T0,
        finished_at=_T0 + timedelta(seconds=seconds),
    )


def _lineage(run_id: UUID, step: RuntimeStep, *sources: RuntimeStep) -> FlowStepLineage:
    aggregate = FlowResolvedInputEdges(
        schema_version=1,
        edges=tuple(
            FlowResolvedInputEdge(
                binding_ref=f"src-{index}",
                source=FlowResolvedInputStepResultSource(
                    kind="step_result",
                    source_step_id=source.step_id,
                    source_attempt_no=1,
                    selector=FlowResolvedInputJsonPath(kind="json_path", path=()),
                ),
                selection=FlowResolvedInputHashedSelection(
                    encoding="utf8", byte_size=3, sha256="0" * 64
                ),
            )
            for index, source in enumerate(sources)
        ),
    )
    edges = parse_resolved_input_edges(aggregate.model_dump(mode="json"))
    assert edges.status == "tracked", edges
    return FlowStepLineage(flow_run_id=run_id, step_id=step.step_id, edges=edges)


def _facts(**overrides: Any):
    keys = dict(flow_id=uuid4(), flow_version=3, definition_checksum="abc", **overrides)
    return review_facts(**keys)


def test_facts_name_the_unconsumed_output_the_repeated_error_and_the_dominant_step():
    s1, s2, s3 = _step(1), _step(2), _step(3)
    completed = [uuid4(), uuid4()]
    failed = [uuid4(), uuid4()]
    metrics = []
    lineage = []
    for run_id in completed:
        # Step 1 carries most tokens; step 3 reads step 1 only, so step 2's
        # output is never observed consumed.
        metrics += [
            _metric(run_id, s1, tokens=800, seconds=8.0),
            _metric(run_id, s2, tokens=100, seconds=1.0),
            _metric(run_id, s3, tokens=100, seconds=1.0),
        ]
        lineage += [_lineage(run_id, s2, s1), _lineage(run_id, s3, s1)]
    for run_id in failed:
        metrics += [
            _metric(run_id, s1),
            _metric(run_id, s2, status="failed", error_code="flow_step_timeout"),
        ]
    facts = _facts(
        steps=[s1, s2, s3],
        completed_run_ids=completed,
        failed_run_ids=failed,
        metrics=metrics,
        lineage=lineage,
    )
    by_kind = {}
    for fact in facts:
        by_kind.setdefault(fact.kind, []).append(fact)
    assert [f.step_order for f in by_kind["output_not_observed_consumed"]] == [2]
    assert isinstance(
        by_kind["output_not_observed_consumed"][0], OutputNotObservedConsumedFact
    )
    [error] = by_kind["repeated_error_code"]
    assert isinstance(error, RepeatedErrorCodeFact)
    assert (error.step_order, error.error_code, error.run_count) == (
        2,
        "flow_step_timeout",
        2,
    )
    [tokens] = by_kind["token_share"]
    [latency] = by_kind["latency_share"]
    assert (
        isinstance(tokens, StepShareFact)
        and tokens.step_order == 1
        and tokens.share == 0.8
    )
    assert latency.step_order == 1 and latency.share == 0.8
    [completeness] = by_kind["evidence_completeness"]
    assert isinstance(completeness, EvidenceCompletenessFact)
    # The failed runs stopped at step 2, so they miss step 3's result and have no lineage.
    assert (
        completeness.runs_with_all_step_results,
        completeness.runs_missing_step_results,
        completeness.runs_without_lineage,
    ) == (2, 2, 2)


def test_finding_ids_are_stable_for_a_version_and_change_with_it():
    s1, s2 = _step(1), _step(2)
    flow_id = uuid4()
    run_id = uuid4()
    kwargs = dict(
        steps=[s1, s2],
        completed_run_ids=[run_id],
        failed_run_ids=[],
        metrics=[_metric(run_id, s1), _metric(run_id, s2)],
        lineage=[],
    )
    first = review_facts(
        flow_id=flow_id, flow_version=1, definition_checksum="a", **kwargs
    )
    again = review_facts(
        flow_id=flow_id, flow_version=1, definition_checksum="a", **kwargs
    )
    other = review_facts(
        flow_id=flow_id, flow_version=2, definition_checksum="b", **kwargs
    )
    assert [f.finding_id for f in first] == [f.finding_id for f in again]
    assert {f.finding_id for f in first}.isdisjoint({f.finding_id for f in other})


def test_a_single_step_flow_has_no_consumption_or_share_facts():
    s1 = _step(1)
    run_id = uuid4()
    facts = _facts(
        steps=[s1],
        completed_run_ids=[run_id],
        failed_run_ids=[],
        metrics=[_metric(run_id, s1)],
        lineage=[],
    )
    assert [f.kind for f in facts] == ["evidence_completeness"]


def _snapshot(
    *,
    flow_id: UUID,
    tenant_id: UUID,
    version: int,
    status: FlowRunStatus,
    level: int | None,
    created_at: datetime,
) -> FlowRunStatusSnapshot:
    return FlowRunStatusSnapshot(
        id=uuid4(),
        flow_id=flow_id,
        flow_version=version,
        tenant_id=tenant_id,
        trace_id=uuid4(),
        status=status,
        evidence_classification_level=level,
        created_at=created_at,
        updated_at=created_at,
    )


def _service(user, *, flow, version, snapshots, denied: set[UUID]):
    async def _ensure(run, *, access_kind):
        assert access_kind == "evidence_view"
        if run.id in denied:
            raise UnauthorizedException("no")

    flow_run_repo = SimpleNamespace(
        list_statuses=AsyncMock(return_value=snapshots),
        list_step_result_metrics=AsyncMock(return_value=[]),
        list_current_attempt_lineage=AsyncMock(return_value=[]),
    )
    return (
        AIBuilderFlowReviewService(
            user=user,
            flow_repo=SimpleNamespace(get=AsyncMock(return_value=flow)),
            flow_run_repo=flow_run_repo,
            flow_version_repo=SimpleNamespace(get=AsyncMock(return_value=version)),
            access_policy=SimpleNamespace(ensure_can_access_run=_ensure),
        ),
        flow_run_repo,
    )


def _published(flow_id: UUID, *, version: int):
    step_id = uuid4()
    return SimpleNamespace(
        definition_checksum=f"sum-{version}",
        definition_json={
            "schema_version": 1,
            "flow_id": str(flow_id),
            "name": "Granska",
            "steps": [
                {
                    "step_id": str(step_id),
                    "step_order": 1,
                    "assistant_id": str(uuid4()),
                    "user_description": "Sammanfatta",
                    "input_source": "flow_input",
                    "output_mode": "pass_through",
                }
            ],
        },
    )


@pytest.mark.asyncio
async def test_packet_reads_only_viewable_runs_of_the_published_version_and_records_their_level(
    user,
):
    flow_id, space_id = uuid4(), uuid4()
    flow = SimpleNamespace(id=flow_id, space_id=space_id, published_version=2)
    mk = lambda version, status, level, minute: _snapshot(  # noqa: E731
        flow_id=flow_id,
        tenant_id=user.tenant_id,
        version=version,
        status=status,
        level=level,
        created_at=_T0 + timedelta(minutes=minute),
    )
    newest_ok = mk(2, FlowRunStatus.COMPLETED, 3, 5)
    denied = mk(2, FlowRunStatus.COMPLETED, 3, 4)
    legacy = mk(2, FlowRunStatus.FAILED, None, 3)
    older_version = mk(1, FlowRunStatus.COMPLETED, 1, 2)
    failed_ok = mk(2, FlowRunStatus.FAILED, 1, 1)
    service, flow_run_repo = _service(
        user,
        flow=flow,
        version=_published(flow_id, version=2),
        snapshots=[newest_ok, denied, legacy, older_version, failed_ok],
        denied={denied.id},
    )
    packet = await service.build_packet(flow_id=flow_id, space_id=space_id)
    assert packet.cohort.completed_run_ids == [newest_ok.id]
    assert packet.cohort.failed_run_ids == [failed_ok.id]
    assert packet.cohort.omitted.model_dump() == {
        "other_version": 1,
        "not_viewable": 1,
        "level_unknown": 1,
    }
    assert packet.evidence_classification_level == 3
    assert (packet.flow_version, packet.definition_checksum) == (2, "sum-2")
    assert [step.label for step in packet.steps] == ["Sammanfatta"]
    assert [fact.kind for fact in packet.facts] == ["evidence_completeness"]
    # Only the runs the packet read are fetched, and only their metadata.
    flow_run_repo.list_step_result_metrics.assert_awaited_once_with(
        tenant_id=user.tenant_id, run_ids=[newest_ok.id, failed_ok.id]
    )


@pytest.mark.asyncio
async def test_packet_caps_the_cohort_at_the_newest_completed_runs(user):
    flow_id, space_id = uuid4(), uuid4()
    flow = SimpleNamespace(id=flow_id, space_id=space_id, published_version=1)
    snapshots = [
        _snapshot(
            flow_id=flow_id,
            tenant_id=user.tenant_id,
            version=1,
            status=FlowRunStatus.COMPLETED,
            level=0,
            created_at=_T0 - timedelta(minutes=index),
        )
        for index in range(COHORT_COMPLETED_LIMIT + 5)
    ]
    service, _ = _service(
        user,
        flow=flow,
        version=_published(flow_id, version=1),
        snapshots=snapshots,
        denied=set(),
    )
    packet = await service.build_packet(flow_id=flow_id, space_id=space_id)
    assert packet.cohort.completed_run_ids == [
        s.id for s in snapshots[:COHORT_COMPLETED_LIMIT]
    ]


@pytest.mark.asyncio
async def test_packet_refuses_an_unpublished_flow_and_a_flow_outside_the_space(user):
    flow_id, space_id = uuid4(), uuid4()
    service, _ = _service(
        user,
        flow=SimpleNamespace(id=flow_id, space_id=space_id, published_version=None),
        version=None,
        snapshots=[],
        denied=set(),
    )
    with pytest.raises(AIBuilderBadRequestException) as unpublished:
        await service.build_packet(flow_id=flow_id, space_id=space_id)
    assert unpublished.value.code == AIBuilderErrorCode.FLOW_NOT_PUBLISHED
    with pytest.raises(AIBuilderBadRequestException) as mismatch:
        await service.build_packet(flow_id=flow_id, space_id=uuid4())
    assert mismatch.value.code == AIBuilderErrorCode.FLOW_SPACE_MISMATCH
