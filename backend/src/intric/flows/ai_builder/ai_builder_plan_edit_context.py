from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
)
from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    StepSpec,
)

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository

PlanEditScope = Literal["whole_plan", "step"]


class AIBuilderPlanEditContext(BaseModel):
    """Structured intent for revising an already proposed AI Builder plan.

    The chat message remains the user's natural-language instruction. This
    context tells the planner which existing proposal the instruction applies
    to, so scoped edits do not depend on matching localized button text or step
    names in the prompt.
    """

    model_config = ConfigDict(extra="forbid")

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


def step_ref_for_context(context: AIBuilderPlanEditContext) -> str | None:
    return context.target_plan_step_ref or context.target_existing_step_ref


def _find_step_by_plan_ref(spec: FlowDraftSpecCore, ref: str) -> StepSpec | None:
    return next((step for step in spec.steps if step.plan_step_ref == ref), None)


def _find_step_by_existing_ref(spec: FlowDraftSpecCore, ref: str) -> StepSpec | None:
    return next((step for step in spec.steps if step.existing_step_ref == ref), None)


def _find_target_step(
    spec: FlowDraftSpecCore,
    context: AIBuilderPlanEditContext,
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
    context: AIBuilderPlanEditContext | None,
) -> tuple[AIBuilderPlanEditContext | None, BuilderPlan | None]:
    """Validate an edit context against the session's latest proposed plan."""

    if context is None:
        return None, None

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

    if context.scope == "step" and _find_target_step(plan.spec, context) is None:
        raise AIBuilderBadRequestException(
            "The selected step no longer exists in the current AI Builder plan.",
            code=AIBuilderErrorCode.INVALID_PLAN_STEP_REF,
            context={"target_step_ref": step_ref_for_context(context)},
        )

    return context, plan


def build_plan_revision_prompt_block(
    *,
    context: AIBuilderPlanEditContext | None,
    prior_plan: BuilderPlan | None,
) -> str | None:
    if context is None or prior_plan is None:
        return None

    lines = [
        "Plan revision directive:",
        f"- Current plan id: {context.plan_id}",
        "- Treat the user's latest message as a revision request for this plan.",
    ]

    if context.scope == "whole_plan":
        lines.extend(
            [
                "- Scope: whole plan.",
                "- You may reshape the proposal if the requested change requires it, but keep valid requirements intact.",
            ]
        )
    else:
        target = _find_target_step(prior_plan.spec, context)
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
                "- Preserve the other steps unless a direct dataflow adjustment is required by the targeted change.",
                "- Do not change runtime form fields. You may update the plan title or description only when needed to reflect the selected step change.",
            ]
        )

    lines.append("- Prior plan steps:")
    for index, step in enumerate(prior_plan.spec.steps, start=1):
        marker = (
            " (target)" if step == _find_target_step(prior_plan.spec, context) else ""
        )
        lines.append(
            f"  {index}. {step.plan_step_ref}: {step.name} | "
            f"{step.input_type}->{step.output_type} | "
            f"source={step.input_source}{marker}"
        )
    return "\n".join(lines)


def validate_scoped_plan_revision(
    *,
    context: AIBuilderPlanEditContext | None,
    prior_spec: FlowDraftSpecCore | None,
    proposed_spec: FlowDraftSpecCore,
) -> str | None:
    """Return repair feedback when a step-scoped plan edit drifts.

    Step edits are intentionally narrower than whole-plan edits. The selected
    step may change freely. Existing downstream consumers may only repair input
    wiring so the compiled dataflow stays valid after the selected step changes.
    Descriptive plan text may follow the selected step change, but runtime
    inputs and unrelated steps are preserved. Broader rewrites should use
    whole-plan editing so the user can review the wider intent explicitly.
    """

    if context is None or context.scope != "step" or prior_spec is None:
        return None

    prior_target = _find_target_step(prior_spec, context)
    proposed_target = _find_target_step(proposed_spec, context)
    target_ref = step_ref_for_context(context) or "unknown"
    if prior_target is None:
        return (
            f"Scoped plan edit target `{target_ref}` was not found in the prior plan. "
            "Use the current plan step refs exactly."
        )
    if proposed_target is None:
        return (
            f"Scoped plan edit target `{target_ref}` disappeared from the revised plan. "
            "Keep the selected step ref and revise that step instead of replacing it with an unrelated step."
        )
    if proposed_target.model_dump(mode="json") == prior_target.model_dump(mode="json"):
        return (
            f"Scoped plan edit target `{target_ref}` was unchanged. "
            "Apply the user's requested change to that selected step, not only to the plan title, description, or another step."
        )
    preservation_feedback = _validate_non_target_preservation(
        prior_spec=prior_spec,
        proposed_spec=proposed_spec,
        target_step_ref=prior_target.plan_step_ref,
    )
    if preservation_feedback is not None:
        return preservation_feedback
    return None


_DOWNSTREAM_INPUT_REPAIR_FIELDS = {
    "input_source",
    "input_type",
    "input_bindings",
    "input_contract",
}


def _validate_non_target_preservation(
    *,
    prior_spec: FlowDraftSpecCore,
    proposed_spec: FlowDraftSpecCore,
    target_step_ref: str,
) -> str | None:
    if _runtime_form_fields_dump(prior_spec) != _runtime_form_fields_dump(
        proposed_spec
    ):
        return (
            "Step-scoped plan edits must not change runtime form fields. Use a "
            "whole-plan edit when the requested change needs new or different "
            "inputs from the user."
        )

    prior_refs = [step.plan_step_ref for step in prior_spec.steps]
    proposed_refs = [step.plan_step_ref for step in proposed_spec.steps]

    duplicate_refs = _duplicate_refs(proposed_refs)
    if duplicate_refs:
        return (
            "Step-scoped plan edits must keep stable step refs unique. "
            f"Duplicate step refs: {', '.join(duplicate_refs)}."
        )

    prior_steps = {step.plan_step_ref: step for step in prior_spec.steps}
    proposed_steps = {step.plan_step_ref: step for step in proposed_spec.steps}

    order_feedback = _validate_existing_step_order(
        prior_refs=prior_refs,
        proposed_refs=proposed_refs,
        target_step_ref=target_step_ref,
    )
    if order_feedback is not None:
        return order_feedback

    target_prior_index = prior_refs.index(target_step_ref)
    downstream_refs = set(prior_refs[target_prior_index + 1 :])
    proposed_target_index = proposed_refs.index(target_step_ref)
    added_refs = [ref for ref in proposed_refs if ref not in prior_steps]
    distant_added_refs = [
        ref
        for ref in added_refs
        if abs(proposed_refs.index(ref) - proposed_target_index) > 1
    ]
    if distant_added_refs:
        return (
            "Step-scoped plan edits may only add helper steps directly next to "
            "the selected step. Use a whole-plan edit for broader structure "
            f"changes. Distant new step refs: {', '.join(distant_added_refs)}."
        )

    target_neighbor_feedback = _validate_target_neighbors(
        prior_refs=prior_refs,
        proposed_refs=proposed_refs,
        target_step_ref=target_step_ref,
    )
    if target_neighbor_feedback is not None:
        return target_neighbor_feedback

    removed_refs = [
        ref
        for ref in prior_refs
        if ref != target_step_ref and ref not in proposed_steps
    ]
    if removed_refs:
        return (
            "Step-scoped plan edits must preserve non-target steps. "
            f"Missing step refs: {', '.join(removed_refs)}."
        )

    for ref, prior_step in prior_steps.items():
        if ref == target_step_ref:
            continue
        proposed_step = proposed_steps.get(ref)
        if proposed_step is None:
            continue

        if prior_step.model_dump(mode="json") != proposed_step.model_dump(mode="json"):
            if ref in downstream_refs and _is_input_wiring_only_change(
                prior_step,
                proposed_step,
            ):
                continue
            if ref in downstream_refs:
                return (
                    "Step-scoped plan edits may only repair downstream input "
                    f"wiring. Step `{ref}` changed in a "
                    "broader way."
                )
            return (
                "Step-scoped plan edits must preserve unrelated steps. "
                f"Step `{ref}` changed even though the user selected "
                f"`{target_step_ref}`."
            )

    return None


def _runtime_form_fields_dump(spec: FlowDraftSpecCore) -> list[dict[str, object]]:
    return [field.model_dump(mode="json") for field in (spec.form_fields or [])]


def _step_dump_except(step: StepSpec, fields: set[str]) -> dict[str, object]:
    data = step.model_dump(mode="json")
    for field in fields:
        data.pop(field, None)
    return data


def _is_input_wiring_only_change(prior_step: StepSpec, proposed_step: StepSpec) -> bool:
    return _step_dump_except(prior_step, _DOWNSTREAM_INPUT_REPAIR_FIELDS) == (
        _step_dump_except(proposed_step, _DOWNSTREAM_INPUT_REPAIR_FIELDS)
    )


def _duplicate_refs(refs: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for ref in refs:
        if ref in seen and ref not in duplicates:
            duplicates.append(ref)
        seen.add(ref)
    return duplicates


def _validate_existing_step_order(
    *,
    prior_refs: list[str],
    proposed_refs: list[str],
    target_step_ref: str,
) -> str | None:
    prior_non_target = [ref for ref in prior_refs if ref != target_step_ref]
    proposed_non_target = [
        ref for ref in proposed_refs if ref in prior_refs and ref != target_step_ref
    ]
    if proposed_non_target != prior_non_target:
        return (
            "Step-scoped plan edits must preserve the order of existing "
            "non-target steps. Use a whole-plan edit for step reordering."
        )
    return None


def _validate_target_neighbors(
    *,
    prior_refs: list[str],
    proposed_refs: list[str],
    target_step_ref: str,
) -> str | None:
    prior_index = prior_refs.index(target_step_ref)
    prior_previous = prior_refs[prior_index - 1] if prior_index > 0 else None
    prior_next = (
        prior_refs[prior_index + 1] if prior_index + 1 < len(prior_refs) else None
    )

    proposed_existing_refs = [ref for ref in proposed_refs if ref in prior_refs]
    proposed_existing_index = proposed_existing_refs.index(target_step_ref)
    proposed_previous = (
        proposed_existing_refs[proposed_existing_index - 1]
        if proposed_existing_index > 0
        else None
    )
    proposed_next = (
        proposed_existing_refs[proposed_existing_index + 1]
        if proposed_existing_index + 1 < len(proposed_existing_refs)
        else None
    )
    if (prior_previous, prior_next) != (proposed_previous, proposed_next):
        return (
            "Step-scoped plan edits must keep the selected step in the same "
            "position. Use a whole-plan edit for structural reordering."
        )
    return None
