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
    from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
    from eneo.flows.ai_builder.ai_builder_resource_catalog import (
        AIBuilderResourceCatalog,
    )
    from eneo.flows.domain.flow import Flow

PlanEditScope = Literal["whole_plan", "step"]


@dataclass(frozen=True, slots=True)
class ScopedStepSpecRevision:
    spec: FlowDraftSpecCore
    kind: Literal["model", "output_artifact"]


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
        target = next(
            (step for step in flow.steps if step.id == context.flow_step_id), None
        )
        if target is None:
            raise AIBuilderBadRequestException(
                "The selected Flow step no longer exists.",
                code=AIBuilderErrorCode.INVALID_EXISTING_STEP_REF,
                context={"flow_step_id": str(context.flow_step_id)},
            )
        return (
            ResolvedAIBuilderEditContext(
                request=context,
                scope="step",
                target_existing_step_ref=existing_step_ref_for_order(target.step_order),
                target_step_name=target.user_description,
                target_step_number=target.step_order,
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

    if context.scope == "step" and _find_target_step(plan.spec, context) is None:
        raise AIBuilderBadRequestException(
            "The selected step no longer exists in the current AI Builder plan.",
            code=AIBuilderErrorCode.INVALID_PLAN_STEP_REF,
            context={"target_step_ref": step_ref_for_context(context)},
        )

    return (
        ResolvedAIBuilderEditContext(
            request=context,
            scope=context.scope,
            target_plan_step_ref=context.target_plan_step_ref,
            target_existing_step_ref=context.target_existing_step_ref,
            target_step_name=context.target_step_name,
            target_step_number=context.target_step_number,
            plan_id=context.plan_id,
        ),
        plan,
    )


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
                "- Preserve the other steps unless a direct dataflow adjustment is required by the targeted change.",
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
    return None


def resolve_scoped_step_revision_if_requested(
    *,
    context: ScopedEditContext | None,
    prior_spec: FlowDraftSpecCore | None,
    latest_user_text: str | None,
    resource_catalog: "AIBuilderResourceCatalog | None",
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
        requested_terminal_output_type=requested_terminal_output_type,
    )
    if output_revision is not None:
        return output_revision

    if target.output_mode == OutputMode.TRANSCRIBE_ONLY:
        if _looks_like_transcribe_only_model_revision_request(latest_user_text):
            return ScopedStepNotice(
                message=_transcription_step_model_revision_message(latest_user_text)
            )
        return None

    if resource_catalog is None or not _looks_like_model_revision_request(
        latest_user_text
    ):
        return None

    mentioned_model_refs = resource_catalog.refs_mentioned_in_text(
        kind="model",
        text=latest_user_text,
    )

    if len(mentioned_model_refs) == 1:
        if not _looks_like_catalog_model_revision_request(latest_user_text):
            return None
        model_ref = next(iter(mentioned_model_refs))
    else:
        if not mentioned_model_refs:
            if not _looks_like_catalog_model_revision_request(latest_user_text):
                return None
            return ScopedStepNotice(
                message=_unknown_step_model_revision_message(latest_user_text)
            )
        if not _looks_like_catalog_model_revision_request(latest_user_text):
            return None
        current_model_ref = target.assistant_spec.model_ref
        if current_model_ref is None:
            return None
        candidate_refs = mentioned_model_refs - {current_model_ref}
        if len(candidate_refs) != 1:
            return None
        model_ref = next(iter(candidate_refs))

    if target.assistant_spec.model_ref == model_ref:
        return None

    updated_target = target.model_copy(
        update={
            "assistant_spec": target.assistant_spec.model_copy(
                update={"model_ref": model_ref}
            )
        }
    )
    revised_spec = prior_spec.model_copy(
        update={
            "steps": [
                updated_target if step is target else step for step in prior_spec.steps
            ]
        }
    )
    return ScopedStepSpecRevision(spec=revised_spec, kind="model")


_DOCUMENT_OUTPUT_TYPES = frozenset({OutputType.PDF, OutputType.DOCX})


def _resolve_scoped_output_artifact_revision(
    *,
    prior_spec: FlowDraftSpecCore,
    target: StepSpec,
    latest_user_text: str,
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
            message=_non_terminal_output_artifact_revision_message(latest_user_text)
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
    return ScopedStepSpecRevision(spec=revised_spec, kind="output_artifact")


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


def _non_terminal_output_artifact_revision_message(text: str) -> str:
    tokens = _word_tokens(text)
    if tokens & _SWEDISH_OUTPUT_ARTIFACT_HINT_WORDS:
        return (
            "Det markerade steget är inte slutsteget. Välj slutsteget om du "
            "vill ändra filformatet för slutresultatet."
        )
    return (
        "The selected step is not the final step. Select the final step to "
        "change the final output file format."
    )


def _looks_like_catalog_model_revision_request(text: str) -> bool:
    # The catalog-bounded model-name check is the real guard; this only avoids
    # treating ordinary mentions of a model name as selected-step edit commands.
    return bool(_MODEL_WORDS & _word_tokens(text))


def _looks_like_model_revision_request(text: str) -> bool:
    tokens = _word_tokens(text)
    if _MODEL_WORDS & tokens:
        return True
    return bool(
        (_MODEL_ACTION_WORDS & tokens)
        and (_MODEL_TARGET_PREPOSITION_WORDS & tokens)
        and (_MODEL_FAMILY_WORDS & tokens)
    )


_MODEL_WORDS = frozenset({"model", "modell"})
_MODEL_ACTION_WORDS = frozenset(
    {
        "byt",
        "byta",
        "ändra",
        "andra",
        "switch",
        "change",
        "use",
        "använd",
        "anvanda",
        "kör",
        "kor",
    }
)
_MODEL_FAMILY_WORDS = frozenset({"gpt", "claude", "gemini", "llama", "mistral"})
_MODEL_TARGET_PREPOSITION_WORDS = frozenset({"till", "to"})
_SWEDISH_MODEL_REVISION_HINT_WORDS = (
    _MODEL_ACTION_WORDS - {"switch", "change", "use"}
) | {"modell", "till"}
_SWEDISH_OUTPUT_ARTIFACT_HINT_WORDS = frozenset(
    {"ändra", "andra", "fil", "istället", "istallet", "får", "far"}
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


def _looks_like_transcribe_only_model_revision_request(text: str) -> bool:
    return _looks_like_model_revision_request(text)


def _word_tokens(text: str) -> set[str]:
    return set(_WORD_PATTERN.findall(text.casefold()))


def _transcription_step_model_revision_message(text: str) -> str:
    tokens = _word_tokens(text)
    if tokens & _SWEDISH_MODEL_REVISION_HINT_WORDS:
        return (
            "Det markerade steget transkriberar ljud och använder flödets "
            "transkriberingsmodell, inte en chattmodell som GPT. Välj ett "
            "analys- eller skrivsteg om du vill byta LLM-modell."
        )
    return (
        "The selected step transcribes audio and uses the flow transcription "
        "model, not a chat model such as GPT. Select an analysis or writing "
        "step if you want to change the LLM model."
    )


def _unknown_step_model_revision_message(text: str) -> str:
    tokens = _word_tokens(text)
    if tokens & _SWEDISH_MODEL_REVISION_HINT_WORDS:
        return (
            "Jag hittar inte den modellen i det här utrymmet. Välj en "
            "tillgänglig modell i modellväljaren eller skriv exakt modellnamn."
        )
    return (
        "I cannot find that model in this space. Select an available model in "
        "the model picker or type the exact model name."
    )


_DOWNSTREAM_INPUT_REPAIR_FIELDS = {
    "input_source",
    "input_type",
    "input_bindings",
    "input_contract",
}


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

        if _step_dump_for_context(prior_step, context) != _step_dump_for_context(
            proposed_step, context
        ):
            if ref in downstream_refs and _is_input_wiring_only_change(
                prior_step,
                proposed_step,
                context=context,
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


def _is_input_wiring_only_change(
    prior_step: StepSpec,
    proposed_step: StepSpec,
    *,
    context: ScopedEditContext,
) -> bool:
    ignored_fields = set(_DOWNSTREAM_INPUT_REPAIR_FIELDS)
    if _uses_existing_step_identity(context):
        ignored_fields.add("plan_step_ref")
    return _step_dump_except(prior_step, ignored_fields) == (
        _step_dump_except(proposed_step, ignored_fields)
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
