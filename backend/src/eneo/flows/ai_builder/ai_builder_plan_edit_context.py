from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_tool_names import DECLINE_FLOW_CHANGE_TOOL_NAME
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    OutputMode,
    StepSpec,
)
from eneo.flows.step_lineage import existing_step_ref_for_order

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_proposal_intent import OrderedEditProposal
    from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
    from eneo.flows.domain.flow import Flow

PlanEditScope = Literal["whole_plan", "step"]


ScopedRevisionRejectionReason = Literal[
    "output_contract_changed",
    "target_step_missing",
    "target_step_unchanged",
    "runtime_form_fields_changed",
    "step_sequence_changed",
    "unrelated_compiled_step_changed",
    "target_step_model_changed",
    "flow_metadata_changed",
]


@dataclass(frozen=True, slots=True)
class ScopedRevisionRejection:
    """Why a step-scoped revision was refused.

    The reason says what failed; whether a repair can reach it is the proposal
    owner's decision, because only that owner knows what the model was shown.
    """

    reason: ScopedRevisionRejectionReason
    feedback: str


class AIBuilderPlanEditContext(BaseModel):
    """Structured intent for revising an already proposed AI Builder plan.

    The chat message remains the user's natural-language instruction. This
    context tells the planner which existing proposal the instruction applies
    to, so scoped edits do not depend on matching localized button text or step
    names in the prompt.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["proposed_plan"] = "proposed_plan"
    scope: PlanEditScope
    plan_id: UUID = Field(description="The proposed plan currently shown to the user.")
    target_plan_step_ref: str | None = Field(
        default=None,
        description="Stable plan step ref such as 'step_f' when scope is 'step'.",
        max_length=80,
    )
    target_existing_step_ref: str | None = Field(
        default=None,
        description="Existing-flow step ref when the proposal edits a saved flow.",
        max_length=80,
    )
    target_step_name: str | None = Field(
        default=None,
        description="User-visible step name for prompt copy and UI echoes only.",
        max_length=200,
    )
    target_step_number: int | None = Field(
        default=None,
        ge=1,
        description="One-based step number from the currently displayed plan.",
    )

    @model_validator(mode="after")
    def validate_step_target(self) -> "AIBuilderPlanEditContext":
        if self.scope == "step" and not (
            self.target_plan_step_ref or self.target_existing_step_ref
        ):
            raise ValueError(
                "Step-scoped plan edits require target_plan_step_ref or "
                "target_existing_step_ref."
            )
        return self

    def to_metadata(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)


class AIBuilderSavedFlowStepEditContext(BaseModel):
    """Stable first-turn scope for editing one persisted Flow step."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["saved_flow_step"] = "saved_flow_step"
    flow_step_id: UUID = Field(
        description="Persisted Flow step identity selected before a proposal exists."
    )

    def to_metadata(self) -> dict[str, object]:
        return self.model_dump(mode="json")


AIBuilderEditContext: TypeAlias = Annotated[
    AIBuilderPlanEditContext | AIBuilderSavedFlowStepEditContext,
    Field(discriminator="kind"),
]


@dataclass(frozen=True, slots=True)
class ResolvedAIBuilderEditContext:
    """Turn-local scope resolved from one API edit-context variant."""

    request: AIBuilderEditContext
    scope: PlanEditScope
    target_plan_step_ref: str | None = None
    target_existing_step_ref: str | None = None
    target_step_name: str | None = None
    target_step_number: int | None = None
    plan_id: UUID | None = None
    preserve_output_contract: bool = False

    def to_metadata(self) -> dict[str, object]:
        return self.request.to_metadata()


ScopedEditContext: TypeAlias = AIBuilderPlanEditContext | ResolvedAIBuilderEditContext


class EditOperationPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_refs: frozenset[str]
    removable_step_refs: frozenset[str]
    may_add: bool


def saved_step_operation_permissions(
    *,
    context: ResolvedAIBuilderEditContext | None,
    prior_spec: FlowDraftSpecCore | None,
    current_step_refs: list[str],
) -> EditOperationPermissions | None:
    if not is_saved_step_revision(
        context=context, prior_spec=prior_spec, current_step_refs=current_step_refs
    ):
        return None
    assert context is not None and context.target_existing_step_ref is not None
    return EditOperationPermissions(
        step_refs=frozenset({context.target_existing_step_ref}),
        removable_step_refs=frozenset(),
        may_add=False,
    )


def is_saved_step_revision(
    *,
    context: ResolvedAIBuilderEditContext | None,
    prior_spec: FlowDraftSpecCore | None,
    current_step_refs: list[str],
) -> bool:
    return (
        context is not None
        and context.scope == "step"
        and context.target_existing_step_ref in current_step_refs
        and prior_spec is not None
        and [step.existing_step_ref for step in prior_spec.steps] == current_step_refs
    )


def step_ref_for_context(context: ScopedEditContext) -> str | None:
    return context.target_plan_step_ref or context.target_existing_step_ref


def _find_step_by_plan_ref(spec: FlowDraftSpecCore, ref: str) -> StepSpec | None:
    return next((step for step in spec.steps if step.plan_step_ref == ref), None)


def _find_step_by_existing_ref(spec: FlowDraftSpecCore, ref: str) -> StepSpec | None:
    return next((step for step in spec.steps if step.existing_step_ref == ref), None)


def _find_target_step(
    spec: FlowDraftSpecCore,
    context: ScopedEditContext,
) -> StepSpec | None:
    if context.target_plan_step_ref:
        return _find_step_by_plan_ref(spec, context.target_plan_step_ref)
    if context.target_existing_step_ref:
        return _find_step_by_existing_ref(spec, context.target_existing_step_ref)
    return None


async def resolve_plan_edit_context(
    *,
    repo: "AIBuilderRepository",
    tenant_id: UUID,
    session: BuilderSession,
    flow: "Flow | None",
    context: AIBuilderEditContext | None,
    failure_step_order: int | None = None,
    failure_step_id: UUID | None = None,
) -> tuple[ResolvedAIBuilderEditContext | None, BuilderPlan | None]:
    """Resolve scope against the saved flow or the latest plan.

    A resolved failure keeps its step and output contract across inherited
    turns, until a different review reference is named or a new session starts.
    """

    if failure_step_order is not None:
        saved = (
            next(
                (
                    step
                    for step in flow.steps
                    if step.step_order == failure_step_order
                    and step.id == failure_step_id
                ),
                None,
            )
            if flow is not None and failure_step_id is not None
            else None
        )
        if saved is None:
            raise AIBuilderBadRequestException(
                "The draft no longer contains the failed Flow step at its recorded position.",
                code=AIBuilderErrorCode.INVALID_EXISTING_STEP_REF,
                context={
                    "reason": "draft_diverged",
                    "step_order": failure_step_order,
                    "step_id": str(failure_step_id)
                    if failure_step_id is not None
                    else None,
                },
            )
        target_ref = existing_step_ref_for_order(failure_step_order)
        derived: AIBuilderEditContext
        if session.latest_plan_id is not None:
            derived = AIBuilderPlanEditContext(
                plan_id=session.latest_plan_id,
                scope="step",
                target_existing_step_ref=target_ref,
            )
        else:
            assert saved.id is not None
            derived = AIBuilderSavedFlowStepEditContext(flow_step_id=saved.id)
        resolved, prior = await resolve_plan_edit_context(
            repo=repo,
            tenant_id=tenant_id,
            session=session,
            flow=flow,
            context=derived,
        )
        assert resolved is not None
        if context is not None:
            client, _ = await resolve_plan_edit_context(
                repo=repo,
                tenant_id=tenant_id,
                session=session,
                flow=flow,
                context=context,
            )
            if (
                client is None
                or client.scope != "step"
                or client.target_existing_step_ref != target_ref
            ):
                raise AIBuilderBadRequestException(
                    "The repair must target the failed Flow step.",
                    code=AIBuilderErrorCode.INVALID_EXISTING_STEP_REF,
                    context={
                        "reason": "repair_scope_mismatch",
                        "step_order": failure_step_order,
                    },
                )
        return replace(resolved, preserve_output_contract=True), prior

    if context is None:
        return None, None

    if isinstance(context, AIBuilderSavedFlowStepEditContext):
        if session.latest_plan_id is not None:
            raise AIBuilderBadRequestException(
                "A saved Flow step can only scope the first proposal. Use the current plan for later revisions.",
                code=AIBuilderErrorCode.STALE_PLAN_REVISION,
                context={"latest_plan_id": str(session.latest_plan_id)},
            )
        if flow is None or session.flow_id is None or flow.id != session.flow_id:
            raise AIBuilderBadRequestException(
                "The saved Flow step is not available in this AI Builder session.",
                code=AIBuilderErrorCode.INVALID_EXISTING_STEP_REF,
                context={"flow_step_id": str(context.flow_step_id)},
            )
        saved_target = next(
            (step for step in flow.steps if step.id == context.flow_step_id), None
        )
        if saved_target is None:
            raise AIBuilderBadRequestException(
                "The selected Flow step no longer exists.",
                code=AIBuilderErrorCode.INVALID_EXISTING_STEP_REF,
                context={"flow_step_id": str(context.flow_step_id)},
            )
        return (
            ResolvedAIBuilderEditContext(
                request=context,
                scope="step",
                target_existing_step_ref=existing_step_ref_for_order(
                    saved_target.step_order
                ),
                target_step_name=saved_target.user_description,
                target_step_number=saved_target.step_order,
            ),
            None,
        )

    if session.latest_plan_id != context.plan_id:
        raise AIBuilderBadRequestException(
            "The AI Builder plan has changed. Refresh the plan and try the edit again.",
            code=AIBuilderErrorCode.STALE_PLAN_REVISION,
            context={
                "latest_plan_id": str(session.latest_plan_id)
                if session.latest_plan_id
                else None,
                "provided_plan_id": str(context.plan_id),
            },
        )

    plan = await repo.get_plan(plan_id=context.plan_id, tenant_id=tenant_id)
    if plan.session_id != session.id:
        raise AIBuilderBadRequestException(
            "The edit context points to a plan outside this AI Builder session.",
            code=AIBuilderErrorCode.PLAN_SESSION_MISMATCH,
        )

    plan_target: StepSpec | None = None
    target_step_number: int | None = None
    if context.scope == "step":
        plan_target = _find_target_step(plan.spec, context)
        if plan_target is None:
            raise AIBuilderBadRequestException(
                "The selected step no longer exists in the current AI Builder plan.",
                code=AIBuilderErrorCode.INVALID_PLAN_STEP_REF,
                context={"target_step_ref": step_ref_for_context(context)},
            )
        if (
            context.target_plan_step_ref is not None
            and context.target_existing_step_ref is not None
            and plan_target.existing_step_ref != context.target_existing_step_ref
        ):
            raise AIBuilderBadRequestException(
                "The selected plan step and existing Flow step do not identify the same step.",
                code=AIBuilderErrorCode.INVALID_EXISTING_STEP_REF,
                context={
                    "target_plan_step_ref": context.target_plan_step_ref,
                    "target_existing_step_ref": context.target_existing_step_ref,
                },
            )
        target_step_number = plan.spec.steps.index(plan_target) + 1

    return (
        ResolvedAIBuilderEditContext(
            request=context,
            scope=context.scope,
            target_plan_step_ref=(
                plan_target.plan_step_ref if plan_target is not None else None
            ),
            target_existing_step_ref=(
                plan_target.existing_step_ref if plan_target is not None else None
            ),
            target_step_name=(plan_target.name if plan_target is not None else None),
            target_step_number=target_step_number,
            plan_id=context.plan_id,
        ),
        plan,
    )


def validate_scoped_edit_proposal(
    *,
    context: ResolvedAIBuilderEditContext | None,
    proposal: "OrderedEditProposal",
    current_step_refs: list[str],
    saved_step_revision: bool = False,
) -> str | None:
    """Reject model-authored changes outside a selected saved Flow step."""

    if context is None or context.scope != "step":
        return None
    target_ref = context.target_existing_step_ref
    if target_ref is None:
        return None
    if saved_step_revision and proposal.model_fields_set.intersection(
        {"flow_name", "flow_description", "form_fields"}
    ):
        return (
            "A selected saved-step edit must preserve the flow name, description "
            "and runtime form fields. Use a whole-plan edit to change them."
        )

    if proposal.removed_existing_step_refs:
        return (
            "A selected-step edit must not remove steps. Use a whole-flow edit "
            "when the requested change alters the flow structure."
        )

    current_refs = set(current_step_refs)
    submitted_refs: set[str] = set()
    for step in proposal.steps:
        if step.kind == "add":
            return (
                "A selected-step edit must not add steps. Use a whole-flow edit "
                "when the requested change alters the flow structure."
            )
        if saved_step_revision:
            if step.existing_step_ref not in current_refs:
                return (
                    f"Unknown saved step `{step.existing_step_ref}`. Submit only "
                    f"modifications to the selected step `{target_ref}`."
                )
            if step.existing_step_ref in submitted_refs:
                return (
                    f"Submit step `{step.existing_step_ref}` only once, with all "
                    "its changes in one modification."
                )
            submitted_refs.add(step.existing_step_ref)
            if step.existing_step_ref != target_ref:
                return (
                    f"Step `{step.existing_step_ref}` is outside the selected "
                    f"scope. Submit only modifications to `{target_ref}`; "
                    "omit unchanged steps."
                )
        if step.existing_step_ref == target_ref:
            continue
        authored_fields = sorted(step.authored_fields)
        if authored_fields:
            return (
                f"Step `{step.existing_step_ref}` changed even though the user "
                f"selected `{target_ref}`. Only the selected step may contain "
                "model-authored changes."
            )
    if saved_step_revision and any(
        step.kind == "modify"
        and step.existing_step_ref == target_ref
        and not step.authored_fields
        for step in proposal.steps
    ):
        # Cheap syntactic refusal; the compiler still judges whether the
        # authored fields change anything (a repeated saved value does not).
        return (
            f"The selected step `{target_ref}` was submitted without changes. "
            "Give the fields of that step that change."
        )
    return None


def build_plan_revision_prompt_block(
    *,
    context: ScopedEditContext | None,
    prior_spec: FlowDraftSpecCore | None,
    can_decline: bool = False,
    saved_step_revision: bool = False,
) -> str | None:
    if context is None or prior_spec is None:
        return None

    model_rule = (
        "- A step's model is chosen in the step's modellväljare/model picker and is "
        f"never part of this revision. When the model is all the user asks to "
        f"change, call `{DECLINE_FLOW_CHANGE_TOOL_NAME}` with reason "
        "`model_choice_belongs_to_step_editor`. When the message also asks for a "
        "change you can make, make that change and say in plan_rationale that the "
        "model is chosen in the picker."
        if can_decline
        else "- A step's model is chosen in the step's modellväljare/model picker and "
        "is never part of this revision; when the user asks for another model, say "
        "that in plan_rationale instead of changing the step's model."
    )
    lines = [
        "Plan revision directive:",
        *(
            [f"- Current plan id: {context.plan_id}"]
            if context.plan_id is not None
            else ["- Current source: saved Flow draft."]
        ),
        "- Treat the user's latest message as a revision request for this flow.",
        model_rule,
    ]
    if (
        isinstance(context, ResolvedAIBuilderEditContext)
        and context.preserve_output_contract
    ):
        # A failure repair: the step's output contract is the fixed point. A
        # rejected answer is fixed through the instruction; an answer that was
        # cut off is fixed through the instruction only when what the contract
        # requires can still fit, otherwise the honest answer is a decline
        # that names the wider edit (a split, a smaller contract) for the user
        # to make deliberately. Never a weaker contract, a larger cap, another
        # model or a retry.
        lines.append(
            "- Repair: the target step's output_type, output_mode, output_contract and "
            "output_config stay exactly as they are; change the instruction so the "
            "answer meets them. If the answer was cut off (finish_reason=length) and "
            "the content the contract requires cannot fit the step's answer, "
            + (
                f"call `{DECLINE_FLOW_CHANGE_TOOL_NAME}` with reason "
                "`requires_wider_edit` and say what must change: split the step or "
                "reduce what its contract requires. "
                if can_decline
                else "say so in plan_rationale and propose the split or the smaller "
                "contract as the wider edit. "
            )
            + "Do not weaken the contract, raise a token limit, change the model or "
            "ask for a retry."
        )

    if context.scope == "whole_plan":
        lines.extend(
            [
                "- Scope: whole plan.",
                "- You may reshape the proposal if the requested change requires it, but keep valid requirements intact.",
            ]
        )
    else:
        target = _find_target_step(prior_spec, context)
        target_ref = step_ref_for_context(context) or "unknown"
        target_label = (
            f"{target.plan_step_ref} ({target.name})"
            if target is not None
            else target_ref
        )
        lines.extend(
            [
                "- Scope: one selected step.",
                f"- Target step: {target_label}.",
                "- The target step must change in the revised plan. Do not satisfy this by only changing the flow title, description, or an unrelated step.",
                "- Submit only the target step's changed fields and omit every other step; the server keeps them exactly as saved. Use a whole-plan edit if the requested change also requires dataflow or downstream-step changes."
                if saved_step_revision
                else "- Preserve every other step unchanged. Use a whole-plan edit if the requested change also requires dataflow or downstream-step changes.",
                "- Do not add, remove, or reorder steps. Use a whole-plan edit when the requested change alters the flow structure.",
                "- Do not change runtime form fields or the flow name or description. Use a whole-plan edit when the requested change requires those changes."
                if saved_step_revision
                else "- Do not change runtime form fields. You may update the plan title or description only when needed to reflect the selected step change.",
            ]
        )

    if saved_step_revision:
        return "\n".join(lines)
    lines.append("- Prior plan steps:")
    for index, step in enumerate(prior_spec.steps, start=1):
        marker = " (target)" if step == _find_target_step(prior_spec, context) else ""
        lines.append(
            f"  {index}. {step.plan_step_ref}: {step.name} | "
            f"{step.input_type}->{step.output_type} | "
            f"source={step.input_source}{marker}"
        )
    return "\n".join(lines)


def validate_scoped_plan_revision(
    *,
    context: ScopedEditContext | None,
    prior_spec: FlowDraftSpecCore | None,
    proposed_spec: FlowDraftSpecCore,
    target_kind: TargetKind,
    saved_step_revision: bool = False,
) -> ScopedRevisionRejection | None:
    """Return repair feedback when a step-scoped plan edit drifts.

    Step edits are intentionally narrower than whole-plan edits. The selected
    step may change freely except for its model, while runtime inputs and every
    unrelated step are preserved. Broader rewrites should use whole-plan editing
    so the user can review the wider intent explicitly.

    Whole-plan revisions of an outline draft are not guarded here: an outline
    step has no stable identity across a restructuring, so a reorder cannot be
    told apart from a model change. Saved-Flow steps do not need the guard —
    their modify contract has no `model_ref` at all.

    A create-compiled revision exempts its terminal document renderer. That
    step is the compiler's own materialization of the committed output
    architecture, so it appears, disappears or retypes itself whenever that
    architecture changes — never because the model drifted. An edit-compiled
    revision has no such exemption: a saved Flow's modify contract lets the
    model author that step's name, instructions and types like any other.
    """

    if context is None or context.scope != "step" or prior_spec is None:
        return None
    if saved_step_revision and (
        prior_spec.flow_name != proposed_spec.flow_name
        or prior_spec.flow_description != proposed_spec.flow_description
    ):
        return ScopedRevisionRejection(
            "flow_metadata_changed",
            "A selected saved-step edit must preserve the flow name and description. "
            "Use a whole-plan edit to change them.",
        )

    exempt_renderer = target_kind is TargetKind.CREATE
    prior_renderer = (
        _terminal_document_renderer(prior_spec) if exempt_renderer else None
    )
    proposed_renderer = (
        _terminal_document_renderer(proposed_spec) if exempt_renderer else None
    )
    prior_target = _find_target_step(prior_spec, context)
    proposed_target = _find_target_step(proposed_spec, context)
    target_ref = step_ref_for_context(context) or "unknown"
    if prior_target is None:
        return ScopedRevisionRejection(
            "target_step_missing",
            f"Scoped plan edit target `{target_ref}` was not found in the prior plan. "
            "Use the current plan step refs exactly.",
        )

    # The user can select the renderer itself. Every field it has is server
    # owned, so this guard has nothing of the model's to judge on it.
    target_is_server_owned = prior_target is prior_renderer
    if not target_is_server_owned:
        if proposed_target is None:
            return ScopedRevisionRejection(
                "target_step_missing",
                f"Scoped plan edit target `{target_ref}` disappeared from the revised plan. "
                "Keep the selected step ref and revise that step instead of replacing it with an unrelated step.",
            )
        if (
            isinstance(context, ResolvedAIBuilderEditContext)
            and context.preserve_output_contract
        ):
            if any(
                getattr(proposed_target, field) != getattr(prior_target, field)
                for field in (
                    "output_type",
                    "output_mode",
                    "output_contract",
                    "output_config",
                )
            ):
                return ScopedRevisionRejection(
                    "output_contract_changed",
                    f"Step `{target_ref}` must keep its failed output contract during instruction repair. "
                    "Preserve output_type, output_mode, output_contract and output_config.",
                )
        if _step_dump_for_context(proposed_target, context) == _step_dump_for_context(
            prior_target, context
        ) and not _server_owned_renderer_changed(
            prior_renderer, proposed_renderer, context
        ):
            return ScopedRevisionRejection(
                "target_step_unchanged",
                f"Scoped plan edit target `{target_ref}` was unchanged. "
                "Apply the user's requested change to that selected step, not only to the plan title, description, or another step.",
            )

    preservation_feedback = _validate_non_target_preservation(
        context=context,
        prior_steps=[step for step in prior_spec.steps if step is not prior_renderer],
        proposed_steps=[
            step for step in proposed_spec.steps if step is not proposed_renderer
        ],
        prior_form_fields=_runtime_form_fields_dump(prior_spec),
        proposed_form_fields=_runtime_form_fields_dump(proposed_spec),
        target_step_ref=_step_identity(prior_target, context),
    )
    if preservation_feedback is not None:
        return preservation_feedback
    if target_is_server_owned or proposed_target is None:
        return None
    model_feedback = _validate_target_step_model(
        prior_target=prior_target,
        proposed_target=proposed_target,
        target_ref=target_ref,
    )
    return (
        None
        if model_feedback is None
        else ScopedRevisionRejection("target_step_model_changed", model_feedback)
    )


def _terminal_document_renderer(spec: FlowDraftSpecCore) -> StepSpec | None:
    """The artifact renderer the create compiler appends after the writers.

    `RENDER_VERBATIM` is legal only for a text-to-PDF/DOCX step and no
    authoring schema offers the mode, so a terminal step in it is always the
    server's own renderer rather than a model-authored step.
    """

    if not spec.steps:
        return None
    terminal = spec.steps[-1]
    return terminal if terminal.output_mode is OutputMode.RENDER_VERBATIM else None


def _server_owned_renderer_changed(
    prior_renderer: StepSpec | None,
    proposed_renderer: StepSpec | None,
    context: ScopedEditContext,
) -> bool:
    if prior_renderer is None or proposed_renderer is None:
        return prior_renderer is not proposed_renderer
    return _step_dump_for_context(prior_renderer, context) != _step_dump_for_context(
        proposed_renderer, context
    )


def _validate_target_step_model(
    *,
    prior_target: StepSpec,
    proposed_target: StepSpec,
    target_ref: str,
) -> str | None:
    """Reject a model change on the step the user selected.

    Both sides are the same step, each located by the ref the edit context
    names, so this compares one identity against itself. It is therefore
    correct whatever the proposal did to step order, and does not depend on
    another check having run first. Unrelated steps keep their models through
    `_validate_non_target_preservation`, which also compares them by ref.
    """

    prior_model_ref = prior_target.assistant_spec.model_ref
    if proposed_target.assistant_spec.model_ref == prior_model_ref:
        return None
    return (
        f"Step-scoped plan edits must keep step `{target_ref}` on its current "
        f"model `{prior_model_ref}`. The model is chosen in the step's model "
        "picker, never by an edit; apply the rest of the requested change and "
        "say that in plan_rationale."
    )


def _validate_non_target_preservation(
    *,
    context: ScopedEditContext,
    prior_steps: list[StepSpec],
    proposed_steps: list[StepSpec],
    prior_form_fields: list[dict[str, object]],
    proposed_form_fields: list[dict[str, object]],
    target_step_ref: str,
) -> ScopedRevisionRejection | None:
    if prior_form_fields != proposed_form_fields:
        return ScopedRevisionRejection(
            "runtime_form_fields_changed",
            "Step-scoped plan edits must not change runtime form fields. Use a "
            "whole-plan edit when the requested change needs new or different "
            "inputs from the user.",
        )

    prior_refs = [_step_identity(step, context) for step in prior_steps]
    proposed_refs = [_step_identity(step, context) for step in proposed_steps]

    duplicate_refs = _duplicate_refs(proposed_refs)
    if duplicate_refs:
        return ScopedRevisionRejection(
            "step_sequence_changed",
            "Step-scoped plan edits must keep stable step refs unique. "
            f"Duplicate step refs: {', '.join(duplicate_refs)}.",
        )

    if proposed_refs != prior_refs:
        return ScopedRevisionRejection(
            "step_sequence_changed",
            "Step-scoped plan edits must not add, remove, or reorder steps. "
            "Use a whole-plan edit when the requested change alters the flow "
            f"structure. Expected refs: {', '.join(prior_refs)}. Received refs: "
            f"{', '.join(proposed_refs)}.",
        )

    proposed_by_ref = {_step_identity(step, context): step for step in proposed_steps}
    for ref, prior_step in (
        (_step_identity(step, context), step) for step in prior_steps
    ):
        if ref == target_step_ref:
            continue
        proposed_step = proposed_by_ref.get(ref)
        if proposed_step is None:
            continue

        if _step_dump_for_context(prior_step, context) != _step_dump_for_context(
            proposed_step, context
        ):
            return ScopedRevisionRejection(
                "unrelated_compiled_step_changed",
                "Step-scoped plan edits must preserve unrelated steps. "
                f"Step `{ref}` changed even though the user selected "
                f"`{target_step_ref}`.",
            )

    return None


def _runtime_form_fields_dump(spec: FlowDraftSpecCore) -> list[dict[str, object]]:
    return [field.model_dump(mode="json") for field in (spec.form_fields or [])]


def _step_dump_except(step: StepSpec, fields: set[str]) -> dict[str, object]:
    data = step.model_dump(mode="json")
    for field in fields:
        data.pop(field, None)
    return data


def _uses_existing_step_identity(context: ScopedEditContext) -> bool:
    return isinstance(context, ResolvedAIBuilderEditContext) and isinstance(
        context.request, AIBuilderSavedFlowStepEditContext
    )


def _step_identity(step: StepSpec, context: ScopedEditContext) -> str:
    if _uses_existing_step_identity(context) and step.existing_step_ref is not None:
        return step.existing_step_ref
    return step.plan_step_ref


def _step_dump_for_context(
    step: StepSpec,
    context: ScopedEditContext,
) -> dict[str, object]:
    ignored_fields: set[str] = (
        {"plan_step_ref"} if _uses_existing_step_identity(context) else set()
    )
    return _step_dump_except(step, ignored_fields)


def _duplicate_refs(refs: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for ref in refs:
        if ref in seen and ref not in duplicates:
            duplicates.append(ref)
        seen.add(ref)
    return duplicates
