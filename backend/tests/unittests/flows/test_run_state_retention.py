"""What a run holds on to while a later step runs.

A run keeps each completed step's output for the steps that read it. These
tests pin that it keeps nothing else alive across steps: not the step's input
copies or prompt, not the full rows it read or wrote, not the previous step's
output object, and not a mapped step's finished item calls. The values later
steps resolve and everything the run persists stay the same.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import dataclasses
import enum
import gc
import hashlib
import json
import sys
import tracemalloc
import unittest.mock
import weakref
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    ToolCallMetadata,
)
from eneo.flows.domain import runtime as runtime_domain
from eneo.flows.domain.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepResult,
    FlowStepResultAnnotation,
    FlowStepResultStatus,
)
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep, StepDiagnostic
from eneo.flows.runtime.execution_state_builder import build_run_execution_state
from eneo.flows.runtime.executor import FlowRunExecutor
from eneo.flows.runtime.inherited_citations import collect_inherited_citation_context
from eneo.flows.runtime.step_failure_evidence import failure_evidence
from eneo.flows.runtime.step_handlers import per_item_map
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.exceptions import TypedIOValidationException
from tests.unit.flows.runtime.step_handlers import speaker_mapping_test_support
from tests.unit.flows.runtime.step_handlers.speaker_mapping_test_support import (
    SOURCE as SPEAKER_SOURCE,
)
from tests.unit.flows.runtime.step_handlers.speaker_mapping_test_support import (
    speaker_handler,
    speaker_step,
)
from tests.unittests.flows import executor_test_support
from tests.unittests.flows.executor_test_support import (
    build_flow_executor,
    build_step_executor,
    completed_grounded_result,
    completed_step_result,
    flow_run,
    mock_assistant_for_execute_step,
    published_flow_version,
    runtime_step,
)

active_snapshot_provider = executor_test_support.active_snapshot_provider
harness = speaker_mapping_test_support.harness

KiB = 1024


def _text(marker: str, size: int) -> str:
    """Distinct ASCII text of exactly `size` bytes."""
    unit = f"{marker} "
    return (unit * (size // len(unit) + 1))[:size]


def _completed_row(
    *, step_order: int, output: dict[str, Any], rag: dict[str, Any] | None = None
) -> FlowStepResult:
    """A completed step result with everything one stores about its input."""
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        current_attempt_no=2,
        input_payload_json={
            "text": _text(f"input-{step_order}", 4 * KiB),
            "text_truncated": False,
            "source_text": _text(f"source-{step_order}", 4 * KiB),
            "source_text_truncated": False,
            "material_aliases": [],
            "input_source": "flow_input",
            "used_question_binding": False,
            "effective_prompt_truncated": False,
            "runtime_input": {
                "text": f"runtime text {step_order}",
                "capture_mode": "flow_input",
            },
            "transcription": {"diarization": "external", "speakers": ["SPEAKER_00"]},
            "long_material": {"coverage": "complete", "sections": 3},
            "rag": rag or {"status": "skipped"},
            "contract_validation": {"parse_attempted": False},
            "diagnostics": [{"code": "note", "message": "kept", "severity": "info"}],
        },
        effective_prompt=_text(f"prompt-{step_order}", 2 * KiB),
        output_payload_json=output,
        model_parameters_json={"temperature": 0.2},
        num_tokens_input=5,
        num_tokens_output=7,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash=f"hash-{step_order}",
        created_at=now,
        updated_at=now,
    )


def _project(result: FlowStepResult) -> FlowStepResult:
    return runtime_domain.project_completed_result(result)


def _state(*results: FlowStepResult, **fields: Any) -> RunExecutionState:
    return RunExecutionState(
        completed_by_order={result.step_order: result for result in results},
        prior_results=list(results),
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        **fields,
    )


# --- The projection --------------------------------------------------------


def test_projection_drops_only_the_input_copies_and_the_prompt() -> None:
    row = _completed_row(
        step_order=1, output={"text": "answer", "structured": {"id": "out-1"}}
    )
    persisted = row.model_dump()

    projected = _project(row)

    assert row.model_dump() == persisted
    assert projected.model_dump() == {
        **persisted,
        "input_payload_json": {
            key: value
            for key, value in persisted["input_payload_json"].items()
            if key not in {"text", "source_text"}
        },
        "effective_prompt": None,
    }
    # Shallow: what later steps read is shared, not copied.
    assert projected.output_payload_json is row.output_payload_json
    assert row.input_payload_json is not None
    assert projected.input_payload_json is not None
    assert projected.input_payload_json["rag"] is row.input_payload_json["rag"]


def test_projection_of_a_row_without_input() -> None:
    row = _completed_row(step_order=1, output={"text": "answer"}).model_copy(
        update={"input_payload_json": None}
    )

    projected = _project(row)

    assert projected.input_payload_json is None
    assert projected.effective_prompt is None
    assert projected.output_payload_json is row.output_payload_json


def test_hydration_and_append_hold_projected_rows_in_the_same_order() -> None:
    first = _completed_row(step_order=1, output={"text": "first"})
    failed = _completed_row(step_order=2, output={"text": "failed"}).model_copy(
        update={"status": FlowStepResultStatus.FAILED}
    )
    third = _completed_row(step_order=3, output={"text": "third"})
    later_first = _completed_row(step_order=1, output={"text": "first again"})
    persisted = [first, failed, third, later_first]
    dumped = [row.model_dump() for row in persisted]

    state = build_run_execution_state(steps=[], persisted_results=persisted)

    assert [row.model_dump() for row in persisted] == dumped
    assert list(state.completed_by_order) == [1, 3]
    assert state.completed_by_order[1] == _project(later_first)
    assert state.completed_by_order[3] == _project(third)
    assert state.prior_results == [_project(later_first), _project(third)]
    assert state.prior_results[0] is state.completed_by_order[1]
    assert state.prior_results[1] is state.completed_by_order[3]

    fourth = _completed_row(step_order=4, output={"text": "fourth"})
    state.append_completed(fourth)
    retried_fourth = _completed_row(step_order=4, output={"text": "fourth again"})
    state.append_completed(retried_fourth)

    assert fourth.input_payload_json is not None
    assert "text" in fourth.input_payload_json
    assert state.completed_by_order[4] == _project(retried_fourth)
    assert state.prior_results[-2:] == [_project(fourth), _project(retried_fourth)]
    assert state.prior_results[-1] is state.completed_by_order[4]
    assert state.all_previous_text_before(5) == (
        "<step_1_output>\nfirst again\n</step_1_output>\n"
        "<step_3_output>\nthird\n</step_3_output>\n"
        "<step_4_output>\nfourth again\n</step_4_output>\n"
    )


# --- Readers of completed rows: a full row and its projection agree --------


def test_variables_and_their_evidence_resolve_alike_from_projected_rows() -> None:
    rows = [
        _completed_row(
            step_order=1,
            output={"text": "first output", "structured": {"id": "out-1", "n": 2}},
        ),
        _completed_row(step_order=2, output={"text": "second output"}),
    ]
    template = (
        "{{step_1.output.text}} | {{step_1.input.text}} | "
        "{{step_1.output.structured.id}} | {{föregående_steg}} | {{Named step}}"
    )
    resolver = FlowVariableResolver()

    def resolve(results: list[FlowStepResult]):
        context = resolver.build_context_with_evidence(
            {"text": "flow input"},
            results,
            current_step_order=3,
            step_names_by_order={2: "Named step"},
            step_ref_mapping={"Named step": 2},
        )
        return dict(context), resolver.interpolate_with_evidence(
            template, context, binding_ref="prompt"
        )

    full_context, full = resolve(rows)
    projected_context, projected = resolve([_project(row) for row in rows])

    assert full.text == (
        "first output | runtime text 1 | out-1 | second output | second output"
    )
    assert projected == full
    assert projected_context == full_context
    assert [edge.selection.sha256 for edge in projected.edges] == [
        edge.selection.sha256 for edge in full.edges
    ]


@pytest.mark.parametrize("input_source", ["previous_step", "all_previous_steps"])
async def test_step_input_resolves_alike_from_projected_rows(
    user, input_source
) -> None:
    executor, *_ = build_step_executor(user)
    run = flow_run(status=FlowRunStatus.RUNNING, user=user, input_payload={})
    rows = [
        _completed_row(step_order=1, output={"text": "first output"}),
        _completed_row(
            step_order=2,
            output={"text": '{"id": "nested-1"}', "structured": {"id": "nested-1"}},
        ),
    ]
    step = runtime_step(step_order=3, input_source=input_source)

    async def resolve(results: list[FlowStepResult]):
        state = _state(*results)
        context = executor.variable_resolver.build_context_with_evidence(
            run.input_payload_json, results, current_step_order=3
        )
        return await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=results,
            state=state,
        )

    full = await resolve(rows)
    projected = await resolve([_project(row) for row in rows])

    assert dataclasses.asdict(projected) == dataclasses.asdict(full)
    assert projected.edges and projected.edges == full.edges


def test_inherited_citations_read_alike_from_projected_rows() -> None:
    first = completed_grounded_result(
        step_order=1, source_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )
    second = completed_grounded_result(
        step_order=2, source_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )
    rows = [
        row.model_copy(
            update={
                "input_payload_json": {
                    **(row.input_payload_json or {}),
                    "text": _text("input", 2 * KiB),
                    "source_text": _text("source", 2 * KiB),
                },
                "effective_prompt": "Prompt with {{ step_1.output.text }}",
            }
        )
        for row in (first, second)
    ]
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=3,
        assistant_id=uuid4(),
        user_description="Final report",
        input_source="previous_step",
        input_bindings={"question": "Samtal: {{ step_2.output.text }}"},
        input_config=None,
        output_mode="pass_through",
        output_config=None,
    )

    def collect(results: list[FlowStepResult]) -> dict[str, Any]:
        return collect_inherited_citation_context(
            step=step,
            state=_state(
                *results,
                step_ref_mapping={"step_1": 1, "step_2": 2},
                step_names_by_order={1: "Grounded summary", 2: "Second summary"},
            ),
            prompt_template="Bakgrund: {{ step_1.output.text }}",
        )

    full = collect(rows)

    assert full["available_source_ids"] == [
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    ]
    assert collect([_project(row) for row in rows]) == full


@pytest.mark.parametrize("diarization", ["external", "skipped:empty_transcript"])
async def test_speaker_mapping_reads_alike_from_a_projected_row(
    harness,
    diarization,
) -> None:
    from eneo.flows.domain.step_output import inline_transcript

    _, activate = harness
    row = _completed_row(step_order=1, output={"text": SPEAKER_SOURCE}).model_copy(
        update={
            "current_attempt_no": 3,
            "input_payload_json": {
                "text": _text("audio input", 2 * KiB),
                "source_text": _text("audio source", 2 * KiB),
                "transcription": {
                    "diarization": diarization,
                    "speakers": [{"label": "SPEAKER_00"}, {"label": "SPEAKER_01"}],
                },
            },
        }
    )
    run = SimpleNamespace(
        id=uuid4(),
        input_payload_json={
            "deltagare": "Anna, Bo",
            "transkribering": inline_transcript(
                text=SPEAKER_SOURCE,
                source_step_id=row.step_id,
                source_attempt_no=3,
                selector_path=("output", "text"),
            ).model_dump(mode="json"),
        },
    )
    step = speaker_step()

    async def execute(previous: FlowStepResult):
        handler, persist = speaker_handler(activate)
        result = await handler.execute(
            step=step,
            run=run,
            state=SimpleNamespace(completed_by_order={1: previous}),
            version_metadata=None,
            attempt_no=1,
        )
        return dataclasses.asdict(result.output), persist.await_args_list

    full = await execute(row)

    assert await execute(_project(row)) == full


# --- What the executor keeps between steps ---------------------------------


class _ProviderGate:
    """Answers each provider call in turn, holding it until released."""

    def __init__(self, outputs: list[str], *, hold: bool) -> None:
        self._outputs = outputs
        self._hold = hold
        self._released: list[asyncio.Event] = []
        self._changed = asyncio.Event()

    @property
    def calls(self) -> int:
        return len(self._released)

    async def respond(self, **_kwargs: Any) -> SimpleNamespace:
        number = len(self._released)
        released = asyncio.Event()
        self._released.append(released)
        self._changed.set()
        if self._hold:
            await released.wait()
        return SimpleNamespace(
            completion=self._outputs[number],
            total_token_count=len(self._outputs[number]) // 4,
        )

    async def wait_for_call(self, number: int, task: asyncio.Task[Any]) -> None:
        """Waits until call `number` is held, releasing the calls before it."""
        async with asyncio.timeout(30):
            while self.calls < number:
                for earlier in self._released:
                    earlier.set()
                if task.done():
                    raise AssertionError(
                        f"run ended before call {number}: {task.result()}"
                    )
                self._changed.clear()
                waiter = asyncio.ensure_future(self._changed.wait())
                await asyncio.wait({waiter, task}, return_when=asyncio.FIRST_COMPLETED)
                waiter.cancel()

    def release(self, number: int) -> None:
        self._released[number - 1].set()

    def release_all(self) -> None:
        for released in self._released:
            released.set()
        self._hold = False


@dataclass
class _Rows:
    """Step results kept as JSON, so every read is a fresh object as the
    database's are, and nothing the run holds is shared with storage."""

    rows: dict[UUID, str] = field(default_factory=dict)
    saved: list[tuple[str, int | None, Any]] = field(default_factory=list)
    reads: list[tuple[str, UUID, weakref.ref[FlowStepResult]]] = field(
        default_factory=list
    )
    saved_rows: list[weakref.ref[FlowStepResult]] = field(default_factory=list)

    def _read(self, step_id: UUID, by: str) -> FlowStepResult:
        result = FlowStepResult.model_validate_json(self.rows[step_id])
        self.reads.append((by, step_id, weakref.ref(result)))
        return result

    def alive(self, by: str, step_id: UUID) -> int:
        return sum(
            1
            for reader, read_step_id, ref in self.reads
            if reader == by and read_step_id == step_id and ref() is not None
        )

    def stored_bytes(self) -> int:
        return sum(sys.getsizeof(value) for value in self.rows.values()) + sum(
            sys.getsizeof(saved) for saved, _, _ in self.saved
        )

    async def list_step_results(self, **_: Any) -> list[FlowStepResult]:
        return sorted(
            (self._read(step_id, "list") for step_id in self.rows),
            key=lambda result: result.step_order,
        )

    async def claim_step_result(
        self, *, run_id: UUID, step_id: UUID, tenant_id: UUID
    ) -> FlowStepResult | None:
        row = FlowStepResult.model_validate_json(self.rows[step_id])
        if row.status not in (
            FlowStepResultStatus.PENDING,
            FlowStepResultStatus.FAILED,
        ):
            return None
        self.rows[step_id] = row.model_copy(
            update={"status": FlowStepResultStatus.RUNNING}
        ).model_dump_json()
        return self._read(step_id, "claim")

    async def get_step_result(self, *, step_id: UUID, **_: Any) -> FlowStepResult:
        return self._read(step_id, "get")

    async def save_step_result(
        self,
        _run_id: UUID,
        result: FlowStepResult,
        *,
        tenant_id: UUID,
        attempt_no: int | None,
        result_file_references: Any = None,
    ) -> FlowStepResult:
        self.saved.append(
            (result.model_dump_json(), attempt_no, result_file_references)
        )
        self.saved_rows.append(weakref.ref(result))
        self.rows[result.step_id] = result.model_copy(
            update={"current_attempt_no": attempt_no}
        ).model_dump_json()
        return self._read(result.step_id, "save")

    async def list_step_result_annotations(self, **_: Any):
        return [
            FlowStepResultAnnotation.model_validate(
                FlowStepResult.model_validate_json(value)
            )
            for value in self.rows.values()
        ]

    async def read_last_completed_output_payload(self, **_: Any):
        completed = [
            result
            for result in (
                FlowStepResult.model_validate_json(value)
                for value in self.rows.values()
            )
            if result.status == FlowStepResultStatus.COMPLETED
        ]
        if not completed:
            return None
        return max(completed, key=lambda result: result.step_order).output_payload_json


@dataclass
class _Rig:
    executor: FlowRunExecutor
    run: FlowRun
    run_repo: AsyncMock
    rows: _Rows
    assistant: MagicMock
    gate: _ProviderGate
    step_ids: list[UUID]
    runs_read: list[weakref.ref[FlowRun]]
    outputs: list[weakref.ref[Any]]
    states: list[RunExecutionState]

    def start(self) -> asyncio.Task[dict[str, Any]]:
        return asyncio.create_task(
            self.executor.execute_claimed(
                run_id=self.run.id,
                flow_id=self.run.flow_id,
                tenant_id=self.run.tenant_id,
                dispatch_task_id="task-1",
                retry_count=0,
            )
        )

    def forget_mock_calls(self) -> None:
        """Mock call records keep their arguments alive; they are the test's,
        not the run's."""
        self.run_repo.reset_mock()
        self.assistant.reset_mock()
        self.executor.session.reset_mock()


@contextlib.asynccontextmanager
async def _running(
    start: Callable[[], asyncio.Task[Any]], gate: _ProviderGate
) -> AsyncIterator[asyncio.Task[Any]]:
    """Runs a task whose provider calls the test holds; however the test
    ends, the calls are released and the task is finished."""
    task = start()
    try:
        yield task
    finally:
        gate.release_all()
        await asyncio.gather(task, return_exceptions=True)


@dataclass(frozen=True)
class _Identity:
    """The ids of a run, so two executions of the same run can be compared."""

    run: FlowRun
    assistant_id: UUID
    step_ids: tuple[UUID, ...]
    created_at: datetime


def _identity(user, *, steps: int) -> _Identity:
    run = flow_run(status=FlowRunStatus.RUNNING, user=user)
    return _Identity(
        run=run,
        assistant_id=uuid4(),
        step_ids=tuple(uuid4() for _ in range(steps)),
        created_at=run.created_at,
    )


def _rig(
    user,
    *,
    outputs: list[str],
    steps: int | None = None,
    flow_input: str = "Flow input",
    prompt: str = "",
    hold: bool = True,
    completed: dict[int, FlowStepResult] | None = None,
    identity: _Identity | None = None,
    review_payloads: tuple[Any, ...] = (),
) -> _Rig:
    """A run of chained text steps through the real executor and step runtime,
    with `completed` step results already stored; `outputs` answer the steps
    the run executes, in order."""
    executor, _, run_repo, version_repo = build_flow_executor(user)
    identity = identity or _identity(user, steps=steps or len(outputs))
    run = identity.run.model_copy(update={"input_payload_json": {"text": flow_input}})
    step_ids = list(identity.step_ids)
    version_repo.get = AsyncMock(
        return_value=published_flow_version(
            flow_id=run.flow_id,
            version=run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum=None,
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": order,
                        "assistant_id": str(identity.assistant_id),
                        "input_source": "flow_input" if order == 1 else "previous_step",
                        "output_mode": "pass_through",
                    }
                    for order, step_id in enumerate(step_ids, start=1)
                ]
            },
            created_at=identity.created_at,
            updated_at=identity.created_at,
        )
    )
    rows = _Rows()
    for order, step_id in enumerate(step_ids, start=1):
        stored = (completed or {}).get(order)
        rows.rows[step_id] = (
            stored.model_copy(
                update={
                    "flow_run_id": run.id,
                    "flow_id": run.flow_id,
                    "tenant_id": run.tenant_id,
                    "step_id": step_id,
                    "step_order": order,
                    "assistant_id": identity.assistant_id,
                    "current_attempt_no": 1,
                }
            )
            if stored is not None
            else FlowStepResult(
                id=UUID(int=order),
                flow_run_id=run.id,
                flow_id=run.flow_id,
                tenant_id=run.tenant_id,
                step_id=step_id,
                step_order=order,
                assistant_id=identity.assistant_id,
                status=FlowStepResultStatus.PENDING,
                created_at=identity.created_at,
                updated_at=identity.created_at,
            )
        ).model_dump_json()
    runs_read: list[weakref.ref[FlowRun]] = []

    async def get_run(**_: Any) -> FlowRun:
        fresh = run.model_copy(deep=True)
        runs_read.append(weakref.ref(fresh))
        return fresh

    run_repo.get = get_run
    run_repo.list_step_results = rows.list_step_results
    run_repo.claim_step_result = rows.claim_step_result
    run_repo.get_step_result = rows.get_step_result
    run_repo.save_step_result = rows.save_step_result
    run_repo.list_step_result_annotations = rows.list_step_result_annotations
    run_repo.read_last_completed_output_payload = (
        rows.read_last_completed_output_payload
    )
    executor.flow_run_review_checkpoint_repo.list_resumed_json_review_payloads = (
        AsyncMock(return_value=review_payloads)
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._run_is_cancelled = AsyncMock(return_value=False)
    gate = _ProviderGate(outputs, hold=hold)
    assistant = mock_assistant_for_execute_step()
    assistant.completion_model.id = UUID(int=7)
    assistant.get_prompt_text.return_value = prompt
    assistant.get_response = AsyncMock(side_effect=gate.respond)
    space = SimpleNamespace(
        id=uuid4(), tenant_id=user.tenant_id, security_classification=None
    )

    async def load_assistant(_assistant_id, state, **_: Any) -> MagicMock:
        state.flow_space = space
        return assistant

    executor._load_assistant = load_assistant
    executed: list[weakref.ref[Any]] = []
    states: list[RunExecutionState] = []
    execute_step = executor._execute_step

    async def recording_execute_step(**kwargs: Any):
        if not states:
            states.append(kwargs["state"])
        result = await execute_step(**kwargs)
        executed.extend((weakref.ref(result), weakref.ref(result.output)))
        return result

    executor._execute_step = recording_execute_step
    return _Rig(
        executor=executor,
        run=run,
        run_repo=run_repo,
        rows=rows,
        assistant=assistant,
        gate=gate,
        step_ids=step_ids,
        runs_read=runs_read,
        outputs=executed,
        states=states,
    )


async def test_rig_runs_chained_steps_through_the_real_runtime(user) -> None:
    rig = _rig(user, outputs=["first", "second", "third"], hold=False)

    result = await rig.start()

    assert result == {"status": "completed"}
    assert [
        call.kwargs["question"] for call in rig.assistant.get_response.await_args_list
    ] == ["Flow input", "first", "second"]


async def test_a_completed_step_leaves_only_its_projected_row_behind(user) -> None:
    flow_input = _text("flow input", 8 * KiB)
    first_output = _text("first output", 8 * KiB)
    rig = _rig(
        user, outputs=[first_output, _text("second", 8 * KiB)], flow_input=flow_input
    )
    async with _running(rig.start, rig.gate) as task:
        await rig.gate.wait_for_call(2, task)
        rig.forget_mock_calls()
        gc.collect()

        # The run read before the loop, step 1's output, the row it built and
        # the row it saved: none outlives step 1.
        assert rig.runs_read[0]() is None
        assert [ref() for ref in rig.outputs] == [None, None]
        assert rig.rows.saved_rows[0]() is None
        assert rig.rows.alive("save", rig.step_ids[0]) == 0
        state = rig.states[0]
        held = state.completed_by_order[1]
        assert held.effective_prompt is None
        assert held.input_payload_json is not None
        assert "text" not in held.input_payload_json
        assert "source_text" not in held.input_payload_json
        assert held.output_payload_json == {"text": first_output}
        assert state.prior_results == [held]

    assert task.result() == {"status": "completed"}
    first_saved = json.loads(rig.rows.saved[0][0])
    assert first_saved["input_payload_json"]["text"] == flow_input
    assert first_saved["input_payload_json"]["source_text"] == flow_input
    assert first_saved["effective_prompt"] is not None


async def test_a_resumed_run_keeps_no_row_it_read_for_completed_steps(user) -> None:
    completed = _completed_row(step_order=1, output={"text": "resumed output"})
    rig = _rig(user, outputs=["second"], steps=2, completed={1: completed})
    async with _running(rig.start, rig.gate) as task:
        await rig.gate.wait_for_call(1, task)
        rig.forget_mock_calls()
        gc.collect()

        # Read twice: with every step result before the loop, and again when
        # step 1 turns out to be done already.
        assert rig.rows.alive("list", rig.step_ids[0]) == 0
        assert rig.rows.alive("get", rig.step_ids[0]) == 0
        assert len([read for read in rig.rows.reads if read[0] == "get"]) == 1
        held = rig.states[0].completed_by_order[1]
        assert held.output_payload_json == {"text": "resumed output"}
        assert held.input_payload_json is not None
        assert held.input_payload_json["runtime_input"] == {
            "text": "runtime text 1",
            "capture_mode": "flow_input",
        }
        assert "text" not in held.input_payload_json

    assert task.result() == {"status": "completed"}
    assert [call[1] for call in rig.rows.saved] == [1]


# Mocks create child mocks and call records as the run uses them: the test's
# memory, not the run's.
_NOT_MOCKS = (tracemalloc.Filter(False, unittest.mock.__file__),)


def _traced_bytes_outside_storage(rig: _Rig) -> int:
    rig.forget_mock_calls()
    gc.collect()
    snapshot = tracemalloc.take_snapshot().filter_traces(_NOT_MOCKS)
    return (
        sum(stat.size for stat in snapshot.statistics("filename"))
        - rig.rows.stored_bytes()
    )


async def test_retained_memory_grows_by_one_output_per_completed_step(user) -> None:
    """A run waiting on step k's provider holds the outputs of steps 1..k-1
    and little else. Measured on the real executor and step runtime, leaving
    out the storage fake's rows and the mocks; the bounds are generous on
    purpose: when run state held the input copies, each completed step grew
    it by about four outputs, now by one."""
    size = 128 * KiB
    steps = 5
    warm = _rig(user, outputs=[_text(f"warm {n}", 4 * KiB) for n in range(3)])
    warm.gate.release_all()
    assert await warm.start() == {"status": "completed"}
    del warm
    rig = _rig(user, outputs=[_text(f"output {n}", size) for n in range(steps)])
    gc.collect()
    tracemalloc.start()
    retained: dict[int, int] = {}
    try:
        baseline = _traced_bytes_outside_storage(rig)
        async with _running(rig.start, rig.gate) as task:
            for call in range(1, steps + 1):
                await rig.gate.wait_for_call(call, task)
                if call in (2, steps):
                    retained[call] = _traced_bytes_outside_storage(rig) - baseline
                rig.gate.release(call)
    finally:
        tracemalloc.stop()
    assert task.result() == {"status": "completed"}

    growth_per_step = (retained[steps] - retained[2]) / (steps - 2)
    assert growth_per_step < 1.5 * size, retained
    assert retained[steps] < (steps + 1) * size, retained


# --- What the run persists does not depend on the projection ---------------


def _plain(value: Any) -> Any:
    """A JSON value of everything a persistence call received."""

    def default(item: Any) -> Any:
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            return dataclasses.asdict(item)
        if hasattr(item, "to_payload"):
            return item.to_payload()
        if isinstance(item, enum.Enum):
            return item.value
        if isinstance(item, UUID | datetime):
            return str(item)
        if isinstance(item, frozenset | set | tuple):
            return sorted(item, key=repr) if not isinstance(item, tuple) else list(item)
        return f"<{type(item).__name__}>"

    return json.loads(json.dumps(value, default=default, sort_keys=True))


# The provider call arguments that are wiring, not what was asked: services,
# callbacks and the observer object itself (its edge indexes are kept).
_PROVIDER_WIRING = frozenset({"completion_service", "provider_call_observer"})


def _persistence_capture(rig: _Rig) -> dict[str, Any]:
    return {
        "step_results": [
            [json.loads(saved), attempt_no, _plain(files)]
            for saved, attempt_no, files in rig.rows.saved
        ],
        "repository_calls": [
            [name, _plain(list(args)), _plain(kwargs)]
            for name, args, kwargs in rig.run_repo.mock_calls
        ],
        "terminal": _plain(
            [
                call.kwargs
                for call in rig.executor.flow_run_terminalizer.terminalize_run.await_args_list
            ]
        ),
        "provider_calls": [
            {
                **_plain(
                    {
                        key: value
                        for key, value in call.kwargs.items()
                        if key not in _PROVIDER_WIRING
                    }
                ),
                "edge_indexes": _plain(
                    call.kwargs["provider_call_observer"].resolved_input_edge_indexes
                ),
            }
            for call in rig.assistant.get_response.await_args_list
        ],
    }


def _assert_same_persistence(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


def _reviewed_step_one() -> FlowStepResult:
    return _completed_row(
        step_order=1,
        output={
            "text": '{"beslut": "Bifall", "id": "case-1"}',
            "structured": {"beslut": "Bifall", "id": "case-1"},
        },
    )


async def _resumed_run_capture(
    user,
    identity: _Identity,
    completed: FlowStepResult,
    *,
    project: bool,
    monkeypatch,
) -> dict[str, Any]:
    """Steps 2 and 3 of a run whose step 1 is done and was reviewed: they read
    its output, its runtime input, its reviewed edit and its citations."""
    with monkeypatch.context() as patch:
        if not project:
            patch.setattr(
                runtime_domain, "project_completed_result", lambda result: result
            )
            patch.setattr(
                "eneo.flows.runtime.execution_state_builder.project_completed_result",
                lambda result: result,
            )
        rig = _rig(
            user,
            outputs=["second answer", "third answer"],
            completed={1: completed},
            identity=identity,
            hold=False,
            prompt=(
                "Earlier: {{step_1.output.text}} | runtime: {{step_1.input.text}}"
                " | decision: {{step_1.output.structured.beslut}}"
                " | previous: {{föregående_steg}}"
            ),
            review_payloads=(
                (
                    identity.step_ids[0],
                    1,
                    {"structured": {"beslut": "Avslag", "id": "case-1"}},
                    {"structured": {"beslut": "Bifall", "id": "case-1"}},
                ),
            ),
        )
        assert await rig.start() == {"status": "completed"}
        return _persistence_capture(rig)


async def test_what_a_resumed_run_persists_does_not_depend_on_the_projection(
    user, monkeypatch
) -> None:
    identity = _identity(user, steps=3)
    completed = _reviewed_step_one()

    projected = await _resumed_run_capture(
        user, identity, completed, project=True, monkeypatch=monkeypatch
    )
    full = await _resumed_run_capture(
        user, identity, completed, project=False, monkeypatch=monkeypatch
    )

    first_prompt = projected["provider_calls"][0]["prompt_override"]
    assert "Earlier: " in first_prompt and "runtime: runtime text 1" in first_prompt
    assert "decision: Bifall" in first_prompt
    assert '["beslut"] set by the reviewer' in first_prompt
    assert len(projected["step_results"]) == 2
    activations = [
        call
        for call in projected["repository_calls"]
        if call[0] == "activate_step_attempt"
    ]
    assert len(activations) == 2
    _assert_same_persistence(projected, full)


async def test_the_persistence_comparison_sees_provenance_and_nested_ids(
    user, monkeypatch
) -> None:
    capture = await _resumed_run_capture(
        user,
        _identity(user, steps=3),
        _reviewed_step_one(),
        project=True,
        monkeypatch=monkeypatch,
    )
    activation = next(
        call
        for call in capture["repository_calls"]
        if call[0] == "activate_step_attempt"
    )

    changed_provenance = copy.deepcopy(capture)
    changed_activation = next(
        call
        for call in changed_provenance["repository_calls"]
        if call[0] == "activate_step_attempt"
    )
    edges = changed_activation[2]["resolved_input_edges"]
    assert edges == activation[2]["resolved_input_edges"]
    edge = _first_selection(edges)
    edge["sha256"] = "0" * 64
    with pytest.raises(AssertionError):
        _assert_same_persistence(changed_provenance, capture)

    # Identifiers and timestamps inside what a step produced are its data.
    with_ids = copy.deepcopy(capture)
    with_ids["step_results"][0][0]["output_payload_json"]["structured"] = {
        "items": [{"id": "item-1", "created_at": "2026-10-24T10:00:00Z"}]
    }
    for key, value in (("id", "item-2"), ("created_at", "2026-10-24T11:00:00Z")):
        changed = copy.deepcopy(with_ids)
        changed["step_results"][0][0]["output_payload_json"]["structured"]["items"][0][
            key
        ] = value
        with pytest.raises(AssertionError):
            _assert_same_persistence(changed, with_ids)


def _first_selection(value: Any) -> dict[str, Any]:
    """The first edge selection (value hash) anywhere in a captured payload."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if "sha256" in item:
                return item
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(reversed(item))
    raise AssertionError("no selection hash in the capture")


# --- Mapped steps ----------------------------------------------------------

_SECTIONS_CONTRACT = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "body": {"type": "string"},
                    "source_label": {"type": "string"},
                    "source_file_id": {"type": "string"},
                },
                "required": ["heading", "body", "source_label", "source_file_id"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sections"],
    "additionalProperties": False,
}


def _mapped_step(*, max_items: int) -> RuntimeStep:
    return runtime_step(
        step_order=2,
        input_source="previous_step",
        input_type="json",
        input_contract={
            "type": "object",
            "properties": {"documents": {"type": "array", "items": {"type": "object"}}},
            "required": ["documents"],
        },
        output_type="json",
        output_contract=_SECTIONS_CONTRACT,
        input_config={"item_map": {"enabled": True, "max_items": max_items}},
    )


def _documents(count: int, *, summary_size: int = 64) -> list[dict[str, Any]]:
    return [
        {
            "title": f"Document {number}",
            "summary": _text(f"summary {number}", summary_size),
            "source_label": f"source-{number}.pdf",
            "source_file_id": f"file-{number}",
        }
        for number in range(1, count + 1)
    ]


def _sections(*headings: str, body_size: int = 16) -> str:
    return json.dumps(
        {
            "sections": [
                {"heading": heading, "body": _text(heading, body_size)}
                for heading in headings
            ]
        }
    )


def _mapped_setup(user, *, documents: list[dict[str, Any]], responses: Any):
    executor, _, run_repo, _ = build_step_executor(user)
    assistant = mock_assistant_for_execute_step()
    assistant.completion_model.id = UUID(int=7)
    assistant.get_response = AsyncMock(side_effect=responses)
    executor._load_assistant = AsyncMock(return_value=assistant)
    run = flow_run(status=FlowRunStatus.RUNNING, user=user, input_payload={})
    previous = completed_step_result(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_order=1,
        text=json.dumps({"documents": documents}),
        structured={"documents": documents},
    ).model_copy(update={"step_id": UUID(int=1)})
    return executor, run_repo, assistant, run, _state(previous)


def _two_different_calls() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            completion=Completion(
                text='{"sections":[{"heading":"A","body":"one"}]}',
                tool_calls_metadata=[
                    ToolCallMetadata(server_name="archive", tool_name="lookup")
                ],
                provider_response_id="response-1",
            ),
            total_token_count=11,
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=4),
            model=SimpleNamespace(name="model-a", provider_type="openai"),
        ),
        SimpleNamespace(
            completion=(
                '{"sections":[{"heading":"B","body":"two"},'
                '{"heading":"C","body":"three"}]}'
            ),
            total_token_count=None,
            model=SimpleNamespace(name="model-b", provider_type="azure"),
        ),
    ]


def _two_call_mapped_step(user, *, second_file_id: str | None = "file-2"):
    """A mapped step whose two item calls differ in everything assembly
    reads: identity, input length, structured output, tokens (the second
    has none), tool calls, model, retrieval evidence and diagnostics."""
    second: dict[str, Any] = {
        "title": "Second",
        "summary": "short",
        "source_label": "second.pdf",
    }
    if second_file_id is not None:
        second["source_file_id"] = second_file_id
    documents = [
        {
            "title": "First",
            "summary": "å" * 2500,
            "source_label": "first.pdf",
            "source_file_id": "file-1",
        },
        second,
    ]
    executor, run_repo, assistant, run, state = _mapped_setup(
        user, documents=documents, responses=_two_different_calls()
    )
    executor._retrieve_rag_chunks = AsyncMock(
        side_effect=[
            (
                [],
                {"status": "success", "references": []},
                [StepDiagnostic(code="retrieval_note", message="Partial index.")],
            ),
            ([], None, [StepDiagnostic(code="retrieval_note", message="Stale index.")]),
        ]
    )
    return executor, run_repo, assistant, run, state, documents


def _item_question(document: dict[str, Any]) -> str:
    return json.dumps({"documents": [document]}, ensure_ascii=False)


# The run, step and tenant of a mapped step are new on every test run.
_ACTIVATION_IDENTITY = frozenset({"run_id", "step_id", "tenant_id"})


def _activation_digest(run_repo: AsyncMock) -> str:
    """The one activation of a mapped step: every edge and execution input."""
    (activation,) = [
        call.kwargs for call in run_repo.activate_step_attempt.await_args_list
    ]
    recorded = {
        key: value
        for key, value in activation.items()
        if key not in _ACTIVATION_IDENTITY
    }
    return hashlib.sha256(
        json.dumps(_plain(recorded), sort_keys=True).encode()
    ).hexdigest()


async def test_mapped_assembly_reads_each_call_and_the_first_calls_context(
    user,
) -> None:
    executor, run_repo, assistant, run, state, documents = _two_call_mapped_step(user)

    output = (
        await executor._execute_step(
            step=_mapped_step(max_items=2), run=run, state=state, attempt_no=1
        )
    ).output

    first_call = assistant.get_response.await_args_list[0].kwargs
    assembled = dataclasses.asdict(output)
    per_item_calls = assembled["runtime_input_metadata"]["per_item_calls"]
    for call in per_item_calls:
        # Timing is the one value that is not the calls' own.
        assert isinstance(call.pop("elapsed_ms"), int)
    sections = {
        "sections": [
            {
                "heading": "A",
                "body": "one",
                "source_label": "first.pdf",
                "source_file_id": "file-1",
            },
            {
                "heading": "B",
                "body": "two",
                "source_label": "second.pdf",
                "source_file_id": "file-2",
            },
            {
                "heading": "C",
                "body": "three",
                "source_label": "second.pdf",
                "source_file_id": "file-2",
            },
        ]
    }
    summary = (
        "[per-item map input: 2 documents[] item calls; "
        "see runtime_input.per_item_calls for model input previews]"
    )
    assert assembled == {
        "input_text": summary,
        "source_text": "",
        "input_source": "previous_step",
        "used_question_binding": False,
        "full_text": json.dumps(sections, ensure_ascii=False),
        "persisted_text": json.dumps(sections, ensure_ascii=False),
        "generated_file_ids": [],
        "tool_calls_metadata": {
            "execution_mode": "per_item",
            "items": [
                {
                    "item_number": 1,
                    "source_label": "first.pdf",
                    "source_file_id": "file-1",
                    "tool_calls": [
                        dataclasses.asdict(
                            ToolCallMetadata(server_name="archive", tool_name="lookup")
                        )
                    ],
                },
                {
                    "item_number": 2,
                    "source_label": "second.pdf",
                    "source_file_id": "file-2",
                    "tool_calls": None,
                },
            ],
        },
        "num_tokens_input": None,
        "num_tokens_output": 4 + per_item_calls[1]["num_tokens_output"],
        "effective_prompt": first_call["prompt_override"],
        "model_parameters_json": {
            "model_id": str(UUID(int=7)),
            "model_name": "test",
            "provider": "test",
            "temperature": None,
            "top_p": None,
            "reasoning_effort": None,
            "verbosity": None,
            "response_format": {"type": "json_object"},
            "presence_penalty": None,
            "frequency_penalty": None,
            "top_k": None,
            "parameter_semantics": {
                "temperature": {"mode": "model_default"},
                "top_p": {"mode": "model_default"},
                "reasoning_effort": {"mode": "model_default"},
                "verbosity": {"mode": "model_default"},
            },
            "item_map_execution_mode": "per_item",
            "per_item_call_count": 2,
        },
        "requested_model": "test",
        "response_model": "model-a",
        "provider": "openai",
        "finish_reason": "tool_calls",
        "provider_response_id": None,
        "contract_validation": {
            "schema_type_hint": "object",
            "parse_attempted": False,
            "parse_succeeded": True,
            "candidate_type": "dict",
        },
        "structured_output": sections,
        "diagnostics": [
            {
                "code": "previous_step_per_item_map",
                "message": (
                    "Step 2: executed once per previous documents[] item "
                    "(2 item calls)."
                ),
                "severity": "info",
            },
            {
                "code": "retrieval_note",
                "message": "Partial index.",
                "severity": "warning",
            },
            {
                "code": "retrieval_note",
                "message": "Stale index.",
                "severity": "warning",
            },
        ],
        "artifacts": None,
        "rag_metadata": {
            "execution_mode": "per_item",
            "mapped_calls_complete": True,
            "items": [
                {
                    "status": "success",
                    "references": [],
                    "query_derivation": {
                        "strategy": "input_text",
                        "input_truncated": True,
                        "query_length": 2048,
                    },
                }
            ],
            "sources_total": 0,
            "sources_with_recorded_passages": 0,
            "passages_recorded": 0,
            "passages_truncated": 0,
            "passages_withheld": 0,
            "recorded_passage_bytes": 0,
            "passages_released_to_step_budget": 0,
            "passage_bytes_released_to_step_budget": 0,
            "passages_omitted_from_view": 0,
            "passage_bytes_omitted_from_view": 0,
        },
        "transcription_metadata": None,
        "runtime_input_metadata": {
            "text": summary,
            "capture_mode": "previous_step_item_map",
            "execution_mode": "per_item",
            "source_step_order": 1,
            "input_array": "documents",
            "output_array": "sections",
            "item_count": 2,
            "per_item_calls": [
                {
                    "item_number": 1,
                    "source_label": "first.pdf",
                    "source_file_id": "file-1",
                    "input_text_length": len(_item_question(documents[0])),
                    "input_text_preview": _item_question(documents[0])[:2000],
                    "num_tokens_input": 7,
                    "num_tokens_output": 4,
                    "diagnostics": [
                        {
                            "code": "retrieval_note",
                            "message": "Partial index.",
                            "severity": "warning",
                        }
                    ],
                },
                {
                    "item_number": 2,
                    "source_label": "second.pdf",
                    "source_file_id": "file-2",
                    "input_text_length": len(_item_question(documents[1])),
                    "input_text_preview": _item_question(documents[1]),
                    "num_tokens_input": None,
                    "num_tokens_output": per_item_calls[1]["num_tokens_output"],
                    "diagnostics": [
                        {
                            "code": "retrieval_note",
                            "message": "Stale index.",
                            "severity": "warning",
                        }
                    ],
                },
            ],
        },
        "output_payload_extensions": None,
        "citation_sidecar": None,
        "inherited_citation_sources": None,
        "raw_completion_text": None,
        "materials": (),
        "max_inline_text_bytes": 1024 * 1024,
        "long_material": None,
    }
    assert len(_item_question(documents[0])) > 2000
    assert per_item_calls[1]["num_tokens_output"] > 0
    assert [call[0] for call in run_repo.mock_calls] == ["activate_step_attempt"]
    assert _activation_digest(run_repo) == (
        "84aa5de9b86ca20ce92a7042d61554fba78bf20549294589eedebb21496c87c5"
    )


async def test_a_mapped_step_releases_each_finished_item_call(
    user, monkeypatch
) -> None:
    items = 4
    gate = _ProviderGate(
        [_sections(f"H{number}", body_size=4 * KiB) for number in range(items)],
        hold=True,
    )
    executor, _, _, run, state = _mapped_setup(
        user, documents=_documents(items, summary_size=4 * KiB), responses=gate.respond
    )
    outputs: list[weakref.ref[Any]] = []
    complete = per_item_map.complete_step_execution

    async def recording_complete(**kwargs: Any):
        output = await complete(**kwargs)
        outputs.append(weakref.ref(output))
        return output

    monkeypatch.setattr(per_item_map, "complete_step_execution", recording_complete)
    activated: list[weakref.ref[Any]] = []
    activate = executor._activate_prepared_assistant_steps

    async def recording_activate(*args: Any):
        prepared_steps = await activate(*args)
        activated.extend(weakref.ref(step) for step in prepared_steps)
        return prepared_steps

    executor._activate_prepared_assistant_steps = recording_activate

    def start() -> asyncio.Task[Any]:
        return asyncio.create_task(
            executor._execute_step(
                step=_mapped_step(max_items=items), run=run, state=state, attempt_no=1
            )
        )

    async with _running(start, gate) as task:
        await gate.wait_for_call(items, task)
        gc.collect()

        assert [ref() is None for ref in outputs] == [True] * (items - 1)
        assert [ref() is None for ref in activated] == [True] * (items - 1) + [False]

    output = task.result().output
    assert output.structured_output is not None
    assert [section["heading"] for section in output.structured_output["sections"]] == [
        f"H{number}" for number in range(items)
    ]


async def test_mapped_progress_counts_every_item_and_stops_at_a_cancellation(
    user, monkeypatch
) -> None:
    progress: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        per_item_map,
        "record_step_progress",
        lambda message, **counts: progress.append((message, counts)),
    )
    executor, _, assistant, run, state = _mapped_setup(
        user,
        documents=_documents(3),
        responses=[
            SimpleNamespace(completion=_sections("H1"), total_token_count=1),
            SimpleNamespace(completion=_sections("H2"), total_token_count=1),
            asyncio.CancelledError(),
        ],
    )

    with pytest.raises(asyncio.CancelledError):
        await executor._execute_step(
            step=_mapped_step(max_items=3), run=run, state=state, attempt_no=1
        )

    assert assistant.get_response.await_count == 3
    assert progress == [
        (f"{done} of 3 items completed", {"completed_items": done, "total_items": 3})
        for done in range(3)
    ]


async def test_a_later_mapped_call_failure_keeps_the_evidence_of_both_calls(
    user,
) -> None:
    executor, _, assistant, run, state = _mapped_setup(
        user,
        documents=_documents(3),
        responses=[
            SimpleNamespace(completion=_sections("H1"), total_token_count=1),
            SimpleNamespace(
                completion='{"sections": "not a list"}', total_token_count=1
            ),
        ],
    )
    executor._retrieve_rag_chunks = AsyncMock(
        side_effect=lambda **_: ([], {"status": "success", "references": []}, [])
    )

    with pytest.raises(TypedIOValidationException) as error:
        await executor._execute_step(
            step=_mapped_step(max_items=3), run=run, state=state, attempt_no=1
        )

    assert error.value.code == "typed_io_contract_violation"
    assert assistant.get_response.await_count == 2
    evidence = failure_evidence(error.value).rag_metadata
    assert evidence is not None
    assert evidence["mapped_calls_complete"] is False
    assert len(evidence["items"]) == 2


async def test_a_rejected_mapped_assembly_reports_the_first_calls_prompt(
    user,
) -> None:
    executor, _, assistant, run, state, _ = _two_call_mapped_step(
        user, second_file_id=None
    )

    with pytest.raises(TypedIOValidationException) as error:
        await executor._execute_step(
            step=_mapped_step(max_items=2), run=run, state=state, attempt_no=1
        )

    assert error.value.code == "typed_io_contract_violation"
    assert "/sections/1" in str(error.value)
    assert (
        error.value.effective_prompt
        == assistant.get_response.await_args_list[0].kwargs["prompt_override"]
    )
    payload = error.value.input_payload_json
    assert payload is not None
    assert payload["source_text"] == ""
    assert payload["input_source"] == "previous_step"
    assert payload["runtime_input"]["item_count"] == 2
    assert [
        call["source_file_id"] for call in payload["runtime_input"]["per_item_calls"]
    ] == ["file-1", None]
    evidence = failure_evidence(error.value).rag_metadata
    assert evidence is not None
    assert len(evidence["items"]) == 1
