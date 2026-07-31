"""Measure Flow run listing and redacted evidence with a reproducible workload.

The workload uses 600 measured runs (300 per Flow) so a 50-row page at offset
250 must perform meaningfully deeper work than the first page.

PostgreSQL planner, buffer, and timing values are observations, not capacity or
optimization claims. Retention and webhook values are recorded context only;
their canonical tests own those contracts.

By default the JSON report is written under pytest's tmp_path. Set
FLOW_RUN_LISTING_EVIDENCE_REPORT_PATH to a caller-controlled file path to retain
a report after the test process exits. No report belongs in the repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import tracemalloc
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import Random
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.infrastructure.data_retention_service import (
    RETENTION_BATCH_SIZE,
)
from eneo.database.tables.flow_tables import FlowRuns
from eneo.files.file_models import FileType
from eneo.files.file_service import FileService
from eneo.flows import FlowRepository, FlowVersionRepository
from eneo.flows.application.flow_run_evidence_service import (
    EMBEDDED_PROVIDER_CALL_LIMIT,
    FlowRunEvidenceService,
)
from eneo.flows.application.flow_run_service import (
    FlowRunPageWithResultFilesAndTokenUsage,
    FlowRunService,
)
from eneo.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_DELIVERY_BATCH_SIZE,
    FLOW_WEBHOOK_DELIVERY_CONCURRENCY,
    FLOW_WEBHOOK_DELIVERY_INTERVAL_SECONDS,
)
from eneo.flows.domain.flow import (
    Flow,
    FlowRunStatus,
    FlowStep,
    FlowStepResult,
)
from eneo.flows.domain.provider_call import (
    ProviderCallCompletion,
    ProviderCallRequest,
)
from eneo.flows.enums import FlowStepAttemptStatus, FlowStepResultStatus
from eneo.flows.flow_run_provenance import FlowResolvedInputEdges
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFileProjection
from eneo.flows.flow_run_step_result_file import FlowStepResultFileReference
from eneo.flows.flow_runtime_upload_repo import FlowRuntimeUploadRepository
from eneo.flows.infrastructure.flow_provider_call_repo import (
    FlowProviderCallRepository,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository, PreseedStep
from eneo.flows.principal import FlowPrincipal
from eneo.flows.published_definition import build_published_definition_json

REPORT_SCHEMA_VERSION = "flow-run-listing-evidence-measurement.v1"
WORKLOAD_SEED = 20260726
MEASURED_TENANT_RUNS = 600
RUNS_PER_FLOW = 300
EVIDENCE_STEP_COUNT = 5
ATTEMPTS_PER_STEP = 3
ATTEMPT_COUNT = EVIDENCE_STEP_COUNT * ATTEMPTS_PER_STEP
PROVIDER_CALL_COUNT = ATTEMPT_COUNT
INPUT_FILE_COUNT = 2
RESULT_FILE_COUNT = 1
# A heavier history for sizing the evidence view as it exists today. Steps,
# attempts, and provider calls all grow together here, so the probe shows what a
# larger run costs but does not isolate any single section's contribution.
HEAVY_STEP_COUNT = 20
HEAVY_ATTEMPTS_PER_STEP = 5
HEAVY_ATTEMPT_COUNT = HEAVY_STEP_COUNT * HEAVY_ATTEMPTS_PER_STEP
HEAVY_PROBE_RUNS = 1
PAGE_LIMIT = 50
DEEP_OFFSET = 250
# Run page, result-file rows, live and retained token aggregation, and
# final-output versions. Both token sources share one fixed-cost statement.
# A page that contains result files adds one durable-content-reference query;
# an empty result-file projection deliberately skips it.
RUN_LISTING_BASE_STATEMENT_COUNT = 4
RUN_LISTING_RESULT_FILE_REFERENCE_STATEMENT_COUNT = 1
# Access resolution, section measurements, bounded section loads, immutable
# resolved-input lineage, durable file projections, and run token usage are
# fixed-cost per bundle; none scales in statement count with the number of
# steps, attempts, provider calls, sources, or attached files.
EVIDENCE_QUERY_COUNT = 30
REPORT_PATH_ENV = "FLOW_RUN_LISTING_EVIDENCE_REPORT_PATH"
SECRET_SENTINEL = "flow-evidence-secret-20260726"
_BASE_TIME = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class _SeededWorkload:
    measured_tenant_id: UUID
    measured_flow_ids: tuple[UUID, UUID]
    representative_run_id: UUID
    heavy_run_id: UUID


@dataclass(frozen=True, slots=True)
class _CapturedStatement:
    sql: str
    parameters: tuple[object, ...]


@contextmanager
def _capture_queries(
    bind: Connection | Engine,
) -> Iterator[list[_CapturedStatement]]:
    captured: list[_CapturedStatement] = []

    def record(
        _connection: object,
        _cursor: object,
        statement: str,
        parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            assert isinstance(parameters, tuple)
            captured.append(_CapturedStatement(statement, parameters))

    sa.event.listen(bind, "before_cursor_execute", record)
    try:
        yield captured
    finally:
        sa.event.remove(bind, "before_cursor_execute", record)


def _next_uuid(random_source: Random) -> UUID:
    return UUID(int=random_source.getrandbits(128), version=4)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _completed_run_row(
    *,
    random_source: Random,
    flow_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    created_at: datetime,
    input_payload: dict[str, object],
    output_text: str,
) -> dict[str, object]:
    return {
        "id": _next_uuid(random_source),
        "created_at": created_at,
        "updated_at": created_at,
        "flow_id": flow_id,
        "flow_version": 1,
        "principal_type": "user",
        "principal_user_id": user_id,
        "tenant_id": tenant_id,
        "trace_id": _next_uuid(random_source),
        "status": "completed",
        "started_at": created_at,
        "finished_at": created_at + timedelta(seconds=1),
        "input_payload_json": input_payload,
        "output_payload_json": {"text": output_text},
    }


def _build_flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
    name: str,
    step_count: int,
) -> Flow:
    return Flow(
        tenant_id=tenant_id,
        space_id=space_id,
        name=name,
        created_by_user_id=user_id,
        owner_user_id=user_id,
        steps=[
            FlowStep(
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=step_order,
                input_source="flow_input" if step_order == 1 else "previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            )
            for step_order in range(1, step_count + 1)
        ],
    )


def _published_definition(flow: Flow) -> dict[str, object]:
    assert flow.id is not None
    steps: list[dict[str, object]] = []
    for step in flow.steps:
        assert step.id is not None
        payload = cast(
            dict[str, object],
            step.model_dump(
                mode="json",
                exclude={"id", "flow_id", "tenant_id", "created_at", "updated_at"},
            ),
        )
        payload["step_id"] = str(step.id)
        payload["assistant_id"] = str(step.assistant_id)
        steps.append(payload)
    return build_published_definition_json(
        flow_id=flow.id,
        name=flow.name,
        description=flow.description,
        metadata_json=flow.metadata_json,
        steps=steps,
    )


async def _create_flow(
    flow_repo: FlowRepository,
    version_repo: FlowVersionRepository,
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
    name: str,
    step_count: int,
) -> Flow:
    flow = await flow_repo.create(
        flow=_build_flow(
            tenant_id=tenant_id,
            space_id=space_id,
            user_id=user_id,
            assistant_id=assistant_id,
            name=name,
            step_count=step_count,
        ),
        tenant_id=tenant_id,
    )
    assert flow.id is not None
    await version_repo.create(
        flow_id=flow.id,
        version=1,
        definition_json=_published_definition(flow),
        tenant_id=flow.tenant_id,
    )
    return flow


async def _create_evidence_files(
    *,
    file_service: FileService,
) -> tuple[tuple[UUID, UUID], UUID]:
    file_ids: list[UUID] = []
    for name, text in (
        ("flow-evidence-input-1.txt", "Representative evidence input 1"),
        ("flow-evidence-input-2.txt", "Representative evidence input 2"),
        ("flow-evidence-result.txt", "Representative evidence result"),
    ):
        created = await file_service.save_generated_file(
            payload=text.encode(),
            name=name,
            mimetype="text/plain",
            file_type=FileType.TEXT,
        )
        file_ids.append(created.id)
    return (file_ids[0], file_ids[1]), file_ids[2]


async def _write_representative_evidence(
    *,
    session: AsyncSession,
    run_repo: FlowRunRepository,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    assistant_id: UUID,
    step_ids: tuple[UUID, ...],
    result_file_id: UUID,
    attempts_per_step: int = ATTEMPTS_PER_STEP,
) -> None:
    provider_repo = FlowProviderCallRepository(session=session)
    result_file_reference = FlowStepResultFileReference(
        file_id=result_file_id,
        source="generated_output",
    )
    final_step_order = len(step_ids)
    for step_order, step_id in enumerate(step_ids, start=1):
        predecessor_attempt_id: UUID | None = None
        for attempt_no in range(1, attempts_per_step + 1):
            attempt = await run_repo.create_or_get_attempt_started(
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step_id=step_id,
                step_order=step_order,
                attempt_no=attempt_no,
                celery_task_id=f"flow-evidence-{step_order}-{attempt_no}",
                predecessor_attempt_id=predecessor_attempt_id,
            )
            if attempt_no > 1:
                await run_repo.copy_step_input_files_from_predecessor_attempt(
                    run_id=run_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    step_id=step_id,
                    step_order=step_order,
                    predecessor_attempt_id=predecessor_attempt_id,
                    target_attempt_no=attempt_no,
                )
            activated = await run_repo.activate_step_attempt(
                run_id=run_id,
                step_id=step_id,
                attempt_no=attempt_no,
                tenant_id=tenant_id,
                resolved_input_edges=FlowResolvedInputEdges(
                    schema_version=1,
                    edges=(),
                ),
                attempt_input=None,
            )
            assert activated is not None
            provider_call = await provider_repo.start_call_for_execution(
                run_id=run_id,
                step_id=step_id,
                attempt_no=attempt_no,
                tenant_id=tenant_id,
                request=ProviderCallRequest(
                    provider_request_hash=_digest(
                        f"provider-{step_order}-{attempt_no}"
                    ),
                    requested_model="openai/gpt-4o-mini",
                    provider="openai",
                    requested_capabilities=(),
                ),
                resolved_input_edge_indexes=(),
            )
            await provider_repo.complete_call(
                call_id=provider_call.id,
                receipt=ProviderCallCompletion(
                    num_tokens_input=10 + step_order,
                    num_tokens_output=5 + attempt_no,
                    input_source="provider",
                    output_source="provider",
                ),
            )
            finished = await run_repo.finish_attempt(
                run_id=run_id,
                step_id=step_id,
                attempt_no=attempt_no,
                tenant_id=tenant_id,
                status=FlowStepAttemptStatus.COMPLETED,
                num_tokens_input=10 + step_order,
                num_tokens_output=5 + attempt_no,
            )
            assert finished is not None
            predecessor_attempt_id = attempt.id

        saved = await run_repo.save_step_result(
            flow_run_id=run_id,
            tenant_id=tenant_id,
            attempt_no=attempts_per_step,
            result_file_references=(
                [result_file_reference] if step_order == final_step_order else []
            ),
            result=FlowStepResult(
                flow_run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step_id=step_id,
                step_order=step_order,
                assistant_id=assistant_id,
                input_payload_json=(
                    {"authorization": f"Bearer {SECRET_SENTINEL}"}
                    if step_order == 1
                    else {"text": f"Input for step {step_order}"}
                ),
                output_payload_json={"text": f"Evidence result {step_order}"},
                status=FlowStepResultStatus.COMPLETED,
                created_at=_BASE_TIME,
                updated_at=_BASE_TIME,
            ),
        )
        assert saved is not None


async def _seed_workload(
    *,
    session: AsyncSession,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    file_service: FileService,
) -> _SeededWorkload:
    random_source = Random(WORKLOAD_SEED)
    model = await completion_model_factory(session, "flow-evidence-measurement-model")
    measured_space = await space_factory(
        session, "Flow run evidence measurement", [model.id]
    )
    assistant = await assistant_factory(
        session,
        "Flow run evidence measurement assistant",
        model.id,
        space_id=measured_space.id,
    )
    flow_repo = FlowRepository(session=session)
    version_repo = FlowVersionRepository(session=session)
    evidence_flow = await _create_flow(
        flow_repo,
        version_repo,
        tenant_id=admin_user.tenant_id,
        space_id=measured_space.id,
        user_id=admin_user.id,
        assistant_id=assistant.id,
        name="Flow evidence measurement",
        step_count=EVIDENCE_STEP_COUNT,
    )
    second_flow = await _create_flow(
        flow_repo,
        version_repo,
        tenant_id=admin_user.tenant_id,
        space_id=measured_space.id,
        user_id=admin_user.id,
        assistant_id=assistant.id,
        name="Flow listing comparison",
        step_count=1,
    )
    step_ids = tuple(cast(UUID, step.id) for step in evidence_flow.steps)

    principal = FlowPrincipal.from_user(admin_user)
    input_file_ids, result_file_id = await _create_evidence_files(
        file_service=file_service,
    )
    upload_repo = FlowRuntimeUploadRepository(session=session)
    for file_id in input_file_ids:
        await upload_repo.create(
            file_id=file_id,
            flow_id=evidence_flow.id,
            tenant_id=admin_user.tenant_id,
            uploaded_for_step_id=step_ids[0],
            principal=principal,
        )

    run_repo = FlowRunRepository(session=session)
    preseed_steps: list[PreseedStep] = [
        {
            "step_id": step_id,
            "step_order": step_order,
            "assistant_id": assistant.id,
        }
        for step_order, step_id in enumerate(step_ids, start=1)
    ]
    step_input_files: list[FlowRunStepInputFileProjection] = [
        {
            "step_id": step_ids[0],
            "step_order": 1,
            "file_ids": list(input_file_ids),
        }
    ]
    representative_run = await run_repo.create(
        flow_id=evidence_flow.id,
        flow_version=1,
        principal_type="user",
        principal_user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        input_payload_json={"api_key": SECRET_SENTINEL},
        preseed_steps=preseed_steps,
        step_input_files=step_input_files,
    )
    await _write_representative_evidence(
        session=session,
        run_repo=run_repo,
        run_id=representative_run.id,
        flow_id=evidence_flow.id,
        tenant_id=admin_user.tenant_id,
        assistant_id=assistant.id,
        step_ids=step_ids,
        result_file_id=result_file_id,
    )
    completed_run = await run_repo.terminalize_run_status(
        run_id=representative_run.id,
        tenant_id=admin_user.tenant_id,
        target_status=FlowRunStatus.COMPLETED,
        output_payload_json={"text": "Representative evidence result"},
    )
    assert completed_run is not None

    heavy_flow = await _create_flow(
        flow_repo,
        version_repo,
        tenant_id=admin_user.tenant_id,
        space_id=measured_space.id,
        user_id=admin_user.id,
        assistant_id=assistant.id,
        name="Flow evidence heavy history",
        step_count=HEAVY_STEP_COUNT,
    )
    heavy_step_ids = tuple(cast(UUID, step.id) for step in heavy_flow.steps)
    heavy_run = await run_repo.create(
        flow_id=heavy_flow.id,
        flow_version=1,
        principal_type="user",
        principal_user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        input_payload_json={"api_key": SECRET_SENTINEL},
        preseed_steps=[
            {
                "step_id": step_id,
                "step_order": step_order,
                "assistant_id": assistant.id,
            }
            for step_order, step_id in enumerate(heavy_step_ids, start=1)
        ],
        step_input_files=[],
    )
    await _write_representative_evidence(
        session=session,
        run_repo=run_repo,
        run_id=heavy_run.id,
        flow_id=heavy_flow.id,
        tenant_id=admin_user.tenant_id,
        assistant_id=assistant.id,
        step_ids=heavy_step_ids,
        result_file_id=result_file_id,
        attempts_per_step=HEAVY_ATTEMPTS_PER_STEP,
    )
    completed_heavy_run = await run_repo.terminalize_run_status(
        run_id=heavy_run.id,
        tenant_id=admin_user.tenant_id,
        target_status=FlowRunStatus.COMPLETED,
        output_payload_json={"text": "Heavy evidence result"},
    )
    assert completed_heavy_run is not None

    measured_flow_ids = (evidence_flow.id, second_flow.id)
    measured_rows = [
        _completed_run_row(
            random_source=random_source,
            flow_id=measured_flow_ids[run_index % 2],
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            created_at=_BASE_TIME - timedelta(seconds=run_index),
            input_payload={"workload_index": run_index},
            output_text=f"Result {run_index}",
        )
        for run_index in range(1, MEASURED_TENANT_RUNS)
    ]
    await session.execute(sa.insert(FlowRuns).values(measured_rows))

    return _SeededWorkload(
        measured_tenant_id=admin_user.tenant_id,
        measured_flow_ids=measured_flow_ids,
        representative_run_id=representative_run.id,
        heavy_run_id=heavy_run.id,
    )


def _json_object(value: object, *, label: str) -> dict[str, object]:
    assert isinstance(value, dict), f"{label} is not a JSON object"
    return cast(dict[str, object], value)


def _decode_explain(value: object) -> dict[str, object]:
    assert isinstance(value, list) and len(value) == 1
    return _json_object(value[0], label="EXPLAIN document")


def _statement_source(statement: str) -> str:
    normalized = " ".join(statement.split())
    _, separator, remainder = normalized.partition(" FROM ")
    return remainder.split(maxsplit=1)[0] if separator else "<cte>"


def _max_actual_rows(explain: dict[str, object]) -> float:
    plan = _json_object(explain.get("Plan"), label="EXPLAIN Plan")
    rows = plan.get("Actual Rows")
    maximum = float(rows) if isinstance(rows, (int, float)) else 0.0
    children = plan.get("Plans")
    if not isinstance(children, list):
        return maximum
    return max(
        (
            maximum,
            *(
                _max_actual_rows({"Plan": _json_object(child, label="plan node")})
                for child in children
            ),
        )
    )


async def _measure_run_listing_page(
    *,
    session: AsyncSession,
    run_service: FlowRunService,
    flow_id: UUID,
    offset: int,
    expected_statement_count: int,
) -> tuple[FlowRunPageWithResultFilesAndTokenUsage, list[dict[str, object]]]:
    bind = session.sync_session.bind
    assert bind is not None
    with _capture_queries(bind) as captured:
        page = await run_service.list_runs_with_result_files_and_token_usage(
            flow_id=flow_id,
            limit=PAGE_LIMIT,
            offset=offset,
        )
    assert len(captured) == expected_statement_count

    connection = await session.connection()
    statement_reports: list[dict[str, object]] = []
    for ordinal, captured_statement in enumerate(captured, start=1):
        result = await connection.exec_driver_sql(
            (f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {captured_statement.sql}"),
            captured_statement.parameters,
        )
        explain = _decode_explain(result.scalar_one())
        statement_reports.append(
            {
                "ordinal": ordinal,
                "sql": captured_statement.sql,
                "explain": explain,
            }
        )
    return page, statement_reports


async def _measure_evidence_assembly(
    *,
    session: AsyncSession,
    evidence_service: FlowRunEvidenceService,
    run_id: UUID,
) -> dict[str, object]:
    """Record what one redacted evidence response costs end to end.

    Peak traced bytes are Python allocations observed across assembly,
    redaction, projection, and serialization. This measures allocation, not
    object lifetime, so it says nothing about which representations are alive
    at the same moment.
    """
    bind = session.sync_session.bind
    assert bind is not None
    tracemalloc.start()
    try:
        with _capture_queries(bind) as queries:
            bundle = await evidence_service.get_redacted_evidence_bundle(run_id=run_id)
        serialized = json.dumps(
            bundle.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {
        "query_count": len(queries),
        "serialized_bytes": len(serialized),
        "peak_traced_bytes": peak_bytes,
        "section_counts": {
            "step_results": len(bundle.step_results),
            "step_attempts": len(bundle.step_attempts),
            "result_files": len(bundle.result_files),
            "review_checkpoints": len(bundle.review_checkpoints),
            "provider_calls": bundle.provider_calls.count,
            "provider_calls_total": bundle.provider_calls.total_count,
        },
    }


async def _run_count(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    flow_id: UUID | None = None,
) -> int:
    statement = (
        sa.select(sa.func.count())
        .select_from(FlowRuns)
        .where(FlowRuns.tenant_id == tenant_id)
    )
    if flow_id is not None:
        statement = statement.where(FlowRuns.flow_id == flow_id)
    return int(await session.scalar(statement) or 0)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_listing_and_evidence_measurement_contract(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    tmp_path: Path,
) -> None:
    async with db_container(user=admin_user) as container:
        session = container.session()
        workload = await _seed_workload(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
            file_service=container.file_service(),
        )

        measured_count = await _run_count(
            session,
            tenant_id=workload.measured_tenant_id,
        )
        measured_flow_count_values: list[int] = []
        for flow_id in workload.measured_flow_ids:
            measured_flow_count_values.append(
                await _run_count(
                    session,
                    tenant_id=workload.measured_tenant_id,
                    flow_id=flow_id,
                )
            )
        measured_flow_counts = tuple(measured_flow_count_values)
        # The heavy probe lives on its own Flow, so it adds to the tenant total
        # while leaving the two listed Flows at their measured page depth.
        assert measured_count == MEASURED_TENANT_RUNS + HEAVY_PROBE_RUNS
        assert measured_flow_counts == (RUNS_PER_FLOW, RUNS_PER_FLOW)

        await session.execute(sa.text("ANALYZE flow_runs"))
        run_service = container.flow_run_service()
        page_reports: dict[str, object] = {}
        for name, offset, expected_has_more, expected_statement_count in (
            (
                "shallow",
                0,
                True,
                RUN_LISTING_BASE_STATEMENT_COUNT
                + RUN_LISTING_RESULT_FILE_REFERENCE_STATEMENT_COUNT,
            ),
            ("deep", DEEP_OFFSET, False, RUN_LISTING_BASE_STATEMENT_COUNT),
        ):
            page, statement_reports = await _measure_run_listing_page(
                session=session,
                run_service=run_service,
                flow_id=workload.measured_flow_ids[0],
                offset=offset,
                expected_statement_count=expected_statement_count,
            )
            assert len(page.items) == PAGE_LIMIT
            assert page.has_more is expected_has_more
            assert all(
                item.run.tenant_id == workload.measured_tenant_id
                and item.run.flow_id == workload.measured_flow_ids[0]
                for item in page.items
            )
            if name == "deep":
                run_query_explain = cast(
                    dict[str, object],
                    statement_reports[0]["explain"],
                )
                assert _max_actual_rows(run_query_explain) >= DEEP_OFFSET + PAGE_LIMIT
            page_reports[name] = {
                "scope": "public_flow_run_listing_service",
                "offset": offset,
                "limit": PAGE_LIMIT,
                "authorized_rows": len(page.items),
                "has_more": page.has_more,
                "statement_count": len(statement_reports),
                "statements": statement_reports,
            }

        bind = session.sync_session.bind
        assert bind is not None
        with _capture_queries(bind) as evidence_queries:
            evidence_bundle = await (
                container.flow_run_evidence_service().get_redacted_evidence_bundle(
                    run_id=workload.representative_run_id
                )
            )

        evidence_payload = evidence_bundle.to_dict()
        serialized_evidence = json.dumps(
            evidence_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        serialized_text = serialized_evidence.decode()
        runtime_input_file_ids = {
            file_id
            for step_result in evidence_bundle.step_results
            for file_id in cast(list[str], step_result["runtime_input_file_ids"])
        }
        section_counts = {
            "step_results": len(evidence_bundle.step_results),
            "step_attempts": len(evidence_bundle.step_attempts),
            "runtime_input_files": len(runtime_input_file_ids),
            "result_files": len(evidence_bundle.result_files),
            "rerun_operations": len(evidence_bundle.rerun_operations),
            "rerun_invalidated_steps": len(evidence_bundle.rerun_invalidated_steps),
            "review_checkpoints": len(evidence_bundle.review_checkpoints),
            "webhook_deliveries": len(evidence_bundle.webhook_deliveries),
            "provider_calls": evidence_bundle.provider_calls.count,
        }
        evidence_query_sources = Counter(
            _statement_source(query.sql) for query in evidence_queries
        )
        assert len(evidence_queries) == EVIDENCE_QUERY_COUNT, "\n".join(
            f"{count} × {source}"
            for source, count in sorted(evidence_query_sources.items())
        )
        assert section_counts["step_results"] == EVIDENCE_STEP_COUNT
        assert section_counts["step_attempts"] == ATTEMPT_COUNT
        assert section_counts["runtime_input_files"] == INPUT_FILE_COUNT
        assert section_counts["result_files"] == RESULT_FILE_COUNT
        assert evidence_bundle.provider_calls.count == PROVIDER_CALL_COUNT
        assert evidence_bundle.provider_calls.total_count == PROVIDER_CALL_COUNT
        assert evidence_bundle.provider_calls.has_more is False
        assert SECRET_SENTINEL not in serialized_text
        expected_masked_paths = {
            "bundle.run.input_payload_json.api_key",
            "bundle.step_results[0].input_payload_json.authorization",
        }
        assert expected_masked_paths <= set(evidence_bundle.masked_paths)

        evidence_service = container.flow_run_evidence_service()
        representative_cost = await _measure_evidence_assembly(
            session=session,
            evidence_service=evidence_service,
            run_id=workload.representative_run_id,
        )
        heavy_cost = await _measure_evidence_assembly(
            session=session,
            evidence_service=evidence_service,
            run_id=workload.heavy_run_id,
        )
        heavy_sections = cast(dict[str, object], heavy_cost["section_counts"])
        assert heavy_sections["step_attempts"] == HEAVY_ATTEMPT_COUNT
        assert heavy_sections["provider_calls_total"] == HEAVY_ATTEMPT_COUNT

        report: dict[str, object] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "workload": {
                "seed": WORKLOAD_SEED,
                "tenant_count": 1,
                "measured_tenant_runs": measured_count,
                "measured_flow_runs": list(measured_flow_counts),
                "evidence_steps": EVIDENCE_STEP_COUNT,
                "attempt_count": ATTEMPT_COUNT,
                "attempts_per_step": ATTEMPTS_PER_STEP,
                "input_files": INPUT_FILE_COUNT,
                "result_files": RESULT_FILE_COUNT,
                "provider_calls": PROVIDER_CALL_COUNT,
            },
            "flow_run_listing": {
                "analyze_before_explain": True,
                "pages": page_reports,
            },
            "evidence": {
                "query_count": len(evidence_queries),
                "queries": [
                    {
                        "ordinal": ordinal,
                        "sql": statement.sql,
                    }
                    for ordinal, statement in enumerate(evidence_queries, start=1)
                ],
                "section_counts": section_counts,
                "serialized_bytes": {
                    "bytes": len(serialized_evidence),
                    "embedded_provider_call_limit": EMBEDDED_PROVIDER_CALL_LIMIT,
                    "embedded_provider_call_count": evidence_bundle.provider_calls.count,
                },
                "redaction_proof": {
                    "secret_absent": SECRET_SENTINEL not in serialized_text,
                    "masked_paths": list(evidence_bundle.masked_paths),
                },
            },
            "evidence_assembly_cost": {
                "note": (
                    "Two observations of the evidence view as it exists today. "
                    "Peak traced bytes are Python allocations during assembly, "
                    "redaction, projection, and serialization. Steps, attempts, "
                    "and provider calls vary together, so no single section's "
                    "contribution is isolated, and this says nothing about "
                    "latency, concurrent requests, or any section the evidence "
                    "path does not yet read."
                ),
                "representative": representative_cost,
                "heavy": heavy_cost,
                "heavy_workload": {
                    "steps": HEAVY_STEP_COUNT,
                    "attempts_per_step": HEAVY_ATTEMPTS_PER_STEP,
                    "attempts": HEAVY_ATTEMPT_COUNT,
                },
            },
            "production_constants": {
                "retention_batch_size": RETENTION_BATCH_SIZE,
                "webhook": {
                    "batch_size": FLOW_WEBHOOK_DELIVERY_BATCH_SIZE,
                    "interval_seconds": FLOW_WEBHOOK_DELIVERY_INTERVAL_SECONDS,
                    "concurrency": FLOW_WEBHOOK_DELIVERY_CONCURRENCY,
                },
            },
        }

        report_path = Path(
            os.environ.get(
                REPORT_PATH_ENV,
                str(tmp_path / f"{REPORT_SCHEMA_VERSION}.json"),
            )
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"{REPORT_SCHEMA_VERSION} report={report_path}")
