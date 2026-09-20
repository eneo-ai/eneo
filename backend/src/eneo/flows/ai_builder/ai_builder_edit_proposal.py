from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
    architecture_failure_outcome,
)
from eneo.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    review_edit_scope_for_turn,
    semantic_conversation,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    CreateCompileContext,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    FlowBuilderEditApproval,
    FlowBuilderProposalContent,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_edit_admission import (
    lower_edit_tool_arguments,
)
from eneo.flows.ai_builder.ai_builder_edit_compiler import (
    compile_edit_proposal,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
)
from eneo.flows.ai_builder.ai_builder_flow_review import (
    review_edit_changed_nothing,
    review_edit_changes_of_the_model,
    validate_review_edit_effect,
    validate_review_edit_proposal,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    ResolvedAIBuilderEditContext,
    ScopedRevisionRejectionReason,
    is_saved_step_revision,
    validate_scoped_edit_proposal,
    validate_scoped_plan_revision,
)
from eneo.flows.ai_builder.ai_builder_proposal_capture import (
    capture_rejected_proposal_arguments,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ModifyExistingStep,
    OrderedEditProposal,
)
from eneo.flows.ai_builder.ai_builder_proposal_policy import (
    evaluate_edit_topology_policy,
    terminal_output_type_for_edit_conversation,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    PROPOSAL_PARSE_MODEL_FAILURE_CODE,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    CorrectableFailure,
    PreparationOutcome,
    ProposalAnswer,
    ProposalReady,
    TerminalFailure,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    AssistantSnapshotResourceUnavailableError,
    collect_flow_spec_resource_bindings,
)
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_validation_common import (
    SpecValidationResult,
)
from eneo.flows.ai_builder.ai_builder_validation_references import (
    iter_step_template_expressions,
)
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore
from eneo.flows.input_binding_contract_rules import (
    source_ref_bindings,
)
from eneo.flows.step_lineage import existing_step_ref_for_order
from eneo.flows.template_reference_analyzer import analyze_template
from eneo.main.exceptions import BadRequestException
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.flows.domain.flow import Flow

logger = get_logger(__name__)
# What the user is told when an investigation ends without a change. The turn
# is complete: the suggestions were tested against the runs and nothing in
# them justified touching the flow.
_REVIEW_FOUND_NOTHING_TO_CHANGE = {
    "sv": (
        "Jag har gått igenom körningarna för de här förslagen och hittar inget "
        "som motiverar en ändring. Flödet står kvar som det är."
    ),
    "en": (
        "I went through the runs behind these suggestions and found nothing "
        "that justifies a change. The flow stays as it is."
    ),
}


@dataclass(frozen=True, slots=True)
class _PreparedCandidate:
    """An edit proposal after projection, compilation and preparation."""

    spec: FlowDraftSpecCore
    validation: SpecValidationResult
    approval: FlowBuilderEditApproval


def _unchanged_edit_proposal(current_steps: Sequence[FlowStep]) -> OrderedEditProposal:
    """Every current step kept as it is: what the compiler does on its own."""

    return OrderedEditProposal(
        plan_rationale="Flow kept as it is.",
        steps=[
            ModifyExistingStep(
                existing_step_ref=existing_step_ref_for_order(step.step_order)
            )
            for step in sorted(current_steps, key=lambda step: step.step_order)
        ],
    )


PROPOSE_FLOW_EDIT_FORCED_TOOL_PROMPT = (
    "Return one valid propose_flow tool call that keeps the flow coherent. "
    "Do not answer with prose."
)


async def process_edit_arguments(
    *,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    arguments: dict[str, Any],
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    flow: Flow | None,
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    resource_catalog: AIBuilderResourceCatalog | None = None,
    planning_state: PlanningState | None = None,
    plan_edit_context: ResolvedAIBuilderEditContext | None = None,
    prior_spec_for_revision: FlowDraftSpecCore | None = None,
    compile_context: CreateCompileContext | None = None,
    baseline_validation: SpecValidationResult | None = None,
) -> PreparationOutcome:
    review_scope = review_edit_scope_for_turn(conversation)
    # Everything below reads the conversation to check the model's proposal
    # against what was asked, never to build a prompt, so it reads the
    # semantic projection: the server's own review command is not a request
    # for an output type or a topology.
    conversation = semantic_conversation(conversation)
    if flow is None:
        # A precondition of the edit session, not something the model wrote.
        return TerminalFailure(
            kind="validation",
            message="propose_flow requires an existing flow context.",
            code=AIBuilderErrorCode.EDIT_SESSION_FLOW_REQUIRED,
            phase=AIBuilderErrorPhase.PROPOSAL,
        )

    model_arguments: dict[str, Any] = dict(arguments)
    try:
        model_arguments = lower_edit_tool_arguments(model_arguments)
        authored_proposal = OrderedEditProposal.model_validate(model_arguments)
    except ValidationError as exc:
        logger.warning("Failed to parse propose_flow edit arguments: %s", exc)
        capture_rejected_proposal_arguments(
            model_arguments,
            session_id=str(turn.session_id),
            issues=[str(exc)],
        )
        return CorrectableFailure(
            feedback=f"Invalid propose_flow arguments: {exc}",
            kind="parse",
            codes=frozenset({PROPOSAL_PARSE_MODEL_FAILURE_CODE}),
        )
    current_step_refs = [
        existing_step_ref_for_order(step.step_order)
        for step in sorted(flow.steps, key=lambda step: step.step_order)
    ]
    saved_step_revision = is_saved_step_revision(
        context=plan_edit_context,
        prior_spec=prior_spec_for_revision,
        current_step_refs=current_step_refs,
    )
    # Judged on what the model wrote, before the server fills in the fields it
    # owns: an omitted form_fields that the server then preserves must not read
    # as the model having changed them.
    review_feedback = validate_review_edit_proposal(
        scope=review_scope,
        proposal=authored_proposal,
        flow_name=flow.name,
        flow_description=flow.description,
        current_step_refs=current_step_refs,
    )
    if review_feedback is not None:
        return CorrectableFailure(feedback=review_feedback, kind="quality")
    scoped_proposal_feedback = validate_scoped_edit_proposal(
        context=plan_edit_context,
        proposal=authored_proposal,
        current_step_refs=current_step_refs,
        saved_step_revision=saved_step_revision,
    )
    if scoped_proposal_feedback is not None:
        return CorrectableFailure(feedback=scoped_proposal_feedback, kind="quality")
    proposal = _apply_server_owned_input_fields(
        authored_proposal, planning_state=planning_state
    )
    ui_language = compile_context.ui_language if compile_context is not None else None

    def compile_and_prepare(
        candidate: OrderedEditProposal,
    ) -> _PreparedCandidate | CorrectableFailure | TerminalFailure:
        """One deterministic path from an edit proposal to the plan it becomes."""

        try:
            edit_result = compile_edit_proposal(
                candidate,
                current_steps=list(flow.steps),
                base_flow_revision=flow.draft_revision,
                flow_name=flow.name,
                flow_description=flow.description,
                current_metadata_json=flow.metadata_json,
                assistant_snapshots=assistant_snapshots,
                resource_catalog=resource_catalog,
                revision_spec=prior_spec_for_revision if saved_step_revision else None,
                requested_primary_runtime_input_type=(
                    compile_context.runtime_input_type
                    if compile_context is not None
                    else None
                ),
                ui_language=ui_language,
                selected_template_count=(
                    compile_context.selected_template_count
                    if compile_context is not None
                    else None
                ),
                selected_template_placeholders=(
                    compile_context.selected_template_placeholders
                    if compile_context is not None
                    else None
                ),
                inherited_template_asset_id=(
                    compile_context.inherited_template_asset_id
                    if compile_context is not None
                    else None
                ),
            )
        except BadRequestException as exc:
            return CorrectableFailure(
                feedback=_format_edit_compilation_request_error(exc), kind="validation"
            )
        except AIBuilderArchitectureError as exc:
            return architecture_failure_outcome(exc)
        except AssistantSnapshotResourceUnavailableError as exc:
            logger.warning(
                "Edit compilation failed because an assistant snapshot references "
                "an unavailable %s resource",
                exc.kind,
            )
            # Only the user can re-select the resource; another model call cannot.
            return TerminalFailure(
                kind="validation",
                message=(
                    "A resource used by the existing flow is no longer available. "
                    "Re-select the affected model or knowledge base and try again."
                ),
                code=AIBuilderErrorCode.AI_BUILDER_PLAN_RESOURCE_BINDING_UNAVAILABLE,
                phase=AIBuilderErrorPhase.PROPOSAL,
                details={"resource_kind": str(exc.kind)},
            )
        prepared = prepare_compiled_spec_for_session(
            spec=edit_result.spec,
            target_kind=TargetKind.EDIT,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            resource_catalog=resource_catalog,
            terminal_output_type=terminal_output_type_for_edit_conversation(
                conversation,
                plan_edit_context=plan_edit_context,
                prior_spec=prior_spec_for_revision,
            ),
            ui_language=ui_language,
            mutation_scope=edit_result.mutation_scope,
        )
        if prepared.failure_feedback is not None:
            return CorrectableFailure(
                feedback=prepared.failure_feedback, kind="validation"
            )
        assert prepared.spec is not None
        assert prepared.validation is not None
        return _PreparedCandidate(
            spec=prepared.spec,
            validation=prepared.validation,
            approval=edit_result.approval_for_prepared_spec(prepared.spec),
        )

    candidate = compile_and_prepare(proposal)
    if not isinstance(candidate, _PreparedCandidate):
        return candidate

    if review_scope is not None:
        # The server projects, compiles and prepares the flow unchanged along
        # the same path: whatever that changes (a confirmed input field it
        # carries, a transcription step ahead of a bare audio input, a
        # document step's output mode, a duplicate name's suffix) is its own
        # housekeeping, not the model reaching past the findings. The scope is
        # held to the difference; the plan the user approves shows all of it.
        baseline = compile_and_prepare(
            _apply_server_owned_input_fields(
                _unchanged_edit_proposal(flow.steps), planning_state=planning_state
            )
        )
        own_changes = review_edit_changes_of_the_model(
            candidate.approval.diff,
            housekeeping=(
                baseline.approval.diff
                if isinstance(baseline, _PreparedCandidate)
                else None
            ),
        )
        effect_feedback = validate_review_edit_effect(
            scope=review_scope, diff=own_changes
        )
        if effect_feedback is not None:
            return CorrectableFailure(feedback=effect_feedback, kind="validation")
        if review_edit_changed_nothing(own_changes.step_changes):
            # Finding nothing to change is a real answer to an investigation,
            # and the only honest one when the runs do not support the
            # suggestion. Asking the model to try again would loop: the repair
            # call withdraws the decline tool and demands a plan.
            return ProposalAnswer(
                answer=_REVIEW_FOUND_NOTHING_TO_CHANGE[
                    "sv" if (ui_language or "sv") == "sv" else "en"
                ]
            )

    compiled_spec = candidate.spec
    validation = candidate.validation
    if saved_step_revision:
        assert plan_edit_context is not None and prior_spec_for_revision is not None
        consumer_failure = _validate_saved_step_consumers(
            proposal=authored_proposal,
            target_ref=plan_edit_context.target_existing_step_ref,
            prior_spec=prior_spec_for_revision,
            proposed_spec=compiled_spec,
            baseline_validation=baseline_validation,
        )
        if consumer_failure is not None:
            return consumer_failure
    if validation.errors:
        error_messages = [err.message for err in validation.errors]
        return CorrectableFailure(
            feedback=(
                "Compiled edit spec validation failed: " + "; ".join(error_messages)
            ),
            kind="validation",
            codes=frozenset(error.code for error in validation.errors),
        )

    topology_policy = evaluate_edit_topology_policy(
        conversation=conversation,
        spec=compiled_spec,
        flow=flow,
        planning_state=planning_state,
        resource_catalog=resource_catalog,
        compile_context=compile_context,
    )
    if topology_policy.rejection_feedback is not None:
        return CorrectableFailure(
            feedback=topology_policy.rejection_feedback,
            kind="validation",
            codes=topology_policy.failure_codes,
        )
    edit_approval = candidate.approval.model_copy(
        update={
            "scoped_target_existing_step_ref": (
                plan_edit_context.target_existing_step_ref
                if plan_edit_context is not None and plan_edit_context.scope == "step"
                else None
            ),
            "scoped_target_plan_step_ref": (
                plan_edit_context.target_plan_step_ref
                if plan_edit_context is not None and plan_edit_context.scope == "step"
                else None
            ),
            "advisories": [
                *candidate.approval.advisories,
                *topology_policy.advisories,
            ],
        }
    )

    # The baseline is the saved step on the first turn and the prior plan thereafter.
    scoped_rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.EDIT,
        saved_step_revision=saved_step_revision,
        context=plan_edit_context,
        prior_spec=prior_spec_for_revision,
        proposed_spec=compiled_spec,
    )
    if scoped_rejection is not None:
        target_step_ref = (
            (
                plan_edit_context.target_plan_step_ref
                or plan_edit_context.target_existing_step_ref
            )
            if plan_edit_context is not None
            else None
        )
        # The feedback is server-authored text naming the offending step; it
        # carries no prompt, model output or credential.
        logger.info(
            "ai_builder_scoped_plan_edit_rejected session_id=%s target_step_ref=%s "
            "reason=%s feedback=%s",
            turn.session_id,
            target_step_ref,
            scoped_rejection.reason,
            scoped_rejection.feedback,
        )
        if (
            saved_step_revision
            and scoped_rejection.reason in _SAVED_STEP_SERVER_OWNED_REJECTIONS
        ):
            # Admission already refused every model-authored change outside
            # the selected step, and the compiler's mutation scope restores
            # the rest after each preparation stage. Drift here is the
            # server's own; another model call cannot undo it.
            return architecture_failure_outcome(
                AIBuilderArchitectureError(
                    public_code="architecture_materialization_failed",
                    repair_disposition="server_defect",
                    detail=scoped_rejection.feedback,
                    log_context={
                        "failure_code": "scoped_edit_preservation_failed",
                        "reason": scoped_rejection.reason,
                        "scoped_target_existing_step_ref": target_step_ref,
                    },
                )
            )
        return CorrectableFailure(feedback=scoped_rejection.feedback, kind="quality")

    return ProposalReady(
        compiled=CompiledProposal(
            content=FlowBuilderProposalContent(
                spec=compiled_spec,
                assumptions=proposal.assumptions,
                plan_rationale=proposal.plan_rationale,
                edit=edit_approval,
            ),
            validation=validation,
            resource_bindings=(
                collect_flow_spec_resource_bindings(
                    compiled_spec, catalog=resource_catalog
                )
                if resource_catalog is not None
                else tuple()
            ),
            aggregation_intent=(
                compile_context.aggregation_intent
                if compile_context is not None
                else "linear"
            ),
        ),
    )


def _apply_server_owned_input_fields(
    proposal: OrderedEditProposal,
    *,
    planning_state: PlanningState | None,
) -> OrderedEditProposal:
    if planning_state is None or not planning_state.input_fields:
        return proposal
    server_fields = {
        record.value.variable_name: record.value
        for record in planning_state.input_fields
    }
    if "form_fields" not in proposal.model_fields_set or proposal.form_fields is None:
        return proposal.model_copy(update={"form_fields": list(server_fields.values())})
    projected_fields = [
        server_fields.get(field.variable_name, field) for field in proposal.form_fields
    ]
    projected_names = {field.variable_name for field in projected_fields}
    projected_fields.extend(
        record.value
        for record in planning_state.input_fields
        if record.value.variable_name not in projected_names
    )
    return proposal.model_copy(update={"form_fields": projected_fields})


def _format_edit_compilation_request_error(exc: BadRequestException) -> str:
    if exc.code != "invalid_existing_step_ref":
        return f"Failed to compile edit: {exc}"
    context = exc.context or {}
    missing_refs = context.get("missing_refs")
    if isinstance(missing_refs, list) and missing_refs:
        return (
            "Edit validation failed: every existing step must appear in steps "
            "or be listed in removed_existing_step_refs. Missing refs: "
            f"{missing_refs}."
        )
    overlap_refs = context.get("overlap_refs")
    if isinstance(overlap_refs, list) and overlap_refs:
        return (
            "Edit validation failed: refs cannot appear in both steps and "
            "removed_existing_step_refs. Overlap refs: "
            f"{overlap_refs}."
        )
    return f"Edit validation failed: {exc}"


# Rejections a saved-step revision can only reach through the server: the
# model's fragment cannot name another step, a form field, the flow name or
# the flow description (validate_scoped_edit_proposal refuses it first).
_SAVED_STEP_SERVER_OWNED_REJECTIONS: frozenset[ScopedRevisionRejectionReason] = (
    frozenset(
        {
            "unrelated_compiled_step_changed",
            "step_sequence_changed",
            "runtime_form_fields_changed",
            "flow_metadata_changed",
        }
    )
)


def _validate_saved_step_consumers(
    *,
    proposal: OrderedEditProposal,
    target_ref: str | None,
    prior_spec: FlowDraftSpecCore,
    proposed_spec: FlowDraftSpecCore,
    baseline_validation: SpecValidationResult | None,
) -> CorrectableFailure | None:
    if not any(
        step.kind == "modify"
        and step.existing_step_ref == target_ref
        and step.authored_fields
        for step in proposal.steps
    ):
        return None
    proposed_target = next(
        (step for step in proposed_spec.steps if step.existing_step_ref == target_ref),
        None,
    )
    if proposed_target is None:
        return None
    # Keep entries carry no model contribution. Validate the target against the
    # prior consumers without attributing compiler housekeeping to the model.
    target_effect = prior_spec.model_copy(
        update={
            "steps": [
                proposed_target if step.existing_step_ref == target_ref else step
                for step in prior_spec.steps
            ],
        }
    )
    if baseline_validation is None:
        baseline_validation = validate_spec(prior_spec)
    prior_errors = set(baseline_validation.errors)
    errors = [
        error
        for error in validate_spec(target_effect).errors
        if error not in prior_errors
    ]
    if errors:
        return CorrectableFailure(
            feedback="Selected-step consumer validation failed: "
            + "; ".join(error.message for error in errors),
            kind="validation",
            codes=frozenset(error.code for error in errors),
        )
    prior_target = next(
        step for step in prior_spec.steps if step.existing_step_ref == target_ref
    )
    if (
        prior_target.output_contract is None
        or proposed_target.output_contract is not None
    ):
        return None
    step_refs = {
        step.plan_step_ref: order for order, step in enumerate(prior_spec.steps, 1)
    }
    target_order = step_refs[prior_target.plan_step_ref]
    for consumer in prior_spec.steps:
        if consumer.existing_step_ref == target_ref:
            continue
        uses_structured_target = any(
            source.step_ref == prior_target.plan_step_ref
            and source.output == "structured"
            for source in source_ref_bindings(consumer.input_bindings)
        ) or any(
            reference.step_order == target_order
            and (
                reference.tail == "output.structured"
                or reference.tail.startswith("output.structured.")
            )
            for expression in iter_step_template_expressions(consumer)
            for reference in analyze_template(
                "{{ " + expression + " }}", step_refs=step_refs, form_field_names=set()
            )
        )
        if uses_structured_target:
            return CorrectableFailure(
                feedback=f"Step `{consumer.plan_step_ref}` consumes structured output from `{prior_target.plan_step_ref}`. "
                "Preserve the producer output_contract, or use a whole-plan edit to revise its consumers.",
                kind="validation",
                codes=frozenset({"consumer_requires_output_contract"}),
            )
    return None
