from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    BuilderPlan,
    BuilderSession,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    PlannerPlanEnvelope,
    PlanStatus,
    SessionStatus,
    StepSpec,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_plan_lifecycle import AIBuilderPlanLifecycle
from intric.main.exceptions import BadRequestException


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user.tenant_id = uuid4()
    return user


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
    edit_result_json: dict[str, object] | None = None,
    spec: FlowDraftSpecCore | None = None,
) -> BuilderPlan:
    used_spec = spec or _make_spec()
    return BuilderPlan(
        id=uuid4(),
        session_id=session_id,
        tenant_id=tenant_id,
        status=status,
        spec=used_spec,
        spec_hash=used_spec.spec_hash(),
        envelope=PlannerPlanEnvelope(spec=used_spec),
        edit_result_json=edit_result_json,
    )


def _make_session(
    *, tenant_id, actor_user_id, flow_id, target_kind: TargetKind, space_id=None
):
    return BuilderSession(
        id=uuid4(),
        tenant_id=tenant_id,
        space_id=space_id or uuid4(),
        actor_user_id=actor_user_id,
        flow_id=flow_id,
        target_kind=target_kind,
        status=SessionStatus.AWAITING_APPROVAL,
    )


class TestAIBuilderPlanLifecycle:
    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.execute_changeset")
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.compile_changeset")
    async def test_apply_plan_passes_manual_description_override_to_compile(
        self,
        mock_compile,
        mock_execute,
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
            edit_result_json={"description_override_manual": True},
        )
        flow_service.get_flow.return_value = SimpleNamespace(
            id=flow_id,
            space_id=session.space_id,
            draft_revision=2,
            published_version=None,
            steps=[],
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session
        mock_compile.return_value = MagicMock()
        mock_execute.return_value = SimpleNamespace(
            flow_id=flow_id,
            flow_name="Flow",
            steps_created=0,
            steps_updated=1,
            steps_removed=0,
        )

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
        )
        await lifecycle.apply_plan(plan_id=plan.id, expected_revision=2)

        assert mock_compile.call_args.kwargs["description_override_manual"] is True
        origin = mock_compile.call_args.kwargs["ai_builder_origin"]
        assert origin["builder_session_id"] == str(session.id)
        assert origin["builder_plan_id"] == str(plan.id)
        assert origin["builder_spec_hash"] == plan.spec_hash
        assert isinstance(origin["applied_at"], str)

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
        )

        with pytest.raises(BadRequestException, match="space"):
            await lifecycle.apply_plan(plan_id=plan.id, expected_revision=1)

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.execute_changeset")
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.compile_changeset")
    async def test_apply_plan_requires_transcription_model_for_audio_create(
        self,
        mock_compile,
        mock_execute,
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

        mock_compile.assert_not_called()
        mock_execute.assert_not_awaited()

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.execute_changeset")
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.compile_changeset")
    async def test_apply_plan_create_failure_rolls_back_without_flow_listing(
        self,
        mock_compile,
        mock_execute,
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
        mock_compile.return_value = MagicMock()
        mock_execute.side_effect = RuntimeError("apply failed")

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
        )

        with pytest.raises(RuntimeError, match="apply failed"):
            await lifecycle.apply_plan(plan_id=plan.id)

        repo.update_session_status.assert_any_await(
            session_id=session.id,
            tenant_id=user.tenant_id,
            status=SessionStatus.AWAITING_APPROVAL,
        )
        flow_service.list_flows.assert_not_awaited()

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.execute_changeset")
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.compile_changeset")
    async def test_apply_plan_canonicalizes_unique_model_and_kb_aliases_before_compile(
        self,
        mock_compile,
        mock_execute,
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
            spec=_make_grounded_spec(
                model_ref="gpt-5.4-nano",
                knowledge_refs=["socio"],
            ),
        )
        space = MagicMock()
        space.get_default_transcription_model.return_value = None
        space.completion_models = [
            SimpleNamespace(id=uuid4(), name="gpt-5.4-nano", provider_type="openai")
        ]
        space.collections = [
            SimpleNamespace(id=uuid4(), name="socio", description="Sociologi")
        ]
        space_service.get_space.return_value = space
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session
        mock_compile.return_value = MagicMock()
        mock_execute.return_value = SimpleNamespace(
            flow_id=uuid4(),
            flow_name="Flow",
            steps_created=1,
            steps_updated=0,
            steps_removed=0,
        )

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=space_service,
        )
        await lifecycle.apply_plan(plan_id=plan.id)

        compiled_spec = mock_compile.call_args.args[0]
        assistant_spec = compiled_spec.steps[0].assistant_spec
        assert assistant_spec.model_ref == str(space.completion_models[0].id)
        assert assistant_spec.knowledge_refs == [str(space.collections[0].id)]

    @pytest.mark.anyio
    async def test_apply_plan_rejects_ambiguous_kb_alias_before_compile(self) -> None:
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
            spec=_make_grounded_spec(model_ref=None, knowledge_refs=["socio"]),
        )
        space = MagicMock()
        space.get_default_transcription_model.return_value = None
        space.completion_models = []
        space.collections = [
            SimpleNamespace(id=uuid4(), name="Socio", description="A"),
            SimpleNamespace(id=uuid4(), name="socio", description="B"),
        ]
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
            BadRequestException, match="Ambiguous knowledge base reference 'socio'"
        ):
            await lifecycle.apply_plan(plan_id=plan.id)

        flow_service.create_flow.assert_not_awaited()
