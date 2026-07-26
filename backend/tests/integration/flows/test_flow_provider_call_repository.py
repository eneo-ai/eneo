from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from eneo.completion_models.domain.provider_call_observer import (
    ProviderCallRequestFacts,
    ProviderCallResultFacts,
)
from eneo.database.database import sessionmanager
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.domain.provider_call import (
    ProviderCallCompletion,
    ProviderCallRequest,
)
from eneo.flows.flow_run_provenance import MappedProviderCallProvenance
from eneo.flows.infrastructure.flow_provider_call_recorder import (
    FlowProviderCallRecorder,
)
from eneo.flows.infrastructure.flow_provider_call_repo import (
    FlowProviderCallNotFoundError,
    FlowProviderCallRepository,
    FlowProviderCallStateConflictError,
)
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository


@dataclass(frozen=True, slots=True)
class _StartedAttempt:
    attempt_id: UUID
    run_id: UUID
    step_id: UUID
    attempt_no: int
    tenant_id: UUID


def _build_flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
) -> Flow:
    return Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=space_id,
        name="Provider call lifecycle flow",
        description="Flow used to prove provider call persistence.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json=None,
        data_retention_days=30,
        created_at=None,
        updated_at=None,
        steps=[
            FlowStep(
                id=None,
                flow_id=uuid4(),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=1,
                user_description="Summarize the input",
                input_source="flow_input",
                input_type="text",
                input_contract=None,
                output_mode="pass_through",
                output_type="text",
                output_contract=None,
                input_bindings={"question": "{{flow.input.question}}"},
                output_classification_override=None,
                input_config=None,
                output_config=None,
            )
        ],
    )


async def _create_started_attempt(
    *,
    session,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
) -> _StartedAttempt:
    model = await completion_model_factory(
        session, f"provider-call-model-{uuid4().hex}"
    )
    space = await space_factory(session, "Provider call lifecycle space", [model.id])
    assistant = await assistant_factory(
        session,
        "Provider call lifecycle assistant",
        model.id,
        space_id=space.id,
    )
    flow = await FlowRepository(session=session).create(
        flow=_build_flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=admin_user.id,
            assistant_id=assistant.id,
        ),
        tenant_id=admin_user.tenant_id,
    )
    step = flow.steps[0]
    assert flow.id is not None
    assert step.id is not None
    await FlowVersionRepository(session=session).create(
        flow_id=flow.id,
        version=1,
        definition_json={
            "steps": [
                {
                    "step_id": str(step.id),
                    "assistant_id": str(step.assistant_id),
                    "step_order": step.step_order,
                }
            ]
        },
        tenant_id=admin_user.tenant_id,
    )
    run_repo = FlowRunRepository(session=session)
    run = await run_repo.create(
        flow_id=flow.id,
        flow_version=1,
        principal_user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        input_payload_json={"question": "What happened?"},
        preseed_steps=[
            {
                "step_id": step.id,
                "assistant_id": step.assistant_id,
                "step_order": step.step_order,
            }
        ],
    )
    attempt = await run_repo.create_or_get_attempt_started(
        run_id=run.id,
        flow_id=flow.id,
        tenant_id=admin_user.tenant_id,
        step_id=step.id,
        step_order=step.step_order,
        attempt_no=1,
        celery_task_id="provider-call-lifecycle-test",
    )
    return _StartedAttempt(
        attempt_id=attempt.id,
        run_id=run.id,
        step_id=step.id,
        attempt_no=attempt.attempt_no,
        tenant_id=admin_user.tenant_id,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_provider_call_ordinals_resume_from_persisted_attempt_rows(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        context = await _create_started_attempt(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        request = ProviderCallRequest(
            provider_request_hash="a" * 64,
            requested_model="openai/gpt-4o-mini",
            provider="openai",
            response_format="json_object",
        )

        first = await FlowProviderCallRepository(session).start_call(
            attempt_id=context.attempt_id,
            request=request,
        )
        await session.flush()
        second = await FlowProviderCallRepository(session).start_call(
            attempt_id=context.attempt_id,
            request=request.model_copy(update={"provider_request_hash": "b" * 64}),
        )

        assert first.ordinal == 1
        assert second.ordinal == 2
        assert first.status == "started"
        assert second.status == "started"
        assert first.flow_step_attempt_id == context.attempt_id
        assert second.flow_step_attempt_id == context.attempt_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_provider_call_completion_is_idempotent_and_rejects_conflicts(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        context = await _create_started_attempt(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        repo = FlowProviderCallRepository(session)
        started = await repo.start_call(
            attempt_id=context.attempt_id,
            request=ProviderCallRequest(
                provider_request_hash="c" * 64,
                requested_model="openai/gpt-4o-mini",
                provider="openai",
            ),
        )
        receipt = ProviderCallCompletion(
            response_model="gpt-4o-mini-2026-07-01",
            provider_response_id="provider-response-1",
            num_tokens_input=21,
            num_tokens_output=8,
            input_source="provider",
            output_source="provider",
        )

        completed = await repo.complete_call(call_id=started.id, receipt=receipt)
        replayed = await repo.complete_call(call_id=started.id, receipt=receipt)

        assert completed == replayed
        assert completed.status == "completed"
        assert completed.finished_at is not None
        assert completed.provider_response_id == "provider-response-1"
        assert completed.num_tokens_input == 21
        assert completed.num_tokens_output == 8

        with pytest.raises(FlowProviderCallStateConflictError):
            await repo.complete_call(
                call_id=started.id,
                receipt=receipt.model_copy(
                    update={"provider_response_id": "conflicting-response"}
                ),
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_provider_call_known_rejection_and_unknown_outcome_are_distinct(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        context = await _create_started_attempt(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        repo = FlowProviderCallRepository(session)
        rejected_start = await repo.start_call(
            attempt_id=context.attempt_id,
            request=ProviderCallRequest(provider_request_hash="d" * 64),
        )
        unknown_start = await repo.start_call(
            attempt_id=context.attempt_id,
            request=ProviderCallRequest(provider_request_hash="e" * 64),
        )

        rejected = await repo.reject_call(
            call_id=rejected_start.id,
            reason="response_format_rejected",
        )
        unknown = await repo.mark_outcome_unknown(
            call_id=unknown_start.id,
            reason="request_timeout",
        )

        assert rejected.status == "rejected"
        assert rejected.outcome_reason == "response_format_rejected"
        assert rejected.finished_at is not None
        assert unknown.status == "outcome_unknown"
        assert unknown.outcome_reason == "request_timeout"
        assert unknown.finished_at is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_provider_call_recorder_commits_outside_executor_session(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as setup_session, setup_session.begin():
        context = await _create_started_attempt(
            session=setup_session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )

    recorder = FlowProviderCallRecorder(
        run_id=context.run_id,
        step_id=context.step_id,
        attempt_no=context.attempt_no,
        tenant_id=context.tenant_id,
        mapped_call=None,
    )
    call_id = await recorder.started(
        ProviderCallRequestFacts(
            request_schema_version=1,
            provider_request_hash="1" * 64,
            requested_model="openai/gpt-4o-mini",
            provider="openai",
            response_format="none",
            reason="initial",
        )
    )
    await recorder.completed(
        call_id,
        ProviderCallResultFacts(
            response_model="gpt-4o-mini-2026-07-01",
            provider_response_id="isolated-session-response",
            num_tokens_input=13,
            num_tokens_output=5,
        ),
    )

    async with (
        sessionmanager.session() as verification_session,
        verification_session.begin(),
    ):
        persisted = await FlowProviderCallRepository(verification_session).get_call(
            call_id=call_id
        )

    assert persisted.status == "completed"
    assert persisted.ordinal == 1
    assert persisted.provider_response_id == "isolated-session-response"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_provider_call_evidence_page_is_stable_bounded_and_cursor_checked(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        context = await _create_started_attempt(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        repo = FlowProviderCallRepository(session)
        calls = [
            await repo.start_call(
                attempt_id=context.attempt_id,
                request=ProviderCallRequest(
                    provider_request_hash=f"{index:x}" * 64,
                    mapped_call=(
                        MappedProviderCallProvenance(
                            execution_mode="per_source_reader",
                            source_index=1,
                            source_id="source-file-1",
                        )
                        if index == 1
                        else None
                    ),
                ),
            )
            for index in (1, 2, 3)
        ]

        first_page = await repo.list_evidence_page(
            run_id=context.run_id,
            tenant_id=context.tenant_id,
            limit=2,
        )
        second_page = await repo.list_evidence_page(
            run_id=context.run_id,
            tenant_id=context.tenant_id,
            limit=2,
            after_event_id=first_page.next_after_event_id,
        )

        assert [item.event_id for item in first_page.items] == [
            calls[0].id,
            calls[1].id,
        ]
        assert first_page.count == 2
        assert first_page.total_count == 3
        assert first_page.has_more is True
        assert first_page.next_after_event_id == calls[1].id
        assert first_page.items[0].mapped_execution_mode == "per_source"
        assert first_page.items[0].mapped_source_index == 1
        assert first_page.items[0].mapped_source_id == "source-file-1"
        assert [item.event_id for item in second_page.items] == [calls[2].id]
        assert second_page.count == 1
        assert second_page.total_count == 3
        assert second_page.has_more is False
        assert second_page.next_after_event_id is None

        with pytest.raises(FlowProviderCallNotFoundError):
            await repo.list_evidence_page(
                run_id=context.run_id,
                tenant_id=context.tenant_id,
                limit=2,
                after_event_id=uuid4(),
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_stale_run_recovery_marks_only_started_provider_calls_unknown(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        context = await _create_started_attempt(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        repo = FlowProviderCallRepository(session)
        completed_start = await repo.start_call(
            attempt_id=context.attempt_id,
            request=ProviderCallRequest(provider_request_hash="a" * 64),
        )
        started = await repo.start_call(
            attempt_id=context.attempt_id,
            request=ProviderCallRequest(provider_request_hash="b" * 64),
        )
        await repo.complete_call(
            call_id=completed_start.id,
            receipt=ProviderCallCompletion(
                num_tokens_input=2,
                num_tokens_output=1,
                input_source="provider",
                output_source="provider",
            ),
        )

        changed = await repo.mark_started_calls_outcome_unknown_for_run(
            run_id=context.run_id,
            tenant_id=context.tenant_id,
            reason="stale_started",
        )

        assert changed == 1
        assert (await repo.get_call(call_id=completed_start.id)).status == "completed"
        recovered = await repo.get_call(call_id=started.id)
        assert recovered.status == "outcome_unknown"
        assert recovered.outcome_reason == "stale_started"
        assert recovered.finished_at is not None
