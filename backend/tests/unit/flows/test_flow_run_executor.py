"""The three-phase step loop against an in-memory repository.

Covers the claim, redelivery, unknown-outcome, review pause and resume,
failure, timeout and cancellation paths without a database or a provider.
"""

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Optional
from uuid import UUID, uuid4

import pytest

from eneo.flows.definition import (
    ComposeStep,
    FlowDefinition,
    FormField,
    LlmStep,
    ReviewStep,
    assign_step_ids,
)
from eneo.flows.flow_assembler import definition_to_json
from eneo.flows.flow_models import (
    FlowRunStatus,
    ReviewCheckpointState,
    StepAttemptStatus,
    StepResultStatus,
)
from eneo.flows.flow_run_executor import OUTCOME_UNKNOWN, FlowRunExecutor
from eneo.flows.step_runners import (
    STEP_TIMEOUT,
    FlowStepError,
    PreparedStep,
    StepOutcome,
)
from eneo.flows.templating import render_template

TENANT = uuid4()
SPACE = uuid4()
USER = uuid4()


class _Session:
    def in_transaction(self) -> bool:
        return True


@dataclass
class FakeRepo:
    """Just enough of FlowRepository for the executor, all in memory."""

    definition: FlowDefinition
    run: SimpleNamespace = field(init=False)
    results: dict[UUID, SimpleNamespace] = field(default_factory=dict)
    attempts: list[SimpleNamespace] = field(default_factory=list)
    checkpoints: list[SimpleNamespace] = field(default_factory=list)
    run_files: list[Any] = field(default_factory=list)
    session: _Session = field(default_factory=_Session)

    def __post_init__(self) -> None:
        self.run = SimpleNamespace(
            id=uuid4(),
            flow_id=uuid4(),
            flow_version=1,
            tenant_id=TENANT,
            principal_user_id=USER,
            status=FlowRunStatus.QUEUED.value,
            input_payload_json={"topic": "harbours"},
            output_payload_json=None,
            error_json=None,
        )
        for order, step in enumerate(self.definition.steps):
            self.results[step.id] = SimpleNamespace(
                step_id=step.id,
                step_order=order,
                status=StepResultStatus.PENDING.value,
                input_payload_json=None,
                output_payload_json=None,
                error_code=None,
                error_message=None,
            )

    # reads
    async def get_run(self, run_id, tenant_id):
        return self.run if run_id == self.run.id else None

    async def get_version(self, flow_id, version):
        return SimpleNamespace(definition=definition_to_json(self.definition))

    async def get_flow(self, flow_id, tenant_id, *, include_deleted=False):
        return SimpleNamespace(id=flow_id, space_id=SPACE)

    async def list_run_files(self, run_id):
        return list(self.run_files)

    async def get_step_result(self, run_id, step_id):
        return self.results[step_id]

    async def get_active_checkpoint(self, run_id):
        return next(
            (
                c
                for c in self.checkpoints
                if c.state in ("awaiting_review", "edited", "approved")
            ),
            None,
        )

    # run
    async def update_run_status(
        self,
        run_id,
        status,
        *,
        output_payload_json=None,
        error=None,
        expected_statuses=None,
    ):
        if (
            expected_statuses
            and FlowRunStatus(self.run.status) not in expected_statuses
        ):
            return False
        self.run.status = status.value
        if output_payload_json is not None:
            self.run.output_payload_json = output_payload_json
        if error is not None:
            self.run.error_json = error
        return True

    # steps
    async def claim_step_result(self, run_id, step_id):
        result = self.results[step_id]
        if result.status != StepResultStatus.PENDING.value:
            return False
        result.status = StepResultStatus.RUNNING.value
        return True

    async def open_attempt(self, run_id, step_id):
        number = len([a for a in self.attempts if a.step_id == step_id]) + 1
        self.attempts.append(
            SimpleNamespace(step_id=step_id, attempt_no=number, status="started")
        )
        return number

    async def finish_attempt(self, run_id, step_id, attempt_no, *, status, error=None):
        for attempt in self.attempts:
            if attempt.step_id == step_id and attempt.attempt_no == attempt_no:
                if attempt.status != "started":
                    return False
                attempt.status = status.value
                attempt.error = error
                return True
        return False

    async def mark_started_attempts_outcome_unknown(self, run_id):
        for attempt in self.attempts:
            if attempt.status == "started":
                attempt.status = StepAttemptStatus.OUTCOME_UNKNOWN.value

    async def fail_running_step_results(self, run_id, *, error_code, error_message):
        for result in self.results.values():
            if result.status == StepResultStatus.RUNNING.value:
                result.status = StepResultStatus.FAILED.value
                result.error_code = error_code

    async def complete_step_result(
        self, run_id, step_id, *, input_payload_json, output_payload_json, **tokens
    ):
        result = self.results[step_id]
        result.status = StepResultStatus.COMPLETED.value
        if input_payload_json is not None:
            result.input_payload_json = input_payload_json
        result.output_payload_json = output_payload_json

    async def fail_step_result(
        self, run_id, step_id, *, error_code, error_message, input_payload_json=None
    ):
        result = self.results[step_id]
        result.status = StepResultStatus.FAILED.value
        result.error_code = error_code
        result.error_message = error_message

    async def set_step_awaiting_review(
        self, run_id, step_id, *, input_payload_json=None
    ):
        self.results[step_id].status = StepResultStatus.AWAITING_REVIEW.value

    async def add_run_files(self, run_id, entries):
        self.run_files.extend(entries)

    # checkpoints
    async def create_checkpoint(self, **values):
        checkpoint = SimpleNamespace(
            id=uuid4(), revision=1, state="awaiting_review", **values
        )
        checkpoint.current_payload_json = values["payload"]
        self.checkpoints.append(checkpoint)
        return checkpoint

    async def mark_resumed(self, checkpoint_id):
        for checkpoint in self.checkpoints:
            if checkpoint.id == checkpoint_id:
                checkpoint.state = ReviewCheckpointState.RESUMED.value


class FakeRunners:
    def __init__(self, *, fail_with: Optional[Exception] = None, delay: float = 0):
        self.calls: list[str] = []
        self.fail_with = fail_with
        self.delay = delay

    async def prepare(self, step, ctx, context):
        if isinstance(step, ComposeStep):
            return PreparedStep(
                input_payload={"template": step.template},
                output_payload={"text": render_template(step.template, context)},
            )
        assert isinstance(step, LlmStep)
        return PreparedStep(
            input_payload={"text": render_template(step.input, context)},
            text_input=render_template(step.input, context),
            prompt=step.prompt,
        )

    async def invoke(self, step, prepared):
        if prepared.output_payload is not None:
            return StepOutcome(output_payload=prepared.output_payload)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append(prepared.text_input)
        return StepOutcome(
            output_payload={"text": f"LLM[{prepared.prompt}|{prepared.text_input}]"},
            num_tokens_input=7,
        )


def _definition(*steps) -> FlowDefinition:
    topic = FormField(key="topic", label="Topic", type="text")
    return assign_step_ids(FlowDefinition(form_fields=[topic], steps=list(steps)))


def _three_steps() -> FlowDefinition:
    return _definition(
        LlmStep(
            key="extract", name="Extract", prompt="extract", input="{{form.topic}}"
        ),
        ComposeStep(key="wrap", name="Wrap", template="Facts: {{previous}}"),
        LlmStep(key="summarize", name="Summarize", prompt="summarize"),
    )


def _reviewed() -> FlowDefinition:
    return _definition(
        LlmStep(key="draft", name="Draft", prompt="draft", input="{{form.topic}}"),
        ReviewStep(key="check", name="Check", of="draft"),
        LlmStep(key="final", name="Final", prompt="final"),
    )


def _executor(repo, runners, **kwargs) -> FlowRunExecutor:
    return FlowRunExecutor(repo, runners, **kwargs)


def _outputs(repo: FakeRepo) -> list[Optional[str]]:
    return [
        (repo.results[step.id].output_payload_json or {}).get("text")
        for step in repo.definition.steps
    ]


async def test_steps_chain_outputs_and_the_run_completes():
    repo = FakeRepo(_three_steps())
    runners = FakeRunners()
    await _executor(repo, runners).execute_run(repo.run.id, TENANT)

    assert repo.run.status == FlowRunStatus.COMPLETED.value
    assert _outputs(repo) == [
        "LLM[extract|harbours]",
        "Facts: LLM[extract|harbours]",
        "LLM[summarize|Facts: LLM[extract|harbours]]",
    ]
    assert repo.run.output_payload_json == {
        "text": "LLM[summarize|Facts: LLM[extract|harbours]]"
    }
    assert [a.status for a in repo.attempts] == ["completed"] * 3
    extract = repo.results[repo.definition.steps[0].id]
    assert extract.input_payload_json == {"text": "harbours"}


async def test_redelivery_skips_completed_steps_without_calling_providers():
    repo = FakeRepo(_three_steps())
    runners = FakeRunners()
    executor = _executor(repo, runners)
    await executor.execute_run(repo.run.id, TENANT)
    first = _outputs(repo)

    repo.run.status = FlowRunStatus.QUEUED.value
    await executor.execute_run(repo.run.id, TENANT)

    assert _outputs(repo) == first
    assert len(runners.calls) == 2
    assert len(repo.attempts) == 3


async def test_step_left_running_by_a_dead_worker_fails_without_repeating_the_call():
    repo = FakeRepo(_three_steps())
    runners = FakeRunners()
    first = repo.definition.steps[0]
    await repo.claim_step_result(repo.run.id, first.id)
    await repo.open_attempt(repo.run.id, first.id)
    repo.run.status = FlowRunStatus.RUNNING.value

    await _executor(repo, runners).execute_run(repo.run.id, TENANT)

    assert runners.calls == []
    assert repo.run.status == FlowRunStatus.FAILED.value
    assert repo.run.error_json["code"] == OUTCOME_UNKNOWN
    assert repo.attempts[0].status == "outcome_unknown"
    assert repo.results[first.id].status == StepResultStatus.FAILED.value
    assert repo.results[repo.definition.steps[1].id].status == "pending"


async def test_review_step_parks_the_run_and_redelivery_leaves_it_parked():
    repo = FakeRepo(_reviewed())
    runners = FakeRunners()
    executor = _executor(repo, runners)
    await executor.execute_run(repo.run.id, TENANT)

    draft, check, final = repo.definition.steps
    assert repo.run.status == FlowRunStatus.AWAITING_REVIEW.value
    assert repo.results[check.id].status == StepResultStatus.AWAITING_REVIEW.value
    assert repo.results[final.id].status == StepResultStatus.PENDING.value
    checkpoint = repo.checkpoints[0]
    assert checkpoint.step_id == check.id
    assert checkpoint.payload == {"text": "LLM[draft|harbours]"}
    assert checkpoint.review_mode == "edit"
    assert checkpoint.output_type == "text"

    await executor.execute_run(repo.run.id, TENANT)
    assert repo.run.status == FlowRunStatus.AWAITING_REVIEW.value
    assert len(runners.calls) == 1


async def test_resume_completes_the_review_step_with_the_edited_payload():
    repo = FakeRepo(_reviewed())
    runners = FakeRunners()
    executor = _executor(repo, runners)
    await executor.execute_run(repo.run.id, TENANT)

    checkpoint = repo.checkpoints[0]
    checkpoint.current_payload_json = {"text": "human-corrected draft"}
    checkpoint.state = ReviewCheckpointState.APPROVED.value
    repo.run.status = FlowRunStatus.QUEUED.value

    await executor.execute_run(repo.run.id, TENANT)

    assert repo.run.status == FlowRunStatus.COMPLETED.value
    assert checkpoint.state == ReviewCheckpointState.RESUMED.value
    assert _outputs(repo) == [
        "LLM[draft|harbours]",
        "human-corrected draft",
        "LLM[final|human-corrected draft]",
    ]
    assert [a.status for a in repo.attempts] == ["completed"] * 3


async def test_resume_with_an_undecided_checkpoint_keeps_the_run_parked():
    repo = FakeRepo(_reviewed())
    executor = _executor(repo, FakeRunners())
    await executor.execute_run(repo.run.id, TENANT)
    repo.run.status = FlowRunStatus.QUEUED.value

    await executor.execute_run(repo.run.id, TENANT)

    assert repo.run.status == FlowRunStatus.AWAITING_REVIEW.value
    assert repo.checkpoints[0].state == ReviewCheckpointState.AWAITING_REVIEW.value


async def test_step_error_fails_the_run_with_its_code():
    repo = FakeRepo(_three_steps())
    runners = FakeRunners(
        fail_with=FlowStepError("flow_step_model_unavailable", "gone")
    )
    await _executor(repo, runners).execute_run(repo.run.id, TENANT)

    first = repo.definition.steps[0]
    assert repo.run.status == FlowRunStatus.FAILED.value
    assert repo.run.error_json["code"] == "flow_step_model_unavailable"
    assert repo.results[first.id].status == StepResultStatus.FAILED.value
    assert repo.results[first.id].error_message == "gone"
    assert repo.attempts[0].status == "failed"


async def test_unexpected_exception_fails_the_run_generically():
    repo = FakeRepo(_three_steps())
    await _executor(repo, FakeRunners(fail_with=RuntimeError("boom"))).execute_run(
        repo.run.id, TENANT
    )
    assert repo.run.status == FlowRunStatus.FAILED.value
    assert repo.run.error_json["code"] == "flow_step_failed"
    assert "boom" in repo.run.error_json["message"]


async def test_slow_step_times_out():
    repo = FakeRepo(_three_steps())
    runners = FakeRunners(delay=0.2)
    await _executor(repo, runners, step_timeout_seconds=0.01).execute_run(
        repo.run.id, TENANT
    )
    assert repo.run.status == FlowRunStatus.FAILED.value
    assert repo.run.error_json["code"] == STEP_TIMEOUT
    assert repo.attempts[0].status == "failed"


async def test_cancellation_is_honoured_at_the_next_step_boundary():
    repo = FakeRepo(_three_steps())

    class CancellingRunners(FakeRunners):
        async def invoke(self, step, prepared):
            outcome = await super().invoke(step, prepared)
            # Someone cancels the run while the first provider call is out.
            repo.run.status = FlowRunStatus.CANCELLED.value
            return outcome

    await _executor(repo, CancellingRunners()).execute_run(repo.run.id, TENANT)

    assert repo.run.status == FlowRunStatus.CANCELLED.value
    statuses = [repo.results[s.id].status for s in repo.definition.steps]
    assert statuses == ["completed", "pending", "pending"]


async def test_finished_runs_are_not_executed_again():
    repo = FakeRepo(_three_steps())
    runners = FakeRunners()
    repo.run.status = FlowRunStatus.CANCELLED.value
    await _executor(repo, runners).execute_run(repo.run.id, TENANT)
    assert runners.calls == []
    assert all(r.status == "pending" for r in repo.results.values())


@pytest.mark.parametrize("output", [{"type": "json", "schema": {"type": "object"}}])
async def test_review_of_a_json_step_opens_a_json_checkpoint(output):
    repo = FakeRepo(
        _definition(
            LlmStep(key="facts", name="Facts", prompt="p", input="x", output=output),
            ReviewStep(key="check", name="Check", mode="view"),
        )
    )
    await _executor(repo, FakeRunners()).execute_run(repo.run.id, TENANT)
    assert repo.checkpoints[0].output_type == "json"
    assert repo.checkpoints[0].review_mode == "view"
