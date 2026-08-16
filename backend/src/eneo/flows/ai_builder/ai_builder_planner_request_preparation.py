from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias, cast
from uuid import UUID

from eneo.files.file_models import File
from eneo.flows.ai_builder.ai_builder_action_policy import (
    named_result_projection,
)
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContext,
    AIBuilderAttachmentContextPolicy,
    build_ai_builder_attachment_context_for_model,
    fit_ai_builder_attachment_context,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    SlotClassificationMetadata,
    provider_safe_tool_call_id,
    question_answer_from_metadata,
    tool_calls_from_message,
    ui_language_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    CreateCompileContext,
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryAnalysis,
)
from eneo.flows.ai_builder.ai_builder_discovery_profile_builder import (
    build_discovery_profile,
)
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    build_discovery_runtime_result,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_flow_context import build_flow_context
from eneo.flows.ai_builder.ai_builder_form_fields import (
    extract_form_fields_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_unprompted_user_text_preserving_case,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    extract_requested_output_sections,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    ResolvedAIBuilderEditContext,
    build_plan_revision_prompt_block,
)
from eneo.flows.ai_builder.ai_builder_plan_proposal_task import (
    build_plan_proposal_system_prompt,
)
from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
    build_requirements_signal_text,
    form_intake_signal_values_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ProposalObligationProjection,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import ProposalTurnTelemetry
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    LLMMessageParam,
    LLMMessageRole,
    ProposalMessageGroup,
    ProposalRequestBudget,
    fit_proposal_message_groups,
    flatten_proposal_message_groups,
    group_proposal_messages,
)
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
    build_requirements_disclosure,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    RequirementsState,
    content_free_confirmation,
    latest_confirmed_requirements,
    resolve_requirements_state,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    DeclaredSchemaCandidate,
    SchemaCandidateRefusal,
    SchemaLimitExceeded,
    derive_freeform_schema_candidates,
    latest_schema_direction_answer_matches_candidates,
    merge_declared_schema_candidates,
)
from eneo.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from eneo.flows.ai_builder.ai_builder_tools import (
    ProposalToolSchema,
    build_propose_flow_tool_schema,
)
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    BuilderTurnDecision,
    GenerateProposal,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.ai_builder.planning_state_builder import apply_attested_requirements
from eneo.flows.application.flow_authoring_snapshot import current_flow_authoring_spec
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.domain.mapped_execution_policy import (
    FlowMappedExecutionPolicy,
    max_mapped_items_per_step,
)
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore
from eneo.main.logging import get_logger
from eneo.observability.failure_events import stable_hash
from eneo.tokens.token_utils import count_message_tokens, count_tool_tokens

if TYPE_CHECKING:
    from eneo.completion_models.infrastructure.completion_service import (
        ResolvedCompletionModelRoute,
    )
    from eneo.flows.domain.flow import Flow

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PlannerRequestPreparationInput:
    conversation: list[ConversationMessage]
    litellm_client: Any
    completion_model_route: ResolvedCompletionModelRoute
    available_models: list[AIBuilderAvailableModelResource] | None
    available_kbs: list[AIBuilderAvailableKnowledgeBaseResource] | None
    flow: Flow | None
    assistant_snapshots: AssistantAuthoringSnapshots | None
    attachment_files: list[File]
    max_input_tokens: int
    max_output_tokens: int
    budget_policy: AIBuilderBudgetPolicy
    attachment_context_policy: AIBuilderAttachmentContextPolicy
    mapped_execution_policy: FlowMappedExecutionPolicy
    base_planning_state_version: int
    tenant_id: UUID
    plan_edit_context: ResolvedAIBuilderEditContext | None
    prior_plan_for_revision: BuilderPlan | None
    persisted_planning_state: PlanningState | None
    current_turn_start: int
    usage_tracker: ProposalTurnTelemetry
    before_provider_call: Callable[[], Awaitable[None]] | None = None
    prepared_attachment_context: AIBuilderAttachmentContext | None = None
    prepared_schema_candidates: tuple[DeclaredSchemaCandidate, ...] | None = None


@dataclass(frozen=True, slots=True)
class PreparedPromptMessages:
    message_groups: tuple[ProposalMessageGroup, ...]
    system_prompt_hash: str
    conversation_budget_tokens: int
    trimmed_message_count: int
    system_prompt_chars: int

    @property
    def llm_messages(self) -> list[LLMMessageParam]:
        return flatten_proposal_message_groups(self.message_groups)


@dataclass(frozen=True, slots=True)
class _PreparedBase:
    requirements_state: RequirementsState
    ui_language: str | None
    slot_classification_metadata: SlotClassificationMetadata | None


@dataclass(frozen=True, slots=True)
class ServerOutputPrepared(_PreparedBase):
    server_decision: BuilderTurnDecision
    discovery_analysis: DiscoveryAnalysis
    planning_state: PlanningState
    resource_catalog: AIBuilderResourceCatalog
    attachment_context: AIBuilderAttachmentContext | None
    flow_context: str | None


@dataclass(frozen=True, slots=True)
class ProposalPrepared(_PreparedBase):
    message_groups: tuple[ProposalMessageGroup, ...]
    system_prompt_hash: str
    plan_edit_context: ResolvedAIBuilderEditContext | None
    prior_spec_for_revision: FlowDraftSpecCore | None
    resource_catalog: AIBuilderResourceCatalog
    planning_state: PlanningState
    compile_context: CreateCompileContext | None
    proposal_tool_schema: ProposalToolSchema
    obligation_projection: ProposalObligationProjection | None = None
    request_budget: ProposalRequestBudget | None = None

    @property
    def llm_messages(self) -> list[LLMMessageParam]:
        return flatten_proposal_message_groups(self.message_groups)


PreparedTurnOutcome: TypeAlias = ServerOutputPrepared | ProposalPrepared


async def prepare_planner_request(
    request: PlannerRequestPreparationInput,
) -> PreparedTurnOutcome:
    requirements_state = resolve_requirements_state(request.conversation)
    ui_language = _resolve_ui_language(request.conversation)
    if request.prepared_schema_candidates is not None:
        attachment_context_result = request.prepared_attachment_context
        schema_candidates = request.prepared_schema_candidates
    else:
        attachment_context_result = build_ai_builder_attachment_context_for_model(
            request.attachment_files,
            policy=request.attachment_context_policy,
            model_name=request.completion_model_route.litellm_model,
            max_input_tokens=request.max_input_tokens,
            max_output_tokens=request.max_output_tokens,
            safety_buffer_tokens=request.budget_policy.conversation_safety_buffer_tokens,
            minimum_conversation_tokens=(
                request.budget_policy.minimum_conversation_budget_tokens
            ),
        )
        schema_candidates = validate_preprovider_schema_gate(
            conversation=request.conversation,
            attachment_context=attachment_context_result,
        )
    # Eligibility is decided against the attachment context this turn actually
    # built, so a coverage change under an unchanged file id cannot pass.
    acknowledged_disclosure = _acknowledged_disclosure(
        request,
        requirements_state,
        attachment_context=attachment_context_result,
    )
    if acknowledged_disclosure is not None:
        # Nothing new was said, so nothing is re-read: the turn resolves from
        # the very state whose disclosure the user just confirmed. That state
        # was persisted before the user answered it, so the acceptance itself
        # still has to be applied — deterministically, from the disclosure
        # that was confirmed, not by re-reading the evidence behind it.
        assert request.persisted_planning_state is not None
        discovery_analysis = DiscoveryAnalysis(issues=())
        rebuilt_planning_state = request.persisted_planning_state.model_copy(deep=True)
        apply_attested_requirements(rebuilt_planning_state, acknowledged_disclosure)
        schema_direction_pending = False
        control_schema_candidates: tuple[DeclaredSchemaCandidate, ...] = ()
        slot_classification_metadata = None
        requirements_disclosure = acknowledged_disclosure
    else:
        discovery_runtime = await build_discovery_runtime_result(
            request.conversation,
            flow=request.flow,
            litellm_client=request.litellm_client,
            completion_model_route=request.completion_model_route,
            ui_language=ui_language,
            tenant_id=request.tenant_id,
            attachment_context=attachment_context_result,
            usage_tracker=request.usage_tracker,
            before_provider_call=request.before_provider_call,
            mapped_execution_policy=request.mapped_execution_policy,
            prepared_schema_candidates=schema_candidates,
            persisted_planning_state=request.persisted_planning_state,
            attached_file_ids={file.id for file in request.attachment_files},
            max_input_tokens=request.max_input_tokens,
            max_output_tokens=request.max_output_tokens,
            safety_buffer_tokens=request.budget_policy.conversation_safety_buffer_tokens,
            minimum_conversation_tokens=(
                request.budget_policy.minimum_conversation_budget_tokens
            ),
        )
        discovery_analysis = discovery_runtime.discovery_analysis
        rebuilt_planning_state = discovery_runtime.planning_state
        schema_direction_pending = discovery_runtime.schema_direction_pending
        control_schema_candidates = discovery_runtime.schema_candidates
        slot_classification_metadata = discovery_runtime.slot_classification_metadata
        requirements_disclosure = build_requirements_disclosure(
            rebuilt_planning_state,
            ui_language=ui_language,
            discovery_assumptions=discovery_analysis.assumptions,
            is_edit_mode=request.flow is not None,
        )

    flow_context = _build_flow_context_if_needed(
        conversation=request.conversation,
        flow=request.flow,
        assistant_snapshots=request.assistant_snapshots,
    )
    prior_resource_bindings = (
        request.prior_plan_for_revision.resource_bindings
        if request.prior_plan_for_revision is not None
        else tuple()
    )
    resource_catalog = build_ai_builder_resource_catalog(
        available_models=request.available_models,
        available_kbs=request.available_kbs,
        prior_bindings=prior_resource_bindings,
    )
    if schema_direction_pending:
        rebuilt_planning_state.replace_schema_resolution(
            input_evidence=None,
            output_evidence=None,
            example_inference=None,
        )
    turn_control = resolve_turn_control(
        session_state=rebuilt_planning_state,
        selected_discovery_question_ids=discovery_analysis.selected_question_ids,
        requirements_disclosure=requirements_disclosure,
        confirmed_requirements_version=(
            requirements_state.confirmed_requirements_version
        ),
        ui_language=ui_language,
        attachment_context=attachment_context_result,
        schema_candidates=control_schema_candidates,
        schema_direction_pending=schema_direction_pending,
        requirements_confirmation_required=(
            request.plan_edit_context is None
            or request.plan_edit_context.scope != "step"
        ),
        is_edit_mode=request.flow is not None,
    )
    if not isinstance(turn_control.decision, GenerateProposal):
        return ServerOutputPrepared(
            requirements_state=requirements_state,
            ui_language=ui_language,
            slot_classification_metadata=slot_classification_metadata,
            discovery_analysis=discovery_analysis,
            server_decision=turn_control.decision,
            planning_state=rebuilt_planning_state,
            resource_catalog=resource_catalog,
            attachment_context=attachment_context_result,
            flow_context=flow_context,
        )

    assert isinstance(turn_control.decision, GenerateProposal)
    return build_proposal_prepared(
        requirements_state=requirements_state,
        ui_language=ui_language,
        slot_classification_metadata=slot_classification_metadata,
        conversation=request.conversation,
        planning_state=rebuilt_planning_state,
        attachment_context=attachment_context_result,
        flow_context=flow_context,
        is_edit_mode=request.flow is not None,
        resource_catalog=resource_catalog,
        flow=request.flow,
        assistant_snapshots=request.assistant_snapshots,
        plan_edit_context=request.plan_edit_context,
        prior_plan_for_revision=request.prior_plan_for_revision,
        litellm_model=request.completion_model_route.litellm_model,
        max_input_tokens=request.max_input_tokens,
        max_output_tokens=request.max_output_tokens,
        budget_policy=request.budget_policy,
        attachment_file_count=len(request.attachment_files),
        current_turn_start=request.current_turn_start,
    )


def _acknowledged_disclosure(
    request: PlannerRequestPreparationInput,
    requirements_state: RequirementsState,
    *,
    attachment_context: AIBuilderAttachmentContext | None,
) -> RequirementsSummaryPayload | None:
    """The exact disclosure this turn merely acknowledges, when it does.

    Confirming is a structured action, not a chat turn. Reading an
    acknowledgment back as fresh semantic evidence is what made the server
    re-interpret unchanged attachments and re-issue a summary the user had
    already confirmed, until the interaction limit.

    The fast path reuses the persisted state that produced the confirmed
    disclosure, so it may only run while that state still describes this turn.
    Anything that could genuinely be new evidence — a missing or stale version,
    changed attachments or changed server policy — falls through to the
    ordinary path and earns a new disclosure. `resolve_requirements_state`
    owns what counts as a confirmation at all, including that it carries no
    message of its own.
    """

    persisted = request.persisted_planning_state
    if persisted is None:
        return None
    if requirements_state.confirmed_requirements_version is None:
        return None
    if not _turn_is_the_acknowledgment(request.conversation):
        return None
    if not _persisted_attachments_are_current(
        persisted,
        attachment_files=request.attachment_files,
        attachment_context=attachment_context,
    ):
        return None
    # The accepted mapped limit compiles into `runtime_max_files`, so a policy
    # the organization changed since the disclosure is a different plan.
    if persisted.mapped_file_limit.proposed_value != max_mapped_items_per_step(
        request.mapped_execution_policy
    ):
        return None
    return requirements_state.latest_summary


def _turn_is_the_acknowledgment(conversation: list[ConversationMessage]) -> bool:
    """Whether this turn is the acknowledgment itself.

    A confirmation stays valid across later revision turns, so a still-valid
    confirmation does not make every later turn an acknowledgment. Only the
    turn that carries a confirmation — and only a confirmation, by the same
    content-free rule that decides validity — may skip re-reading the evidence.
    """

    latest = conversation[-1] if conversation else None
    return (
        latest is not None
        and latest.role == "user"
        and content_free_confirmation(latest) is not None
    )


def _persisted_attachments_are_current(
    persisted: PlanningState,
    *,
    attachment_files: list[File],
    attachment_context: AIBuilderAttachmentContext | None,
) -> bool:
    # Exact membership, not containment: detaching a disclosed file changes the
    # plan just as much as attaching a new one, and only the ordinary rebuild
    # reconciles roles against current session membership.
    if {role.file_id for role in persisted.file_roles} != {
        file.id for file in attachment_files
    }:
        return False
    # The same file can be read differently by a different model or budget, and
    # how much of it the planner saw is disclosed evidence.
    current_coverage = {
        item.file_id: item.coverage
        for item in (
            attachment_context.evidence if attachment_context is not None else ()
        )
    }
    return all(
        role.coverage == current_coverage.get(role.file_id)
        for role in persisted.file_roles
    )


def build_proposal_prepared(
    *,
    requirements_state: RequirementsState,
    ui_language: str | None,
    slot_classification_metadata: SlotClassificationMetadata | None,
    conversation: list[ConversationMessage],
    planning_state: PlanningState,
    attachment_context: AIBuilderAttachmentContext | None,
    flow_context: str | None,
    is_edit_mode: bool,
    resource_catalog: AIBuilderResourceCatalog,
    flow: "Flow | None",
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    plan_edit_context: ResolvedAIBuilderEditContext | None,
    prior_plan_for_revision: BuilderPlan | None,
    litellm_model: str,
    max_input_tokens: int,
    max_output_tokens: int,
    budget_policy: AIBuilderBudgetPolicy,
    attachment_file_count: int,
    current_turn_start: int,
) -> ProposalPrepared:
    confirmed_requirements = latest_confirmed_requirements(conversation)
    section_signal_text = "\n".join(
        part
        for part in (
            aggregate_unprompted_user_text_preserving_case(conversation),
            build_requirements_signal_text(confirmed_requirements),
        )
        if part
    )
    requested_output_sections = extract_requested_output_sections(
        section_signal_text,
        model_form_intake_signals=form_intake_signal_values_from_planning_state(
            planning_state
        ),
    )
    prior_spec_for_revision = _prior_spec_for_revision(
        context=plan_edit_context,
        prior_plan=prior_plan_for_revision,
        flow=flow,
        assistant_snapshots=assistant_snapshots,
        resource_catalog=resource_catalog,
    )
    plan_revision_context = build_plan_revision_prompt_block(
        context=plan_edit_context,
        prior_spec=prior_spec_for_revision,
    )
    compile_context = create_compile_context_from_planning_state(
        planning_state,
        ui_language=ui_language,
        requested_output_sections=requested_output_sections,
    )
    is_pure_audio_transcription = (
        not is_edit_mode
        and compile_context is not None
        and compile_context.is_pure_audio_transcription
    )
    if (
        not is_edit_mode
        and compile_context is not None
        and compile_context.is_audio_transcription_envelope
        and not is_pure_audio_transcription
    ):
        raise AIBuilderBadRequestException(
            "Audio-to-text post-processing requires a downstream semantic step.",
            code=AIBuilderErrorCode.ARCHITECTURE_MATERIALIZATION_FAILED,
            context={
                "reason": "audio_transcription_post_processing_unsupported",
                "post_processing_goal": compile_context.post_processing_goal,
                "secondary_obligations": list(compile_context.secondary_obligations),
            },
        )
    obligation_projection = named_result_projection(
        planning_state,
        is_edit_mode=is_edit_mode,
    )
    proposal_tool_schema = build_propose_flow_tool_schema(
        current_steps=None if flow is None else list(flow.steps),
        resource_catalog=resource_catalog,
        is_pure_audio_transcription=is_pure_audio_transcription,
        confirmed_runtime_inputs=(
            compile_context.confirmed_runtime_input_requirements
            if compile_context is not None and not is_edit_mode
            else ()
        ),
        obligation_projection=obligation_projection,
    )
    incompatible_field_names = (
        compile_context.incompatible_confirmed_form_field_names
        if compile_context is not None and not is_edit_mode
        else ()
    )
    if incompatible_field_names:
        raise AIBuilderBadRequestException(
            "Confirmed runtime fields conflict with the primary flow input.",
            code=AIBuilderErrorCode.ARCHITECTURE_MATERIALIZATION_FAILED,
            context={
                "reason": "confirmed_form_field_incompatible",
                "field_names": list(incompatible_field_names),
            },
        )

    def build_proposal_prompt(
        attachment_text: str | None,
        replayed_requirements: RequirementsSummaryPayload | None,
    ) -> str:
        return build_plan_proposal_system_prompt(
            planning_state=planning_state,
            confirmed_requirements=replayed_requirements,
            attachment_context=attachment_text,
            flow_context=flow_context,
            is_edit_mode=is_edit_mode,
            is_pure_audio_transcription=is_pure_audio_transcription,
            resource_catalog=resource_catalog,
            requested_output_sections=requested_output_sections,
            plan_revision_context=plan_revision_context,
            confirmed_runtime_inputs=(
                compile_context.confirmed_runtime_input_requirements
                if compile_context is not None and not is_edit_mode
                else ()
            ),
        )

    system_prompt_token_limit = _proposal_system_prompt_token_limit(
        proposal_tool_schema=proposal_tool_schema,
        litellm_model=litellm_model,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        budget_policy=budget_policy,
    )

    def prompt_fits(
        attachment_text: str | None,
        replayed_requirements: RequirementsSummaryPayload | None,
    ) -> bool:
        return (
            count_message_tokens(
                [
                    {
                        "role": "system",
                        "content": build_proposal_prompt(
                            attachment_text, replayed_requirements
                        ),
                    }
                ],
                litellm_model,
            )
            <= system_prompt_token_limit
        )

    replayed_requirements = _fit_replayed_requirements(
        confirmed_requirements,
        fits=lambda requirements: prompt_fits(None, requirements),
    )
    fitted_attachment_context = (
        fit_ai_builder_attachment_context(
            attachment_context,
            fits_context=lambda context: prompt_fits(context, replayed_requirements),
        )
        if attachment_context is not None
        else None
    )
    proposal_system_prompt = build_proposal_prompt(
        (
            fitted_attachment_context.context
            if fitted_attachment_context is not None
            else None
        ),
        replayed_requirements,
    )
    prepared_prompt = _prepare_prompt_messages(
        conversation=conversation,
        system_prompt=proposal_system_prompt,
        litellm_model=litellm_model,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        budget_policy=budget_policy,
        current_turn_start=current_turn_start,
    )
    logger.info(
        "AI Builder plan proposal prompt metrics",
        extra={
            "system_prompt_chars": prepared_prompt.system_prompt_chars,
            "attachment_context_chars": len(
                fitted_attachment_context.context or ""
                if fitted_attachment_context is not None
                else ""
            ),
            "conversation_budget_tokens": prepared_prompt.conversation_budget_tokens,
            "conversation_message_count": len(conversation),
            "trimmed_message_count": prepared_prompt.trimmed_message_count,
            "attachment_file_count": attachment_file_count,
            "confirmed_requirements_present": confirmed_requirements is not None,
            "replayed_requirement_assumptions": (
                len(replayed_requirements.assumptions)
                if replayed_requirements is not None
                else 0
            ),
        },
    )

    return ProposalPrepared(
        requirements_state=requirements_state,
        ui_language=ui_language,
        slot_classification_metadata=slot_classification_metadata,
        message_groups=prepared_prompt.message_groups,
        system_prompt_hash=prepared_prompt.system_prompt_hash,
        plan_edit_context=plan_edit_context,
        prior_spec_for_revision=prior_spec_for_revision,
        resource_catalog=resource_catalog,
        planning_state=planning_state,
        compile_context=compile_context,
        proposal_tool_schema=proposal_tool_schema,
        obligation_projection=obligation_projection,
        request_budget=ProposalRequestBudget(
            context_window_tokens=max_input_tokens,
            output_reserve_tokens=max_output_tokens,
            safety_buffer_tokens=budget_policy.conversation_safety_buffer_tokens,
        ),
    )


def _prior_spec_for_revision(
    *,
    context: ResolvedAIBuilderEditContext | None,
    prior_plan: BuilderPlan | None,
    flow: "Flow | None",
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    resource_catalog: AIBuilderResourceCatalog,
) -> FlowDraftSpecCore | None:
    if context is None:
        return None
    if prior_plan is not None:
        return prior_plan.spec
    if flow is None:
        raise AIBuilderBadRequestException(
            "The saved Flow step is not available in this AI Builder session.",
            code=AIBuilderErrorCode.INVALID_EXISTING_STEP_REF,
        )
    return current_flow_authoring_spec(
        current_steps=list(flow.steps),
        flow_name=flow.name,
        flow_description=flow.description,
        assistant_snapshots=assistant_snapshots,
        assistant_snapshot_projector=resource_catalog.assistant_spec_from_snapshot,
        form_fields=extract_form_fields_from_metadata(flow.metadata_json),
    )


def _proposal_system_prompt_token_limit(
    *,
    proposal_tool_schema: ProposalToolSchema,
    litellm_model: str,
    max_input_tokens: int,
    max_output_tokens: int,
    budget_policy: AIBuilderBudgetPolicy,
) -> int:
    """What the model can actually carry as a system prompt this turn."""

    return max(
        0,
        max_input_tokens
        - max_output_tokens
        - budget_policy.conversation_safety_buffer_tokens
        - budget_policy.minimum_conversation_budget_tokens
        - count_tool_tokens(
            [cast(dict[str, Any], proposal_tool_schema)], litellm_model
        ),
    )


def _fit_replayed_requirements(
    confirmed_requirements: RequirementsSummaryPayload | None,
    *,
    fits: Callable[[RequirementsSummaryPayload | None], bool],
) -> RequirementsSummaryPayload | None:
    """Bound the replayed disclosure against the model, not a fixed count.

    The disclosure is as long as the evidence the user must see — a template
    can contribute thousands of placeholders — while the proposal prompt is
    bounded by the model. The same budget that fits attachment text decides
    how many confirmed assumptions are replayed; the confirmed decisions and
    descriptions always stay, and `PlanningState` still carries every typed
    fact into compilation.
    """

    if confirmed_requirements is None or fits(confirmed_requirements):
        return confirmed_requirements

    def with_assumptions(count: int) -> RequirementsSummaryPayload:
        return confirmed_requirements.model_copy(
            update={"assumptions": confirmed_requirements.assumptions[:count]},
            deep=True,
        )

    lower = 0
    upper = len(confirmed_requirements.assumptions)
    while lower < upper:
        middle = (lower + upper + 1) // 2
        if fits(with_assumptions(middle)):
            lower = middle
        else:
            upper = middle - 1
    if lower:
        return with_assumptions(lower)

    # The bounded parts of the disclosure are bounded by evidence, not by the
    # model: a hundred named results can outgrow the prompt on their own. What
    # this function returns must fit, so the replay is dropped entirely rather
    # than handed on over budget. `PlanningState` still carries every typed
    # fact into the prompt and into compilation.
    without_assumptions = with_assumptions(0)
    return without_assumptions if fits(without_assumptions) else None


def validate_preprovider_schema_gate(
    *,
    conversation: list[ConversationMessage],
    attachment_context: AIBuilderAttachmentContext | None,
) -> tuple[DeclaredSchemaCandidate, ...]:
    """Validate deterministic schema blockers before any provider work."""

    if attachment_context is not None:
        blocking_refusal = next(
            (
                refusal
                for refusal in attachment_context.schema_discovery.refusals
                if refusal.blocks_provider_work
            ),
            None,
        )
        if blocking_refusal is not None:
            _raise_schema_limit(blocking_refusal)
    try:
        candidates = merge_declared_schema_candidates(
            derive_freeform_schema_candidates(conversation),
            (
                attachment_context.schema_discovery.candidates
                if attachment_context is not None
                else ()
            ),
        )
    except SchemaLimitExceeded as error:
        raise AIBuilderBadRequestException(
            "The supplied schema exceeds the Builder safety limit.",
            code=AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED,
            context={
                "reason": error.reason,
                "max_value": error.max_value,
                **(
                    {"actual_value": error.actual_value}
                    if error.actual_value is not None
                    else {}
                ),
            },
        ) from error
    if not latest_schema_direction_answer_matches_candidates(
        conversation=conversation,
        candidates=candidates,
    ):
        raise AIBuilderBadRequestException(
            "The schema-direction answer does not match the current schemas.",
            code=AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD,
            context={"reason": "invalid_schema_direction"},
        )
    return candidates


def _raise_schema_limit(refusal: SchemaCandidateRefusal) -> None:
    raise AIBuilderBadRequestException(
        "An attached schema exceeds the Builder safety limit.",
        code=AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED,
        context={
            "reason": refusal.reason,
            "max_value": refusal.max_value,
            **(
                {"actual_value": refusal.actual_value}
                if refusal.actual_value is not None
                else {}
            ),
            "file_id": str(refusal.file_id),
        },
    )


def _build_flow_context_if_needed(
    *,
    conversation: list[ConversationMessage],
    flow: Flow | None,
    assistant_snapshots: AssistantAuthoringSnapshots | None,
) -> str | None:
    if flow is None:
        return None
    discovery_profile = build_discovery_profile(conversation, flow=flow)
    return build_flow_context(
        flow,
        assistant_snapshots=assistant_snapshots,
        is_edit_mode=True,
        capabilities=discovery_profile.capabilities,
        edit_scope=discovery_profile.edit_scope,
    )


def _prepare_prompt_messages(
    *,
    conversation: list[ConversationMessage],
    system_prompt: str,
    litellm_model: str,
    max_input_tokens: int,
    max_output_tokens: int,
    budget_policy: AIBuilderBudgetPolicy,
    current_turn_start: int,
) -> PreparedPromptMessages:
    prompt_tokens = count_message_tokens(
        [{"role": "system", "content": system_prompt}],
        litellm_model,
    )
    conversation_budget = compute_conversation_token_budget(
        model_max_input_tokens=max_input_tokens,
        system_prompt_tokens=prompt_tokens,
        max_output_tokens=max_output_tokens,
        safety_buffer_tokens=budget_policy.conversation_safety_buffer_tokens,
    )
    raw_messages = [
        conversation_message_to_llm_message(message) for message in conversation
    ]
    conversation_groups = group_proposal_messages(
        raw_messages,
        current_turn_index=current_turn_start,
    )
    trimmed_groups = fit_proposal_message_groups(
        conversation_groups,
        token_limit=conversation_budget,
        model_name=litellm_model,
    )
    if trimmed_groups is None:
        trimmed_groups = tuple(
            group for group in conversation_groups if group.protected
        )
    system_group = ProposalMessageGroup(
        messages=({"role": "system", "content": system_prompt},),
        kind="system",
        protected=True,
    )
    return PreparedPromptMessages(
        message_groups=(system_group, *trimmed_groups),
        system_prompt_hash=stable_hash(system_prompt),
        conversation_budget_tokens=conversation_budget,
        trimmed_message_count=sum(len(group.messages) for group in trimmed_groups),
        system_prompt_chars=len(system_prompt),
    )


def compute_conversation_token_budget(
    *,
    model_max_input_tokens: int,
    system_prompt_tokens: int,
    max_output_tokens: int,
    safety_buffer_tokens: int,
) -> int:
    budget = (
        model_max_input_tokens
        - system_prompt_tokens
        - max_output_tokens
        - safety_buffer_tokens
    )
    return max(budget, 0)


def trim_conversation_for_context(
    messages: list[LLMMessageParam],
    *,
    max_tokens: int,
    litellm_model: str = "",
) -> list[LLMMessageParam]:
    if not messages:
        return []
    groups = group_proposal_messages(
        messages,
        current_turn_index=len(messages) - 1,
    )
    fitted = fit_proposal_message_groups(
        groups,
        token_limit=max_tokens,
        model_name=litellm_model,
    )
    if fitted is None:
        fitted = tuple(group for group in groups if group.protected)
    return flatten_proposal_message_groups(fitted)


def conversation_message_to_llm_message(msg: ConversationMessage) -> LLMMessageParam:
    content = msg.content
    question_answer = question_answer_from_metadata(msg.metadata)
    if msg.role == "user" and question_answer is not None:
        question_answer_payload = question_answer.model_dump(
            mode="json",
            exclude_none=True,
            exclude={"kind", "ui_language"},
        )
        sanitized_answer = {
            key: value
            for key, value in question_answer_payload.items()
            if key
            in {
                "question_id",
                "selected_option_ids",
                "selected_values",
                "custom_value",
            }
        }
        if sanitized_answer:
            structured_note = json.dumps(
                sanitized_answer,
                ensure_ascii=False,
                sort_keys=True,
            )
            content = (
                f"{content}\n\n[Structured answer metadata: {structured_note}]"
                if content
                else f"[Structured answer metadata: {structured_note}]"
            )

    payload: LLMMessageParam = {
        "role": _llm_message_role(msg.role),
        "content": content,
    }
    tool_calls = tool_calls_from_message(msg)
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": provider_safe_tool_call_id(tool_call.id),
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments),
                },
            }
            for tool_call in tool_calls
        ]
    if msg.tool_call_id:
        payload["tool_call_id"] = provider_safe_tool_call_id(msg.tool_call_id)
    return payload


def _llm_message_role(role: str) -> LLMMessageRole:
    match role:
        case "system":
            return "system"
        case "user":
            return "user"
        case "assistant":
            return "assistant"
        case "tool":
            return "tool"
        case _:
            raise ValueError(f"Unsupported AI Builder conversation role: {role!r}")


def _resolve_ui_language(conversation: list[ConversationMessage]) -> str | None:
    for message in reversed(conversation):
        if message.role != "user":
            continue
        ui_language = ui_language_from_metadata(message.metadata)
        if ui_language is not None:
            return ui_language
    return None
