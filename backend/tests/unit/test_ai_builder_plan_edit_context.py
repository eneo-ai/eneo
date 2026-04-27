from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from intric.flows.ai_builder.ai_builder_domain_models import (
    AssistantSpec,
    ConversationMessage,
    FlowDraftSpecCore,
    FormFieldSpec,
    OutputType,
    PlannerPlanEnvelope,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
    CompiledEditResult,
    FlowEditDiff,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    _DOWNSTREAM_INPUT_REPAIR_FIELDS,
    AIBuilderPlanEditContext,
    build_plan_revision_prompt_block,
    validate_scoped_plan_revision,
)
from intric.flows.ai_builder.ai_builder_proposal_processor import (
    AIBuilderProposalProcessor,
    _terminal_output_type_for_conversation,
)
from intric.flows.domain.flow import FlowStep


def test_step_scoped_revision_rejects_unchanged_target_step() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _spec(
        [
            _step("step_a", "Analyze input", output_type="json"),
            _step("step_b", "Create final result", output_type="text"),
        ]
    )
    proposed = _spec(
        [
            _step("step_a", "Analyze input", output_type="json"),
            _step("step_b", "Create final result", output_type="text"),
            _step("step_c", "Render PDF", output_type="pdf"),
        ]
    )

    feedback = validate_scoped_plan_revision(
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
    assert "step_b" in feedback
    assert "was unchanged" in feedback


def test_step_scoped_revision_accepts_changed_target_step() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _spec([_step("step_b", "Create final result", output_type="text")])
    proposed = _spec([_step("step_b", "Create final result", output_type="pdf")])

    assert (
        validate_scoped_plan_revision(
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def test_step_scoped_revision_rejects_unrelated_step_rewrite() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _spec(
        [
            _step("step_a", "Analyze input", output_type="json"),
            _step("step_b", "Create final result", output_type="text"),
            _step("step_c", "Notify reviewer", output_type="text"),
        ]
    )
    proposed = _spec(
        [
            _step("step_a", "Analyze input differently", output_type="json"),
            _step("step_b", "Create final result", output_type="pdf"),
            _step("step_c", "Notify reviewer", output_type="text"),
        ]
    )

    feedback = validate_scoped_plan_revision(
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
    assert "unrelated steps" in feedback
    assert "step_a" in feedback


def test_step_scoped_revision_allows_direct_successor_input_repair() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _spec(
        [
            _step("step_a", "Analyze input", output_type="json"),
            _step("step_b", "Create final result", output_type="text"),
            _step("step_c", "Format response", input_type="text", output_type="text"),
        ]
    )
    proposed = _spec(
        [
            _step("step_a", "Analyze input", output_type="json"),
            _step("step_b", "Create final result", output_type="json"),
            _step("step_c", "Format response", input_type="json", output_type="text"),
        ]
    )

    assert (
        validate_scoped_plan_revision(
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def test_step_scoped_revision_allows_downstream_input_repair() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _spec(
        [
            _step("step_a", "Analyze input", output_type="json"),
            _step("step_b", "Create final result", output_type="text"),
            _step("step_c", "Review intermediate result", output_type="text"),
            _step("step_d", "Format response", input_type="text", output_type="text"),
        ]
    )
    proposed = _spec(
        [
            _step("step_a", "Analyze input", output_type="json"),
            _step("step_b", "Create final result", output_type="json"),
            _step("step_c", "Review intermediate result", output_type="text"),
            _step("step_d", "Format response", input_type="json", output_type="text"),
        ]
    )

    assert (
        validate_scoped_plan_revision(
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def test_step_scoped_revision_rejects_downstream_semantic_rewrite() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _spec(
        [
            _step("step_a", "Analyze input", output_type="json"),
            _step("step_b", "Create final result", output_type="text"),
            _step("step_c", "Format response", input_type="text", output_type="text"),
        ]
    )
    proposed = _spec(
        [
            _step("step_a", "Analyze input", output_type="json"),
            _step("step_b", "Create final result", output_type="json"),
            _step(
                "step_c", "Rewrite all results", input_type="json", output_type="text"
            ),
        ]
    )

    feedback = validate_scoped_plan_revision(
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
    assert "downstream input wiring" in feedback
    assert "step_c" in feedback


def test_step_scoped_revision_rejects_existing_step_reorder() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _spec(
        [
            _step("step_a", "Analyze input", output_type="json"),
            _step("step_b", "Create final result", output_type="text"),
            _step("step_c", "Format response", output_type="text"),
        ]
    )
    proposed = _spec(
        [
            _step("step_c", "Format response", output_type="text"),
            _step("step_a", "Analyze input", output_type="json"),
            _step("step_b", "Create final result", output_type="pdf"),
        ]
    )

    feedback = validate_scoped_plan_revision(
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
    assert "preserve the order" in feedback


def test_step_scoped_revision_rejects_duplicate_step_refs() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _spec(
        [
            _step("step_a", "Analyze input", output_type="json"),
            _step("step_b", "Create final result", output_type="text"),
        ]
    )
    proposed = _spec(
        [
            _step("step_a", "Analyze input", output_type="json"),
            _step("step_b", "Create final result", output_type="pdf"),
            _step("step_a", "Duplicate ref", output_type="text"),
        ]
    )

    feedback = validate_scoped_plan_revision(
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
    assert "Duplicate step refs" in feedback
    assert "step_a" in feedback


def test_step_scoped_revision_allows_descriptive_plan_text_changes() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _spec([_step("step_b", "Create final result", output_type="text")])
    proposed = _spec([_step("step_b", "Create final result", output_type="pdf")])
    proposed.flow_name = "Employee review PDF"
    proposed.flow_description = "Create a PDF result."

    assert (
        validate_scoped_plan_revision(
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def test_step_scoped_revision_rejects_runtime_form_field_changes() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _spec([_step("step_b", "Create final result", output_type="text")])
    proposed = _spec(
        [_step("step_b", "Create final result", output_type="pdf")],
        form_fields=[
            FormFieldSpec(
                name="new_input",
                type="text",
                label="New input",
                required=True,
            )
        ],
    )

    feedback = validate_scoped_plan_revision(
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
    assert "runtime form fields" in feedback


def test_downstream_input_repair_fields_are_valid_step_fields() -> None:
    assert _DOWNSTREAM_INPUT_REPAIR_FIELDS <= set(StepSpec.model_fields)


def test_plan_revision_terminal_output_intent_uses_latest_user_message() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Bygg ett flöde som skapar en PDF-rapport.",
        ),
        ConversationMessage(role="assistant", content="Här är planen."),
        ConversationMessage(
            role="user",
            content="Byt namn på steget till tydligare rubrik.",
        ),
    ]

    assert (
        _terminal_output_type_for_conversation(
            conversation,
            plan_edit_context=context,
        )
        is None
    )


def test_plan_revision_terminal_output_intent_accepts_current_pdf_edit() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Bygg ett flöde som skapar ett strukturerat textresultat.",
        ),
        ConversationMessage(role="assistant", content="Här är planen."),
        ConversationMessage(
            role="user",
            content="Ändra så att jag får ut en pdf fil istället för text.",
        ),
    ]

    assert (
        _terminal_output_type_for_conversation(
            conversation,
            plan_edit_context=context,
        )
        == OutputType.PDF
    )


def test_initial_plan_terminal_output_intent_can_use_full_requirements() -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content="Bygg ett flöde som skapar en PDF-rapport.",
        ),
        ConversationMessage(role="assistant", content="Vill du bygga planen?"),
        ConversationMessage(role="user", content="Ja, bygg planen."),
    ]

    assert (
        _terminal_output_type_for_conversation(
            conversation,
            plan_edit_context=None,
        )
        == OutputType.PDF
    )


@pytest.mark.asyncio
async def test_create_path_validates_scoped_revision_after_terminal_artifact_fold(
    monkeypatch,
) -> None:
    tenant_id = UUID("00000000-0000-0000-0000-0000000000aa")
    plan_id = UUID("00000000-0000-0000-0000-000000000001")
    processor = AIBuilderProposalProcessor(
        user=SimpleNamespace(tenant_id=tenant_id),
        repo=SimpleNamespace(),
        litellm_client=SimpleNamespace(),
        self_correction_temperature=0.0,
        self_correction_bumped_temperature=0.0,
        forced_proposal_temperature=0.0,
        quality_retry_warning_codes=set(),
    )
    prior = _spec(
        [
            _step("step_a", "Analyze salary discussion", output_type="json"),
            _step("step_b", "Create final result", output_type="text"),
        ]
    )
    raw_proposal = _spec(
        [
            _step("step_a", "Analyze salary discussion", output_type="json"),
            _step("step_c", "Render PDF helper", output_type="pdf"),
            _step("step_b", "Create final result", output_type="text"),
        ]
    )
    stored_specs: list[FlowDraftSpecCore] = []

    async def fake_store_plan_and_update_conversation(**kwargs):
        spec = kwargs["spec"]
        stored_specs.append(spec)
        return (
            SimpleNamespace(id=UUID("00000000-0000-0000-0000-000000000099")),
            PlannerPlanEnvelope(spec=spec),
        )

    monkeypatch.setattr(
        "intric.flows.ai_builder.ai_builder_proposal_processor.normalize_create_draft_mechanics",
        lambda draft: draft,
    )
    monkeypatch.setattr(
        "intric.flows.ai_builder.ai_builder_proposal_processor.validate_create_draft",
        lambda draft: SimpleNamespace(errors=[]),
    )
    monkeypatch.setattr(
        "intric.flows.ai_builder.ai_builder_proposal_processor.compile_create_draft",
        lambda draft: raw_proposal,
    )
    monkeypatch.setattr(
        "intric.flows.ai_builder.ai_builder_proposal_processor.store_plan_and_update_conversation",
        fake_store_plan_and_update_conversation,
    )
    monkeypatch.setattr(processor, "_format_quality_feedback", lambda validation: None)
    monkeypatch.setattr(
        processor,
        "_format_contextual_quality_feedback",
        lambda **kwargs: None,
    )

    result = await processor._process_create_draft(
        session_id=uuid4(),
        conversation=[
            ConversationMessage(
                role="user",
                content="Ändra steg 2 så att jag får ut en pdf fil istället för text.",
            )
        ],
        new_messages_start=0,
        draft=SimpleNamespace(assumptions=[], plan_rationale="Change final output."),
        arguments={},
        assistant_content="Här är mitt förslag:",
        assistant_metadata=None,
        tool_call_id="call_outline",
        tool_name="outline_flow",
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
        flow=None,
        lease_request_id=None,
        lease_lock_token=None,
        plan_edit_context=AIBuilderPlanEditContext(
            scope="step",
            plan_id=plan_id,
            target_plan_step_ref="step_b",
        ),
        prior_plan_for_revision=SimpleNamespace(spec=prior),
    )

    assert result.failure_kind is None
    assert result.event is not None
    assert stored_specs
    assert [step.plan_step_ref for step in stored_specs[0].steps] == [
        "step_a",
        "step_b",
    ]
    assert stored_specs[0].steps[-1].output_type == OutputType.PDF


@pytest.mark.asyncio
async def test_edit_flow_path_enforces_scoped_revision_guard(monkeypatch) -> None:
    tenant_id = UUID("00000000-0000-0000-0000-0000000000aa")
    plan_id = UUID("00000000-0000-0000-0000-000000000001")
    processor = AIBuilderProposalProcessor(
        user=SimpleNamespace(tenant_id=tenant_id),
        repo=SimpleNamespace(),
        litellm_client=SimpleNamespace(),
        self_correction_temperature=0.0,
        self_correction_bumped_temperature=0.0,
        forced_proposal_temperature=0.0,
        quality_retry_warning_codes=set(),
    )
    prior = _spec(
        [
            _step(
                "step_a",
                "Create final result",
                output_type="text",
                existing_step_ref="existing_step_1",
            ),
            _step(
                "step_b",
                "Notify reviewer",
                output_type="text",
                existing_step_ref="existing_step_2",
            ),
        ]
    )
    proposed = _spec(
        [
            _step(
                "step_a",
                "Create final result",
                output_type="pdf",
                existing_step_ref="existing_step_1",
            ),
            _step(
                "step_b",
                "Rewrite unrelated reviewer notification",
                output_type="text",
                existing_step_ref="existing_step_2",
            ),
        ]
    )

    def fake_compile_edit_draft(*args, **kwargs):
        draft = args[0]
        return CompiledEditResult(
            compiled_spec=proposed,
            diff=FlowEditDiff(step_changes=[]),
            original_draft=draft,
            base_flow_revision=1,
        )

    monkeypatch.setattr(
        "intric.flows.ai_builder.ai_builder_proposal_processor.compile_edit_draft",
        fake_compile_edit_draft,
    )

    result = await processor._process_edit_arguments(
        session_id=uuid4(),
        conversation=[],
        new_messages_start=0,
        arguments={
            "plan_rationale": "Change only the final output format.",
            "operations": [
                {
                    "op": "modify",
                    "target_ref": "existing_step_1",
                    "patch": {"output_type": "pdf"},
                }
            ],
        },
        assistant_content="",
        tool_call_id="call_edit",
        available_model_refs=None,
        available_kb_refs=None,
        flow=SimpleNamespace(
            steps=[
                _flow_step(step_order=1, output_type="text"),
                _flow_step(step_order=2, output_type="text"),
            ],
            draft_revision=1,
            name="Employee review",
            description="",
            metadata_json=None,
        ),
        assistant_snapshots=None,
        litellm_model="openai/gpt-4o-mini",
        litellm_kwargs={},
        max_output_tokens=1024,
        plan_edit_context=AIBuilderPlanEditContext(
            scope="step",
            plan_id=plan_id,
            target_existing_step_ref="existing_step_1",
        ),
        prior_plan_for_revision=SimpleNamespace(spec=prior),
    )

    assert result.event is None
    assert result.failure_kind == "quality"
    assert result.feedback is not None
    assert "downstream input wiring" in result.feedback
    assert "step_b" in result.feedback


def test_step_scoped_context_requires_a_stable_step_ref() -> None:
    with pytest.raises(ValueError, match="target_plan_step_ref"):
        AIBuilderPlanEditContext(
            scope="step",
            plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        )


def test_revision_prompt_names_the_target_step_and_prior_refs() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
        target_step_name="Create final result",
    )
    prior_plan = type(
        "PriorPlan",
        (),
        {
            "id": context.plan_id,
            "spec": _spec(
                [
                    _step("step_a", "Analyze input", output_type="json"),
                    _step("step_b", "Create final result", output_type="text"),
                ]
            ),
        },
    )()

    prompt = build_plan_revision_prompt_block(
        context=context,
        prior_plan=prior_plan,  # type: ignore[arg-type]
    )

    assert prompt is not None
    assert "Scope: one selected step" in prompt
    assert "step_b (Create final result)" in prompt
    assert "step_a: Analyze input" in prompt
    assert "step_b: Create final result" in prompt


def _spec(
    steps: list[StepSpec],
    *,
    form_fields: list[FormFieldSpec] | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Employee review",
        flow_description="",
        steps=steps,
        form_fields=form_fields,
    )


def _step(
    ref: str,
    name: str,
    *,
    input_type: str = "text",
    output_type: str,
    existing_step_ref: str | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        existing_step_ref=existing_step_ref,
        name=name,
        assistant_spec=AssistantSpec(
            instructions=f"{name}.",
            model_ref=None,
            knowledge_refs=[],
            mcp_server_refs=[],
            mcp_tool_refs=[],
        ),
        input_source="previous_step" if ref != "step_a" else "flow_input",
        input_type=input_type,
        output_mode="pass_through",
        output_type=output_type,
        input_bindings=None,
        input_contract=None,
        output_contract=None,
        input_config=None,
        output_config=None,
    )


def _flow_step(*, step_order: int, output_type: str) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Step {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type=output_type,
        mcp_policy="inherit",
    )
