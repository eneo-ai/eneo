"""Human review checkpoints pause, edit, approve, reject and resume runs."""

import pytest

from eneo.flows.definition import FlowDefinition, LlmStep, ReviewStep
from eneo.flows.flow_models import (
    FlowRunStatus,
    ReviewCheckpointState,
    StepResultStatus,
)
from eneo.flows.flow_run_executor import REVIEW_REJECTED
from eneo.main.exceptions import BadRequestException
from tests.integration.flows.conftest import topic_field


def _reviewed(model_id, *, mode: str = "edit") -> FlowDefinition:
    return FlowDefinition(
        form_fields=[topic_field()],
        steps=[
            LlmStep(
                key="draft",
                name="Draft",
                prompt="draft",
                input="{{form.topic}}",
                model_id=model_id,
            ),
            ReviewStep(key="check", name="Check", mode=mode, of="draft"),
            LlmStep(
                key="finalize", name="Finalize", prompt="finalize", model_id=model_id
            ),
        ],
    )


async def _paused_run(
    container, member_space, completion_model_factory, publish_flow, name, **kw
):
    session = container.session()
    model = await completion_model_factory(session, f"{name}-model")
    space = await member_space(session, f"{name} Space", [model.id])
    flow = await publish_flow(container, space, _reviewed(model.id, **kw))
    run_service = container.flow_run_service()
    run = await run_service.create_run(
        flow.id, values={"topic": "the request"}, files={}
    )
    await run_service.execute_run(run.id)
    return flow, run, run_service


async def test_run_pauses_for_review_and_resumes_with_edited_output(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        flow, run, run_service = await _paused_run(
            container, member_space, completion_model_factory, publish_flow, "review"
        )
        paused = await run_service.get_run(run.id)
        assert paused.status == FlowRunStatus.AWAITING_REVIEW
        assert paused.steps[1].status == StepResultStatus.AWAITING_REVIEW
        assert paused.steps[2].status == StepResultStatus.PENDING

        checkpoint = paused.review_checkpoint
        assert checkpoint is not None
        assert checkpoint.state == ReviewCheckpointState.AWAITING_REVIEW
        assert checkpoint.review_mode == "edit"
        assert checkpoint.output_type == "text"
        assert checkpoint.original_payload_json == {
            "text": "LLM[draft|the request]",
            "value": None,
        }
        assert checkpoint.revision == 1
        assert (await run_service.get_active_checkpoint(run.id)).id == checkpoint.id

        edited = await run_service.edit_checkpoint(
            run.id,
            checkpoint.id,
            expected_revision=1,
            current_payload_json={"text": "human-corrected draft"},
            flow_id=flow.id,
        )
        assert edited.state == ReviewCheckpointState.EDITED
        assert edited.revision == 2
        assert edited.current_payload_json == {
            "text": "human-corrected draft",
            "value": None,
        }
        assert edited.original_payload_json["text"] == "LLM[draft|the request]"

        # A stale revision is refused.
        with pytest.raises(BadRequestException):
            await run_service.approve_checkpoint(
                run.id, checkpoint.id, expected_revision=1
            )

        response = await run_service.approve_checkpoint(
            run.id, checkpoint.id, expected_revision=2, flow_id=flow.id, resume=True
        )
        assert response.checkpoint.state == ReviewCheckpointState.APPROVED
        assert response.run.status == FlowRunStatus.QUEUED

        # The worker picks the resumed run back up.
        await run_service.execute_run(run.id)
        finished = await run_service.get_run(run.id)
        assert finished.status == FlowRunStatus.COMPLETED
        assert finished.steps[1].status == StepResultStatus.COMPLETED
        assert finished.steps[1].output_payload_json["text"] == "human-corrected draft"
        assert (
            finished.output_payload_json["text"]
            == "LLM[finalize|human-corrected draft]"
        )
        assert finished.review_checkpoint is None
        assert await run_service.get_active_checkpoint(run.id) is None
        decided = await container.flow_repo().get_checkpoint(checkpoint.id, run.id)
        assert decided.state == ReviewCheckpointState.RESUMED.value
        assert decided.resumed_at is not None


async def test_approve_without_resume_then_resume(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        flow, run, run_service = await _paused_run(
            container, member_space, completion_model_factory, publish_flow, "two-step"
        )
        checkpoint = await run_service.get_active_checkpoint(run.id)
        approved = await run_service.approve_checkpoint(
            run.id, checkpoint.id, expected_revision=1, resume=False
        )
        assert approved.checkpoint.state == ReviewCheckpointState.APPROVED
        assert approved.run.status == FlowRunStatus.AWAITING_REVIEW

        # Approving twice is refused; resuming moves the run to queued.
        with pytest.raises(BadRequestException):
            await run_service.approve_checkpoint(
                run.id, checkpoint.id, expected_revision=1
            )
        resumed = await run_service.resume_checkpoint(
            run.id, checkpoint.id, expected_revision=1
        )
        assert resumed.run.status == FlowRunStatus.QUEUED

        await run_service.execute_run(run.id)
        finished = await run_service.get_run(run.id)
        assert finished.status == FlowRunStatus.COMPLETED
        assert (
            finished.output_payload_json["text"]
            == "LLM[finalize|LLM[draft|the request]]"
        )


async def test_rejecting_review_fails_the_run(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        flow, run, run_service = await _paused_run(
            container, member_space, completion_model_factory, publish_flow, "reject"
        )
        checkpoint = await run_service.get_active_checkpoint(run.id)
        rejected = await run_service.reject_checkpoint(
            run.id, checkpoint.id, expected_revision=1, reason="not good enough"
        )
        assert rejected.state == ReviewCheckpointState.REJECTED
        assert rejected.reason == "not good enough"

        failed = await run_service.get_run(run.id)
        assert failed.status == FlowRunStatus.FAILED
        assert failed.error.code == REVIEW_REJECTED
        assert "not good enough" in failed.error.message
        assert failed.steps[1].status == StepResultStatus.FAILED
        assert failed.steps[2].status == StepResultStatus.CANCELLED

        with pytest.raises(BadRequestException):
            await run_service.approve_checkpoint(
                run.id, checkpoint.id, expected_revision=1
            )


async def test_awaiting_review_run_ignores_redelivered_jobs(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        flow, run, run_service = await _paused_run(
            container, member_space, completion_model_factory, publish_flow, "redeliver"
        )
        calls = len(provider.calls)
        await run_service.execute_run(run.id)
        still_paused = await run_service.get_run(run.id)
        assert still_paused.status == FlowRunStatus.AWAITING_REVIEW
        assert still_paused.steps[2].status == StepResultStatus.PENDING
        assert len(provider.calls) == calls


async def test_view_mode_checkpoint_cannot_be_edited(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        flow, run, run_service = await _paused_run(
            container,
            member_space,
            completion_model_factory,
            publish_flow,
            "view",
            mode="view",
        )
        checkpoint = await run_service.get_active_checkpoint(run.id)
        assert checkpoint.review_mode == "view"
        with pytest.raises(BadRequestException, match="not editing"):
            await run_service.edit_checkpoint(
                run.id,
                checkpoint.id,
                expected_revision=1,
                current_payload_json={"text": "changed"},
            )


async def test_json_review_validates_the_edited_value_against_the_schema(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    provider.answer = lambda prompt, text_input: (
        '{"priority": 2}' if "JSON Schema" in prompt else f"LLM[{prompt}|{text_input}]"
    )
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "json-review-model")
        space = await member_space(session, "JSON Review Space", [model.id])
        definition = FlowDefinition(
            form_fields=[topic_field()],
            steps=[
                LlmStep(
                    key="classify",
                    name="Classify",
                    prompt="classify",
                    input="{{form.topic}}",
                    model_id=model.id,
                    output={
                        "type": "json",
                        "schema": {
                            "type": "object",
                            "required": ["priority"],
                            "properties": {"priority": {"type": "integer"}},
                        },
                    },
                ),
                ReviewStep(key="check", name="Check"),
                LlmStep(
                    key="answer",
                    name="Answer",
                    prompt="answer",
                    input="Priority {{steps.classify.json.priority}}",
                    model_id=model.id,
                ),
            ],
        )
        flow = await publish_flow(container, space, definition)
        run_service = container.flow_run_service()
        run = await run_service.create_run(flow.id, values={"topic": "x"}, files={})
        await run_service.execute_run(run.id)

        checkpoint = await run_service.get_active_checkpoint(run.id)
        assert checkpoint.output_type == "json"
        assert checkpoint.current_payload_json["value"] == {"priority": 2}

        with pytest.raises(BadRequestException, match="does not satisfy"):
            await run_service.edit_checkpoint(
                run.id,
                checkpoint.id,
                expected_revision=1,
                current_payload_json={"value": {"priority": "high"}},
            )
        edited = await run_service.edit_checkpoint(
            run.id,
            checkpoint.id,
            expected_revision=1,
            current_payload_json={"value": {"priority": 1}},
        )
        await run_service.approve_checkpoint(
            run.id, checkpoint.id, expected_revision=edited.revision
        )
        await run_service.execute_run(run.id)
        finished = await run_service.get_run(run.id)
        assert finished.status == FlowRunStatus.COMPLETED
        # Downstream reads the reviewed value when it names the reviewed step.
        assert finished.output_payload_json["text"] == "LLM[answer|Priority 1]"
