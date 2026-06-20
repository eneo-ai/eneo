from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_authoring_policy import AIBuilderAuthoringPolicy
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
    LintSeverity,
    LintWarning,
    PlannerPlanEnvelope,
    PlanStatus,
    SessionStatus,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
    BuilderPlanEditResult,
    CompiledEditResult,
    FlowEditDiff,
    FlowEditDraft,
    StepChange,
    StepEditOperation,
)
from intric.flows.ai_builder.ai_builder_plan_lifecycle import AIBuilderPlanLifecycle
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    MaterializerProgressSnapshot,
)
from intric.flows.application.flow_authoring_command import (
    EditFlowAuthoringCommand,
    FlowAuthoringCommandService,
    FlowAuthoringResult,
)
from intric.flows.application.flow_draft_materialization import (
    FlowDraftChangeSet,
    FlowDraftMaterializationProgress,
    FlowDraftMaterializationStage,
)
from intric.flows.domain.flow import Flow, FlowStep
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    StepSpec,
)
from intric.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from intric.main.exceptions import BadRequestException


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user.tenant_id = uuid4()
    return user


def _make_space_service() -> AsyncMock:
    space_service = AsyncMock()
    space = MagicMock()
    space.get_default_transcription_model.return_value = None
    space.completion_models = []
    space.collections = []
    space.mcp_servers = []
    space_service.get_space.return_value = space
    return space_service


@asynccontextmanager
async def _noop_savepoint() -> AsyncIterator[None]:
    yield


def _make_repo_mock() -> AsyncMock:
    repo = AsyncMock()
    repo.savepoint = _noop_savepoint
    return repo


def _make_authoring_service(
    *,
    flow_id=None,
    flow_name: str = "Flow",
    steps_created: int = 0,
    steps_updated: int = 1,
    steps_removed: int = 0,
) -> AsyncMock:
    service = AsyncMock()
    service.prepare.return_value = SimpleNamespace(
        changeset=FlowDraftChangeSet(flow_name=flow_name, flow_description="")
    )
    service.apply_prepared.return_value = FlowAuthoringResult(
        flow_id=flow_id or uuid4(),
        flow_name=flow_name,
        draft_revision=2,
        steps_created=steps_created,
        steps_updated=steps_updated,
        steps_removed=steps_removed,
        command_spec_hash="spec-hash",
    )
    return service


def _make_spec(*, input_type: InputType = InputType.TEXT) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Flow",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Step A",
                assistant_spec=AssistantSpec(instructions="Do something."),
                input_source=InputSource.FLOW_INPUT,
                input_type=input_type,
            )
        ],
    )


def _make_grounded_spec(
    *, model_ref: str | None, knowledge_refs: list[str]
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Flow",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Step A",
                assistant_spec=AssistantSpec(
                    instructions="Do something.",
                    model_ref=model_ref,
                    knowledge_refs=knowledge_refs,
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
            )
        ],
    )


def _make_plan(
    *,
    session_id,
    tenant_id,
    status: PlanStatus = PlanStatus.APPROVED,
    edit_result: BuilderPlanEditResult | None = None,
    spec: FlowDraftSpecCore | None = None,
    resource_bindings: tuple[LocalResourceBinding, ...] = tuple(),
    envelope: PlannerPlanEnvelope | None = None,
) -> BuilderPlan:
    used_spec = spec or _make_spec()
    return BuilderPlan(
        id=uuid4(),
        session_id=session_id,
        tenant_id=tenant_id,
        status=status,
        spec=used_spec,
        spec_hash=used_spec.spec_hash(),
        envelope=envelope or PlannerPlanEnvelope(spec=used_spec),
        resource_bindings=resource_bindings,
        edit_result=edit_result,
    )


def _make_compiled_edit_result(
    spec: FlowDraftSpecCore,
    *,
    operations: list[StepEditOperation] | None = None,
) -> CompiledEditResult:
    return CompiledEditResult(
        compiled_spec=spec,
        diff=FlowEditDiff(
            step_changes=[StepChange(kind="unchanged", step_name="Step A")]
        ),
        original_draft=FlowEditDraft(operations=operations or []),
        base_flow_revision=1,
    )


def _make_plan_edit_result(
    spec: FlowDraftSpecCore,
    *,
    operations: list[StepEditOperation] | None = None,
    description_override_manual: bool = False,
) -> BuilderPlanEditResult:
    return BuilderPlanEditResult(
        compiled_edit=_make_compiled_edit_result(spec, operations=operations),
        description_override_manual=description_override_manual,
    )


def _make_binding(
    *,
    kind: ResourceSlotKind,
    slot: str,
    label: str,
    local_kind: LocalResourceKind,
    local_id,
) -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=ResourceSlotRef(kind=kind, slot=slot, label=label),
        local_kind=local_kind,
        local_id=local_id,
    )


def _make_session(
    *,
    tenant_id,
    actor_user_id,
    flow_id,
    target_kind: TargetKind,
    space_id=None,
    status: SessionStatus = SessionStatus.AWAITING_APPROVAL,
):
    return BuilderSession(
        id=uuid4(),
        tenant_id=tenant_id,
        space_id=space_id or uuid4(),
        actor_user_id=actor_user_id,
        flow_id=flow_id,
        target_kind=target_kind,
        status=status,
    )


def _make_flow_for_edit(
    *,
    flow_id,
    space_id,
    draft_revision: int = 1,
    step_count: int = 1,
) -> Flow:
    return Flow(
        id=flow_id,
        tenant_id=uuid4(),
        space_id=space_id,
        name="Existing flow",
        description="Existing flow description.",
        draft_revision=draft_revision,
        steps=[
            FlowStep(
                id=uuid4(),
                flow_id=flow_id,
                tenant_id=uuid4(),
                assistant_id=uuid4(),
                step_order=index,
                user_description=f"Step {index}",
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
                mcp_policy="inherit",
            )
            for index in range(1, step_count + 1)
        ],
    )


class TestAIBuilderPlanLifecycle:
    @pytest.mark.anyio
    async def test_revise_plan_persists_replacement_without_active_send_turn(self):
        user = _make_user()
        repo = _make_repo_mock()
        binding = _make_binding(
            kind=ResourceSlotKind.MODEL,
            slot="fast-model",
            label="Fast model",
            local_kind=LocalResourceKind.COMPLETION_MODEL,
            local_id=uuid4(),
        )
        plan_spec = _make_spec()
        compiled_edit_result = _make_compiled_edit_result(plan_spec)
        plan = _make_plan(
            session_id=uuid4(),
            tenant_id=user.tenant_id,
            status=PlanStatus.PROPOSED,
            spec=plan_spec,
            resource_bindings=(binding,),
            edit_result=BuilderPlanEditResult(compiled_edit=compiled_edit_result),
            envelope=PlannerPlanEnvelope(
                spec=plan_spec,
                lint_warnings=[
                    LintWarning(
                        code="needs_model",
                        message="Select a model before applying.",
                        severity=LintSeverity.WARNING,
                    )
                ],
                reasoning="prior proposal reasoning",
            ),
        )
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=None,
            target_kind=TargetKind.CREATE,
        )
        session.id = plan.session_id
        revised_plan = _make_plan(
            session_id=plan.session_id,
            tenant_id=user.tenant_id,
            status=PlanStatus.PROPOSED,
            resource_bindings=(binding,),
            edit_result=BuilderPlanEditResult(
                compiled_edit=compiled_edit_result,
                description_override_manual=True,
            ),
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session
        repo.create_plan.return_value = revised_plan

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=AsyncMock(),
            space_service=_make_space_service(),
        )

        result = await lifecycle.revise_plan(
            plan_id=plan.id,
            revision_type="keep_current_description",
        )

        assert result == revised_plan
        repo.supersede_existing_plans.assert_awaited_once_with(
            session_id=plan.session_id,
            tenant_id=user.tenant_id,
        )
        assert repo.create_plan.await_args is not None
        create_kwargs = repo.create_plan.await_args.kwargs
        assert create_kwargs["session_id"] == plan.session_id
        assert create_kwargs["tenant_id"] == user.tenant_id
        assert create_kwargs["spec"] == plan.spec
        assert create_kwargs["envelope"].lint_warnings == plan.envelope.lint_warnings
        assert create_kwargs["envelope"].reasoning is None
        assert create_kwargs["resource_bindings"] == (binding,)
        assert create_kwargs["edit_result"] == BuilderPlanEditResult(
            compiled_edit=compiled_edit_result, description_override_manual=True
        )
        repo.update_session_latest_plan_without_send_lease.assert_awaited_once_with(
            session_id=plan.session_id,
            tenant_id=user.tenant_id,
            plan_id=revised_plan.id,
        )

    @pytest.mark.anyio
    async def test_revise_plan_rejects_unsupported_revision_type(self):
        user = _make_user()
        repo = _make_repo_mock()
        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=AsyncMock(),
            space_service=_make_space_service(),
        )

        with pytest.raises(BadRequestException) as exc_info:
            await lifecycle.revise_plan(
                plan_id=uuid4(),
                revision_type="regenerate_description",
            )

        assert exc_info.value.code == "unsupported_revision_type"
        repo.get_plan.assert_not_called()

    @pytest.mark.anyio
    async def test_apply_plan_passes_manual_description_override_to_compile(
        self,
    ):
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        flow_id = uuid4()

        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=flow_id,
            target_kind=TargetKind.EDIT,
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            edit_result=_make_plan_edit_result(
                _make_spec(),
                description_override_manual=True,
            ),
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session
        authoring_service = _make_authoring_service(flow_id=flow_id)

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=_make_space_service(),
            authoring_service=authoring_service,
        )
        await lifecycle.apply_plan(plan_id=plan.id, expected_revision=1)

        command = authoring_service.prepare.await_args.kwargs["command"]
        assert isinstance(command, EditFlowAuthoringCommand)
        assert command.origin.description_override_manual is True
        assert command.origin.session_id == session.id
        assert command.origin.plan_id == plan.id
        assert command.origin.spec_hash == plan.spec_hash
        assert command.expected_revision == 1
        assert command.resource_bindings == tuple()
        assert isinstance(
            authoring_service.prepare.await_args.kwargs["origin_policy"],
            AIBuilderAuthoringPolicy,
        )

    @pytest.mark.anyio
    async def test_apply_plan_derives_removed_refs_from_persisted_edit_intent(
        self,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        flow_id = uuid4()
        spec = FlowDraftSpecCore(
            flow_name="Flow",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    name="Step A",
                    assistant_spec=AssistantSpec(instructions="Do something."),
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.TEXT,
                )
            ],
        )
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=flow_id,
            target_kind=TargetKind.EDIT,
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            spec=spec,
            edit_result=_make_plan_edit_result(
                spec,
                operations=[
                    StepEditOperation(op="remove", target_ref="existing_step_2")
                ],
            ),
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session
        authoring_service = _make_authoring_service(flow_id=flow_id, steps_removed=1)

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=_make_space_service(),
            authoring_service=authoring_service,
        )
        await lifecycle.apply_plan(plan_id=plan.id, expected_revision=1)

        command = authoring_service.prepare.await_args.kwargs["command"]
        assert isinstance(command, EditFlowAuthoringCommand)
        assert command.removed_existing_step_refs == frozenset({"existing_step_2"})

    @pytest.mark.anyio
    async def test_apply_plan_rejects_create_plan_with_existing_step_ref_at_authoring_boundary(
        self,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        spec = FlowDraftSpecCore(
            flow_name="Flow",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    name="Step A",
                    assistant_spec=AssistantSpec(instructions="Do something."),
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.TEXT,
                )
            ],
        )
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=None,
            target_kind=TargetKind.CREATE,
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            spec=spec,
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=_make_space_service(),
            authoring_service=FlowAuthoringCommandService(),
        )

        with pytest.raises(BadRequestException) as exc_info:
            await lifecycle.apply_plan(plan_id=plan.id)

        assert exc_info.value.code == "invalid_existing_step_ref"
        assert exc_info.value.context == {
            "reason": "create_cannot_use_existing_step_ref",
            "existing_step_ref": "existing_step_1",
        }
        repo.update_plan_status.assert_not_awaited()

    @pytest.mark.anyio
    async def test_apply_plan_rejects_truncated_edit_spec_without_explicit_removal(
        self,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        flow_id = uuid4()
        spec = FlowDraftSpecCore(
            flow_name="Flow",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    name="Step A",
                    assistant_spec=AssistantSpec(instructions="Do something."),
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.TEXT,
                )
            ],
        )
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=flow_id,
            target_kind=TargetKind.EDIT,
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            spec=spec,
            edit_result=_make_plan_edit_result(spec, operations=[]),
        )
        flow_service.get_flow.return_value = _make_flow_for_edit(
            flow_id=flow_id,
            space_id=session.space_id,
            draft_revision=1,
            step_count=2,
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=_make_space_service(),
            authoring_service=FlowAuthoringCommandService(),
        )

        with pytest.raises(BadRequestException) as exc_info:
            await lifecycle.apply_plan(plan_id=plan.id, expected_revision=1)

        assert exc_info.value.code == "invalid_existing_step_ref"
        assert exc_info.value.context == {
            "reason": "missing_existing_step_ref",
            "missing_refs": ["existing_step_2"],
        }
        repo.update_plan_status.assert_not_awaited()

    @pytest.mark.anyio
    async def test_apply_plan_rejects_edit_plan_without_compiled_edit(
        self,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        flow_id = uuid4()
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=flow_id,
            target_kind=TargetKind.EDIT,
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            edit_result=BuilderPlanEditResult(),
        )
        flow_service.get_flow.return_value = SimpleNamespace(
            id=flow_id,
            space_id=session.space_id,
            draft_revision=1,
            published_version=None,
            steps=[],
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=_make_space_service(),
        )

        with pytest.raises(BadRequestException) as exc_info:
            await lifecycle.apply_plan(plan_id=plan.id, expected_revision=1)

        assert exc_info.value.code == "bad_request"
        assert "compiled edit artifact" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_apply_plan_rejects_edit_flow_space_mismatch(self):
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        flow_id = uuid4()

        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=flow_id,
            target_kind=TargetKind.EDIT,
            space_id=uuid4(),
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            edit_result=_make_plan_edit_result(_make_spec()),
        )
        flow_service.get_flow.return_value = SimpleNamespace(
            id=flow_id,
            space_id=uuid4(),
            draft_revision=1,
            published_version=None,
            steps=[],
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=_make_space_service(),
        )

        with pytest.raises(BadRequestException, match="space"):
            await lifecycle.apply_plan(plan_id=plan.id, expected_revision=1)

    @pytest.mark.anyio
    async def test_apply_plan_requires_transcription_model_for_audio_create(
        self,
    ):
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        space_service = AsyncMock()

        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=None,
            target_kind=TargetKind.CREATE,
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            spec=_make_spec(input_type=InputType.AUDIO),
        )
        space = MagicMock()
        space.get_default_transcription_model.return_value = None
        space_service.get_space.return_value = space
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=space_service,
        )

        with pytest.raises(
            BadRequestException, match="transcription model must be selected"
        ):
            await lifecycle.apply_plan(plan_id=plan.id)

    @pytest.mark.anyio
    async def test_apply_plan_create_failure_marks_applying_without_flow_listing(
        self,
    ):
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()

        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=None,
            target_kind=TargetKind.CREATE,
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session
        authoring_service = _make_authoring_service()
        authoring_service.apply_prepared.side_effect = RuntimeError("apply failed")

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=_make_space_service(),
            authoring_service=authoring_service,
        )

        with pytest.raises(RuntimeError, match="apply failed"):
            await lifecycle.apply_plan(plan_id=plan.id)

        repo.update_session_status_without_send_lease.assert_any_await(
            session_id=session.id,
            tenant_id=user.tenant_id,
            status=SessionStatus.APPLYING,
        )
        flow_service.list_flows.assert_not_awaited()

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.log_apply_failed")
    async def test_apply_plan_logs_compile_runtime_failure(
        self,
        mock_log_apply_failed,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        flow_id = uuid4()
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=flow_id,
            target_kind=TargetKind.EDIT,
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            edit_result=_make_plan_edit_result(_make_spec()),
        )
        flow_service.get_flow.return_value = SimpleNamespace(
            id=flow_id,
            space_id=session.space_id,
            draft_revision=1,
            published_version=None,
            steps=[],
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session
        authoring_service = _make_authoring_service(flow_id=flow_id)
        authoring_service.prepare.side_effect = RuntimeError("compile exploded")

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=_make_space_service(),
            authoring_service=authoring_service,
        )

        with pytest.raises(RuntimeError, match="compile exploded"):
            await lifecycle.apply_plan(plan_id=plan.id, expected_revision=1)

        authoring_service.apply_prepared.assert_not_awaited()
        mock_log_apply_failed.assert_called_once()
        assert mock_log_apply_failed.call_args.kwargs["phase"] == "prepare_authoring"
        assert mock_log_apply_failed.call_args.kwargs["plan_id"] == plan.id
        assert mock_log_apply_failed.call_args.kwargs["session_id"] == session.id
        assert mock_log_apply_failed.call_args.kwargs["flow_id"] == flow_id
        assert isinstance(
            mock_log_apply_failed.call_args.kwargs["exception"], RuntimeError
        )
        assert mock_log_apply_failed.call_args.kwargs["changeset_counts"] is None
        assert mock_log_apply_failed.call_args.kwargs["materializer_progress"] is None
        repo.update_session_status_without_send_lease.assert_any_await(
            session_id=session.id,
            tenant_id=user.tenant_id,
            status=SessionStatus.APPLYING,
        )

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.log_apply_failed")
    async def test_apply_plan_logs_compile_bad_request_code(
        self,
        mock_log_apply_failed,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=None,
            target_kind=TargetKind.CREATE,
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            edit_result=_make_plan_edit_result(_make_spec()),
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session
        authoring_service = _make_authoring_service()
        authoring_service.prepare.side_effect = BadRequestException(
            "invalid compile",
            code="invalid_compiled_spec",
        )

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=_make_space_service(),
            authoring_service=authoring_service,
        )

        with pytest.raises(BadRequestException, match="invalid compile"):
            await lifecycle.apply_plan(plan_id=plan.id)

        authoring_service.apply_prepared.assert_not_awaited()
        assert mock_log_apply_failed.call_args.kwargs["phase"] == "prepare_authoring"
        exception = mock_log_apply_failed.call_args.kwargs["exception"]
        assert isinstance(exception, BadRequestException)
        assert exception.code == "invalid_compiled_spec"

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.log_apply_failed")
    async def test_apply_plan_logs_execute_runtime_failure_with_progress(
        self,
        mock_log_apply_failed,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        flow_id = uuid4()
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=flow_id,
            target_kind=TargetKind.EDIT,
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            edit_result=_make_plan_edit_result(_make_spec()),
        )
        flow_service.get_flow.return_value = SimpleNamespace(
            id=flow_id,
            space_id=session.space_id,
            draft_revision=1,
            published_version=None,
            steps=[],
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session
        changeset = FlowDraftChangeSet(
            flow_name="Flow",
            flow_description="Desc",
            assistants_to_create=[],
            assistants_to_update=[],
            assistants_to_delete=[],
            compiled_steps=[],
        )
        authoring_service = _make_authoring_service(flow_id=flow_id)
        authoring_service.prepare.return_value = SimpleNamespace(changeset=changeset)
        progress = FlowDraftMaterializationProgress(
            stage=FlowDraftMaterializationStage.ASSISTANTS_UPDATED,
            assistants_created=0,
            assistants_configured=0,
            assistants_updated=1,
            assistants_deleted=0,
            flow_created=False,
            flow_updated=False,
        )

        async def fail_execute(**kwargs):
            kwargs["progress_callback"](progress)
            raise RuntimeError("execute exploded")

        authoring_service.apply_prepared.side_effect = fail_execute

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=_make_space_service(),
            authoring_service=authoring_service,
        )

        with pytest.raises(RuntimeError, match="execute exploded"):
            await lifecycle.apply_plan(plan_id=plan.id, expected_revision=1)

        mock_log_apply_failed.assert_called_once()
        assert mock_log_apply_failed.call_args.kwargs["phase"] == "apply_authoring"
        assert mock_log_apply_failed.call_args.kwargs["changeset_counts"] is not None
        assert mock_log_apply_failed.call_args.kwargs[
            "materializer_progress"
        ] == MaterializerProgressSnapshot(
            stage="assistants_updated",
            assistants_created=0,
            assistants_configured=0,
            assistants_updated=1,
            assistants_deleted=0,
            flow_created=False,
            flow_updated=False,
        )
        repo.update_session_status_without_send_lease.assert_any_await(
            session_id=session.id,
            tenant_id=user.tenant_id,
            status=SessionStatus.APPLYING,
        )

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.log_apply_failed")
    async def test_apply_plan_logs_execute_bad_request_code(
        self,
        mock_log_apply_failed,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        flow_id = uuid4()
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=flow_id,
            target_kind=TargetKind.EDIT,
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            edit_result=_make_plan_edit_result(_make_spec()),
        )
        flow_service.get_flow.return_value = SimpleNamespace(
            id=flow_id,
            space_id=session.space_id,
            draft_revision=1,
            published_version=None,
            steps=[],
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session
        authoring_service = _make_authoring_service(flow_id=flow_id)
        authoring_service.prepare.return_value = SimpleNamespace(
            changeset=FlowDraftChangeSet(
                flow_name="Flow",
                flow_description="Desc",
            )
        )
        authoring_service.apply_prepared.side_effect = BadRequestException(
            "stale",
            code="stale_revision",
        )

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=_make_space_service(),
            authoring_service=authoring_service,
        )

        with pytest.raises(BadRequestException, match="stale"):
            await lifecycle.apply_plan(plan_id=plan.id, expected_revision=1)

        assert mock_log_apply_failed.call_args.kwargs["phase"] == "apply_authoring"
        exception = mock_log_apply_failed.call_args.kwargs["exception"]
        assert isinstance(exception, BadRequestException)
        assert exception.code == "stale_revision"

    @pytest.mark.anyio
    async def test_apply_plan_uses_plan_resource_bindings_without_rederiving(
        self,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        space_service = AsyncMock()

        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=None,
            target_kind=TargetKind.CREATE,
        )
        model_id = uuid4()
        collection_id = uuid4()
        plan_bindings = (
            _make_binding(
                kind=ResourceSlotKind.MODEL,
                slot="fast-model",
                label="Fast model",
                local_kind=LocalResourceKind.COMPLETION_MODEL,
                local_id=model_id,
            ),
            _make_binding(
                kind=ResourceSlotKind.KNOWLEDGE,
                slot="policy-kb",
                label="Policy KB",
                local_kind=LocalResourceKind.COLLECTION,
                local_id=collection_id,
            ),
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            spec=_make_grounded_spec(
                model_ref="model.fast-model",
                knowledge_refs=["knowledge.policy-kb"],
            ),
            resource_bindings=plan_bindings,
        )
        space = MagicMock()
        space.get_default_transcription_model.return_value = None
        space.completion_models = [
            SimpleNamespace(id=model_id, name="gpt-5.4-nano", provider_type="openai")
        ]
        space.collections = [
            SimpleNamespace(id=collection_id, name="socio", description="Sociologi")
        ]
        space_service.get_space.return_value = space
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session
        authoring_service = _make_authoring_service(
            flow_name="Flow",
            steps_created=1,
            steps_updated=0,
        )

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=space_service,
            authoring_service=authoring_service,
        )
        with patch(
            (
                "intric.flows.ai_builder.ai_builder_plan_lifecycle."
                "collect_flow_spec_resource_bindings"
            ),
            side_effect=AssertionError("apply must not re-derive bindings"),
            create=True,
        ):
            await lifecycle.apply_plan(plan_id=plan.id)

        command = authoring_service.prepare.await_args.kwargs["command"]
        assistant_spec = command.spec.steps[0].assistant_spec
        assert assistant_spec.model_ref == "model.fast-model"
        assert assistant_spec.knowledge_refs == ["knowledge.policy-kb"]
        assert command.resource_bindings == plan_bindings

    @pytest.mark.anyio
    async def test_apply_plan_rejects_resource_plan_without_binding_snapshot(
        self,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        space_service = AsyncMock()
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=None,
            target_kind=TargetKind.CREATE,
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            spec=_make_grounded_spec(model_ref="model.fast-model", knowledge_refs=[]),
        )
        space = MagicMock()
        space.get_default_transcription_model.return_value = None
        space_service.get_space.return_value = space
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=space_service,
        )

        with pytest.raises(BadRequestException) as exc_info:
            await lifecycle.apply_plan(plan_id=plan.id)

        assert exc_info.value.code == "ai_builder_plan_resource_bindings_missing"
        repo.update_session_status_without_send_lease.assert_not_awaited()

    @pytest.mark.anyio
    async def test_apply_plan_rejects_replaced_resource_with_same_name_before_compile(
        self,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        space_service = AsyncMock()
        missing_model_id = uuid4()
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            flow_id=None,
            target_kind=TargetKind.CREATE,
        )
        plan = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            spec=_make_grounded_spec(
                model_ref="model.fast-model",
                knowledge_refs=[],
            ),
            resource_bindings=(
                _make_binding(
                    kind=ResourceSlotKind.MODEL,
                    slot="fast-model",
                    label="Fast model",
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                    local_id=missing_model_id,
                ),
            ),
        )
        space = MagicMock()
        space.get_default_transcription_model.return_value = None
        space.completion_models = [
            SimpleNamespace(id=uuid4(), name="Fast model", provider_type="openai")
        ]
        space.collections = []
        space_service.get_space.return_value = space
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=space_service,
        )

        with pytest.raises(BadRequestException) as exc_info:
            await lifecycle.apply_plan(plan_id=plan.id)

        assert exc_info.value.code == "ai_builder_plan_resource_binding_unavailable"
        assert exc_info.value.context["slot_ref"] == "model.fast-model"
        assert exc_info.value.context["slot_kind"] == "model"
        assert exc_info.value.context["local_kind"] == "completion_model"
        repo.update_session_status_without_send_lease.assert_not_awaited()
