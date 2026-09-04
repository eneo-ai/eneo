from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Callable
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import litellm
import pytest
from pydantic import ValidationError

from eneo.authentication.principal_types import PrincipalType
from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.files.file_models import File, FileType
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContext,
    AIBuilderAttachmentContextPolicy,
    AIBuilderAttachmentSchemaDiscovery,
    build_ai_builder_attachment_context,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    SlotClassificationNamedResultEvidenceMetadata,
    requirements_summary_to_metadata,
    slot_classification_metadata_from_attempt,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import DiscoveryAnalysis
from eneo.flows.ai_builder.ai_builder_discovery_runtime import DiscoveryRuntimeResult
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
    BuilderTurnLifecycle,
    BuilderTurnState,
    ConversationMessage,
    SessionStatus,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderKnownProviderRejectionException,
    build_ai_builder_error_event,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderStatus,
    AIBuilderStreamEvent,
    KeyDecisionPayload,
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_events import (
    build_status_event,
    build_text_event,
    encode_ai_builder_stream_event,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    AIBuilderSavedFlowStepEditContext,
    ResolvedAIBuilderEditContext,
)
from eneo.flows.ai_builder.ai_builder_planner import (
    AIBuilderPlanner,
)
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    PlannerRequestPreparationInput,
    ProposalPrepared,
    ServerOutputPrepared,
    _fit_replayed_requirements,
    build_proposal_prepared,
    prepare_planner_request,
    validate_preprovider_schema_gate,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    FlowInputFieldIntent,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import ProposalTurnTelemetry
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalMessageGroup,
    fit_proposal_request_budget,
    flatten_proposal_message_groups,
)
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
    build_requirements_disclosure,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    RequirementsState,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_requirements import (
    ConfirmedRuntimeInputRequirement,
    render_confirmed_runtime_input_requirements,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    SCHEMA_MAX_JSON_BYTES,
    DeclaredSchemaCandidate,
)
from eneo.flows.ai_builder.ai_builder_server_decision_dispatch import (
    ServerDecisionDispatchRequest,
    ServerDecisionDispatchResult,
    ServerDecisionProposalContinuation,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionTurnClaim,
    SessionTurnClaimDisposition,
    SessionTurnPreflight,
    SessionTurnPreparationBaseline,
)
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
    AIBuilderRequestBudget,
)
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    SLOT_CLASSIFICATION_SCHEMA_VERSION,
    ClassifiedEvidence,
    SlotClassificationAttempt,
    SlotClassificationInput,
    SlotClassificationResult,
    SlotClassificationSource,
)
from eneo.flows.ai_builder.ai_builder_tool_names import (
    DECLINE_FLOW_CHANGE_TOOL_NAME,
    PROPOSE_FLOW_TOOL_NAME,
)
from eneo.flows.ai_builder.ai_builder_tools import (
    ProposalToolSchema,
    build_native_strict_tool_schema,
    build_propose_flow_tool_schema,
    validate_native_strict_schema,
    validate_propose_flow_tool_arguments,
)
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    AskCanonicalQuestion,
    CommitArchitecture,
    ConfirmRequirements,
    ReviseArchitecture,
    resolve_turn_control,
)
from eneo.flows.ai_builder.ai_builder_user_question_metadata import (
    prepare_user_question_metadata,
)
from eneo.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    NAMED_RESULT_EVIDENCE_MAX_ITEMS,
    ArchitectureCommit,
    AttachmentCoverage,
    ConfirmedRuntimeMetadataField,
    ExactNamedResultPlacement,
    ExampleOutputCitation,
    ExampleOutputConstraintEvidence,
    ExampleOutputSourceCoverage,
    FileRoleEvidence,
    MappedFileLimit,
    NamedResultEvidence,
    PlanningSignal,
    PlanningState,
    PlanningStatePayloadTooLargeError,
    ResolvedSlot,
    StepTriple,
)
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from eneo.flows.input_binding_contract_rules import source_ref_bindings
from eneo.main.exceptions import BadRequestException, ErrorCodes
from eneo.tokens.token_utils import count_message_tokens, count_tool_tokens


def _route(
    *,
    model: str = "openai/gpt-5.4",
    kwargs: dict[str, object] | None = None,
) -> ResolvedCompletionModelRoute:
    return ResolvedCompletionModelRoute(
        litellm_model=model,
        provider_type="openai",
        litellm_kwargs=kwargs or {},
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(supported=True)
        ),
    )


_TEST_CLIENT_TURN_ID = UUID("11111111-1111-4111-8111-111111111111")
_TEST_REQUEST_FINGERPRINT = "a" * 64


def _empty_proposal_tool_schema() -> ProposalToolSchema:
    return build_propose_flow_tool_schema(
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
        )
    )


def _test_request_snapshot(message: str) -> FlowPersistedJsonObject:
    return {
        "client_turn_id": str(_TEST_CLIENT_TURN_ID),
        "message": message,
    }


def _make_planner() -> AIBuilderPlanner:
    planner = AIBuilderPlanner(
        user=MagicMock(tenant_id=uuid4()),
        repo=AsyncMock(),
        litellm_client=AsyncMock(),
        planner_temperature=0.1,
        self_correction_temperature=0.1,
        forced_proposal_temperature=0.1,
        quality_retry_warning_codes=set(),
    )

    async def accept_turn(**kwargs: object) -> SessionTurnClaim:
        acceptance = kwargs["acceptance"]
        user_message = cast(
            ConversationMessage,
            getattr(acceptance, "user_message"),
        )
        session = planner.repo.get_session.return_value
        if hasattr(session, "conversation"):
            session.conversation = [*session.conversation, user_message]
        return SessionTurnClaim(
            disposition=SessionTurnClaimDisposition.EXECUTE,
            user_message=user_message,
            base_planning_state_version=getattr(session, "planning_state_version", 0),
        )

    async def preflight_turn(**_: object) -> SessionTurnPreflight:
        session = planner.repo.get_session.return_value
        if session.status not in {
            SessionStatus.CHATTING,
            SessionStatus.AWAITING_APPROVAL,
        }:
            raise AIBuilderBadRequestException(
                "Cannot send messages in this AI Builder session right now.",
                code=AIBuilderErrorCode.INVALID_SESSION_TRANSITION,
            )
        return SessionTurnPreflight(
            session=session,
            baseline=SessionTurnPreparationBaseline(
                session_status=SessionStatus(session.status),
                latest_plan_id=getattr(session, "latest_plan_id", None),
                planning_state_version=getattr(session, "planning_state_version", 0),
                latest_turn_id=None,
                latest_turn_state=None,
                attachment_file_ids=(),
            ),
        )

    planner.repo.accept_session_turn.side_effect = accept_turn
    planner.repo.preflight_session_turn.side_effect = preflight_turn
    return planner


def _model_resource(
    local_id: str,
    name: str,
    *,
    provider: str = "test",
) -> AIBuilderAvailableModelResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "provider": provider,
    }


def _kb_resource(
    local_id: str,
    name: str,
    *,
    description: str = "",
) -> AIBuilderAvailableKnowledgeBaseResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "description": description,
    }


def _make_file(
    text: str = "Reference",
    *,
    name: str = "reference.txt",
    mimetype: str = "text/plain",
) -> File:
    return File(
        id=uuid4(),
        name=name,
        checksum="checksum",
        size=len(text.encode("utf-8")),
        mimetype=mimetype,
        file_type=FileType.TEXT,
        text=text,
        blob=None,
        transcription=None,
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=uuid4(),
    )


def _runtime_result(
    discovery_analysis: DiscoveryAnalysis,
    planning_state: PlanningState,
) -> DiscoveryRuntimeResult:
    return DiscoveryRuntimeResult(
        discovery_analysis=discovery_analysis,
        planning_state=planning_state,
    )


def _discovery_analysis(
    *,
    mvs_met: bool = True,
    selected_question_ids: tuple[str, ...] = (),
) -> DiscoveryAnalysis:
    return DiscoveryAnalysis(
        issues=(),
        mvs_met=mvs_met,
        selected_question_ids=selected_question_ids,
    )


async def _prepare_planner_request_for_test(
    planner: AIBuilderPlanner,
    *,
    conversation: list[ConversationMessage],
    completion_model_route: ResolvedCompletionModelRoute,
    available_models: list[AIBuilderAvailableModelResource] | None = None,
    available_kbs: list[AIBuilderAvailableKnowledgeBaseResource] | None = None,
    flow: object = None,
    assistant_snapshots: object = None,
    attachment_files: list[File] | None = None,
    max_input_tokens: int = 100_000,
    max_output_tokens: int = 1024,
    budget_policy: AIBuilderBudgetPolicy | None = None,
    base_planning_state_version: int = 0,
    plan_edit_context: object = None,
    prior_plan_for_revision: BuilderPlan | None = None,
    persisted_planning_state: PlanningState | None = None,
    mapped_execution_policy: FlowMappedExecutionPolicy | None = None,
    before_provider_call: AsyncMock | None = None,
    prepared_attachment_context: AIBuilderAttachmentContext | None = None,
    prepared_schema_candidates: tuple[DeclaredSchemaCandidate, ...] | None = None,
):
    return await prepare_planner_request(
        PlannerRequestPreparationInput(
            conversation=conversation,
            litellm_client=planner.litellm_client,
            completion_model_route=completion_model_route,
            available_models=available_models,
            available_kbs=available_kbs,
            flow=cast(Any, flow),
            assistant_snapshots=cast(Any, assistant_snapshots),
            attachment_files=attachment_files or [],
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            mapped_execution_policy=(
                mapped_execution_policy or FlowMappedExecutionPolicy()
            ),
            budget_policy=budget_policy
            or AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            attachment_context_policy=AIBuilderAttachmentContextPolicy(),
            base_planning_state_version=base_planning_state_version,
            tenant_id=planner.user.tenant_id,
            plan_edit_context=cast(Any, plan_edit_context),
            prior_plan_for_revision=prior_plan_for_revision,
            persisted_planning_state=persisted_planning_state,
            current_turn_start=0,
            usage_tracker=ProposalTurnTelemetry(
                request_id="req-prepare-test",
                model=completion_model_route.litellm_model,
                target_kind=TargetKind.CREATE,
            ),
            before_provider_call=before_provider_call,
            prepared_attachment_context=prepared_attachment_context,
            prepared_schema_candidates=prepared_schema_candidates,
        )
    )


def _requirements_summary(version: str) -> RequirementsSummaryPayload:
    return RequirementsSummaryPayload(
        requirements_version=version,
        summary="Build a report flow.",
        key_decisions=[KeyDecisionPayload(topic="Input", decision="Use text input")],
        input_description="Text input.",
        output_description="Text output.",
        assumptions=[],
        manual_setup_notes=[],
    )


def _requirements_state_unconfirmed() -> RequirementsState:
    return RequirementsState()


def _requirements_state_confirmed(
    version: str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
) -> RequirementsState:
    return RequirementsState(
        latest_summary=_requirements_summary(version),
        latest_version=version,
        confirmed_version=version,
    )


def _requirements_state_confirmed_for(
    state: PlanningState,
    *,
    ui_language: str | None = "en",
) -> RequirementsState:
    disclosure = build_requirements_disclosure(
        state,
        ui_language=ui_language,
    )
    decision = resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        requirements_disclosure=disclosure,
        confirmed_requirements_version=None,
        ui_language=ui_language,
    ).decision
    assert isinstance(decision, ConfirmRequirements)
    version = decision.payload.requirements_version
    return RequirementsState(
        latest_summary=decision.payload,
        latest_version=version,
        confirmed_version=version,
    )


def _architecture_commit() -> ArchitectureCommit:
    return ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=["input_text"],
        committed_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )


def _document_architecture_state() -> PlanningState:
    state = PlanningState.empty()
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["document_to_structured_report"],
        required_capabilities=["input_document", "output_mode_pass_through"],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="documents",
            source="requirements_summary",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="requirements_summary",
            confidence="high",
        ),
        "document_material_scope": ResolvedSlot(
            name="document_material_scope",
            value="single_document_case",
            source="requirements_summary",
            confidence="high",
        ),
    }
    return state


def _budget_policy() -> AIBuilderBudgetPolicy:
    return AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=128,
        minimum_conversation_budget_tokens=256,
    )


def _proposal_budget(
    *,
    context_window_tokens: int = 4_096,
    model_output_ceiling_tokens: int = 1_024,
) -> AIBuilderRequestBudget:
    return _budget_policy().proposal_request_budget(
        context_window_tokens=context_window_tokens,
        model_output_ceiling_tokens=model_output_ceiling_tokens,
    )


def _build_create_proposal_for_architecture(
    state: PlanningState,
) -> ProposalPrepared:
    return build_proposal_prepared(
        requirements_state=RequirementsState(),
        ui_language="en",
        slot_classification_metadata=None,
        conversation=[ConversationMessage(role="user", content="Build the flow.")],
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[], available_kbs=[], prior_bindings=()
        ),
        flow=None,
        assistant_snapshots=None,
        plan_edit_context=None,
        prior_plan_for_revision=None,
        litellm_model="openai/gpt-5.4",
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
        attachment_file_count=0,
        current_turn_start=0,
    )


def test_property_names_are_not_read_as_schema_keywords() -> None:
    # A property may legitimately be called "type" or "required"; only schemas
    # carry keywords.
    validate_native_strict_schema(
        {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "required": {"type": ["string", "null"]},
            },
            "required": ["type", "required"],
            "additionalProperties": False,
        }
    )


def test_prepared_create_schema_has_a_native_strict_transport_projection() -> None:
    prepared = _build_create_proposal_for_architecture(_document_architecture_state())
    tool_schema = prepared.proposal_tool_schema
    parameters = tool_schema["function"]["parameters"]

    assert "strict" not in tool_schema["function"]
    assert set(parameters["required"]) != set(parameters["properties"])
    strict_tool_schema = build_native_strict_tool_schema(tool_schema)
    validate_native_strict_schema(strict_tool_schema["function"]["parameters"])

    raw_create_payload = {
        "flow_name": "Case assessment",
        "flow_description": None,
        "plan_rationale": "Extract the case facts and prepare a decision summary.",
        "steps": [
            {
                "name": "Assess case",
                "instructions": "Assess the submitted case material.",
                "output_fields": [
                    {
                        "name": "assessment",
                        "field_type": "object",
                        "description": "The structured case assessment.",
                        "required": True,
                        "children": [
                            {
                                "name": "summary",
                                "field_type": "string",
                                "description": "A concise case summary.",
                                "required": True,
                            },
                            {
                                "name": "actions",
                                "field_type": "array",
                                "description": "Recommended follow-up actions.",
                                "required": True,
                                "children": [
                                    {
                                        "name": "owner",
                                        "field_type": "string",
                                        "description": "The action owner.",
                                        "required": True,
                                    }
                                ],
                            },
                        ],
                    }
                ],
                "model_ref": None,
                "knowledge_refs": [
                    " knowledge.policy ",
                    "knowledge.policy",
                ],
                "citations_requested": False,
            }
        ],
        "assumptions": [],
    }
    validate_propose_flow_tool_arguments(
        arguments=raw_create_payload,
        tool_schema=tool_schema,
    )
    parsed = parse_create_flow_intent_arguments(raw_create_payload)
    assert parsed.steps[0].knowledge_refs == ["knowledge.policy"]


def test_prepared_edit_schema_is_not_native_strict() -> None:
    tool_schema = build_propose_flow_tool_schema(
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
        ),
        current_steps=[],
    )
    encoded = json.dumps(tool_schema, ensure_ascii=False, sort_keys=True)

    assert "strict" not in tool_schema["function"]
    assert "uniqueItems" in encoded


def _audio_text_architecture_state(
    *,
    post_processing_goal: str,
    secondary_obligation: str | None = None,
) -> PlanningState:
    """An audio flow with a text terminal, committed the way production does."""

    state = PlanningState.empty()
    for name, value in (
        ("primary_runtime_input", "audio"),
        ("terminal_output", "structured_text"),
        ("post_processing_goal", post_processing_goal),
    ):
        state.resolved_slots[name] = ResolvedSlot(
            name=name,
            value=value,
            source="structured_answer",
            confidence="high",
        )
    if secondary_obligation is not None:
        state.signals.append(
            PlanningSignal(
                question_id="result_obligation",
                value=secondary_obligation,
                confidence="high",
                source="model",
            )
        )
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    state.architecture_commit = finalize_architecture_commit(draft)
    return state


@pytest.mark.parametrize("secondary_obligation", [None, "summary"])
def test_create_preparation_projects_explicit_transcript_only_context(
    secondary_obligation: str | None,
) -> None:
    # A retained obligation signal from earlier in the conversation must not
    # turn the settled transcript-only answer into a multi-step flow.
    state = _audio_text_architecture_state(
        post_processing_goal="stop_after_primary_operation",
        secondary_obligation=secondary_obligation,
    )

    prepared = _build_create_proposal_for_architecture(state)

    assert prepared.compile_context is not None
    assert prepared.compile_context.is_pure_audio_transcription is True
    prompt = prepared.llm_messages[0]["content"]
    assert isinstance(prompt, str)
    assert "exactly one semantic transcription step" in prompt
    steps_schema = prepared.proposal_tool_schema["function"]["parameters"][
        "properties"
    ]["steps"]
    assert steps_schema["maxItems"] == 1
    assert set(steps_schema["items"]["properties"]) == {"name", "instructions"}


@pytest.mark.parametrize(
    "post_processing_goal",
    ["summarize_or_overview", "action_followup", "structure_key_information"],
)
def test_create_preparation_plans_semantic_steps_for_audio_text_post_processing(
    post_processing_goal: str,
) -> None:
    state = _audio_text_architecture_state(
        post_processing_goal=post_processing_goal,
    )

    prepared = _build_create_proposal_for_architecture(state)

    assert prepared.compile_context is not None
    assert prepared.compile_context.is_pure_audio_transcription is False
    # The generic create contract: the model owns the semantic steps that turn
    # the transcript into the terminal text.
    assert prepared.proposal_tool_schema == build_propose_flow_tool_schema(
        resource_catalog=prepared.resource_catalog
    )
    prompt = prepared.llm_messages[0]["content"]
    assert isinstance(prompt, str)
    assert "exactly one semantic transcription step" not in prompt


def test_create_preparation_keeps_audio_report_prompt_and_generic_schema() -> None:
    state = PlanningState.empty()
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="audio",
                output_type="text",
                output_mode="transcribe_only",
            ),
            StepTriple(
                input_type="text",
                output_type="pdf",
                output_mode="render_verbatim",
            ),
        ],
        chosen_patterns=["audio_transcription", "audio_to_artifact_report"],
        required_capabilities=["input_audio", "output_pdf"],
        committed_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        architecture_hash="d" * 64,
    )
    state.resolved_slots["post_processing_goal"] = ResolvedSlot(
        name="post_processing_goal",
        value="action_followup",
        source="structured_answer",
        confidence="high",
    )

    prepared = _build_create_proposal_for_architecture(state)

    assert prepared.compile_context is not None
    assert prepared.compile_context.is_pure_audio_transcription is False
    assert prepared.proposal_tool_schema == build_propose_flow_tool_schema(
        resource_catalog=prepared.resource_catalog
    )
    prompt = prepared.llm_messages[0]["content"]
    assert isinstance(prompt, str)
    assert "start propose_flow steps with the analysis" in prompt
    assert "exactly one semantic transcription step" not in prompt
    assert "Next steps or actions" in prompt


def test_create_preparation_without_runtime_fields_keeps_generic_provider_contract() -> (
    None
):
    state = _document_architecture_state()

    prepared = _build_create_proposal_for_architecture(state)
    baseline_schema = build_propose_flow_tool_schema(
        resource_catalog=prepared.resource_catalog
    )

    assert prepared.compile_context is not None
    assert prepared.compile_context.confirmed_runtime_input_requirements == ()
    assert prepared.proposal_tool_schema == baseline_schema
    prompt = prepared.llm_messages[0]["content"]
    assert isinstance(prompt, str)
    assert "Confirmed runtime inputs:" not in prompt


def test_named_report_sections_flow_from_request_preparation_into_lowering() -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content=(
                "Create a PDF report with these sections:\n"
                "- Résumé\n- Findings\n- Analysis\n- Recommendations"
            ),
        )
    ]
    state = _document_architecture_state()
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="pdf",
                output_mode="render_verbatim",
            )
        ],
        chosen_patterns=["document_to_structured_report"],
        required_capabilities=["input_document", "output_pdf"],
        report_disposition="both",
        committed_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        architecture_hash="b" * 64,
    )
    prepared = build_proposal_prepared(
        requirements_state=RequirementsState(),
        ui_language="en",
        slot_classification_metadata=None,
        conversation=conversation,
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[], available_kbs=[], prior_bindings=()
        ),
        flow=None,
        assistant_snapshots=None,
        plan_edit_context=None,
        prior_plan_for_revision=None,
        litellm_model="openai/gpt-5.4",
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
        attachment_file_count=0,
        current_turn_start=0,
    )
    context = prepared.compile_context
    assert context is not None
    assert context.requested_output_sections.sections == (
        "Résumé",
        "Findings",
        "Analysis",
        "Recommendations",
    )
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Source report",
            "plan_rationale": "Extract source evidence and render the report.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract source-grounded evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One record per source.",
                            "children": [
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Source summary.",
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Write report",
                    "instructions": "Write the requested report.",
                },
            ],
        }
    )
    spec = compile_create_intent_to_spec(intent, context=context)

    compose_refs = source_ref_bindings(spec.steps[-2].input_bindings)
    assert {
        (ref.field_path, ref.label)
        for ref in compose_refs
        if ref.label in context.requested_output_sections.sections
    } == {
        (("requested_section_1",), "Résumé"),
        (("requested_section_2",), "Findings"),
        (("requested_section_3",), "Analysis"),
        (("requested_section_4",), "Recommendations"),
    }


def test_example_document_headings_stay_guidance_and_never_become_topology() -> None:
    """An attached example shows how one earlier document looked.

    Its headings guide the model's structure and style, but they are not an
    output topology the plan owes the user: they must not become requested
    output sections, must not reach the prompt as a requirement, and must not
    be lowered into per-section report contracts.
    """

    file_id = uuid4()
    conversation = [
        ConversationMessage(
            role="user",
            content=(
                "The attached report is only a format example of how our "
                "reviews look. It is not a source and nothing from it may end "
                "up in my reviews."
            ),
        )
    ]
    state = _document_architecture_state()
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="pdf",
                output_mode="render_verbatim",
            )
        ],
        chosen_patterns=["document_to_structured_report"],
        required_capabilities=["input_document", "output_pdf"],
        report_disposition="both",
        committed_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        architecture_hash="b" * 64,
    )
    state.file_roles = [
        FileRoleEvidence(
            file_id=file_id,
            filename="example_report.docx",
            file_type=FileType.TEXT,
            has_readable_text=True,
            coverage="fully_seen",
            role="example_output",
            source="model",
            confidence="high",
            evidence=["quote:only a format example"],
            evidence_level="explicit",
        )
    ]
    state.example_output_constraints = ExampleOutputConstraintEvidence(
        source_file_ids=[file_id],
        source_coverage=[
            ExampleOutputSourceCoverage(file_id=file_id, coverage="fully_seen")
        ],
        headings=["Résumé", "Findings", "Analysis", "Recommendations"],
        confidence="high",
        citations=[
            ExampleOutputCitation(
                source_id="user_message:0",
                quote="only a format example of how our reviews look",
            )
        ],
    )
    prepared = build_proposal_prepared(
        requirements_state=RequirementsState(),
        ui_language="en",
        slot_classification_metadata=None,
        conversation=conversation,
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[], available_kbs=[], prior_bindings=()
        ),
        flow=None,
        assistant_snapshots=None,
        plan_edit_context=None,
        prior_plan_for_revision=None,
        litellm_model="openai/gpt-5.4",
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
        attachment_file_count=1,
        current_turn_start=0,
    )
    context = prepared.compile_context
    assert context is not None
    assert context.requested_output_sections.sections == ()

    prompt = prepared.llm_messages[0]["content"]
    assert isinstance(prompt, str)
    assert "Requested output sections:" not in prompt
    assert "Example-output evidence:" in prompt
    assert "- heading: Findings" in prompt
    assert "it is not a required output topology" in prompt

    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Source report",
            "plan_rationale": "Extract source evidence and render the report.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract source-grounded evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One record per source.",
                            "children": [
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Source summary.",
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Write report",
                    "instructions": "Write the requested report.",
                },
            ],
        }
    )
    spec = compile_create_intent_to_spec(intent, context=context)

    assert not [
        ref
        for step in spec.steps
        for ref in source_ref_bindings(step.input_bindings)
        if any(part.startswith("requested_section_") for part in ref.field_path)
    ]


def _server_output_prepared() -> ServerOutputPrepared:
    return ServerOutputPrepared(
        requirements_state=_requirements_state_unconfirmed(),
        ui_language="sv",
        slot_classification_metadata=None,
        server_decision=AskCanonicalQuestion(
            slot_name="terminal_output",
        ),
        discovery_analysis=DiscoveryAnalysis(issues=()),
        planning_state=PlanningState.empty(),
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
            prior_bindings=(),
        ),
        attachment_context=None,
        schema_candidates=(),
        schema_direction_pending=False,
        requirements_confirmation_required=True,
        flow_context=None,
    )


def _configure_minimal_send_message(
    planner: AIBuilderPlanner,
    monkeypatch: pytest.MonkeyPatch,
    prepared_request: ProposalPrepared | ServerOutputPrepared,
) -> None:
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        status=SessionStatus.CHATTING,
        planning_state_version=1,
    )
    planner.repo.load_planning_state.return_value = None
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(return_value=(None, None)),
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.prepare_planner_request",
        AsyncMock(return_value=prepared_request),
    )


async def _collect_send_message_events(
    planner: AIBuilderPlanner,
    *,
    session_id: UUID,
) -> list[dict[str, str]]:
    client_turn_id = uuid4()
    return [
        encode_ai_builder_stream_event(event)
        async for event in planner.send_message(
            session_id=session_id,
            client_turn_id=client_turn_id,
            request_fingerprint="a" * 64,
            request_snapshot={
                "client_turn_id": str(client_turn_id),
                "message": "Build a flow",
            },
            message="Build a flow",
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=None,
            max_input_tokens=100_000,
            max_output_tokens=4_096,
            budget_policy=_budget_policy(),
        )
    ]


def _force_fast_send_lock_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_send_lease."
        "_send_lock_refresh_interval_seconds",
        lambda: 0,
    )


def test_prepare_user_question_metadata_preserves_requirements_confirmation_and_ui_language() -> (
    None
):
    result = prepare_user_question_metadata(
        conversation=[],
        message="",
        question_answer={
            "kind": "requirements_confirmation",
            "requirements_confirmed": True,
            "requirements_version": "d" * 64,
            "ui_language": "en",
        },
    )

    assert result.is_requirements_confirmation is True
    assert result.metadata == {
        "requirements_confirmed": True,
        "requirements_version": "d" * 64,
        "ui_language": "en",
    }


@pytest.mark.asyncio
async def test_requirements_confirmation_reuses_latest_saved_step_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    step_id = uuid4()
    scoped_context = AIBuilderSavedFlowStepEditContext(flow_step_id=step_id)
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[
            ConversationMessage(
                role="user",
                content="Change this step",
                metadata={"edit_context": scoped_context.to_metadata()},
            ),
            ConversationMessage(role="assistant", content="Confirm requirements"),
        ],
        status=SessionStatus.CHATTING,
        planning_state_version=1,
        latest_plan_id=None,
    )
    resolve_context = AsyncMock(side_effect=RuntimeError("scope captured"))
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        resolve_context,
    )

    stream = planner.send_message(
        session_id=uuid4(),
        client_turn_id=_TEST_CLIENT_TURN_ID,
        request_fingerprint=_TEST_REQUEST_FINGERPRINT,
        request_snapshot=_test_request_snapshot("Confirm"),
        message="Confirm",
        question_answer={
            "kind": "requirements_confirmation",
            "requirements_confirmed": True,
            "requirements_version": "e" * 64,
        },
        completion_model_route=_route(),
        flow=cast(Any, SimpleNamespace(id=uuid4())),
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
    )

    with pytest.raises(RuntimeError, match="scope captured"):
        await anext(stream)

    assert resolve_context.await_args.kwargs["context"] == scoped_context


def test_prepare_user_question_metadata_ingests_structured_slot_answer() -> None:
    result = prepare_user_question_metadata(
        conversation=[],
        message="documents",
        question_answer={
            "kind": "structured_question_answer",
            "question_id": "primary_runtime_input",
            "selected_values": ["documents"],
        },
    )

    assert result.metadata == {
        "question_answer": {
            "question_id": "primary_runtime_input",
            "selected_values": ["documents"],
        }
    }
    state = build_planning_state_from_conversation(
        [
            ConversationMessage(
                role="user",
                content="documents",
                metadata=result.metadata,
            )
        ]
    )
    slot = state.resolved_slots["primary_runtime_input"]
    assert slot.value == "documents"
    assert slot.source == "structured_answer"


@pytest.mark.parametrize(
    ("question_answer", "reason"),
    [
        (
            {
                "kind": "structured_question_answer",
                "selected_values": ["documents"],
            },
            "missing_question_id",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "multi_file_strategy",
                "selected_values": ["same_run"],
            },
            "unsupported_question_id",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "output_style",
                "selected_values": ["formal"],
            },
            "unsupported_question_id",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "output_tone",
                "selected_values": ["formal"],
            },
            "unsupported_question_id",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "detail_level",
                "selected_values": ["detailed"],
            },
            "unsupported_question_id",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "primary_runtime_input",
            },
            "empty_question_answer",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "primary_runtime_input",
                "selected_values": ["banana"],
            },
            "unsupported_question_value",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "document_material_scope",
                "selected_values": ["single_document_case", "banana"],
            },
            "unsupported_question_value",
        ),
    ],
)
def test_prepare_user_question_metadata_rejects_uningestable_structured_answers(
    question_answer: dict[str, object],
    reason: str,
) -> None:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=[],
            message="",
            question_answer=question_answer,
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": reason}


@pytest.mark.parametrize(
    "question_id",
    ["flow_input_architecture"],
)
def test_prepare_user_question_metadata_keeps_supported_non_slot_questions(
    question_id: str,
) -> None:
    result = prepare_user_question_metadata(
        conversation=[],
        message="",
        question_answer={
            "kind": "structured_question_answer",
            "question_id": question_id,
            "selected_values": ["banana"],
        },
    )

    assert result.metadata == {
        "question_answer": {
            "question_id": question_id,
            "selected_values": ["banana"],
        }
    }


def test_prepare_user_question_metadata_accepts_schema_direction_answer() -> None:
    fingerprint = "a" * 64
    option_values = [
        f"input:{fingerprint}",
        f"output:{fingerprint}",
        "reference_only",
    ]

    prepared = prepare_user_question_metadata(
        conversation=[
            ConversationMessage(
                role="assistant",
                content="Assign the schema.",
                tool_calls=[
                    {
                        "id": "schema-direction",
                        "name": "ask_structured_question",
                        "arguments": {
                            "question_id": "schema_direction",
                            "question": "How should the schema be used?",
                            "options": [
                                {"id": value, "label": value, "value": value}
                                for value in option_values
                            ],
                            "selection_mode": "multi",
                            "allow_custom": False,
                            "requires_confirm": True,
                        },
                    }
                ],
            )
        ],
        message="",
        question_answer={
            "kind": "structured_question_answer",
            "question_id": "schema_direction",
            "selected_values": [f"output:{fingerprint}"],
        },
    )

    assert prepared.metadata == {
        "question_answer": {
            "question_id": "schema_direction",
            "selected_values": [f"output:{fingerprint}"],
        }
    }


def test_prepare_user_question_metadata_without_pending_question_is_neutral() -> None:
    prepared = prepare_user_question_metadata(
        conversation=[],
        message="Hello",
        question_answer=None,
    )

    assert prepared.metadata is None
    assert prepared.is_requirements_confirmation is False


@pytest.mark.asyncio
async def test_prepare_planner_request_skips_prompt_for_server_owned_action() -> None:
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    requirements_state = _requirements_state_unconfirmed()
    discovery_analysis = _discovery_analysis()

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(discovery_analysis, PlanningState.empty()),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ) as compute_budget,
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            max_input_tokens=100_000,
            max_output_tokens=4_096,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=4,
        )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, AskCanonicalQuestion)
    assert not hasattr(prepared, "llm_messages")
    compute_budget.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_reopen_command_dispatches_canonical_question_without_classifying() -> (
    None
):
    planner = _make_planner()
    state = _document_architecture_state()
    state.resolved_slots["document_material_scope"] = ResolvedSlot(
        name="document_material_scope",
        value="flexible_document_case",
        source="policy_default",
        confidence="medium",
        evidence=["policy_default:document_material_scope=flexible_document_case"],
    )
    disclosure = build_requirements_disclosure(state, ui_language="en")
    conversation = [
        ConversationMessage(
            role="assistant",
            content=disclosure.summary,
            metadata=requirements_summary_to_metadata(disclosure),
        ),
        ConversationMessage(
            role="user",
            content="",
            metadata={
                "reopen_question": {
                    "question_id": "document_material_scope",
                    "requirements_version": disclosure.requirements_version,
                }
            },
        ),
    ]

    with patch(
        "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
        "build_discovery_runtime_result",
        new_callable=AsyncMock,
        return_value=_runtime_result(_discovery_analysis(), state),
    ) as build_runtime:
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            persisted_planning_state=state,
        )

    assert isinstance(prepared, ServerOutputPrepared)
    assert prepared.server_decision == AskCanonicalQuestion(
        slot_name="document_material_scope",
        reopen=True,
    )
    assert build_runtime.await_args.kwargs["allow_classification"] is False
    planner.litellm_client.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_planner_request_asks_when_attachment_schema_direction_is_unresolved() -> (
    None
):
    planner = _make_planner()
    provider_callback = AsyncMock()

    prepared = await _prepare_planner_request_for_test(
        planner,
        conversation=[ConversationMessage(role="user", content="Build a flow")],
        completion_model_route=_route(),
        attachment_files=[
            _make_file(
                '{"type":"object","properties":{"decision":{"type":"string"}}}',
                name="first.schema.json",
                mimetype="application/json",
            ),
            _make_file(
                '{"type":"object","properties":{"count":{"type":"integer"}}}',
                name="second.schema.json",
                mimetype="application/json",
            ),
        ],
        before_provider_call=provider_callback,
        max_input_tokens=100_000,
    )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, AskCanonicalQuestion)
    assert prepared.server_decision.slot_name == "schema_direction"
    assert prepared.server_decision.question is not None
    assert prepared.server_decision.question.question_data.question_id == (
        "schema_direction"
    )
    assert len(prepared.server_decision.question.question_data.options) == 5
    provider_callback.assert_awaited_once()


def test_preprovider_gate_promotes_structural_schema_refusal() -> None:
    attachment = _make_file(
        name="expected.schema.json",
        text='{"description":"' + ("x" * SCHEMA_MAX_JSON_BYTES) + '"}',
        mimetype="application/schema+json",
    )
    attachment_context = build_ai_builder_attachment_context([attachment])
    assert attachment_context is not None

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        validate_preprovider_schema_gate(
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Use the attachment as reference material.",
                )
            ],
            attachment_context=attachment_context,
        )

    assert exc_info.value.code is AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED
    assert exc_info.value.context["file_id"] == str(attachment.id)


@pytest.mark.asyncio
async def test_prepare_planner_request_rejects_canonical_schema_expansion_before_provider() -> (
    None
):
    raw_json = (
        '{"type":"object","allOf":['
        + ",".join('{"default":1e9}' for _ in range(5_500))
        + "]}"
    )
    attachment = _make_file(
        name="expanded.schema.json",
        text=raw_json,
        mimetype="application/schema+json",
    )
    provider_callback = AsyncMock()

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        await _prepare_planner_request_for_test(
            _make_planner(),
            conversation=[ConversationMessage(role="user", content="Build a flow")],
            completion_model_route=_route(),
            attachment_files=[attachment],
            before_provider_call=provider_callback,
        )

    assert exc_info.value.code is AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED
    assert exc_info.value.context["reason"] == "canonical_bytes"
    assert exc_info.value.context["file_id"] == str(attachment.id)
    provider_callback.assert_not_awaited()


def test_preprovider_gate_keeps_unclassified_large_json_text_nonblocking() -> None:
    attachment = _make_file(
        name="large-example.txt",
        text='{"records":"' + ("x" * SCHEMA_MAX_JSON_BYTES) + '"}',
        mimetype="text/plain",
    )
    attachment_context = build_ai_builder_attachment_context([attachment])
    assert attachment_context is not None

    result = validate_preprovider_schema_gate(
        conversation=[
            ConversationMessage(
                role="user",
                content="Use the attachment as general reference material.",
            )
        ],
        attachment_context=attachment_context,
    )

    assert result == ()


@pytest.mark.asyncio
async def test_prepare_planner_request_reuses_checked_empty_attachment_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    rebuild_context = MagicMock(
        side_effect=AssertionError("checked attachment context must not be rebuilt")
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
        "build_ai_builder_attachment_context_for_model",
        rebuild_context,
    )

    prepared = await _prepare_planner_request_for_test(
        planner,
        conversation=[ConversationMessage(role="user", content="Build a flow")],
        completion_model_route=_route(),
        attachment_files=[],
        prepared_attachment_context=None,
        prepared_schema_candidates=(),
        max_input_tokens=100_000,
    )

    assert isinstance(prepared, ServerOutputPrepared)
    rebuild_context.assert_not_called()


@pytest.mark.asyncio
async def test_send_message_builds_attachment_context_once_before_request_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        status=SessionStatus.CHATTING,
        planning_state_version=1,
    )
    planner.repo.load_planning_state.return_value = None
    attachments = [
        _make_file(
            '{"type":"object","properties":{"decision":{"type":"string"}}}',
            name="first.schema.json",
            mimetype="application/json",
        ),
        _make_file(
            '{"type":"object","properties":{"count":{"type":"integer"}}}',
            name="second.schema.json",
            mimetype="application/json",
        ),
    ]
    prepared_context = build_ai_builder_attachment_context(attachments)
    build_context = MagicMock(return_value=prepared_context)
    captured_request: PlannerRequestPreparationInput | None = None

    async def stop_after_request(
        request: PlannerRequestPreparationInput,
    ) -> ServerOutputPrepared:
        nonlocal captured_request
        captured_request = request
        raise RuntimeError("request captured")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(return_value=(None, None)),
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner."
        "build_ai_builder_attachment_context_for_model",
        build_context,
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.prepare_planner_request",
        stop_after_request,
    )
    stream = planner.send_message(
        session_id=uuid4(),
        client_turn_id=_TEST_CLIENT_TURN_ID,
        request_fingerprint=_TEST_REQUEST_FINGERPRINT,
        request_snapshot=_test_request_snapshot("Build a flow"),
        message="Build a flow",
        completion_model_route=_route(),
        attachment_files=attachments,
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
    )

    with pytest.raises(RuntimeError, match="request captured"):
        await anext(stream)

    build_context.assert_called_once_with(
        attachments,
        policy=AIBuilderAttachmentContextPolicy(),
        model_name="openai/gpt-5.4",
        max_input_tokens=4096,
        max_output_tokens=1024,
        safety_buffer_tokens=128,
        minimum_conversation_tokens=256,
    )
    assert captured_request is not None
    assert captured_request.prepared_attachment_context is prepared_context
    assert captured_request.prepared_schema_candidates is not None
    assert len(captured_request.prepared_schema_candidates) == 2
    planner.repo.mark_session_turn_processing.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_rejects_schema_overflow_before_accepting_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session = SimpleNamespace(
        conversation=[],
        status=SessionStatus.CHATTING,
        planning_state_version=1,
    )
    planner.repo.get_session.return_value = session
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(return_value=(None, None)),
    )
    message = "\n".join(
        "```json\n"
        + json.dumps(
            {
                "type": "object",
                "properties": {f"field_{index}": {"type": "string"}},
            }
        )
        + "\n```"
        for index in range(101)
    )
    stream = planner.send_message(
        session_id=uuid4(),
        client_turn_id=_TEST_CLIENT_TURN_ID,
        request_fingerprint=_TEST_REQUEST_FINGERPRINT,
        request_snapshot=_test_request_snapshot(message),
        message=message,
        completion_model_route=_route(),
        attachment_files=[],
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
    )

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        await anext(stream)

    assert exc_info.value.code is AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED
    planner.repo.accept_session_turn.assert_not_awaited()
    assert session.conversation == []


@pytest.mark.asyncio
async def test_prepare_planner_request_requires_fresh_confirmation_after_attachment_change() -> (
    None
):
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a report flow")]
    discovery_analysis = _discovery_analysis()
    state = _document_architecture_state()
    state.file_roles = [
        FileRoleEvidence(
            file_id=UUID(int=index + 1),
            filename=f"reference-{index}.pdf",
            file_type="document",
            mimetype="application/pdf",
            has_readable_text=True,
            coverage="fully_seen",
            role="context_only",
            source="heuristic",
            confidence="low",
        )
        for index in range(12)
    ]
    prior_confirmation = resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        requirements_disclosure=build_requirements_disclosure(state, ui_language="en"),
        confirmed_requirements_version=None,
        ui_language="en",
    ).decision
    assert isinstance(prior_confirmation, ConfirmRequirements)
    confirmed_version = prior_confirmation.payload.requirements_version
    requirements_state = RequirementsState(
        latest_summary=prior_confirmation.payload,
        latest_version=confirmed_version,
        confirmed_version=confirmed_version,
    )
    state.file_roles[11] = state.file_roles[11].model_copy(
        update={
            "coverage": "excerpt_truncated",
            "role": "reference_material",
            "source": "model",
            "confidence": "high",
        }
    )
    provider_callback = AsyncMock()

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(discovery_analysis, state),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_plan_proposal_system_prompt",
            return_value="proposal prompt",
        ) as build_proposal_prompt,
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build a report flow"}],
        ),
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            before_provider_call=provider_callback,
        )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, ConfirmRequirements)
    attachment_assumptions = [
        assumption
        for assumption in prepared.server_decision.payload.assumptions
        if assumption.startswith("Attachment evidence — ")
    ]
    assert len(attachment_assumptions) == 12
    assert any(
        "Reference material" in assumption for assumption in attachment_assumptions
    )
    build_proposal_prompt.assert_not_called()
    provider_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_action_policy_overrides_stale_discovery_question() -> None:
    planner = _make_planner()
    conversation = [
        ConversationMessage(
            role="user",
            content=(
                "Skapa ett flöde som tar emot en kort text från användaren och "
                "sammanfattar den i tre tydliga punkter."
            ),
        )
    ]
    requirements_state = _requirements_state_unconfirmed()
    discovery_analysis = _discovery_analysis(
        mvs_met=False,
        selected_question_ids=("primary_runtime_input",),
    )
    planning_state = build_planning_state_from_conversation(conversation)
    planning_state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="text",
            source="requirements_summary",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="requirements_summary",
            confidence="high",
        ),
    }

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(
                discovery_analysis,
                planning_state,
            ),
        ),
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            max_input_tokens=100_000,
            max_output_tokens=4_096,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=4,
        )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, CommitArchitecture)
    assert not hasattr(prepared, "llm_messages")


@pytest.mark.asyncio
async def test_prepare_planner_request_asks_for_model_medium_output_before_commit() -> (
    None
):
    planner = _make_planner()
    conversation = [
        ConversationMessage(
            role="user",
            content="Jag vill bygga ett transkriberingsflöde",
            metadata={"ui_language": "sv"},
        )
    ]
    requirements_state = _requirements_state_unconfirmed()
    discovery_analysis = _discovery_analysis()
    planning_state = PlanningState.empty()
    planning_state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="requirements_summary",
            evidence=["requirements_summary:primary_runtime_input"],
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="model",
            evidence=[
                "model:terminal_output:" + "a" * 64,
                "quote:user_message:test:structured_text",
            ],
            confidence="medium",
            evidence_level="inferred",
        ),
    }
    assert planning_state.resolved_slots["terminal_output"].source == "model"
    assert planning_state.resolved_slots["terminal_output"].confidence == "medium"

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(
                discovery_analysis,
                planning_state,
            ),
        ),
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=4,
        )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, AskCanonicalQuestion)
    assert prepared.server_decision.slot_name == "terminal_output"
    assert not hasattr(prepared, "llm_messages")


@pytest.mark.asyncio
async def test_prepare_planner_request_passes_attachment_context_into_discovery_before_proposal() -> (
    None
):
    planner = _make_planner()
    conversation = [
        ConversationMessage(
            role="user",
            content="Jag vill bygga ett transkriberingsflöde.",
            metadata={"ui_language": "sv"},
        )
    ]
    requirements_state = _requirements_state_unconfirmed()
    discovery_analysis = _discovery_analysis()
    planning_state = PlanningState.empty()
    planning_state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="heuristic",
            evidence=["heuristic:role-aware freeform analysis"],
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="model",
            evidence=[
                "model:terminal_output:" + "a" * 64,
                "quote:user_message:test:structured_text",
            ],
            confidence="medium",
            evidence_level="inferred",
        ),
    }
    attachment_context = AIBuilderAttachmentContext(
        context=None,
        evidence=(),
        included_file_ids=[],
        total_chars=0,
        truncated=False,
        schema_discovery=AIBuilderAttachmentSchemaDiscovery(candidates=()),
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
            "build_ai_builder_attachment_context_for_model",
            return_value=attachment_context,
        ) as build_attachment_context,
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(
                discovery_analysis,
                planning_state,
            ),
        ) as build_discovery_runtime_result,
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=[_make_file()],
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=4,
        )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, AskCanonicalQuestion)
    build_attachment_context.assert_called_once()
    assert (
        build_discovery_runtime_result.call_args.kwargs["attachment_context"]
        is attachment_context
    )
    assert build_discovery_runtime_result.call_args.kwargs["max_output_tokens"] == 1024


@pytest.mark.asyncio
async def test_prepare_planner_request_passes_attachment_context_into_proposal_prompt() -> (
    None
):
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build from this file")]
    discovery_analysis = _discovery_analysis()
    state = _document_architecture_state()
    requirements_state = _requirements_state_confirmed_for(state)
    requirements = RequirementsSummaryPayload(
        requirements_version="0" * 64,
        summary="Build from this file.",
        key_decisions=[],
        input_description="Attachment",
        output_description="Summary",
        assumptions=[],
        manual_setup_notes=[],
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(discovery_analysis, state),
        ) as build_discovery_runtime_result,
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.latest_confirmed_requirements",
            return_value=requirements,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
            "build_ai_builder_attachment_context_for_model",
            return_value=AIBuilderAttachmentContext(
                context="attachment context",
                evidence=(),
                included_file_ids=[],
                total_chars=18,
                truncated=False,
                schema_discovery=AIBuilderAttachmentSchemaDiscovery(candidates=()),
            ),
        ) as build_attachment_context,
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_plan_proposal_system_prompt",
            return_value="proposal prompt",
        ) as build_plan_proposal_system_prompt,
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build from this file"}],
        ),
    ):
        await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=[_make_file()],
            # The create tool schema alone costs thousands of tokens, so a
            # window that cannot hold it leaves no room for attachment text.
            max_input_tokens=32_768,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=0,
        )

    build_attachment_context.assert_called_once()
    assert (
        build_discovery_runtime_result.call_args.kwargs["attachment_context"]
        is build_attachment_context.return_value
    )
    assert (
        build_plan_proposal_system_prompt.call_args.kwargs["attachment_context"]
        == "attachment context"
    )


@pytest.mark.asyncio
async def test_prepare_planner_request_uses_proposal_task_after_confirmation() -> None:
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a report flow")]
    discovery_analysis = _discovery_analysis()
    state = _document_architecture_state()
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="case_id",
                label="Case ID",
                required=True,
                provenance="user_confirmed",
            ),
            purpose="interpret_input",
            structured_answer_message_id="message-runtime-fields",
        )
    ]
    requirements_state = _requirements_state_confirmed_for(state)
    requirements = RequirementsSummaryPayload(
        requirements_version="0" * 64,
        summary="Build a report flow.",
        key_decisions=[
            KeyDecisionPayload(topic="Input", decision="Uploaded documents")
        ],
        input_description="Documents",
        output_description="Report",
        assumptions=[],
        manual_setup_notes=[],
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(discovery_analysis, state),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.latest_confirmed_requirements",
            return_value=requirements,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build a report flow"}],
        ),
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=[],
            max_input_tokens=100_000,
            max_output_tokens=4_096,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=4,
        )

    assert isinstance(prepared, ProposalPrepared)
    assert prepared.llm_messages[0]["role"] == "system"
    assert "Call exactly one `propose_flow` tool" in prepared.llm_messages[0]["content"]
    rendered_requirement = render_confirmed_runtime_input_requirements(
        (
            ConfirmedRuntimeInputRequirement(
                name="case_id",
                purpose="interpret_input",
            ),
        )
    )
    assert rendered_requirement in prepared.llm_messages[0]["content"]
    output_fields_description = prepared.proposal_tool_schema["function"]["parameters"][
        "properties"
    ]["steps"]["items"]["properties"]["output_fields"]["description"]
    assert rendered_requirement in output_fields_description
    assert prepared.compile_context is not None
    assert [
        field.value.variable_name
        for field in prepared.compile_context.runtime_input_fields
    ] == ["case_id"]


def test_real_proposal_boundary_fits_attachments_and_protects_current_turn() -> None:
    model_name = "gpt-4o-mini"
    current_turn = ConversationMessage(
        role="user",
        content="Build the confirmed reporting flow from my attached source.",
    )
    history = ConversationMessage(role="user", content="old context " * 5_000)
    attachment_text = "ATTACHMENT-EVIDENCE " * 5_000
    attachment_context = build_ai_builder_attachment_context(
        [_make_file(attachment_text)]
    )
    assert attachment_context is not None
    catalog = build_ai_builder_resource_catalog(
        available_models=None,
        available_kbs=None,
    )
    policy = AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=64,
        minimum_conversation_budget_tokens=128,
    )
    common = {
        "requirements_state": RequirementsState(),
        "ui_language": "en",
        "slot_classification_metadata": None,
        "planning_state": PlanningState.empty(),
        "flow_context": None,
        "is_edit_mode": False,
        "resource_catalog": catalog,
        "flow": None,
        "assistant_snapshots": None,
        "plan_edit_context": None,
        "prior_plan_for_revision": None,
        "litellm_model": model_name,
        "max_output_tokens": 1_024,
        "budget_policy": policy,
        "attachment_file_count": 1,
    }
    baseline = build_proposal_prepared(
        **common,
        conversation=[current_turn],
        attachment_context=None,
        max_input_tokens=100_000,
        current_turn_start=0,
    )
    tool_schema = baseline.proposal_tool_schema
    tool_schema_for_budget = cast(dict[str, Any], tool_schema)
    irreducible_request_tokens = (
        count_message_tokens(baseline.llm_messages, model_name)
        + count_tool_tokens([tool_schema_for_budget], model_name)
        + 1_024
        + policy.conversation_safety_buffer_tokens
    )
    tight_context_window = irreducible_request_tokens + 300

    prepared = build_proposal_prepared(
        **common,
        conversation=[history, current_turn],
        attachment_context=attachment_context,
        max_input_tokens=tight_context_window,
        current_turn_start=1,
    )
    assert prepared.proposal_tool_schema == tool_schema
    prepared_tool_schema_for_budget = cast(
        dict[str, Any], prepared.proposal_tool_schema
    )

    assert prepared.request_budget is not None
    fitted_groups, resolved_budget = fit_proposal_request_budget(
        budget=prepared.request_budget,
        message_groups=prepared.message_groups,
        tool_schemas=[prepared_tool_schema_for_budget],
        model_name=model_name,
    )
    fitted_messages = flatten_proposal_message_groups(fitted_groups)
    final_request_tokens = (
        count_message_tokens(fitted_messages, model_name)
        + count_tool_tokens([prepared_tool_schema_for_budget], model_name)
        + resolved_budget.resolved_output_tokens
        + resolved_budget.safety_buffer_tokens
    )
    assert final_request_tokens <= tight_context_window
    assert current_turn.content in [message["content"] for message in fitted_messages]
    system_content = fitted_messages[0]["content"]
    assert isinstance(system_content, str)
    assert attachment_text not in system_content
    assert "ATTACHMENT-EVIDENCE" in system_content

    assert baseline.request_budget is not None
    impossible_budget = replace(
        baseline.request_budget,
        context_window_tokens=irreducible_request_tokens - 1,
    )
    with pytest.raises(AIBuilderKnownProviderRejectionException):
        fit_proposal_request_budget(
            budget=impossible_budget,
            message_groups=baseline.message_groups,
            tool_schemas=[tool_schema_for_budget],
            model_name=model_name,
        )


def _litellm_function_estimate(tool_schema: dict[str, Any], model_name: str) -> int:
    """What the tool schema cost before the reserve counted its nesting.

    Reproduced here rather than kept in production so the two consumer tests
    below can show the request the old charge would have admitted.
    """
    empty = [{"role": "user", "content": ""}]
    return litellm.token_counter(
        model=model_name, messages=empty, tools=[tool_schema]
    ) - litellm.token_counter(model=model_name, messages=empty)


def test_proposal_attachment_fitting_reserves_the_whole_create_schema() -> None:
    # The Builder expands attachment text into whatever room the tool reserve
    # says is left, so a schema charged at a fraction of its cost let the
    # attachment overrun the window. Size the window so it fits the old charge
    # and not the real schema: the attachment text must now be excluded.
    model_name = "gpt-4o-mini"
    current_turn = ConversationMessage(
        role="user", content="Build the confirmed reporting flow."
    )
    attachment_text = "ATTACHMENT-EVIDENCE " * 2_000
    attachment_context = build_ai_builder_attachment_context(
        [_make_file(attachment_text)]
    )
    assert attachment_context is not None
    policy = AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=128,
        minimum_conversation_budget_tokens=256,
    )
    common = {
        "requirements_state": RequirementsState(),
        "ui_language": "en",
        "slot_classification_metadata": None,
        "planning_state": PlanningState.empty(),
        "flow_context": None,
        "is_edit_mode": False,
        "resource_catalog": build_ai_builder_resource_catalog(
            available_models=None, available_kbs=None
        ),
        "flow": None,
        "assistant_snapshots": None,
        "plan_edit_context": None,
        "prior_plan_for_revision": None,
        "litellm_model": model_name,
        "max_output_tokens": 256,
        "budget_policy": policy,
        "attachment_file_count": 1,
    }
    baseline = build_proposal_prepared(
        **common,
        conversation=[current_turn],
        attachment_context=None,
        max_input_tokens=100_000,
        current_turn_start=0,
    )
    tool_schema = cast(dict[str, Any], baseline.proposal_tool_schema)
    old_charge = _litellm_function_estimate(tool_schema, model_name)
    true_reserve = count_tool_tokens([tool_schema], model_name)
    assert true_reserve > old_charge

    system_prompt_tokens = count_message_tokens(baseline.llm_messages[:1], model_name)
    fixed = (
        system_prompt_tokens
        + 256
        + policy.conversation_safety_buffer_tokens
        + policy.minimum_conversation_budget_tokens
    )
    prepared = build_proposal_prepared(
        **common,
        conversation=[current_turn],
        # Room for the schema as it used to be charged, but not as it costs.
        max_input_tokens=fixed + old_charge + 64,
        attachment_context=attachment_context,
        current_turn_start=0,
    )

    system_content = prepared.llm_messages[0]["content"]
    assert isinstance(system_content, str)
    assert "ATTACHMENT-EVIDENCE" not in system_content


def test_proposal_boundary_rejects_confirmed_primary_input_shadow() -> None:
    state = PlanningState.empty()
    state.architecture_commit = _architecture_commit()
    state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
        name="primary_runtime_input",
        value="text",
        source="structured_answer",
        confidence="high",
    )
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="text",
                label="Text",
                provenance="user_confirmed",
            ),
            purpose="interpret_input",
            structured_answer_message_id="message-runtime-fields",
        )
    ]

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        build_proposal_prepared(
            requirements_state=RequirementsState(),
            ui_language="en",
            slot_classification_metadata=None,
            conversation=[ConversationMessage(role="user", content="Summarize text")],
            planning_state=state,
            attachment_context=None,
            flow_context=None,
            is_edit_mode=False,
            resource_catalog=build_ai_builder_resource_catalog(
                available_models=None,
                available_kbs=None,
            ),
            flow=None,
            assistant_snapshots=None,
            plan_edit_context=None,
            prior_plan_for_revision=None,
            litellm_model="gpt-4o-mini",
            max_input_tokens=4096,
            max_output_tokens=256,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            attachment_file_count=0,
            current_turn_start=0,
        )

    assert exc_info.value.code is AIBuilderErrorCode.ARCHITECTURE_MATERIALIZATION_FAILED
    assert exc_info.value.context == {
        "reason": "confirmed_form_field_incompatible",
        "field_names": ["text"],
    }


def test_proposal_boundary_defaults_missing_runtime_type_to_text() -> None:
    state = PlanningState.empty()
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="text",
                label="Text",
                provenance="user_confirmed",
            ),
            purpose="interpret_input",
            structured_answer_message_id="message-runtime-fields",
        )
    ]

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        build_proposal_prepared(
            requirements_state=RequirementsState(),
            ui_language="en",
            slot_classification_metadata=None,
            conversation=[ConversationMessage(role="user", content="Summarize text")],
            planning_state=state,
            attachment_context=None,
            flow_context=None,
            is_edit_mode=False,
            resource_catalog=build_ai_builder_resource_catalog(
                available_models=None,
                available_kbs=None,
            ),
            flow=None,
            assistant_snapshots=None,
            plan_edit_context=None,
            prior_plan_for_revision=None,
            litellm_model="gpt-4o-mini",
            max_input_tokens=4096,
            max_output_tokens=256,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            attachment_file_count=0,
            current_turn_start=0,
        )

    assert exc_info.value.context == {
        "reason": "confirmed_form_field_incompatible",
        "field_names": ["text"],
    }


@pytest.mark.asyncio
async def test_prepare_planner_request_logs_prompt_metrics() -> None:
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a report flow")]
    discovery_analysis = _discovery_analysis()
    state = _document_architecture_state()
    requirements_state = _requirements_state_confirmed_for(state)
    requirements = RequirementsSummaryPayload(
        requirements_version="0" * 64,
        summary="Build a report flow.",
        key_decisions=[],
        input_description="Documents",
        output_description="Report",
        assumptions=[],
        manual_setup_notes=[],
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(discovery_analysis, state),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.latest_confirmed_requirements",
            return_value=requirements,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build a flow"}],
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.logger.info"
        ) as logger_info,
    ):
        await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=None,
            max_input_tokens=100_000,
            max_output_tokens=4_096,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=0,
        )

    assert any(
        call.args and call.args[0] == "AI Builder plan proposal prompt metrics"
        for call in logger_info.call_args_list
    )


@pytest.mark.asyncio
async def test_send_message_rejects_when_another_send_is_already_in_progress() -> None:
    planner = _make_planner()
    planner.repo.accept_session_turn.side_effect = AIBuilderBadRequestException(
        "Another AI Builder message is already being processed for this session.",
        code=AIBuilderErrorCode.SESSION_MESSAGE_IN_PROGRESS,
    )
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        planning_state_version=0,
        status="chatting",
    )

    with pytest.raises(BadRequestException, match="already being processed"):
        async for _ in planner.send_message(
            session_id=uuid4(),
            client_turn_id=_TEST_CLIENT_TURN_ID,
            request_fingerprint=_TEST_REQUEST_FINGERPRINT,
            request_snapshot=_test_request_snapshot("Build a flow"),
            message="Build a flow",
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
        ):
            pass


@pytest.mark.asyncio
async def test_send_message_converts_dispatch_lease_lost_exception_to_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    _configure_minimal_send_message(planner, monkeypatch, _server_output_prepared())

    async def fail_with_lease_lost(
        _: ServerDecisionDispatchRequest,
    ) -> ServerDecisionDispatchResult:
        raise AIBuilderBadRequestException(
            "lease lost",
            code=AIBuilderErrorCode.SESSION_SEND_LEASE_LOST,
        )

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        fail_with_lease_lost,
    )

    events = await _collect_send_message_events(planner, session_id=session_id)

    assert [event["event"] for event in events] == ["error", "done"]
    assert json.loads(events[0]["data"])["code"] == "session_send_lease_lost"
    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_commits_planning_state_payload_too_large_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    _configure_minimal_send_message(planner, monkeypatch, _server_output_prepared())

    async def reject_oversized_state(
        _: ServerDecisionDispatchRequest,
    ) -> ServerDecisionDispatchResult:
        raise PlanningStatePayloadTooLargeError(
            byte_size=131_073,
            cap_bytes=131_072,
        )

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        reject_oversized_state,
    )

    events = await _collect_send_message_events(planner, session_id=session_id)

    assert [event["event"] for event in events] == ["error", "done"]
    error = json.loads(events[0]["data"])
    assert error["code"] == "planning_state_payload_too_large"
    assert error["category"] == "bad_request"
    assert error["phase"] == "planner"
    assert error["details"] == {
        "payload_bytes": 131_073,
        "payload_cap_bytes": 131_072,
    }
    planner.repo.complete_session_turn.assert_awaited_once()
    assert (
        planner.repo.complete_session_turn.await_args.kwargs["error"].model_dump(
            mode="json",
            exclude_none=True,
        )
        == error
    )
    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_emits_lease_lost_when_refresh_fails_during_server_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    refresh_attempted = asyncio.Event()
    _configure_minimal_send_message(planner, monkeypatch, _server_output_prepared())
    _force_fast_send_lock_refresh(monkeypatch)

    async def refresh_fails(**_: object) -> bool:
        refresh_attempted.set()
        return False

    async def wait_for_refresh_loss(
        _: ServerDecisionDispatchRequest,
    ) -> ServerDecisionDispatchResult:
        await asyncio.wait_for(refresh_attempted.wait(), timeout=12)
        return ServerDecisionDispatchResult(
            action_kind="ask_question",
            events=(build_text_event("server result"),),
            new_planning_state_version=2,
        )

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_send_lease._refresh_session_send_lease",
        refresh_fails,
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        wait_for_refresh_loss,
    )

    events = await _collect_send_message_events(planner, session_id=session_id)

    assert [event["event"] for event in events] == ["error", "done"]
    assert json.loads(events[0]["data"])["code"] == "session_send_lease_lost"
    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_continues_to_proposal_after_confirmed_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    continuation_state = PlanningState.empty()
    _configure_minimal_send_message(
        planner,
        monkeypatch,
        replace(
            _server_output_prepared(),
            requirements_state=_requirements_state_confirmed(),
            server_decision=ReviseArchitecture(
                architecture_commit=_architecture_commit()
            ),
            planning_state=continuation_state,
        ),
    )

    async def fake_dispatch(
        request: ServerDecisionDispatchRequest,
    ) -> ServerDecisionDispatchResult:
        assert isinstance(request.decision, ReviseArchitecture)
        return ServerDecisionDispatchResult(
            action_kind="revise_architecture",
            events=(build_status_event(AIBuilderStatus.ARCHITECTURE_REVISED),),
            new_planning_state_version=9,
            proposal_continuation=ServerDecisionProposalContinuation(
                planning_state=continuation_state,
                new_messages_start=0,
            ),
        )

    captured: dict[str, object] = {}

    async def fake_propose_plan(
        **kwargs: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        captured.update(kwargs)
        yield build_text_event("proposal result")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        fake_dispatch,
    )
    monkeypatch.setattr(
        planner._proposal_submission,
        "run_active_submission_attempt",
        fake_propose_plan,
    )

    events = await _collect_send_message_events(planner, session_id=session_id)

    assert [event["event"] for event in events] == ["status", "text", "done"]
    assert json.loads(events[0]["data"])["status"] == "architecture_revised"
    assert events[1]["data"] == '{"text":"proposal result"}'
    assert captured["new_messages_start"] == 0
    message_groups = cast(tuple[object, ...], captured["message_groups"])
    current_turn_groups = [
        group for group in message_groups if getattr(group, "kind") == "current_turn"
    ]
    assert len(current_turn_groups) == 1
    assert getattr(current_turn_groups[0], "protected") is True
    assert captured["planning_state"] is continuation_state
    turn = cast(object, captured["turn"])
    assert getattr(turn, "base_planning_state_version") == 9
    planner.repo.complete_session_turn.assert_awaited_once()
    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_server_continuation_commits_the_exact_proposal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    continuation_state = PlanningState.empty()
    _configure_minimal_send_message(
        planner,
        monkeypatch,
        replace(
            _server_output_prepared(),
            requirements_state=_requirements_state_confirmed(),
            server_decision=ReviseArchitecture(
                architecture_commit=_architecture_commit()
            ),
            planning_state=continuation_state,
        ),
    )

    async def fake_dispatch(
        _: ServerDecisionDispatchRequest,
    ) -> ServerDecisionDispatchResult:
        return ServerDecisionDispatchResult(
            action_kind="revise_architecture",
            events=(build_status_event(AIBuilderStatus.ARCHITECTURE_REVISED),),
            new_planning_state_version=9,
            proposal_continuation=ServerDecisionProposalContinuation(
                planning_state=continuation_state,
                new_messages_start=1,
            ),
        )

    committed_error_event = build_ai_builder_error_event(
        message="Invalid proposal",
        code=AIBuilderErrorCode.PLANNER_REJECTED,
        request_id="proposal-error-request",
        diagnostic_context={"outcome_kind": "server_confirm_requirements"},
        details={"quality_failure_codes": "missing_source_refs"},
    )

    async def fake_propose_plan(
        **_: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        yield committed_error_event

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        fake_dispatch,
    )
    monkeypatch.setattr(
        planner._proposal_submission,
        "run_active_submission_attempt",
        fake_propose_plan,
    )

    events = await _collect_send_message_events(planner, session_id=uuid4())

    assert [event["event"] for event in events] == ["status", "error", "done"]
    planner.repo.complete_session_turn.assert_awaited_once()
    assert (
        planner.repo.complete_session_turn.await_args.kwargs["error"]
        == committed_error_event.data
    )


@pytest.mark.asyncio
async def test_send_message_proposal_branch_ignores_in_process_lease_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    refresh_attempted = asyncio.Event()
    _force_fast_send_lock_refresh(monkeypatch)
    _configure_minimal_send_message(
        planner,
        monkeypatch,
        ProposalPrepared(
            requirements_state=_requirements_state_confirmed(),
            ui_language="sv",
            message_groups=(
                ProposalMessageGroup(
                    messages=({"role": "system", "content": "proposal"},),
                    kind="system",
                    protected=True,
                ),
            ),
            system_prompt_hash="proposal-hash",
            prior_spec_for_revision=None,
            slot_classification_metadata=None,
            plan_edit_context=None,
            planning_state=PlanningState.empty(),
            compile_context=None,
            proposal_tool_schema=_empty_proposal_tool_schema(),
            request_budget=_proposal_budget(),
            resource_catalog=build_ai_builder_resource_catalog(
                available_models=[],
                available_kbs=[],
                prior_bindings=(),
            ),
        ),
    )

    async def refresh_fails(**_: object) -> bool:
        refresh_attempted.set()
        return False

    async def fake_propose_plan(
        **_: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        await asyncio.wait_for(refresh_attempted.wait(), timeout=12)
        yield build_text_event("proposal result")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_send_lease._refresh_session_send_lease",
        refresh_fails,
    )
    monkeypatch.setattr(
        planner._proposal_submission,
        "run_active_submission_attempt",
        fake_propose_plan,
    )

    events = await _collect_send_message_events(planner, session_id=session_id)

    assert [event["event"] for event in events] == ["text", "done"]
    assert events[0]["data"] == '{"text":"proposal result"}'
    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_releases_pre_provider_dispatch_failure_for_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    _configure_minimal_send_message(planner, monkeypatch, _server_output_prepared())

    async def fail_dispatch(
        _: ServerDecisionDispatchRequest,
    ) -> ServerDecisionDispatchResult:
        raise RuntimeError("dispatch failed")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        fail_dispatch,
    )

    with pytest.raises(RuntimeError, match="dispatch failed"):
        await _collect_send_message_events(planner, session_id=session_id)

    planner.repo.mark_session_turn_processing.assert_not_awaited()
    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_refuses_unsupported_architecture_without_provider_or_planning_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    persisted_state = PlanningState.empty()
    persisted_snapshot = persisted_state.model_dump(mode="json")
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[
            ConversationMessage(
                role="user",
                content="json",
                metadata={
                    "question_answer": {
                        "question_id": "primary_runtime_input",
                        "selected_values": ["json"],
                    }
                },
            )
        ],
        status=SessionStatus.CHATTING,
        planning_state_version=4,
        latest_plan_id=None,
    )
    planner.repo.load_planning_state.return_value = persisted_state
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(return_value=(None, None)),
    )

    events = [
        encode_ai_builder_stream_event(event)
        async for event in planner.send_message(
            session_id=session_id,
            client_turn_id=_TEST_CLIENT_TURN_ID,
            request_fingerprint=_TEST_REQUEST_FINGERPRINT,
            request_snapshot=_test_request_snapshot("Strukturerat textresultat"),
            message="Strukturerat textresultat",
            question_answer={
                "kind": "structured_question_answer",
                "question_id": "terminal_output",
                "selected_values": ["structured_text"],
            },
            ui_language="sv",
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=_budget_policy(),
        )
    ]

    assert [event["event"] for event in events] == ["error", "done"]
    error_payload = json.loads(events[0]["data"])
    assert error_payload == {
        "schema_version": 2,
        "code": "unsupported_architecture",
        "category": "bad_request",
        "message": (
            "Den här kombinationen av indata och slutresultat stöds inte. Börja om "
            "och välj en annan indata eller ett annat slutresultat."
        ),
        "phase": "planner",
        "eneo_error_code": ErrorCodes.BAD_REQUEST.value,
        "request_id": error_payload["request_id"],
        "diagnostic_context": {
            "request_id": error_payload["request_id"],
            "error_code": "unsupported_architecture",
            "error_category": "bad_request",
            "error_phase": "planner",
        },
    }
    planner.litellm_client.acompletion.assert_not_awaited()
    planner.repo.mark_session_turn_processing.assert_not_awaited()
    planner.repo.commit_turn.assert_not_awaited()
    planner.repo.create_plan.assert_not_awaited()
    assert persisted_state.model_dump(mode="json") == persisted_snapshot
    completed_error = planner.repo.complete_session_turn.await_args.kwargs["error"]
    assert completed_error.model_dump(mode="json", exclude_none=True) == error_payload


@pytest.mark.asyncio
async def test_send_message_requires_one_template_before_proposal_without_provider_or_plan_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    persisted_state = PlanningState.empty()
    persisted_snapshot = persisted_state.model_dump(mode="json")
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[
            ConversationMessage(
                role="user",
                content="documents",
                metadata={
                    "question_answer": {
                        "question_id": "primary_runtime_input",
                        "selected_values": ["documents"],
                    }
                },
            ),
            ConversationMessage(
                role="user",
                content="docx document",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_values": ["docx_document"],
                    }
                },
            ),
            ConversationMessage(
                role="user",
                content="fill a template",
                metadata={
                    "question_answer": {
                        "question_id": "docx_output_mode",
                        "selected_values": ["template_fill_docx"],
                    }
                },
            ),
        ],
        status=SessionStatus.CHATTING,
        planning_state_version=4,
        latest_plan_id=None,
    )
    planner.repo.load_planning_state.return_value = persisted_state
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(return_value=(None, None)),
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_discovery_runtime.classify_slots",
        AsyncMock(return_value=SlotClassificationAttempt(outcome="no_content")),
    )

    events = [
        encode_ai_builder_stream_event(event)
        async for event in planner.send_message(
            session_id=session_id,
            client_turn_id=_TEST_CLIENT_TURN_ID,
            request_fingerprint=_TEST_REQUEST_FINGERPRINT,
            request_snapshot=_test_request_snapshot("Single document"),
            message="Single document",
            question_answer={
                "kind": "structured_question_answer",
                "question_id": "document_material_scope",
                "selected_values": ["single_document_case"],
            },
            ui_language="en",
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=None,
            max_input_tokens=100_000,
            max_output_tokens=4_096,
            budget_policy=_budget_policy(),
        )
    ]

    assert [event["event"] for event in events] == ["error", "done"]
    error_payload = json.loads(events[0]["data"])
    assert error_payload["code"] == "template_attachment_selection_invalid"
    assert error_payload["category"] == "bad_request"
    assert error_payload["phase"] == "planner"
    assert error_payload["message"] == (
        "A template-fill Flow requires exactly one selected DOCX template. "
        "Attach or select one DOCX template and try again."
    )
    planner.litellm_client.acompletion.assert_not_awaited()
    planner.repo.mark_session_turn_processing.assert_not_awaited()
    planner.repo.commit_turn.assert_not_awaited()
    planner.repo.create_plan.assert_not_awaited()
    assert persisted_state.model_dump(mode="json") == persisted_snapshot
    completed_error = planner.repo.complete_session_turn.await_args.kwargs["error"]
    assert completed_error.model_dump(mode="json", exclude_none=True) == error_payload


@pytest.mark.asyncio
async def test_send_message_releases_lease_when_request_preparation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        status=SessionStatus.CHATTING,
        planning_state_version=1,
    )
    planner.repo.load_planning_state.return_value = None
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(return_value=(None, None)),
    )

    async def fail_prepare(_: PlannerRequestPreparationInput) -> ServerOutputPrepared:
        raise RuntimeError("preparation failed")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.prepare_planner_request",
        fail_prepare,
    )
    stream = planner.send_message(
        session_id=session_id,
        client_turn_id=_TEST_CLIENT_TURN_ID,
        request_fingerprint=_TEST_REQUEST_FINGERPRINT,
        request_snapshot=_test_request_snapshot("Build a flow"),
        message="Build a flow",
        completion_model_route=_route(),
        available_models=None,
        available_kbs=None,
        flow=None,
        assistant_snapshots=None,
        attachment_files=None,
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
    )

    with pytest.raises(RuntimeError, match="preparation failed"):
        await anext(stream)

    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_rejects_legacy_mcp_revision_before_provider_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    plan_id = uuid4()
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        status=SessionStatus.AWAITING_APPROVAL,
        planning_state_version=1,
        latest_plan_id=plan_id,
    )
    planner.repo.load_planning_state.return_value = None
    with pytest.raises(ValidationError) as validation_error:
        AssistantSpec.model_validate(
            {
                "instructions": "Use the legacy tool.",
                "mcp_tool_refs": ["mcp_tool.legacy"],
            }
        )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(side_effect=validation_error.value),
    )
    stream = planner.send_message(
        session_id=uuid4(),
        client_turn_id=_TEST_CLIENT_TURN_ID,
        request_fingerprint=_TEST_REQUEST_FINGERPRINT,
        request_snapshot=_test_request_snapshot("Revise the plan"),
        message="Revise the plan",
        edit_context=AIBuilderPlanEditContext(
            scope="whole_plan",
            plan_id=plan_id,
        ),
        completion_model_route=_route(),
        available_models=None,
        available_kbs=None,
        flow=None,
        assistant_snapshots=None,
        attachment_files=None,
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
    )

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        await anext(stream)

    assert exc_info.value.code is AIBuilderErrorCode.BAD_REQUEST
    planner.litellm_client.assert_not_awaited()
    planner.repo.accept_session_turn.assert_not_awaited()
    planner.repo.mark_session_turn_processing.assert_not_awaited()
    planner.repo.create_plan.assert_not_awaited()
    planner.repo.release_session_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_releases_lease_when_stream_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    _configure_minimal_send_message(
        planner,
        monkeypatch,
        ProposalPrepared(
            requirements_state=_requirements_state_confirmed(),
            ui_language="sv",
            message_groups=(
                ProposalMessageGroup(
                    messages=({"role": "system", "content": "proposal"},),
                    kind="system",
                    protected=True,
                ),
            ),
            system_prompt_hash="proposal-hash",
            prior_spec_for_revision=None,
            slot_classification_metadata=None,
            plan_edit_context=None,
            planning_state=PlanningState.empty(),
            compile_context=None,
            proposal_tool_schema=_empty_proposal_tool_schema(),
            request_budget=_proposal_budget(),
            resource_catalog=build_ai_builder_resource_catalog(
                available_models=[],
                available_kbs=[],
                prior_bindings=(),
            ),
        ),
    )

    proposal_started = asyncio.Event()

    async def fake_propose_plan(
        **_: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        proposal_started.set()
        await asyncio.Event().wait()
        yield build_text_event("unreachable")

    monkeypatch.setattr(
        planner._proposal_submission,
        "run_active_submission_attempt",
        fake_propose_plan,
    )
    stream = planner.send_message(
        session_id=session_id,
        client_turn_id=_TEST_CLIENT_TURN_ID,
        request_fingerprint=_TEST_REQUEST_FINGERPRINT,
        request_snapshot=_test_request_snapshot("Build a flow"),
        message="Build a flow",
        completion_model_route=_route(),
        available_models=None,
        available_kbs=None,
        flow=None,
        assistant_snapshots=None,
        attachment_files=None,
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
    )

    pending_event = asyncio.create_task(anext(stream))
    await asyncio.wait_for(proposal_started.wait(), timeout=1)
    pending_event.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_event

    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_proposal_catalog_uses_prior_plan_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    local_model_id = uuid4()
    prior_binding = LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot="fast-model",
            label="Fast model",
        ),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=local_model_id,
    )
    prior_plan = SimpleNamespace(resource_bindings=(prior_binding,))
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        status=SessionStatus.CHATTING,
        planning_state_version=1,
    )
    planner.repo.load_planning_state.return_value = None

    async def fake_prepare(_: PlannerRequestPreparationInput) -> ProposalPrepared:
        return ProposalPrepared(
            requirements_state=_requirements_state_confirmed(),
            ui_language="sv",
            message_groups=(
                ProposalMessageGroup(
                    messages=({"role": "system", "content": "proposal"},),
                    kind="system",
                    protected=True,
                ),
            ),
            system_prompt_hash="proposal-hash",
            prior_spec_for_revision=None,
            slot_classification_metadata=None,
            plan_edit_context=None,
            planning_state=PlanningState.empty(),
            compile_context=None,
            proposal_tool_schema=_empty_proposal_tool_schema(),
            request_budget=_proposal_budget(),
            resource_catalog=build_ai_builder_resource_catalog(
                available_models=[
                    _model_resource(str(local_model_id), "Renamed model")
                ],
                available_kbs=[],
                prior_bindings=(prior_binding,),
            ),
        )

    captured: dict[str, object] = {}

    async def fake_propose_plan(
        **kwargs: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        captured.update(kwargs)
        yield build_text_event("proposal")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(return_value=(None, prior_plan)),
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.prepare_planner_request",
        fake_prepare,
    )
    monkeypatch.setattr(
        planner._proposal_submission,
        "run_active_submission_attempt",
        fake_propose_plan,
    )

    events = [
        encode_ai_builder_stream_event(event)
        async for event in planner.send_message(
            session_id=session_id,
            client_turn_id=_TEST_CLIENT_TURN_ID,
            request_fingerprint=_TEST_REQUEST_FINGERPRINT,
            request_snapshot=_test_request_snapshot("Revise the plan"),
            message="Revise the plan",
            completion_model_route=_route(),
            available_models=[_model_resource(str(local_model_id), "Renamed model")],
            available_kbs=[],
            flow=None,
            assistant_snapshots=None,
            attachment_files=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
        )
    ]

    resource_catalog = cast(AIBuilderResourceCatalog, captured["resource_catalog"])
    assert resource_catalog.models[0].authoring_ref == "model.fast-model"
    assert resource_catalog.models[0].slot_ref.label == "Renamed model"
    assert events[-1] == {"event": "done", "data": ""}


@pytest.mark.asyncio
async def test_stream_proposal_events_commits_planning_state_payload_too_large(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    turn = cast(Any, SimpleNamespace())
    proposal_request = ProposalPrepared(
        requirements_state=_requirements_state_confirmed(),
        ui_language="sv",
        message_groups=(
            ProposalMessageGroup(
                messages=({"role": "system", "content": "proposal"},),
                kind="system",
                protected=True,
            ),
        ),
        system_prompt_hash="proposal-hash",
        prior_spec_for_revision=None,
        slot_classification_metadata=None,
        plan_edit_context=None,
        planning_state=PlanningState.empty(),
        compile_context=None,
        proposal_tool_schema=_empty_proposal_tool_schema(),
        request_budget=_proposal_budget(),
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
            prior_bindings=(),
        ),
    )

    async def reject_oversized_state(
        **_: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        raise PlanningStatePayloadTooLargeError(
            byte_size=131_073,
            cap_bytes=131_072,
        )
        yield

    monkeypatch.setattr(
        planner._proposal_submission,
        "run_active_submission_attempt",
        reject_oversized_state,
    )

    events = [
        event
        async for event in planner._stream_proposal_events(
            turn=turn,
            conversation=[],
            new_messages_start=0,
            proposal_request=proposal_request,
            completion_model_route=_route(),
            request_id="oversized-proposal-state",
            usage_tracker=ProposalTurnTelemetry(
                request_id="oversized-proposal-state",
                model="openai/gpt-5.4",
                target_kind=TargetKind.CREATE,
            ),
            flow=None,
            assistant_snapshots=None,
            before_provider_call=AsyncMock(),
        )
    ]

    assert len(events) == 1
    error_event = events[0]
    assert error_event.event == "error"
    assert error_event.data.code == AIBuilderErrorCode.PLANNING_STATE_PAYLOAD_TOO_LARGE
    assert error_event.data.details == {
        "payload_bytes": 131_073,
        "payload_cap_bytes": 131_072,
    }
    planner.repo.complete_session_turn.assert_awaited_once_with(
        turn=turn,
        error=error_event.data,
    )


@pytest.mark.asyncio
async def test_send_message_rejects_closed_session_before_claiming_lock() -> None:
    planner = _make_planner()
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        status=SessionStatus.CANCELLED,
    )

    with pytest.raises(BadRequestException, match="Cannot send messages"):
        async for _ in planner.send_message(
            session_id=uuid4(),
            client_turn_id=_TEST_CLIENT_TURN_ID,
            request_fingerprint=_TEST_REQUEST_FINGERPRINT,
            request_snapshot=_test_request_snapshot("Build a flow"),
            message="Build a flow",
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
        ):
            pass

    planner.repo.claim_session_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_replays_the_exact_committed_error_without_provider_work() -> (
    None
):
    planner = _make_planner()
    tenant_id = cast(UUID, planner.user.tenant_id)
    committed_error = build_ai_builder_error_event(
        message="The committed planner failure.",
        code=AIBuilderErrorCode.PLANNER_REJECTED,
        request_id="committed-request",
        diagnostic_context={"outcome_kind": "server_confirm_requirements"},
        details={"quality_failure_codes": "missing_source_refs"},
    ).data
    session = BuilderSession(
        id=uuid4(),
        tenant_id=tenant_id,
        space_id=uuid4(),
        target_kind=TargetKind.CREATE,
        latest_turn=BuilderTurnLifecycle(
            client_turn_id=_TEST_CLIENT_TURN_ID,
            request_fingerprint=_TEST_REQUEST_FINGERPRINT,
            request=_test_request_snapshot("Build a flow"),
            state=BuilderTurnState.COMMITTED,
            user_message_id=uuid4(),
            error=committed_error,
        ),
    )
    preflight = SessionTurnPreflight(
        session=session,
        baseline=SessionTurnPreparationBaseline(
            session_status=SessionStatus.CHATTING,
            latest_plan_id=None,
            planning_state_version=0,
            latest_turn_id=_TEST_CLIENT_TURN_ID,
            latest_turn_state=BuilderTurnState.COMMITTED,
            attachment_file_ids=(),
        ),
        replayed=True,
    )

    events = [
        encode_ai_builder_stream_event(event)
        async for event in planner.send_message(
            session_id=session.id,
            client_turn_id=_TEST_CLIENT_TURN_ID,
            request_fingerprint=_TEST_REQUEST_FINGERPRINT,
            request_snapshot=_test_request_snapshot("Build a flow"),
            message="Build a flow",
            completion_model_route=_route(),
            turn_preflight=preflight,
            max_input_tokens=100_000,
            max_output_tokens=4_096,
        )
    ]

    assert events == [
        {
            "event": "error",
            "data": committed_error.model_dump_json(exclude_none=True),
        },
        {"event": "done", "data": ""},
    ]
    planner.repo.accept_session_turn.assert_not_awaited()
    planner.litellm_client.assert_not_awaited()


def _confirmation_conversation(
    disclosure: RequirementsSummaryPayload,
    *,
    message: str = "",
) -> list[ConversationMessage]:
    """The disclosure the user saw, followed by the turn that confirms it."""

    return [
        ConversationMessage(role="user", content="Build a document report flow"),
        ConversationMessage(
            role="assistant",
            content=disclosure.summary,
            metadata={
                "requirements_summary": disclosure.model_dump(mode="json"),
                "requirements_version": disclosure.requirements_version,
            },
        ),
        ConversationMessage(
            role="user",
            content=message,
            metadata={
                "requirements_confirmed": True,
                "requirements_version": disclosure.requirements_version,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_resumed_stale_classification_is_rejected_and_rearms_discovery() -> None:
    planner = _make_planner()
    legacy_message_id = "legacy-hierarchy"
    legacy_quote = (
        "Return JSON with documents[]. Each candidate_passages[] belongs directly "
        "under documents, and each page_or_section belongs directly under "
        "candidate_passages."
    )
    legacy_source_id = f"user_message:{legacy_message_id}"
    legacy_evidence = ClassifiedEvidence(
        source_id=legacy_source_id,
        quote=legacy_quote,
    )
    legacy_state = PlanningState.empty()
    legacy_state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="text",
            source="requirements_summary",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_json",
            source="requirements_summary",
            confidence="high",
        ),
    }
    legacy_state.named_result_evidence = [
        NamedResultEvidence(
            name="documents",
            declared_shape="array",
            confidence="high",
            evidence=[legacy_evidence.planning_reference()],
        ),
        NamedResultEvidence(
            name="candidate_passages",
            declared_shape="array",
            confidence="high",
            evidence=[legacy_evidence.planning_reference()],
        ),
        NamedResultEvidence(
            name="page_or_section",
            confidence="high",
            evidence=[legacy_evidence.planning_reference()],
        ),
    ]
    assert legacy_state.named_result_evidence
    draft = derive_architecture_commit_draft(legacy_state)
    assert draft is not None
    legacy_state.architecture_commit = finalize_architecture_commit(draft)
    legacy_disclosure = build_requirements_disclosure(
        legacy_state,
        ui_language="en",
    )
    classification_input = SlotClassificationInput(
        sources=(
            SlotClassificationSource(
                source_id=legacy_source_id,
                kind="user_message",
                text=legacy_quote,
                message_id=legacy_message_id,
            ),
        ),
        current_user_message_id=legacy_message_id,
    )
    snapshot = SlotClassificationNamedResultEvidenceMetadata.from_materialized_state(
        operation="replace",
        named_results=legacy_state.named_result_evidence,
        confidence="high",
        reason="The complete legacy named-result snapshot.",
        evidence=(legacy_evidence,),
    )
    current_metadata = slot_classification_metadata_from_attempt(
        SlotClassificationAttempt(
            outcome="resolved",
            result=SlotClassificationResult(),
        ),
        prompt_hash="c" * 64,
        classification_input=classification_input,
        model="openai/gpt-test",
        provider="openai",
        named_result_evidence_snapshot=snapshot,
    )
    stale_payload = current_metadata.model_dump(mode="json")
    stale_payload["schema_version"] = SLOT_CLASSIFICATION_SCHEMA_VERSION - 1

    resumed_message_id = "resumed-hierarchy"
    resumed_source_id = f"user_message:{resumed_message_id}"
    citation = {"source_id": resumed_source_id, "quote": legacy_quote}
    classification_payload = {
        "slots": [],
        "file_roles": [],
        "checkpoint_updates": [],
        "form_intake": None,
        "named_result_evidence": {
            "operation": "update",
            "upserts": [
                {"name": "documents", "segments": [], "evidence": [citation]},
                {
                    "name": "candidate_passages",
                    "segments": ["documents"],
                    "evidence": [citation],
                },
                {
                    "name": "page_or_section",
                    "segments": ["documents", "candidate_passages"],
                    "evidence": [citation],
                },
            ],
            "removals": [],
            "confidence": "high",
            "reason": "The user restated the complete result hierarchy.",
            "evidence": [citation],
        },
        "example_output_constraints": None,
        "schema_direction": None,
        "secondary_obligations": [],
    }
    response = MagicMock()
    response.choices = [
        SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(classification_payload))
        )
    ]
    planner.litellm_client.acompletion.return_value = response
    conversation = [
        ConversationMessage(
            message_id=legacy_message_id,
            role="user",
            content=legacy_quote,
            metadata={"slot_classification": stale_payload},
        ),
        ConversationMessage(
            role="assistant",
            content=legacy_disclosure.summary,
            metadata={
                "requirements_summary": legacy_disclosure.model_dump(mode="json"),
                "requirements_version": legacy_disclosure.requirements_version,
            },
        ),
        ConversationMessage(
            role="user",
            content="",
            metadata={
                "requirements_confirmed": True,
                "requirements_version": legacy_disclosure.requirements_version,
            },
        ),
        ConversationMessage(
            message_id=resumed_message_id,
            role="user",
            content=legacy_quote,
        ),
    ]

    prepared = await _prepare_planner_request_for_test(
        planner,
        conversation=conversation,
        completion_model_route=_route(),
        persisted_planning_state=None,
    )

    planner.litellm_client.acompletion.assert_awaited_once()
    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, AskCanonicalQuestion)
    assert prepared.server_decision.slot_name == "post_processing_goal"
    assert prepared.slot_classification_metadata is not None
    assert (
        prepared.slot_classification_metadata.schema_version
        == SLOT_CLASSIFICATION_SCHEMA_VERSION
    )
    assert [
        item.placement.segments
        for item in prepared.planning_state.named_result_evidence
        if isinstance(item.placement, ExactNamedResultPlacement)
    ] == [(), ("documents",), ("documents", "candidate_passages")]
    assert prepared.requirements_confirmation_required is True


@pytest.mark.asyncio
async def test_confirmation_of_a_state_this_build_no_longer_loads_rearms_confirmation() -> (
    None
):
    # The repository returns no state for a payload stamped by another builder
    # schema version, so a confirmation recorded against that state arrives
    # with nothing persisted behind it.
    planner = _make_planner()
    legacy_state = _document_architecture_state()
    legacy_state.named_result_evidence = [
        NamedResultEvidence(
            name="legacy_field",
            confidence="high",
            evidence=["quote:user_message:legacy:legacy_field"],
        )
    ]
    legacy_disclosure = build_requirements_disclosure(
        legacy_state,
        ui_language="en",
    )

    prepared = await _prepare_planner_request_for_test(
        planner,
        conversation=_confirmation_conversation(legacy_disclosure),
        completion_model_route=_route(),
        persisted_planning_state=None,
    )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, AskCanonicalQuestion)
    assert prepared.server_decision.slot_name == "post_processing_goal"
    assert prepared.planning_state.builder_schema_version == BUILDER_SCHEMA_VERSION
    assert prepared.planning_state.named_result_evidence == []
    assert prepared.requirements_confirmation_required is True


def _text_attachment_role(file: File, coverage: AttachmentCoverage) -> FileRoleEvidence:
    return FileRoleEvidence(
        file_id=file.id,
        filename=file.name,
        file_type=FileType.TEXT,
        mimetype="text/plain",
        has_readable_text=True,
        coverage=coverage,
        role="reference_material",
        source="model",
        confidence="high",
        evidence=["quote:user_message:user-1:bilagan"],
        evidence_level="explicit",
    )


@pytest.mark.asyncio
async def test_confirmation_acknowledgment_makes_no_understanding_call() -> None:
    """Acknowledging a disclosure is not new evidence, so nothing is re-read.

    The Builder used to rebuild planning state and re-run the classifier on the
    confirmation turn itself. Re-interpreting the same attachments moved the
    summary, so the confirmation could never match and the session re-confirmed
    until the interaction limit.

    The deployment ships a mapped-execution ceiling, so the persisted state
    carries the file limit it disclosed. Acknowledging under a policy that
    proposes nothing at all is the one case that never reached production.
    """

    planner = _make_planner()
    state = _document_architecture_state()
    state.mapped_file_limit = MappedFileLimit(
        proposed_value=149,
        accepted_value=149,
        provenance="policy_default",
    )
    conversation = _confirmation_conversation(
        build_requirements_disclosure(state, ui_language="en")
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
        "build_discovery_runtime_result",
        new_callable=AsyncMock,
    ) as build_runtime:
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            persisted_planning_state=state,
            mapped_execution_policy=FlowMappedExecutionPolicy(
                max_provider_calls_per_mapped_step=150
            ),
        )

    build_runtime.assert_not_awaited()
    assert isinstance(prepared, ProposalPrepared)


@pytest.mark.asyncio
async def test_a_first_create_turn_is_offered_no_way_to_decline() -> None:
    """Nothing exists to decline yet, so the turn keeps one forced tool."""

    planner = _make_planner()
    state = _document_architecture_state()
    conversation = _confirmation_conversation(
        build_requirements_disclosure(state, ui_language="en")
    )

    prepared = await _prepare_planner_request_for_test(
        planner,
        conversation=conversation,
        completion_model_route=_route(),
        persisted_planning_state=state,
    )

    assert isinstance(prepared, ProposalPrepared)
    assert prepared.decline_tool_schema is None
    system_prompt = prepared.message_groups[0].messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert DECLINE_FLOW_CHANGE_TOOL_NAME not in system_prompt


@pytest.mark.asyncio
async def test_an_acknowledgment_resolves_the_requirements_it_confirms() -> None:
    """A confirmation turn resolves from the state its own commit will persist.

    The session can move between showing a disclosure and being answered: storing
    the disclosure lets the next deterministic pass read its own prose, resolve
    the runtime input for the first time, and apply the document-scope policy
    default — which a medium-confidence reading can no longer displace. The
    acknowledgment used to start from that persisted copy and could only confirm
    a value that already matched, so it dropped the scope the user had just
    accepted, kept the report disposition below commit grade, and derived an
    architecture without it. `commit_turn` reconstructs the session from its
    conversation, where the accepted value is the answer, so it derived the
    disposition the user accepted and refused the architecture the same turn had
    proposed — one confirmation, two architectures, and an internal error instead
    of a plan.
    """

    planner = _make_planner()
    disclosed_state = _document_architecture_state()
    disclosed_state.resolved_slots["terminal_output"] = ResolvedSlot(
        name="terminal_output",
        value="pdf_document",
        source="structured_answer",
        confidence="high",
        evidence=["question_answer:terminal_output"],
    )
    disclosed_state.resolved_slots["document_material_scope"] = ResolvedSlot(
        name="document_material_scope",
        value="multiple_documents_case",
        source="model",
        confidence="medium",
        evidence=["quote:user_message:user-1:flera ansökningar"],
        evidence_level="explicit",
    )
    disclosed_state.resolved_slots["report_disposition"] = ResolvedSlot(
        name="report_disposition",
        value="synthesized_overview",
        source="model",
        confidence="medium",
        evidence=["quote:user_message:user-1:en samlad överblick"],
        evidence_level="inferred",
    )
    disclosure = build_requirements_disclosure(disclosed_state, ui_language="en")

    # What the session actually persisted once the disclosure was stored.
    persisted = disclosed_state.model_copy(deep=True)
    persisted.resolved_slots["document_material_scope"] = ResolvedSlot(
        name="document_material_scope",
        value="flexible_document_case",
        source="policy_default",
        confidence="medium",
        evidence=["policy_default:document_material_scope=flexible_document_case"],
    )
    assert persisted.commit_grade_slot_value("report_disposition") is None

    prepared = await _prepare_planner_request_for_test(
        planner,
        conversation=_confirmation_conversation(disclosure),
        completion_model_route=_route(),
        persisted_planning_state=persisted,
    )

    resolved = prepared.planning_state
    assert (
        resolved.commit_grade_slot_value("document_material_scope")
        == "multiple_documents_case"
    )
    draft = derive_architecture_commit_draft(resolved)
    assert draft is not None
    assert draft.report_disposition == "synthesized_overview"


@pytest.mark.asyncio
async def test_an_acknowledgment_keeps_the_schema_the_user_assigned() -> None:
    """A declared schema survives the confirmation that approved it.

    Nothing carries a declared schema forward: persisted state is not reused
    across a rebuild, and carry-forward deliberately refuses declared evidence
    because the attachment it came from may be gone. The assignment is recovered
    by replaying the user's own direction answer, so the acknowledgment has to
    reconstruct through the owner that replays it. Reconstructing the slot
    surface alone and calling the direction settled would hand the proposal a
    flow with no input contract, and suppress the question that would have shown
    it.
    """

    planner = _make_planner()
    schema_file = _make_file(
        '{"type":"object","properties":{"decision":{"type":"string"}}}',
        name="ansokan.schema.json",
        mimetype="application/json",
    )
    asked = await _prepare_planner_request_for_test(
        planner,
        conversation=[ConversationMessage(role="user", content="Build a flow")],
        completion_model_route=_route(),
        attachment_files=[schema_file],
        max_input_tokens=100_000,
    )
    assert isinstance(asked, ServerOutputPrepared)
    assert isinstance(asked.server_decision, AskCanonicalQuestion)
    assert asked.server_decision.question is not None
    input_option = next(
        option.value
        for option in asked.server_decision.question.question_data.options
        if option.value.startswith("input:")
    )

    answered = [
        ConversationMessage(role="user", content="Build a flow"),
        ConversationMessage(
            role="assistant",
            content="Assign the schema.",
            tool_calls=[
                {
                    "id": "schema-direction",
                    "name": "ask_structured_question",
                    "arguments": asked.server_decision.question.question_data.model_dump(
                        mode="json"
                    ),
                }
            ],
        ),
        ConversationMessage(
            role="user",
            content="",
            metadata={
                "question_answer": {
                    "question_id": "schema_direction",
                    "selected_values": [input_option],
                }
            },
        ),
    ]
    assigned = await _prepare_planner_request_for_test(
        planner,
        conversation=answered,
        completion_model_route=_route(),
        attachment_files=[schema_file],
        max_input_tokens=100_000,
    )
    assigned_state = assigned.planning_state
    assert assigned_state.input_schema_evidence is not None
    disclosure = build_requirements_disclosure(assigned_state, ui_language="en")

    acknowledged = await _prepare_planner_request_for_test(
        planner,
        conversation=[
            *answered,
            ConversationMessage(
                role="assistant",
                content=disclosure.summary,
                metadata={
                    "requirements_summary": disclosure.model_dump(mode="json"),
                    "requirements_version": disclosure.requirements_version,
                },
            ),
            ConversationMessage(
                role="user",
                content="",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": disclosure.requirements_version,
                },
            ),
        ],
        completion_model_route=_route(),
        attachment_files=[schema_file],
        persisted_planning_state=assigned_state,
        max_input_tokens=100_000,
    )

    assert (
        acknowledged.planning_state.input_schema_evidence
        == assigned_state.input_schema_evidence
    )


def _proposal_prepared_for_test(
    *,
    planning_state: PlanningState,
    conversation: list[ConversationMessage],
    architecture_revised_this_turn: bool,
    prior_terminal_output_type: OutputType = OutputType.TEXT,
) -> ProposalPrepared:
    return build_proposal_prepared(
        requirements_state=_requirements_state_confirmed(),
        ui_language="sv",
        slot_classification_metadata=None,
        conversation=conversation,
        planning_state=planning_state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
            prior_bindings=(),
        ),
        flow=None,
        assistant_snapshots=None,
        plan_edit_context=ResolvedAIBuilderEditContext(
            request=AIBuilderPlanEditContext(
                scope="step",
                plan_id=uuid4(),
                target_plan_step_ref="step_a",
            ),
            scope="step",
            target_plan_step_ref="step_a",
        ),
        prior_plan_for_revision=cast(
            Any,
            SimpleNamespace(
                spec=FlowDraftSpecCore(
                    flow_name="Beslutsunderlag",
                    steps=[
                        StepSpec(
                            plan_step_ref="step_a",
                            name="Skriv underlaget",
                            assistant_spec=AssistantSpec(instructions="Skriv."),
                            input_source=InputSource.FLOW_INPUT,
                            input_type=InputType.TEXT,
                            output_mode=OutputMode.PASS_THROUGH,
                            output_type=prior_terminal_output_type,
                        )
                    ],
                )
            ),
        ),
        litellm_model=_route().litellm_model,
        max_input_tokens=32000,
        max_output_tokens=2048,
        budget_policy=AIBuilderBudgetPolicy(
            conversation_safety_buffer_tokens=128,
            minimum_conversation_budget_tokens=256,
        ),
        attachment_file_count=0,
        current_turn_start=0,
        architecture_revised_this_turn=architecture_revised_this_turn,
    )


def test_a_turn_holding_an_unbuilt_committed_change_cannot_decline() -> None:
    """A mixed request must not be answered by the model sentence alone.

    "gör slutfilen till pdf och byt modell" commits a PDF terminal the shown
    plan does not have yet. Declining the whole turn would drop the half the
    server already committed, so the tool is not offered while the two
    disagree.
    """

    state = _document_architecture_state()
    conversation = _confirmation_conversation(
        build_requirements_disclosure(state, ui_language="en")
    )

    matching = _proposal_prepared_for_test(
        planning_state=state,
        conversation=conversation,
        architecture_revised_this_turn=False,
    )
    prior_terminal = matching.prior_spec_for_revision
    assert prior_terminal is not None

    diverged = _proposal_prepared_for_test(
        planning_state=state,
        conversation=conversation,
        architecture_revised_this_turn=False,
        prior_terminal_output_type=OutputType.PDF,
    )

    assert matching.decline_tool_schema is not None
    assert diverged.decline_tool_schema is None


def test_a_turn_that_just_revised_the_architecture_cannot_decline() -> None:
    """The revision is already persisted, so this turn is not model-only.

    Declining here would tell the user nothing changed while the session keeps
    the architecture change that same turn committed.
    """

    state = _document_architecture_state()
    conversation = _confirmation_conversation(
        build_requirements_disclosure(state, ui_language="en")
    )

    revising = _proposal_prepared_for_test(
        planning_state=state,
        conversation=conversation,
        architecture_revised_this_turn=True,
    )
    plain = _proposal_prepared_for_test(
        planning_state=state,
        conversation=conversation,
        architecture_revised_this_turn=False,
    )

    assert revising.decline_tool_schema is None
    assert plain.decline_tool_schema is not None


@pytest.mark.asyncio
async def test_a_saved_flow_edit_turn_can_decline() -> None:
    """An edit of an existing Flow may answer that it cannot make the change."""

    planner = _make_planner()
    state = _document_architecture_state()
    conversation = _confirmation_conversation(
        build_requirements_disclosure(state, ui_language="en")
    )

    prepared = await _prepare_planner_request_for_test(
        planner,
        conversation=conversation,
        completion_model_route=_route(),
        persisted_planning_state=state,
        flow=cast(
            Any,
            SimpleNamespace(
                id=uuid4(),
                name="Beslutsunderlag",
                description="",
                steps=[],
                metadata_json={},
                draft_revision=1,
            ),
        ),
    )

    assert isinstance(prepared, ProposalPrepared)
    assert prepared.decline_tool_schema is not None
    system_prompt = prepared.message_groups[0].messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert DECLINE_FLOW_CHANGE_TOOL_NAME in system_prompt


@pytest.mark.asyncio
async def test_text_beside_a_confirmation_is_read_as_a_change() -> None:
    """ "Ja, men skriv den i en informell ton" is a change, never a silent yes.

    The classifier is deliberately left returning unchanged state here, which
    is the case that used to slip through: reading the request as evidence is
    not enough on its own, because an unchanged disclosure still matches the
    old confirmation and would go straight to a plan. A confirmation carrying a
    message does not confirm, so the user gets the disclosure back to attest to.
    """

    planner = _make_planner()
    state = _document_architecture_state()
    conversation = _confirmation_conversation(
        build_requirements_disclosure(state, ui_language="en"),
        message="Ja, men skriv den i en informell ton.",
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
        "build_discovery_runtime_result",
        new_callable=AsyncMock,
        return_value=_runtime_result(DiscoveryAnalysis(issues=()), state),
    ) as build_runtime:
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            persisted_planning_state=state,
        )

    build_runtime.assert_awaited_once()
    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, ConfirmRequirements)


@pytest.mark.asyncio
async def test_a_new_attachment_beside_a_confirmation_earns_a_new_disclosure() -> None:
    """Confirm-and-change is a change: it re-derives instead of inheriting."""

    planner = _make_planner()
    state = _document_architecture_state()
    conversation = _confirmation_conversation(
        build_requirements_disclosure(state, ui_language="en")
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
        "build_discovery_runtime_result",
        new_callable=AsyncMock,
        return_value=_runtime_result(DiscoveryAnalysis(issues=()), state),
    ) as build_runtime:
        await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            persisted_planning_state=state,
            attachment_files=[_make_file()],
        )

    build_runtime.assert_awaited_once()


@pytest.mark.asyncio
async def test_detaching_a_disclosed_file_earns_a_new_disclosure() -> None:
    """Removing evidence changes the plan as much as adding it.

    Only the ordinary rebuild reconciles file roles against current session
    membership, so an acknowledgment may never reuse state that still carries
    a detached attachment.
    """

    planner = _make_planner()
    state = _document_architecture_state()
    state.file_roles = [_text_attachment_role(_make_file(), "fully_seen")]
    conversation = _confirmation_conversation(
        build_requirements_disclosure(state, ui_language="en")
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
        "build_discovery_runtime_result",
        new_callable=AsyncMock,
        return_value=_runtime_result(DiscoveryAnalysis(issues=()), state),
    ) as build_runtime:
        await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            persisted_planning_state=state,
            attachment_files=[],
        )

    build_runtime.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("persisted_coverage", "rereads_evidence"),
    [
        pytest.param("fully_seen", False, id="coverage unchanged"),
        pytest.param("excerpt_truncated", True, id="coverage changed"),
    ],
)
async def test_a_confirmation_reuses_state_only_while_coverage_still_matches(
    persisted_coverage: AttachmentCoverage,
    rereads_evidence: bool,
) -> None:
    """How much of a file the planner saw is disclosed, so it is confirmed.

    The same file id can be read differently by a different model or budget.
    The fast path reuses the persisted roles wholesale, so it may only run
    while the coverage it disclosed is still the coverage this turn produces.
    """

    planner = _make_planner()
    attachment = _make_file()
    state = _document_architecture_state()
    state.file_roles = [_text_attachment_role(attachment, persisted_coverage)]
    conversation = _confirmation_conversation(
        build_requirements_disclosure(state, ui_language="en")
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
        "build_discovery_runtime_result",
        new_callable=AsyncMock,
        return_value=_runtime_result(DiscoveryAnalysis(issues=()), state),
    ) as build_runtime:
        await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            persisted_planning_state=state,
            attachment_files=[attachment],
        )

    assert build_runtime.await_count == (1 if rereads_evidence else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("call_ceiling", "rereads_evidence"),
    [
        pytest.param(10, False, id="policy unchanged"),
        pytest.param(6, True, id="policy lowered"),
    ],
)
async def test_a_confirmation_reuses_state_only_under_the_disclosed_policy(
    call_ceiling: int,
    rereads_evidence: bool,
) -> None:
    """The accepted mapped limit compiles into `runtime_max_files`.

    An organization can lower the mapped-execution ceiling between the
    disclosure and the confirmation. Reusing the old accepted value would
    compile a limit the current policy no longer permits.
    """

    planner = _make_planner()
    state = _document_architecture_state()
    state.mapped_file_limit = MappedFileLimit(
        proposed_value=9,
        accepted_value=9,
        provenance="policy_default",
    )
    conversation = _confirmation_conversation(
        build_requirements_disclosure(state, ui_language="en")
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
        "build_discovery_runtime_result",
        new_callable=AsyncMock,
        return_value=_runtime_result(DiscoveryAnalysis(issues=()), state),
    ) as build_runtime:
        await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            persisted_planning_state=state,
            mapped_execution_policy=FlowMappedExecutionPolicy(
                max_provider_calls_per_mapped_step=call_ceiling
            ),
        )

    assert build_runtime.await_count == (1 if rereads_evidence else 0)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_a_confirmed_requirement_core_that_cannot_fit_is_rejected() -> None:
    planner = _make_planner()
    state = _document_architecture_state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name=f"sokt_insats_med_ett_ganska_langt_namn_{index:03d}",
            confidence="high",
            evidence=["quote:user_message:user-1:sökta insatser"],
        )
        for index in range(NAMED_RESULT_EVIDENCE_MAX_ITEMS)
    ]
    disclosure = build_requirements_disclosure(state, ui_language="en")
    conversation = _confirmation_conversation(disclosure)

    with pytest.raises(AIBuilderKnownProviderRejectionException) as exc_info:
        await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            persisted_planning_state=state,
            max_input_tokens=4_096,
        )

    assert (
        exc_info.value.public_error.code
        is AIBuilderErrorCode.PLANNER_CONTEXT_LIMIT_EXCEEDED
    )
    planner.litellm_client.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_text_beside_a_confirmation_after_a_plan_is_read_as_a_change() -> None:
    """A confirmation stays valid across revision turns; the fast path does not.

    Once a plan exists, an ordinary revision message deliberately keeps the
    requirements confirmed. A revision that also carries confirmation metadata
    must therefore still be read as a revision: reusing the persisted state
    would compile the previous output contract while the user asked for a
    different one.
    """

    planner = _make_planner()
    state = _document_architecture_state()
    disclosure = build_requirements_disclosure(state, ui_language="en")
    conversation = [
        *_confirmation_conversation(disclosure),
        ConversationMessage(
            role="assistant",
            content="Here is the draft.",
            tool_calls=[
                {
                    "id": "call_plan",
                    "name": PROPOSE_FLOW_TOOL_NAME,
                    "arguments": {"flow_name": "Report flow"},
                }
            ],
        ),
        ConversationMessage(
            role="user",
            content="Ändra utdata till JSON.",
            metadata={
                "requirements_confirmed": True,
                "requirements_version": disclosure.requirements_version,
            },
        ),
    ]

    with patch(
        "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
        "build_discovery_runtime_result",
        new_callable=AsyncMock,
        return_value=_runtime_result(DiscoveryAnalysis(issues=()), state),
    ) as build_runtime:
        await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            persisted_planning_state=state,
        )

    build_runtime.assert_awaited_once()


def test_example_output_headings_never_become_requested_output_sections() -> None:
    """Headings seen in an attached example are evidence, not a requested outline.

    The disclosure discloses them back to the user as an assumption
    ("Selected example-output headings: ..."). While that prose was appended
    to the section-signal text, the extractor's own `headings:` cue turned an
    uploaded example's layout into an output topology the plan had to
    reproduce — the exact thing its module contract forbids.
    """

    from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
        REQUIREMENTS_SUMMARY_METADATA_KEY,
    )
    from eneo.flows.ai_builder.ai_builder_event_models import (
        RequirementsSummaryPayload,
    )

    disclosure = RequirementsSummaryPayload.model_validate(
        {
            "summary": "Skapa en rapport från underlaget.",
            "key_decisions": [],
            "input_description": "Primär indata vid körning: Dokument.",
            "output_description": "Huvudsakligt slutresultat: DOCX-dokument.",
            "assumptions": [
                "Selected example-output headings: Bakgrund, Nuläge, "
                "Bedömning, Beslut.",
            ],
            "requirements_version": "b" * 64,
        }
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Vi laddar upp underlag och vill ha en rapport som DOCX.",
        ),
        ConversationMessage(
            role="assistant",
            content="Summary",
            metadata={
                REQUIREMENTS_SUMMARY_METADATA_KEY: disclosure.model_dump(mode="json"),
            },
        ),
        ConversationMessage(
            role="user",
            content="",
            metadata={
                "requirements_confirmed": True,
                "requirements_version": disclosure.requirements_version,
            },
        ),
    ]

    prepared = build_proposal_prepared(
        requirements_state=RequirementsState(),
        ui_language="sv",
        slot_classification_metadata=None,
        conversation=conversation,
        planning_state=PlanningState.empty(),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[], available_kbs=[], prior_bindings=()
        ),
        flow=None,
        assistant_snapshots=None,
        plan_edit_context=None,
        prior_plan_for_revision=None,
        litellm_model="openai/gpt-5.4",
        max_input_tokens=100_000,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
        attachment_file_count=0,
        current_turn_start=0,
    )

    compile_context = prepared.compile_context
    assert compile_context is not None
    assert compile_context.requested_output_sections.sections == ()


def _named_fields_interview() -> list[ConversationMessage]:
    """A create session whose answers resolve the slots the disclosure needs."""

    return [
        ConversationMessage(role="user", content="Build a document report flow"),
        *[
            ConversationMessage(
                role="user",
                content="",
                metadata={
                    "question_answer": {
                        "question_id": question_id,
                        "selected_values": [value],
                    }
                },
            )
            for question_id, value in (
                ("primary_runtime_input", "documents"),
                ("terminal_output", "structured_text"),
                ("document_material_scope", "single_document_case"),
                ("post_processing_goal", "summarize_or_overview"),
            )
        ],
    ]


def _field_edit_conversation(
    disclosure: RequirementsSummaryPayload,
    *field_names: str,
) -> list[ConversationMessage]:
    """The disclosure the user saw, followed by their edit of its field list."""

    return [
        *_named_fields_interview(),
        ConversationMessage(
            role="assistant",
            content=disclosure.summary,
            metadata={
                "requirements_summary": disclosure.model_dump(mode="json"),
                "requirements_version": disclosure.requirements_version,
            },
        ),
        ConversationMessage(
            message_id="field-edit",
            role="user",
            content="",
            metadata={
                "named_content_fields_edit": {
                    "schema_version": 1,
                    "requirements_version": disclosure.requirements_version,
                    "field_names": list(field_names),
                }
            },
        ),
    ]


def _named_fields_state() -> PlanningState:
    state = _document_architecture_state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name=name,
            confidence="high",
            evidence=["quote:user_message:user-1:beslut och farhagor"],
        )
        for name in ("beslut", "farhagor")
    ]
    return state


@pytest.mark.asyncio
async def test_editing_the_field_list_makes_no_understanding_call() -> None:
    """The edit states the whole set, so there is nothing left to read.

    Classifying this turn could only re-read sentences the user has already
    been shown a reading of, and would charge them a provider call for the
    privilege of maybe disagreeing with the list they just corrected.
    """

    planner = _make_planner()
    state = _named_fields_state()
    conversation = _field_edit_conversation(
        build_requirements_disclosure(state, ui_language="sv"),
        "beslut",
        "Beslutsdatum",
    )

    prepared = await _prepare_planner_request_for_test(
        planner,
        conversation=conversation,
        completion_model_route=_route(),
        persisted_planning_state=state,
    )

    planner.litellm_client.assert_not_awaited()
    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, ConfirmRequirements)
    assert [
        field.label for field in prepared.server_decision.payload.named_content_fields
    ] == ["beslut", "Beslutsdatum"]


@pytest.mark.asyncio
async def test_legacy_field_edit_does_not_promote_raw_names_to_root() -> None:
    planner = _make_planner()
    state = _named_fields_state()
    shown = build_requirements_disclosure(state, ui_language="sv")
    conversation = _field_edit_conversation(shown, "beslut", "legacy_root")
    edit_metadata = conversation[-1].metadata
    assert edit_metadata is not None
    raw_edit = edit_metadata["named_content_fields_edit"]
    assert isinstance(raw_edit, dict)
    raw_edit.pop("schema_version")

    prepared = await _prepare_planner_request_for_test(
        planner,
        conversation=conversation,
        completion_model_route=_route(),
        persisted_planning_state=state,
    )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, ConfirmRequirements)
    assert all(
        field.name != "legacy_root"
        for field in prepared.server_decision.payload.named_content_fields
    )


@pytest.mark.asyncio
async def test_editing_the_field_list_asks_the_user_to_confirm_the_new_summary() -> (
    None
):
    planner = _make_planner()
    state = _named_fields_state()
    shown = build_requirements_disclosure(state, ui_language="sv")

    prepared = await _prepare_planner_request_for_test(
        planner,
        conversation=_field_edit_conversation(shown, "beslut"),
        completion_model_route=_route(),
        persisted_planning_state=state,
    )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, ConfirmRequirements)
    assert (
        prepared.server_decision.payload.requirements_version
        != shown.requirements_version
    )


@pytest.mark.asyncio
async def test_an_unchanged_field_list_leaves_the_requirements_alone() -> None:
    """A no-op edit has to be a no-op.

    Submitting the list back unchanged must not manufacture a second version of
    the same requirements and ask the user to confirm what they already read.
    Both disclosures are derived through the turn itself, because that is the
    path a re-submitted list actually travels.
    """

    planner = _make_planner()
    state = _named_fields_state()
    disclosed = await _prepare_planner_request_for_test(
        planner,
        conversation=_named_fields_interview(),
        completion_model_route=_route(),
        persisted_planning_state=state,
    )
    assert isinstance(disclosed, ServerOutputPrepared)
    assert isinstance(disclosed.server_decision, ConfirmRequirements)
    shown = disclosed.server_decision.payload

    prepared = await _prepare_planner_request_for_test(
        planner,
        conversation=_field_edit_conversation(
            shown,
            *[field.id for field in shown.named_content_fields],
        ),
        completion_model_route=_route(),
        persisted_planning_state=state,
    )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, ConfirmRequirements)
    assert prepared.server_decision.payload == shown


def _confirmed_disclosure_with_assumption_rows() -> RequirementsSummaryPayload:
    """A disclosure with two assumption rows of very different length."""

    state = _document_architecture_state()
    state.mapped_file_limit = MappedFileLimit(
        proposed_value=20,
        accepted_value=10,
        provenance="authored",
    )
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                name=f"falt_{index}",
                label=f"Fält {index}",
                type="select",
                options=[
                    f"Antagande {index}: "
                    f"{'redovisa varje beslut i en egen tabellrad. ' * 6}"
                ],
                provenance="user_confirmed",
            ),
            purpose="whole_flow",
            structured_answer_message_id=f"answer-{index}",
        )
        for index in range(20)
    ]
    disclosure = build_requirements_disclosure(state, ui_language="en")
    assert len(disclosure.assumptions) >= 2
    return disclosure


def test_replayed_requirements_keep_the_assumptions_that_fit_the_model() -> None:
    """The disclosure is bounded by evidence; the prompt is bounded by the model.

    A confirmed disclosure lists every assumption the user attested to, and a
    runtime form alone can contribute paragraphs. Replaying it whole would let
    a confirmable session become one that cannot produce a proposal at all, so
    the budget decides how many confirmed assumptions are replayed while the
    confirmed decisions always stay.
    """

    disclosure = _confirmed_disclosure_with_assumption_rows()

    def fits_up_to(limit: int) -> Callable[[RequirementsSummaryPayload | None], bool]:
        return lambda payload: payload is not None and (
            sum(len(row) for row in payload.assumptions) <= limit
        )

    whole = _fit_replayed_requirements(disclosure, fits=fits_up_to(10**9))
    assert whole is disclosure

    trimmed = _fit_replayed_requirements(
        disclosure, fits=fits_up_to(len(disclosure.assumptions[0]))
    )
    assert trimmed is not None
    assert trimmed.assumptions == disclosure.assumptions[:1]
    assert trimmed.key_decisions == disclosure.key_decisions

    bare = _fit_replayed_requirements(disclosure, fits=fits_up_to(0))
    assert bare is not None
    assert bare.assumptions == []
    assert bare.key_decisions == disclosure.key_decisions


def test_replayed_requirements_whose_core_cannot_fit_are_rejected() -> None:
    disclosure = _confirmed_disclosure_with_assumption_rows()

    with pytest.raises(AIBuilderKnownProviderRejectionException):
        _fit_replayed_requirements(disclosure, fits=lambda _payload: False)
