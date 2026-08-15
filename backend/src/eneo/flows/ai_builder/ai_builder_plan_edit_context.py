from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.step_lineage import existing_step_ref_for_order

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_proposal_intent import OrderedEditProposal
    from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
    from eneo.flows.domain.flow import Flow

PlanEditScope = Literal["whole_plan", "step"]


@dataclass(frozen=True, slots=True)
class ScopedStepSpecRevision:
    spec: FlowDraftSpecCore


@dataclass(frozen=True, slots=True)
class ScopedStepNotice:
    message: str


ScopedStepRevision = ScopedStepSpecRevision | ScopedStepNotice


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

    def to_metadata(self) -> dict[str, object]:
        return self.request.to_metadata()


ScopedEditContext: TypeAlias = AIBuilderPlanEditContext | ResolvedAIBuilderEditContext


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
) -> tuple[ResolvedAIBuilderEditContext | None, BuilderPlan | None]:
    """Validate an edit context against the session's latest proposed plan."""

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
) -> str | None:
    """Reject model-authored changes outside a selected saved Flow step."""

    if context is None or context.scope != "step":
        return None
    target_ref = context.target_existing_step_ref
    if target_ref is None:
        return None

    if proposal.removed_existing_step_refs:
        return (
            "A selected-step edit must not remove steps. Use a whole-flow edit "
            "when the requested change alters the flow structure."
        )

    identity_fields = {"kind", "existing_step_ref"}
    for step in proposal.steps:
        if step.kind == "add":
            return (
                "A selected-step edit must not add steps. Use a whole-flow edit "
                "when the requested change alters the flow structure."
            )
        if step.existing_step_ref == target_ref:
            continue
        authored_fields = sorted(step.model_fields_set - identity_fields)
        if authored_fields:
            return (
                f"Step `{step.existing_step_ref}` changed even though the user "
                f"selected `{target_ref}`. Only the selected step may contain "
                "model-authored changes."
            )
    return None


def build_plan_revision_prompt_block(
    *,
    context: ScopedEditContext | None,
    prior_spec: FlowDraftSpecCore | None,
) -> str | None:
    if context is None or prior_spec is None:
        return None

    lines = [
        "Plan revision directive:",
        *(
            [f"- Current plan id: {context.plan_id}"]
            if context.plan_id is not None
            else ["- Current source: saved Flow draft."]
        ),
        "- Treat the user's latest message as a revision request for this flow.",
        "- A step's model is chosen in the step's modellväljare/model picker and is "
        "never part of this revision; when the user asks for another model, say that "
        "in plan_rationale instead of changing the step's model.",
    ]

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
                "- Preserve every other step unchanged. Use a whole-plan edit if the requested change also requires dataflow or downstream-step changes.",
                "- Do not add, remove, or reorder steps. Use a whole-plan edit when the requested change alters the flow structure.",
                "- Do not change runtime form fields. You may update the plan title or description only when needed to reflect the selected step change.",
            ]
        )

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
) -> str | None:
    """Return repair feedback when a step-scoped plan edit drifts.

    Step edits are intentionally narrower than whole-plan edits. The selected
    step may change freely except for its model, while runtime inputs and every
    unrelated step are preserved. Broader rewrites should use whole-plan editing
    so the user can review the wider intent explicitly.

    Whole-plan revisions of an outline draft are not guarded here: an outline
    step has no stable identity across a restructuring, so a reorder cannot be
    told apart from a model change. Saved-Flow steps do not need the guard —
    their modify contract has no `model_ref` at all.
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
    if _step_dump_for_context(proposed_target, context) == _step_dump_for_context(
        prior_target, context
    ):
        return (
            f"Scoped plan edit target `{target_ref}` was unchanged. "
            "Apply the user's requested change to that selected step, not only to the plan title, description, or another step."
        )
    preservation_feedback = _validate_non_target_preservation(
        context=context,
        prior_spec=prior_spec,
        proposed_spec=proposed_spec,
        target_step_ref=_step_identity(prior_target, context),
    )
    if preservation_feedback is not None:
        return preservation_feedback
    return _validate_target_step_model(
        prior_target=prior_target,
        proposed_target=proposed_target,
        target_ref=target_ref,
    )


def resolve_scoped_step_revision_if_requested(
    *,
    context: ScopedEditContext | None,
    prior_spec: FlowDraftSpecCore | None,
    latest_user_text: str | None,
    ui_language: Literal["sv", "en"] | None,
    requested_terminal_output_type: OutputType | None = None,
) -> ScopedStepRevision | None:
    """Handle selected-step edits that are safer as deterministic patches.

    The create intent LLM cannot reliably edit backend-inserted steps such as the
    audio transcription step or a terminal artifact change. When the selected
    step and requested change are unambiguous, patch the prior plan directly
    instead of asking repair to chase LLM drift on unrelated steps.
    """

    if (
        context is None
        or context.scope != "step"
        or prior_spec is None
        or not latest_user_text
    ):
        return None

    target = _find_target_step(prior_spec, context)
    if target is None:
        return None

    output_revision = _resolve_scoped_output_artifact_revision(
        prior_spec=prior_spec,
        target=target,
        latest_user_text=latest_user_text,
        ui_language=ui_language,
        requested_terminal_output_type=requested_terminal_output_type,
    )
    return output_revision


_DOCUMENT_OUTPUT_TYPES = frozenset({OutputType.PDF, OutputType.DOCX})


def _resolve_scoped_output_artifact_revision(
    *,
    prior_spec: FlowDraftSpecCore,
    target: StepSpec,
    latest_user_text: str,
    ui_language: Literal["sv", "en"] | None,
    requested_terminal_output_type: OutputType | None,
) -> ScopedStepRevision | None:
    output_type = requested_terminal_output_type
    if output_type is None or output_type not in _DOCUMENT_OUTPUT_TYPES:
        return None
    # Two gates: typed slot evidence picks the artifact type, while text tokens
    # confirm this is an output-file edit rather than an incidental file mention.
    if not _looks_like_output_artifact_revision_request(
        latest_user_text,
        output_type,
    ):
        return None
    if target is not prior_spec.steps[-1]:
        return ScopedStepNotice(
            message=_non_terminal_output_artifact_revision_message(
                ui_language=ui_language
            )
        )
    if target.output_type == output_type:
        return None

    updated_target = target.model_copy(
        update={
            "output_type": output_type,
            "output_mode": OutputMode.PASS_THROUGH,
            "output_contract": None,
            "output_config": None,
        }
    )
    revised_spec = prior_spec.model_copy(
        update={
            "steps": [
                updated_target if step == target else step for step in prior_spec.steps
            ]
        }
    )
    return ScopedStepSpecRevision(spec=revised_spec)


def _looks_like_output_artifact_revision_request(
    text: str,
    requested_terminal_output_type: OutputType,
) -> bool:
    tokens = _word_tokens(text)
    if requested_terminal_output_type == OutputType.PDF:
        return "pdf" in tokens and bool(tokens & _OUTPUT_ARTIFACT_HINT_WORDS)
    if requested_terminal_output_type == OutputType.DOCX:
        if tokens & {"docx", "word"}:
            return bool(tokens & _OUTPUT_ARTIFACT_HINT_WORDS)
        # Generic "document" needs an action verb; input-document mentions
        # must not patch the selected terminal step.
        if tokens & {"dokument", "document"}:
            return bool(tokens & _OUTPUT_ARTIFACT_CHANGE_WORDS)
        return False
    return False


def _non_terminal_output_artifact_revision_message(
    *, ui_language: Literal["sv", "en"] | None
) -> str:
    if ui_language == "en":
        return (
            "The selected step is not the final step. Select the final step to "
            "change the final output file format."
        )
    return (
        "Det markerade steget är inte slutsteget. Välj slutsteget om du "
        "vill ändra filformatet för slutresultatet."
    )


_OUTPUT_ARTIFACT_CHANGE_WORDS = frozenset(
    {
        "ändra",
        "andra",
        "byt",
        "byta",
        "change",
        "switch",
        "gör",
        "gor",
        "make",
        "skapa",
        "create",
        "generate",
        "generera",
    }
)
_OUTPUT_ARTIFACT_HINT_WORDS = _OUTPUT_ARTIFACT_CHANGE_WORDS | frozenset(
    {
        "fil",
        "filen",
        "file",
        "format",
        "formatet",
        "output",
        "utdata",
        "utdatat",
        "resultat",
        "slutresultat",
        "slutresultatet",
        "final",
        "last",
        "sista",
        "rapport",
        "report",
        "dokument",
        "document",
    }
)
_WORD_PATTERN = re.compile(r"\w+", re.UNICODE)


def _word_tokens(text: str) -> set[str]:
    return set(_WORD_PATTERN.findall(text.casefold()))


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

    prior_refs = [_step_identity(step, context) for step in prior_spec.steps]
    proposed_refs = [_step_identity(step, context) for step in proposed_spec.steps]

    duplicate_refs = _duplicate_refs(proposed_refs)
    if duplicate_refs:
        return (
            "Step-scoped plan edits must keep stable step refs unique. "
            f"Duplicate step refs: {', '.join(duplicate_refs)}."
        )

    prior_steps = {_step_identity(step, context): step for step in prior_spec.steps}
    proposed_steps = {
        _step_identity(step, context): step for step in proposed_spec.steps
    }

    if proposed_refs != prior_refs:
        return (
            "Step-scoped plan edits must not add, remove, or reorder steps. "
            "Use a whole-plan edit when the requested change alters the flow "
            f"structure. Expected refs: {', '.join(prior_refs)}. Received refs: "
            f"{', '.join(proposed_refs)}."
        )

    for ref, prior_step in prior_steps.items():
        if ref == target_step_ref:
            continue
        proposed_step = proposed_steps.get(ref)
        if proposed_step is None:
            continue

        if _step_dump_for_context(prior_step, context) != _step_dump_for_context(
            proposed_step, context
        ):
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
