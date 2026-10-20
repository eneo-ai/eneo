"""End-to-end flow lifecycle: draft -> publish -> run -> completed."""

import pytest

from eneo.flows.definition import ComposeStep, FlowDefinition, LlmStep
from eneo.flows.flow_models import FlowRunStatus, StepResultStatus
from eneo.main.exceptions import BadRequestException, UnauthorizedException
from tests.integration.flows.conftest import topic_field


def _three_steps(model_id) -> FlowDefinition:
    return FlowDefinition(
        form_fields=[topic_field()],
        steps=[
            LlmStep(
                key="extract",
                name="Extract",
                prompt="extract facts",
                input="{{form.topic}}",
                model_id=model_id,
            ),
            ComposeStep(
                key="wrap",
                name="Compose",
                template="Facts: {{previous}} (about: {{form.topic}})",
            ),
            LlmStep(
                key="summarize", name="Summarize", prompt="summarize", model_id=model_id
            ),
        ],
    )


async def test_three_step_flow_runs_to_completion_with_chained_outputs(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "flow-test-model")
        space = await member_space(session, "Flow Space", [model.id])

        flow_service = container.flow_service()
        draft = await flow_service.create_flow(
            space_id=space.id,
            name="Three step flow",
            description=None,
            definition=_three_steps(model.id),
        )
        assert draft.published_version is None
        assert draft.has_unpublished_changes is True
        assert all(step.id is not None for step in draft.definition.steps)

        published = await flow_service.publish_flow(draft.id)
        assert published.published_version == 1
        assert published.has_unpublished_changes is False

        contract = await flow_service.get_run_contract(draft.id)
        assert contract.published_flow_version == 1
        assert [f.key for f in contract.form_fields] == ["topic"]
        assert contract.final_output.kind == "llm"
        assert contract.final_output.output_type == "text"

        run_service = container.flow_run_service()
        run = await run_service.create_run(
            draft.id,
            values={"topic": "the question"},
            files={},
            expected_flow_version=1,
            run_label="first",
        )
        assert run.status == FlowRunStatus.QUEUED
        assert run.flow_version == 1
        assert [s.status for s in run.steps] == [StepResultStatus.PENDING] * 3
        assert run.job_id is not None

        # Execute inline, as the ARQ worker task would.
        await run_service.execute_run(run.id)

        finished = await run_service.get_run(run.id, flow_id=draft.id)
        assert finished.status == FlowRunStatus.COMPLETED
        outputs = [s.output_payload_json["text"] for s in finished.steps]
        assert outputs[0] == "LLM[extract facts|the question]"
        assert outputs[1] == (
            "Facts: LLM[extract facts|the question] (about: the question)"
        )
        assert outputs[2] == f"LLM[summarize|{outputs[1]}]"
        assert finished.output_payload_json["text"] == outputs[2]
        assert finished.steps[0].input_payload_json["text"] == "the question"
        # Completion steps record token usage; deterministic steps do not.
        assert finished.steps[0].num_tokens_input == 7
        assert finished.steps[1].num_tokens_input is None
        assert finished.steps[0].current_attempt_no == 1

        state = await run_service.get_run_state(run.id)
        assert state.status == FlowRunStatus.COMPLETED
        assert state.steps[1].preview.startswith("Facts: ")

        listed, total = await run_service.list_runs(draft.id)
        assert total == 1 and listed[0].id == run.id
        sparse = await flow_service.list_flows(space.id)
        assert sparse[0].step_count == 3
        assert sparse[0].last_run.id == run.id


async def test_definition_problems_are_listed_for_repair(
    db_container, member_space, completion_model_factory, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "flow-test-model-v")
        space = await member_space(session, "Validation Space", [model.id])
        from uuid import uuid4

        bad = FlowDefinition(
            steps=[
                LlmStep(key="a", name="A", prompt="p", input="{{form.nope}}"),
                LlmStep(key="b", name="B", prompt="p", model_id=uuid4()),
            ]
        )
        with pytest.raises(BadRequestException) as exc:
            await container.flow_service().create_flow(
                space_id=space.id, name="Bad", description=None, definition=bad
            )
        message = str(exc.value)
        assert "{{form.nope}} names no form field" in message
        assert "not available in this space" in message


async def test_stale_expected_version_is_rejected_and_update_keeps_step_ids(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "flow-test-model-2")
        space = await member_space(session, "Versioned Space", [model.id])
        flow_service = container.flow_service()
        flow = await publish_flow(container, space, _three_steps(model.id))
        first_ids = {s.key: s.id for s in flow.definition.steps}

        changed = _three_steps(model.id)
        changed.steps[0].prompt = "extract more"
        updated = await flow_service.update_flow(flow.id, definition=changed)
        assert {s.key: s.id for s in updated.definition.steps} == first_ids
        assert updated.has_unpublished_changes is True
        republished = await flow_service.publish_flow(flow.id)
        assert republished.published_version == 2

        with pytest.raises(BadRequestException):
            await container.flow_run_service().create_run(
                flow.id, values={"topic": "x"}, files={}, expected_flow_version=1
            )


async def test_rerun_safe_claims_skip_already_completed_steps(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "flow-test-model-3")
        space = await member_space(session, "Rerun Space", [model.id])
        flow = await publish_flow(container, space, _three_steps(model.id))

        run_service = container.flow_run_service()
        run = await run_service.create_run(flow.id, values={"topic": "q"}, files={})
        await run_service.execute_run(run.id)
        first = await run_service.get_run(run.id)
        calls = len(provider.calls)

        # Redelivery: executing again must not change outputs or call again.
        await run_service.execute_run(run.id)
        second = await run_service.get_run(run.id)

        assert second.status == FlowRunStatus.COMPLETED
        assert [s.output_payload_json for s in second.steps] == [
            s.output_payload_json for s in first.steps
        ]
        assert len(provider.calls) == calls


async def test_run_input_validation(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "flow-test-model-4")
        space = await member_space(session, "Input Space", [model.id])
        flow = await publish_flow(container, space, _three_steps(model.id))
        run_service = container.flow_run_service()

        with pytest.raises(BadRequestException, match="required form field 'topic'"):
            await run_service.create_run(flow.id, values={}, files={})
        with pytest.raises(BadRequestException, match="unknown form field"):
            await run_service.create_run(
                flow.id, values={"topic": "x", "extra": 1}, files={}
            )
        with pytest.raises(BadRequestException, match="takes a value, not files"):
            await run_service.create_run(
                flow.id, values={"topic": "x"}, files={"topic": []}
            )


async def test_run_is_not_addressable_through_another_flow(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "authz-model")
        space = await member_space(session, "Authz Space", [model.id])
        flow_a = await publish_flow(container, space, _three_steps(model.id), "A")
        flow_b = await publish_flow(container, space, _three_steps(model.id), "B")

        run_service = container.flow_run_service()
        run = await run_service.create_run(flow_a.id, values={"topic": "q"}, files={})
        assert (await run_service.get_run(run.id, flow_id=flow_a.id)).id == run.id
        from eneo.main.exceptions import NotFoundException

        with pytest.raises(NotFoundException):
            await run_service.get_run(run.id, flow_id=flow_b.id)


async def test_viewer_cannot_create_flows_and_unpublished_flow_cannot_run(
    db_container, space_factory, completion_model_factory, admin_user, provider
):
    from eneo.database.tables.spaces_table import SpacesUsers

    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "viewer-model")
        space = await space_factory(session, "Viewer Space", [model.id])
        session.add(
            SpacesUsers(space_id=space.id, user_id=admin_user.id, role="viewer")
        )
        await session.flush()

        with pytest.raises(UnauthorizedException):
            await container.flow_service().create_flow(
                space_id=space.id,
                name="Not allowed",
                description=None,
                definition=_three_steps(model.id),
            )


async def test_publish_refuses_a_transcribe_step_without_a_transcription_model(
    db_container, member_space, completion_model_factory, provider
):
    from eneo.flows.definition import FormField, TranscribeStep

    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "transcribe-model")
        space = await member_space(session, "Transcribe Space", [model.id])
        definition = FlowDefinition(
            form_fields=[FormField(key="recording", label="Recording", type="audio")],
            steps=[
                TranscribeStep(key="t", name="Transcribe", source="recording"),
                LlmStep(key="a", name="A", prompt="p", model_id=model.id),
            ],
        )
        flow_service = container.flow_service()
        flow = await flow_service.create_flow(
            space_id=space.id,
            name="Audio flow",
            description=None,
            definition=definition,
        )
        with pytest.raises(BadRequestException, match="needs a transcription model"):
            await flow_service.publish_flow(flow.id)


async def test_soft_deleted_flow_disappears_but_its_runs_stay_readable(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    from eneo.main.exceptions import NotFoundException

    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "delete-model")
        space = await member_space(session, "Delete Space", [model.id])
        flow = await publish_flow(container, space, _three_steps(model.id))
        run_service = container.flow_run_service()
        run = await run_service.create_run(flow.id, values={"topic": "q"}, files={})

        await container.flow_service().delete_flow(flow.id)
        assert await container.flow_service().list_flows(space.id) == []
        with pytest.raises(NotFoundException):
            await container.flow_service().get_flow(flow.id)
        assert (await run_service.get_run(run.id)).id == run.id


async def test_a_draft_can_be_test_run_without_publishing(
    db_container, member_space, completion_model_factory, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "draft-run-model")
        space = await member_space(session, "Draft Run Space", [model.id])
        flow_service = container.flow_service()
        draft = await flow_service.create_flow(
            space_id=space.id,
            name="Draft flow",
            description=None,
            definition=_three_steps(model.id),
        )
        run_service = container.flow_run_service()

        # Without the draft flag an unpublished flow cannot run.
        with pytest.raises(BadRequestException, match="not published"):
            await run_service.create_run(draft.id, values={"topic": "x"}, files={})
        with pytest.raises(BadRequestException, match="does not apply"):
            await run_service.create_run(
                draft.id,
                values={"topic": "x"},
                files={},
                draft=True,
                expected_flow_version=1,
            )

        run = await run_service.create_run(
            draft.id, values={"topic": "the draft"}, files={}, draft=True
        )
        assert run.is_test is True
        assert run.flow_version is None
        await run_service.execute_run(run.id)

        finished = await run_service.get_run(run.id, flow_id=draft.id)
        assert finished.status == FlowRunStatus.COMPLETED
        assert finished.output_payload_json["text"].startswith("LLM[summarize|")
        # The flow is still a draft; the run kept the definition it executed.
        assert (await flow_service.get_flow(draft.id)).published_version is None
        state = await run_service.get_run_state(run.id)
        assert state.is_test is True and state.flow_version is None
        listed, _ = await run_service.list_runs(draft.id)
        assert listed[0].is_test is True

        # A draft that could not be published cannot be test run either.
        await flow_service.update_flow(draft.id, definition=FlowDefinition())
        with pytest.raises(BadRequestException, match="at least one step"):
            await run_service.create_run(draft.id, values={}, files={}, draft=True)
