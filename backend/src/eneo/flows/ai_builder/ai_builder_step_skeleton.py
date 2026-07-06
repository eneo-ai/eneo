from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Literal

from eneo.flows.ai_builder.ai_builder_new_step_compiler import derive_output_mode
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    DocumentDeliveryMode,
    NewStepDraft,
    PreviousFieldRef,
    PreviousOutputRef,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_structured_field_paths import (
    missing_draft_field_path,
)
from eneo.flows.ai_builder.pattern_registry import (
    EXTRACT_TEMPLATE_VARIABLES_STEP,
    FLOW_INPUT_AUDIO_TRANSCRIPTION,
    PATTERN_REGISTRY,
    TEMPLATE_FILL_DOCX_STEP,
    TERMINAL_ARTIFACT_STEP,
    ChainStepToken,
    compiled_chain_pattern_ids,
)
from eneo.flows.ai_builder.planning_state import AggregationIntent
from eneo.flows.flow_authoring_spec import (
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode

StepSkeletonRole = Literal[
    "backend_fixed",
    "semantic_required",
]
MechanicsPolicy = Literal["locked", "fill_missing", "reject_if_conflicting"]
SemanticPolicy = Literal[
    "backend_default",
    "required_from_intent",
    "optional_from_intent",
]
SemanticOutputPolicy = Literal["final_output_on_last_semantic", "text_for_all_semantic"]
SemanticFanInPolicy = Literal["none", "last_semantic"]

_DOCX_TEMPLATE_PATTERN_ID = "document_to_docx_template"
_AUDIO_ARTIFACT_PATTERN_ID = "audio_to_artifact_report"
_COMPARISON_PATTERN_ID = "comparison"
_COMPILED_PATTERN_MATERIALIZER_IDS = frozenset(
    {
        _DOCX_TEMPLATE_PATTERN_ID,
        _AUDIO_ARTIFACT_PATTERN_ID,
    }
)
_FILE_INPUT_TYPES = {InputType.AUDIO, InputType.DOCUMENT, InputType.FILE}
_DOCUMENT_OUTPUT_TYPES = {OutputType.DOCX, OutputType.PDF}
_MIN_DOCUMENT_BODY_FAN_IN_PHASES = 3
_LEGAL_STEP_SKELETON_POLICIES = frozenset(
    {
        ("backend_fixed", "locked", "backend_default"),
        ("semantic_required", "fill_missing", "required_from_intent"),
    }
)


@dataclass(frozen=True, slots=True)
class CompiledChainStepTemplate:
    """Default step text for backend-added skeleton and chain steps."""

    name: str
    instructions: str


@dataclass(frozen=True, slots=True)
class StepSkeletonSemanticContent:
    name: str
    instructions: str
    requested_output_type: OutputType | None = None
    output_fields: tuple[StructuredFieldDraft, ...] = ()
    uses_form_fields: tuple[str, ...] = ()
    uses_previous_fields: tuple[PreviousFieldRef, ...] = ()
    uses_previous_outputs: tuple[PreviousOutputRef, ...] = ()
    model_ref: str | None = None
    knowledge_refs: tuple[str, ...] = ()
    mcp_server_refs: tuple[str, ...] = ()
    mcp_tool_refs: tuple[str, ...] = ()
    citations_requested: bool = False
    review_mode: FlowStepReviewMode | None = None


@dataclass(frozen=True, slots=True)
class StepSkeletonPatternResolution:
    pattern_ids: tuple[str, ...]
    chain_steps: tuple[ChainStepToken, ...]


@dataclass(frozen=True, slots=True)
class StepSkeletonOutputTypeDrift:
    slot_id: str
    slot_ordinal: int
    requested_output_type: OutputType
    enforced_output_type: OutputType
    dropped_output_fields: bool = False


@dataclass(frozen=True, slots=True)
class StepSkeletonComposition:
    """Create-draft steps plus semantic drift detected during skeleton fill."""

    steps: tuple[NewStepDraft, ...]
    output_type_drifts: tuple[StepSkeletonOutputTypeDrift, ...]
    document_body_writer_step_indexes: tuple[int, ...] = ()


_COMPILED_CHAIN_STEP_TEMPLATES = MappingProxyType(
    {
        FLOW_INPUT_AUDIO_TRANSCRIPTION: CompiledChainStepTemplate(
            name="Transcribe audio",
            instructions=(
                "Transcribe the uploaded audio into text before downstream "
                "analysis or artifact generation."
            ),
        ),
        EXTRACT_TEMPLATE_VARIABLES_STEP: CompiledChainStepTemplate(
            name="Extract template variables",
            instructions=(
                "Extract the stable fields and source facts needed before "
                "filling the DOCX template."
            ),
        ),
        TEMPLATE_FILL_DOCX_STEP: CompiledChainStepTemplate(
            name="Fill DOCX template",
            instructions=(
                "Fill the DOCX template from the prepared content. Preserve "
                "the user's requested scope and terminology."
            ),
        ),
        TERMINAL_ARTIFACT_STEP: CompiledChainStepTemplate(
            name="Create final output",
            instructions=(
                "Create the final output from the reviewed analysis. Preserve "
                "the user's requested scope, ordering, and constraints."
            ),
        ),
    }
)

_SWEDISH_COMPILED_CHAIN_STEP_TEMPLATES = MappingProxyType(
    {
        FLOW_INPUT_AUDIO_TRANSCRIPTION: CompiledChainStepTemplate(
            name="Transkribera ljud",
            instructions=(
                "Transkribera det uppladdade ljudet till text innan analys "
                "eller artefaktgenerering."
            ),
        ),
        EXTRACT_TEMPLATE_VARIABLES_STEP: CompiledChainStepTemplate(
            name="Extrahera mallvariabler",
            instructions=(
                "Extrahera stabila fält och källfakta som behövs innan "
                "DOCX-mallen fylls."
            ),
        ),
        TEMPLATE_FILL_DOCX_STEP: CompiledChainStepTemplate(
            name="Fyll DOCX-mall",
            instructions=(
                "Fyll DOCX-mallen med det förberedda innehållet. Bevara "
                "användarens önskade omfattning och terminologi."
            ),
        ),
        TERMINAL_ARTIFACT_STEP: CompiledChainStepTemplate(
            name="Skapa slutresultat",
            instructions=(
                "Skapa slutresultatet från den granskade analysen. Bevara "
                "användarens önskade omfattning, ordning och begränsningar."
            ),
        ),
    }
)


@dataclass(frozen=True, slots=True)
class StepSkeleton:
    """Backend mechanics contract that leaves semantic content to the intent.

    Mechanics and semantic policies stay separate because create mode fills
    empty slots, while edit mode must preserve valid user-authored mechanics
    and reject conflicting mechanics instead of overwriting them silently.
    Expanded semantic slots share a template `slot_id`; use `slot_ordinal`
    when matching a concrete intent step to a concrete skeleton slot.
    """

    slot_ordinal: int
    slot_id: str
    role: StepSkeletonRole
    mechanics_policy: MechanicsPolicy
    semantic_policy: SemanticPolicy
    chain_token: ChainStepToken | None
    default_name: str
    default_instructions: str
    input_source: InputSource
    input_type: InputType
    output_type: OutputType
    output_mode: OutputMode
    document_delivery_mode: DocumentDeliveryMode
    runtime_required: bool
    runtime_max_files: int | None
    output_fields: tuple[StructuredFieldDraft, ...] = ()

    def __post_init__(self) -> None:
        if self.slot_ordinal < 0:
            raise ValueError("StepSkeleton.slot_ordinal must be non-negative")
        if not self.slot_id.strip():
            raise ValueError("StepSkeleton.slot_id must be non-empty")
        if not self.default_name.strip():
            raise ValueError("StepSkeleton.default_name must be non-empty")
        if not self.default_instructions.strip():
            raise ValueError("StepSkeleton.default_instructions must be non-empty")
        policy = (self.role, self.mechanics_policy, self.semantic_policy)
        if policy not in _LEGAL_STEP_SKELETON_POLICIES:
            raise ValueError(
                "Illegal StepSkeleton policy tuple: "
                f"{self.role}/{self.mechanics_policy}/{self.semantic_policy}"
            )
        if self.role == "backend_fixed" and self.chain_token is None:
            raise ValueError("Backend-fixed skeleton slots require a chain token")
        if self.role != "backend_fixed" and self.chain_token is not None:
            raise ValueError("Only backend-fixed skeleton slots may carry chain tokens")
        has_runtime_constraints = (
            self.runtime_required or self.runtime_max_files is not None
        )
        if self.slot_ordinal > 0 and has_runtime_constraints:
            raise ValueError(
                "Only the first skeleton slot may own runtime input constraints"
            )
        if has_runtime_constraints and self.input_type not in _FILE_INPUT_TYPES:
            raise ValueError(
                "Runtime input constraints require a file-capable input type"
            )
        if (
            self.document_delivery_mode == "template_fill"
            and self.output_type != OutputType.DOCX
        ):
            raise ValueError("template_fill document delivery requires DOCX output")
        if self.output_fields and self.output_type != OutputType.JSON:
            raise ValueError("output_fields require JSON output")


@dataclass(frozen=True, slots=True)
class StepSkeletonPlan:
    prefix_slots: tuple[StepSkeleton, ...]
    semantic_slot: StepSkeleton
    suffix_slots: tuple[StepSkeleton, ...]
    final_output_type: OutputType
    final_output_mode: OutputMode | None
    semantic_output_policy: SemanticOutputPolicy
    fan_in_policy: SemanticFanInPolicy = "none"
    minimum_semantic_slots: int = 1
    runtime_required: bool = True
    runtime_max_files: int | None = None
    ui_language: str | None = None

    def __post_init__(self) -> None:
        if self.minimum_semantic_slots < 1:
            raise ValueError("StepSkeletonPlan requires at least one semantic slot")
        for slot in (*self.prefix_slots, *self.suffix_slots):
            if slot.role != "backend_fixed":
                raise ValueError("Prefix and suffix skeleton slots must be fixed")
        if self.semantic_slot.role != "semantic_required":
            raise ValueError("StepSkeletonPlan.semantic_slot must be semantic_required")

    @property
    def minimum_slots(self) -> tuple[StepSkeleton, ...]:
        return self.slots_for_semantic_count(self.minimum_semantic_slots)

    def slots_for_semantic_count(
        self,
        semantic_count: int,
    ) -> tuple[StepSkeleton, ...]:
        if semantic_count < self.minimum_semantic_slots:
            raise ValueError(
                "semantic_count must be at least "
                f"{self.minimum_semantic_slots}; got {semantic_count}"
            )

        semantic_slots = tuple(
            self._semantic_slot_at(index=index, semantic_count=semantic_count)
            for index in range(semantic_count)
        )
        return _renumber_slots(
            (
                *self.prefix_slots,
                *semantic_slots,
                *self.suffix_slots,
            ),
            runtime_required=self.runtime_required,
            runtime_max_files=self.runtime_max_files,
        )

    def compose(
        self,
        semantic_steps: Sequence[StepSkeletonSemanticContent],
    ) -> StepSkeletonComposition:
        """Fill semantic content into slots and return final create-step mechanics."""

        slots = self.slots_for_semantic_count(len(semantic_steps))
        steps: list[NewStepDraft] = []
        output_type_drifts: list[StepSkeletonOutputTypeDrift] = []
        document_body_writer_step_indexes: list[int] = []
        semantic_step_to_compiled_step: dict[int, int] = {}
        semantic_index = 0

        for slot_index, slot in enumerate(slots):
            if (
                _slot_renders_generated_document(slot)
                and steps
                and steps[-1].output_type != OutputType.TEXT
            ):
                body_slot = _terminal_artifact_slot(
                    slot_ordinal=len(steps),
                    input_source=InputSource.PREVIOUS_STEP,
                    final_output_type=OutputType.TEXT,
                    final_output_mode=None,
                    ui_language=self.ui_language,
                )
                body_step, _ = _compose_step_skeleton_slot(
                    slot=body_slot,
                    content=None,
                    prior_step=steps[-1],
                    allow_json_output=True,
                )
                steps.append(body_step)
                if _slot_writes_document_body(body_slot):
                    document_body_writer_step_indexes.append(len(steps) - 1)

            content: StepSkeletonSemanticContent | None = None
            semantic_step_number: int | None = None
            if slot.role == "semantic_required":
                semantic_step_number = semantic_index + 1
                content = semantic_steps[semantic_index]
                semantic_index += 1
                # Model refs are semantic-step numbered; compose owns compiled ordinals.
                content = _remap_semantic_previous_refs(
                    content,
                    semantic_step_to_compiled_step=semantic_step_to_compiled_step,
                    prior_steps=steps,
                )
            step, drift = _compose_step_skeleton_slot(
                slot=slot,
                content=content,
                prior_step=steps[-1] if steps else None,
                allow_json_output=_semantic_json_output_allowed(
                    slot_index=slot_index,
                    slots=slots,
                ),
            )
            steps.append(step)
            if semantic_step_number is not None:
                semantic_step_to_compiled_step[semantic_step_number] = len(steps)
            if _slot_writes_document_body(slot):
                document_body_writer_step_indexes.append(len(steps) - 1)
            _mark_body_writer_before_generated_renderer(
                slot=slot,
                steps=steps,
                document_body_writer_step_indexes=document_body_writer_step_indexes,
            )
            if drift is not None:
                output_type_drifts.append(drift)

        if (
            steps
            and self.final_output_type in _DOCUMENT_OUTPUT_TYPES
            and steps[-1].output_type != OutputType.TEXT
            and steps[-1].output_type != self.final_output_type
        ):
            body_slot = _terminal_artifact_slot(
                slot_ordinal=len(steps),
                input_source=InputSource.PREVIOUS_STEP,
                final_output_type=OutputType.TEXT,
                final_output_mode=None,
                ui_language=self.ui_language,
            )
            body_step, _ = _compose_step_skeleton_slot(
                slot=body_slot,
                content=None,
                prior_step=steps[-1],
                allow_json_output=True,
            )
            steps.append(body_step)
            if _slot_writes_document_body(body_slot):
                document_body_writer_step_indexes.append(len(steps) - 1)

        if steps and steps[-1].output_type != self.final_output_type:
            terminal_slot = _terminal_artifact_slot(
                slot_ordinal=len(steps),
                input_source=InputSource.PREVIOUS_STEP,
                final_output_type=self.final_output_type,
                final_output_mode=self.final_output_mode,
                ui_language=self.ui_language,
            )
            terminal_step, _ = _compose_step_skeleton_slot(
                slot=terminal_slot,
                content=None,
                prior_step=steps[-1],
                allow_json_output=True,
            )
            steps.append(terminal_step)
            if _slot_writes_document_body(terminal_slot):
                document_body_writer_step_indexes.append(len(steps) - 1)
            _mark_body_writer_before_generated_renderer(
                slot=terminal_slot,
                steps=steps,
                document_body_writer_step_indexes=document_body_writer_step_indexes,
            )
        return StepSkeletonComposition(
            steps=tuple(steps),
            output_type_drifts=tuple(output_type_drifts),
            document_body_writer_step_indexes=tuple(document_body_writer_step_indexes),
        )

    def _semantic_slot_at(
        self,
        *,
        index: int,
        semantic_count: int,
    ) -> StepSkeleton:
        ordinal = len(self.prefix_slots) + index
        is_last = index == semantic_count - 1
        input_source = self._semantic_input_source(
            ordinal=ordinal,
            is_last=is_last,
            semantic_count=semantic_count,
        )
        input_type = self._semantic_input_type(
            index=index,
            input_source=input_source,
        )
        output_type = self._semantic_output_type(is_last=is_last)
        owns_runtime_input = _owns_runtime_input_constraints(
            slot_ordinal=ordinal,
            input_type=input_type,
        )
        return replace(
            self.semantic_slot,
            slot_ordinal=ordinal,
            input_source=input_source,
            input_type=input_type,
            output_type=output_type,
            output_mode=self._semantic_output_mode(
                index=index,
                input_type=input_type,
                output_type=output_type,
                is_last=is_last,
            ),
            document_delivery_mode=_document_delivery_mode_for_output(
                output_type=output_type,
                final_output_mode=self.final_output_mode if is_last else None,
            ),
            runtime_required=owns_runtime_input and self.runtime_required,
            runtime_max_files=self.runtime_max_files if owns_runtime_input else None,
        )

    def _semantic_input_source(
        self,
        *,
        ordinal: int,
        is_last: bool,
        semantic_count: int,
    ) -> InputSource:
        if self._last_document_body_reads_all_prior_work(
            ordinal=ordinal,
            is_last=is_last,
            semantic_count=semantic_count,
        ):
            return InputSource.ALL_PREVIOUS_STEPS
        if (
            self.fan_in_policy == "last_semantic"
            and is_last
            and (ordinal > 0 or semantic_count > 1)
        ):
            return InputSource.ALL_PREVIOUS_STEPS
        if ordinal == 0:
            return InputSource.FLOW_INPUT
        return InputSource.PREVIOUS_STEP

    def _last_document_body_reads_all_prior_work(
        self,
        *,
        ordinal: int,
        is_last: bool,
        semantic_count: int,
    ) -> bool:
        if self.final_output_type not in _DOCUMENT_OUTPUT_TYPES:
            return False
        if self.semantic_output_policy != "text_for_all_semantic":
            return False
        if not is_last or ordinal == 0:
            return False
        # Three or more semantic phases means the last text step is a document
        # body synthesis step; previous_step alone can drop earlier structured
        # sections before the backend DOCX/PDF renderer runs.
        return semantic_count >= _MIN_DOCUMENT_BODY_FAN_IN_PHASES

    def _semantic_input_type(
        self,
        *,
        index: int,
        input_source: InputSource,
    ) -> InputType:
        if input_source == InputSource.ALL_PREVIOUS_STEPS:
            return InputType.TEXT
        if index == 0:
            return self.semantic_slot.input_type
        return InputType.TEXT

    def _semantic_output_type(self, *, is_last: bool) -> OutputType:
        if self.semantic_output_policy == "final_output_on_last_semantic" and is_last:
            return self.final_output_type
        return OutputType.TEXT

    def _semantic_output_mode(
        self,
        *,
        index: int,
        input_type: InputType,
        output_type: OutputType,
        is_last: bool,
    ) -> OutputMode:
        if (
            index == 0
            and input_type == InputType.AUDIO
            and output_type == OutputType.TEXT
        ):
            return OutputMode.TRANSCRIBE_ONLY
        if self.semantic_output_policy == "final_output_on_last_semantic" and is_last:
            return _final_output_mode(
                input_type=input_type,
                final_output_type=output_type,
                final_output_mode=self.final_output_mode,
            )
        return OutputMode.PASS_THROUGH


def materialize_step_skeleton(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
    aggregation_intent: AggregationIntent = "linear",
    runtime_required: bool = True,
    runtime_max_files: int | None = None,
    ui_language: str | None = None,
) -> StepSkeletonPlan:
    pattern_resolution = resolve_step_skeleton_patterns(
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        pattern_ids=pattern_ids,
        chain_steps=chain_steps,
    )
    compiled_pattern_ids = compiled_chain_pattern_ids(pattern_resolution.pattern_ids)
    if len(compiled_pattern_ids) > 1:
        raise ValueError(
            "Only one compiler-backed pattern chain can be materialized at a time; "
            f"got {sorted(compiled_pattern_ids)}"
        )

    if _DOCX_TEMPLATE_PATTERN_ID in compiled_pattern_ids:
        return _materialize_docx_template_skeleton(
            runtime_input_type=runtime_input_type,
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            aggregation_intent=aggregation_intent,
            ui_language=ui_language,
        )
    if _AUDIO_ARTIFACT_PATTERN_ID in compiled_pattern_ids:
        return _materialize_audio_artifact_skeleton(
            final_output_type=final_output_type,
            aggregation_intent=aggregation_intent,
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            ui_language=ui_language,
        )
    if _requires_comparison_skeleton(
        pattern_ids=pattern_resolution.pattern_ids,
        aggregation_intent=aggregation_intent,
    ):
        return _materialize_comparison_skeleton(
            runtime_input_type=runtime_input_type,
            final_output_type=final_output_type,
            final_output_mode=final_output_mode,
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            ui_language=ui_language,
        )
    return _materialize_linear_skeleton(
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        aggregation_intent=aggregation_intent,
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        ui_language=ui_language,
    )


def _compiled_chain_step_template(
    chain_token: ChainStepToken,
    *,
    ui_language: str | None,
) -> CompiledChainStepTemplate:
    if ui_language == "sv":
        return _SWEDISH_COMPILED_CHAIN_STEP_TEMPLATES[chain_token]
    return _COMPILED_CHAIN_STEP_TEMPLATES[chain_token]


def materialized_compiled_pattern_ids() -> frozenset[str]:
    return _COMPILED_PATTERN_MATERIALIZER_IDS


def _slot_writes_document_body(slot: StepSkeleton) -> bool:
    return (
        slot.chain_token == TERMINAL_ARTIFACT_STEP
        and slot.output_type == OutputType.TEXT
    )


def _mark_body_writer_before_generated_renderer(
    *,
    slot: StepSkeleton,
    steps: list[NewStepDraft],
    document_body_writer_step_indexes: list[int],
) -> None:
    if not _slot_renders_generated_document(slot) or len(steps) < 2:
        return
    body_writer_index = len(steps) - 2
    if body_writer_index in document_body_writer_step_indexes:
        return
    if steps[body_writer_index].output_type != OutputType.TEXT:
        return
    document_body_writer_step_indexes.append(body_writer_index)


def _slot_renders_generated_document(slot: StepSkeleton) -> bool:
    return (
        slot.chain_token == TERMINAL_ARTIFACT_STEP
        and slot.input_type == InputType.TEXT
        and slot.output_type in _DOCUMENT_OUTPUT_TYPES
        and slot.document_delivery_mode == "generated"
    )


def _compose_step_skeleton_slot(
    *,
    slot: StepSkeleton,
    content: StepSkeletonSemanticContent | None,
    prior_step: NewStepDraft | None,
    allow_json_output: bool,
) -> tuple[NewStepDraft, StepSkeletonOutputTypeDrift | None]:
    output_type, output_type_drift = _compose_output_type(
        slot=slot,
        content=content,
        allow_json_output=allow_json_output,
    )
    input_type = _compose_input_type(
        slot=slot,
        content=content,
        prior_step=prior_step,
    )
    output_fields = _compose_output_fields(
        slot=slot,
        content=content,
        output_type=output_type,
    )
    return (
        NewStepDraft(
            name=content.name if content is not None else slot.default_name,
            instructions=(
                content.instructions
                if content is not None
                else slot.default_instructions
            ),
            input_source=slot.input_source,
            input_type=input_type,
            output_type=output_type,
            model_ref=content.model_ref if content is not None else None,
            knowledge_refs=list(content.knowledge_refs) if content is not None else [],
            mcp_server_refs=(
                list(content.mcp_server_refs) if content is not None else []
            ),
            mcp_tool_refs=list(content.mcp_tool_refs) if content is not None else [],
            runtime_required=slot.runtime_required,
            runtime_max_files=slot.runtime_max_files,
            uses_form_fields=(
                list(content.uses_form_fields) if content is not None else []
            ),
            uses_previous_fields=(
                list(content.uses_previous_fields) if content is not None else []
            ),
            uses_previous_outputs=(
                list(content.uses_previous_outputs) if content is not None else []
            ),
            document_delivery_mode=(
                "not_applicable"
                if output_type == OutputType.JSON
                else slot.document_delivery_mode
            ),
            citations_requested=(
                content is not None
                and content.citations_requested
                and output_type == OutputType.TEXT
            ),
            review_mode=content.review_mode if content is not None else None,
            output_fields=output_fields,
        ),
        output_type_drift,
    )


def _remap_semantic_previous_refs(
    content: StepSkeletonSemanticContent,
    *,
    semantic_step_to_compiled_step: dict[int, int],
    prior_steps: list[NewStepDraft],
) -> StepSkeletonSemanticContent:
    if not content.uses_previous_fields and not content.uses_previous_outputs:
        return content
    return replace(
        content,
        uses_previous_fields=_remap_semantic_previous_field_refs(
            content.uses_previous_fields,
            semantic_step_to_compiled_step=semantic_step_to_compiled_step,
            prior_steps=prior_steps,
        ),
        uses_previous_outputs=_remap_semantic_previous_output_refs(
            content.uses_previous_outputs,
            semantic_step_to_compiled_step=semantic_step_to_compiled_step,
            prior_steps=prior_steps,
        ),
    )


def _remap_semantic_previous_field_refs(
    refs: tuple[PreviousFieldRef, ...],
    *,
    semantic_step_to_compiled_step: dict[int, int],
    prior_steps: list[NewStepDraft],
) -> tuple[PreviousFieldRef, ...]:
    remapped: list[PreviousFieldRef] = []
    for ref in refs:
        compiled_step_number = semantic_step_to_compiled_step.get(ref.from_step)
        if compiled_step_number is None:
            continue
        source_step = prior_steps[compiled_step_number - 1]
        if (
            source_step.output_type != OutputType.JSON
            or source_step.output_fields is None
        ):
            continue
        if missing_draft_field_path(source_step.output_fields, ref.field_path):
            continue
        remapped.append(ref.model_copy(update={"from_step": compiled_step_number}))
    return tuple(remapped)


def _remap_semantic_previous_output_refs(
    refs: tuple[PreviousOutputRef, ...],
    *,
    semantic_step_to_compiled_step: dict[int, int],
    prior_steps: list[NewStepDraft],
) -> tuple[PreviousOutputRef, ...]:
    remapped: list[PreviousOutputRef] = []
    for ref in refs:
        compiled_step_number = semantic_step_to_compiled_step.get(ref.from_step)
        if compiled_step_number is None:
            continue
        source_step = prior_steps[compiled_step_number - 1]
        if source_step.output_type != OutputType.TEXT:
            continue
        remapped.append(ref.model_copy(update={"from_step": compiled_step_number}))
    return tuple(remapped)


def _compose_output_fields(
    *,
    slot: StepSkeleton,
    content: StepSkeletonSemanticContent | None,
    output_type: OutputType,
) -> list[StructuredFieldDraft] | None:
    if output_type != OutputType.JSON:
        return None
    if content is None:
        return list(slot.output_fields) or None
    if content.output_fields:
        return list(content.output_fields)
    return list(slot.output_fields) or None


def _compose_output_type(
    *,
    slot: StepSkeleton,
    content: StepSkeletonSemanticContent | None,
    allow_json_output: bool,
) -> tuple[OutputType, StepSkeletonOutputTypeDrift | None]:
    if content is None:
        return slot.output_type, None

    if _semantic_content_requests_json(content):
        if (
            allow_json_output
            and slot.output_type not in _DOCUMENT_OUTPUT_TYPES
            and not _flow_input_audio_text_slot(slot)
        ):
            return OutputType.JSON, None
        if slot.output_type != OutputType.JSON:
            return (
                slot.output_type,
                StepSkeletonOutputTypeDrift(
                    slot_id=slot.slot_id,
                    slot_ordinal=slot.slot_ordinal,
                    requested_output_type=OutputType.JSON,
                    enforced_output_type=slot.output_type,
                    dropped_output_fields=bool(content.output_fields),
                ),
            )

    requested_output_type = content.requested_output_type
    if requested_output_type is None or requested_output_type == slot.output_type:
        return slot.output_type, None

    return (
        slot.output_type,
        StepSkeletonOutputTypeDrift(
            slot_id=slot.slot_id,
            slot_ordinal=slot.slot_ordinal,
            requested_output_type=requested_output_type,
            enforced_output_type=slot.output_type,
        ),
    )


def _semantic_json_output_allowed(
    *,
    slot_index: int,
    slots: tuple[StepSkeleton, ...],
) -> bool:
    slot = slots[slot_index]
    if slot.role != "semantic_required":
        return True

    remaining_slots = slots[slot_index + 1 :]
    if any(
        remaining_slot.role == "semantic_required" for remaining_slot in remaining_slots
    ):
        return True

    backend_text_consumers = [
        remaining_slot
        for remaining_slot in remaining_slots
        if _backend_fixed_text_consumer(remaining_slot)
    ]
    if not backend_text_consumers:
        return True

    return all(
        _slot_renders_generated_document(remaining_slot)
        for remaining_slot in backend_text_consumers
    )


def _backend_fixed_text_consumer(slot: StepSkeleton) -> bool:
    return (
        slot.role == "backend_fixed"
        and slot.input_type == InputType.TEXT
        and slot.input_source
        in {InputSource.PREVIOUS_STEP, InputSource.ALL_PREVIOUS_STEPS}
    )


def _semantic_content_requests_json(content: StepSkeletonSemanticContent) -> bool:
    return (
        bool(content.output_fields) or content.requested_output_type == OutputType.JSON
    )


def _flow_input_audio_text_slot(slot: StepSkeleton) -> bool:
    return (
        slot.input_source == InputSource.FLOW_INPUT
        and slot.input_type == InputType.AUDIO
        and slot.output_type == OutputType.TEXT
    )


def _compose_input_type(
    *,
    slot: StepSkeleton,
    content: StepSkeletonSemanticContent | None,
    prior_step: NewStepDraft | None,
) -> InputType:
    if slot.mechanics_policy == "locked":
        return slot.input_type
    if slot.input_source != InputSource.PREVIOUS_STEP or prior_step is None:
        return slot.input_type
    if slot.input_type != InputType.TEXT:
        return slot.input_type
    if content is not None and content.uses_form_fields:
        return InputType.TEXT
    if prior_step.output_type == OutputType.JSON:
        return InputType.JSON
    return slot.input_type


def default_structured_output_fields() -> list[StructuredFieldDraft]:
    return [
        StructuredFieldDraft(
            name="source_facts",
            field_type="array",
            description="Important source facts extracted from the input material.",
            item_fields=[
                StructuredFieldDraft(
                    name="fact",
                    field_type="string",
                    description="A concise source fact.",
                ),
                StructuredFieldDraft(
                    name="source_note",
                    field_type="string",
                    description="Where the fact came from or why it matters.",
                    required=False,
                ),
            ],
        ),
        StructuredFieldDraft(
            name="uncertainties",
            field_type="array",
            description="Missing, ambiguous, or uncertain information.",
            item_fields=[
                StructuredFieldDraft(
                    name="issue",
                    field_type="string",
                    description="A missing or uncertain point.",
                )
            ],
            required=False,
        ),
    ]


def default_final_step_name(
    output_type: OutputType,
    *,
    ui_language: str | None,
) -> str:
    if ui_language == "sv":
        if output_type == OutputType.DOCX:
            return "Skapa DOCX"
        if output_type == OutputType.PDF:
            return "Skapa PDF"
        if output_type == OutputType.JSON:
            return "Skapa strukturerad JSON"
        return "Skapa slutresultat"

    if output_type == OutputType.DOCX:
        return "Create DOCX"
    if output_type == OutputType.PDF:
        return "Create PDF"
    if output_type == OutputType.JSON:
        return "Create structured JSON"
    return "Create final answer"


def default_final_step_instructions(*, ui_language: str | None) -> str:
    if ui_language == "sv":
        return (
            "Skapa slutresultatet från föregående strukturerade arbete. "
            "Bevara användarens önskade omfattning, ordning och begränsningar."
        )
    return (
        "Create the final output from the previous structured work. "
        "Preserve the user's requested scope, ordering, and constraints."
    )


def default_render_step_instructions(
    output_type: OutputType,
    *,
    ui_language: str | None,
) -> str:
    output_label = output_type.value.upper()
    if ui_language == "sv":
        return f"Rendera föregående text som {output_label} utan att ändra innehållet."
    return f"Render the previous text as a {output_label} without changing the content."


def _semantic_default_name(*, slot_id: str, ui_language: str | None) -> str:
    if ui_language == "sv":
        return {
            "audio_analysis": "Analysera transkript",
            "comparison_semantic_step": "Analysera jämförelsematerial",
            "final_response": "Bearbeta svarsinnehåll",
            "structured_analysis": "Analysera strukturerat underlag",
            "template_content": "Förbered mallinnehåll",
        }.get(slot_id, "Analysera underlag")
    return {
        "audio_analysis": "Analyze transcript",
        "comparison_semantic_step": "Analyze comparison material",
        "final_response": "Draft response content",
        "structured_analysis": "Analyze structured material",
        "template_content": "Prepare template content",
    }.get(slot_id, "Analyze material")


def _semantic_default_instructions(*, slot_id: str, ui_language: str | None) -> str:
    if ui_language == "sv":
        return {
            "audio_analysis": (
                "Analysera det transkriberade ljudet och skapa önskat resultat."
            ),
            "comparison_semantic_step": (
                "Analysera jämförelsematerialet och bevara önskad omfattning."
            ),
            "final_response": (
                "Bearbeta underlaget till ett svar enligt användarens önskemål."
            ),
            "structured_analysis": (
                "Analysera det strukturerade underlaget enligt användarens önskemål."
            ),
            "template_content": ("Förbered innehållet som ska placeras i DOCX-mallen."),
        }.get(slot_id, "Analysera underlaget enligt användarens önskemål.")
    return {
        "audio_analysis": (
            "Analyze the transcribed audio and create the requested output."
        ),
        "comparison_semantic_step": (
            "Analyze the comparison material and preserve the requested scope."
        ),
        "final_response": ("Draft response content according to the user's request."),
        "structured_analysis": (
            "Analyze the structured source material according to the request."
        ),
        "template_content": (
            "Prepare the content that should be placed in the DOCX template."
        ),
    }.get(slot_id, "Analyze the material according to the request.")


def resolve_step_skeleton_patterns(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
) -> StepSkeletonPatternResolution:
    skeleton_pattern_ids = list(pattern_ids)
    skeleton_chain_steps = list(chain_steps)
    for pattern_id in pattern_ids:
        pattern = PATTERN_REGISTRY.get(pattern_id)
        if pattern is None:
            continue
        _extend_missing_chain_steps(skeleton_chain_steps, pattern.chain_steps)

    if _should_materialize_template_fill(
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        pattern_ids=tuple(skeleton_pattern_ids),
        chain_steps=tuple(skeleton_chain_steps),
    ):
        pattern = PATTERN_REGISTRY[_DOCX_TEMPLATE_PATTERN_ID]
        skeleton_pattern_ids.append(pattern.id)
        _extend_missing_chain_steps(skeleton_chain_steps, pattern.chain_steps)

    if _should_materialize_audio_artifact(
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        pattern_ids=tuple(skeleton_pattern_ids),
        chain_steps=tuple(skeleton_chain_steps),
    ):
        pattern = PATTERN_REGISTRY[_AUDIO_ARTIFACT_PATTERN_ID]
        skeleton_pattern_ids.append(pattern.id)
        _extend_missing_chain_steps(skeleton_chain_steps, pattern.chain_steps)

    return StepSkeletonPatternResolution(
        pattern_ids=tuple(skeleton_pattern_ids),
        chain_steps=tuple(skeleton_chain_steps),
    )


def _extend_missing_chain_steps(
    target: list[ChainStepToken],
    chain_steps: tuple[ChainStepToken, ...],
) -> None:
    for chain_step in chain_steps:
        if chain_step not in target:
            target.append(chain_step)


def _should_materialize_template_fill(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
) -> bool:
    if _chain_requests_docx_template_fill(
        pattern_ids=pattern_ids,
        chain_steps=chain_steps,
    ):
        return False
    return (
        runtime_input_type in {InputType.DOCUMENT, InputType.FILE}
        and final_output_type == OutputType.DOCX
        and final_output_mode == OutputMode.TEMPLATE_FILL
    )


def _should_materialize_audio_artifact(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
) -> bool:
    if _chain_requests_audio_artifact(
        pattern_ids=pattern_ids,
        chain_steps=chain_steps,
    ):
        return False
    return (
        runtime_input_type == InputType.AUDIO
        and final_output_type in _DOCUMENT_OUTPUT_TYPES
    )


def _materialize_docx_template_skeleton(
    *,
    runtime_input_type: InputType,
    runtime_required: bool,
    runtime_max_files: int | None,
    aggregation_intent: AggregationIntent,
    ui_language: str | None,
) -> StepSkeletonPlan:
    if runtime_input_type not in {InputType.DOCUMENT, InputType.FILE}:
        raise ValueError("DOCX template skeleton requires document or file input")
    return _skeleton_plan(
        prefix_slots=(
            _backend_fixed_slot(
                slot_ordinal=0,
                chain_token=EXTRACT_TEMPLATE_VARIABLES_STEP,
                input_source=InputSource.FLOW_INPUT,
                input_type=runtime_input_type,
                output_type=OutputType.JSON,
                output_mode=OutputMode.PASS_THROUGH,
                document_delivery_mode="not_applicable",
                runtime_required=runtime_required,
                runtime_max_files=runtime_max_files,
                output_fields=tuple(default_structured_output_fields()),
                ui_language=ui_language,
            ),
        ),
        semantic_slot=_semantic_required_slot(
            slot_ordinal=1,
            slot_id="template_content",
            input_source=InputSource.PREVIOUS_STEP,
            input_type=InputType.JSON,
            output_type=OutputType.TEXT,
            output_mode=OutputMode.PASS_THROUGH,
            document_delivery_mode="not_applicable",
            default_name=_semantic_default_name(
                slot_id="template_content",
                ui_language=ui_language,
            ),
            default_instructions=_semantic_default_instructions(
                slot_id="template_content",
                ui_language=ui_language,
            ),
        ),
        suffix_slots=(
            _backend_fixed_slot(
                slot_ordinal=2,
                chain_token=TEMPLATE_FILL_DOCX_STEP,
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.DOCX,
                output_mode=OutputMode.TEMPLATE_FILL,
                document_delivery_mode="template_fill",
                ui_language=ui_language,
            ),
        ),
        final_output_type=OutputType.DOCX,
        final_output_mode=OutputMode.TEMPLATE_FILL,
        semantic_output_policy="text_for_all_semantic",
        fan_in_policy=(
            "last_semantic"
            if aggregation_intent in {"aggregate", "compare"}
            else "none"
        ),
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        ui_language=ui_language,
    )


def _materialize_audio_artifact_skeleton(
    *,
    final_output_type: OutputType,
    aggregation_intent: AggregationIntent,
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
) -> StepSkeletonPlan:
    terminal_artifact_needed = final_output_type in _DOCUMENT_OUTPUT_TYPES
    terminal_input_source = (
        InputSource.ALL_PREVIOUS_STEPS
        if aggregation_intent in {"aggregate", "compare"}
        else InputSource.PREVIOUS_STEP
    )
    return _skeleton_plan(
        prefix_slots=(
            _backend_fixed_slot(
                slot_ordinal=0,
                chain_token=FLOW_INPUT_AUDIO_TRANSCRIPTION,
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                document_delivery_mode="not_applicable",
                runtime_required=runtime_required,
                runtime_max_files=runtime_max_files,
                ui_language=ui_language,
            ),
        ),
        semantic_slot=_semantic_required_slot(
            slot_ordinal=1,
            slot_id="audio_analysis",
            input_source=InputSource.PREVIOUS_STEP,
            input_type=InputType.TEXT,
            output_type=OutputType.TEXT
            if terminal_artifact_needed
            else final_output_type,
            output_mode=OutputMode.PASS_THROUGH,
            document_delivery_mode=_document_delivery_mode_for_output(
                output_type=OutputType.TEXT
                if terminal_artifact_needed
                else final_output_type,
                final_output_mode=None,
            ),
            default_name=_semantic_default_name(
                slot_id="audio_analysis",
                ui_language=ui_language,
            ),
            default_instructions=_semantic_default_instructions(
                slot_id="audio_analysis",
                ui_language=ui_language,
            ),
            ui_language=ui_language,
        ),
        suffix_slots=(
            (
                _terminal_artifact_slot(
                    slot_ordinal=2,
                    input_source=terminal_input_source,
                    final_output_type=final_output_type,
                    final_output_mode=None,
                    ui_language=ui_language,
                ),
            )
            if terminal_artifact_needed
            else ()
        ),
        final_output_type=final_output_type,
        final_output_mode=None,
        semantic_output_policy=(
            "text_for_all_semantic"
            if terminal_artifact_needed
            else "final_output_on_last_semantic"
        ),
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        ui_language=ui_language,
    )


def _requires_comparison_skeleton(
    *,
    pattern_ids: tuple[str, ...],
    aggregation_intent: AggregationIntent,
) -> bool:
    return aggregation_intent in {"aggregate", "compare"} or (
        _COMPARISON_PATTERN_ID in pattern_ids
    )


def _materialize_comparison_skeleton(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
) -> StepSkeletonPlan:
    terminal_artifact_needed = final_output_type in _DOCUMENT_OUTPUT_TYPES
    semantic_output_type = (
        OutputType.TEXT if terminal_artifact_needed else final_output_type
    )
    return _skeleton_plan(
        prefix_slots=(),
        semantic_slot=_semantic_required_slot(
            slot_ordinal=0,
            slot_id="comparison_semantic_step",
            input_source=InputSource.FLOW_INPUT,
            input_type=runtime_input_type,
            output_type=semantic_output_type,
            output_mode=_final_output_mode(
                input_type=runtime_input_type,
                final_output_type=semantic_output_type,
                final_output_mode=None
                if terminal_artifact_needed
                else final_output_mode,
            ),
            document_delivery_mode=_document_delivery_mode_for_output(
                output_type=semantic_output_type,
                final_output_mode=None
                if terminal_artifact_needed
                else final_output_mode,
            ),
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            default_name=_semantic_default_name(
                slot_id="comparison_semantic_step",
                ui_language=ui_language,
            ),
            default_instructions=_semantic_default_instructions(
                slot_id="comparison_semantic_step",
                ui_language=ui_language,
            ),
            ui_language=ui_language,
        ),
        suffix_slots=(),
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        semantic_output_policy=(
            "text_for_all_semantic"
            if terminal_artifact_needed
            else "final_output_on_last_semantic"
        ),
        fan_in_policy="last_semantic",
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        ui_language=ui_language,
    )


def _materialize_linear_skeleton(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    aggregation_intent: AggregationIntent,
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
) -> StepSkeletonPlan:
    terminal_artifact_needed = final_output_type in _DOCUMENT_OUTPUT_TYPES
    terminal_input_source = (
        InputSource.ALL_PREVIOUS_STEPS
        if aggregation_intent in {"aggregate", "compare"}
        else InputSource.PREVIOUS_STEP
    )
    semantic_output_type = (
        OutputType.TEXT if terminal_artifact_needed else final_output_type
    )
    return _skeleton_plan(
        prefix_slots=(),
        semantic_slot=_semantic_required_slot(
            slot_ordinal=0,
            slot_id="final_response",
            input_source=InputSource.FLOW_INPUT,
            input_type=runtime_input_type,
            output_type=semantic_output_type,
            output_mode=_final_output_mode(
                input_type=runtime_input_type,
                final_output_type=semantic_output_type,
                final_output_mode=None
                if terminal_artifact_needed
                else final_output_mode,
            ),
            document_delivery_mode=_document_delivery_mode_for_output(
                output_type=semantic_output_type,
                final_output_mode=None
                if terminal_artifact_needed
                else final_output_mode,
            ),
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            default_name=_semantic_default_name(
                slot_id="final_response",
                ui_language=ui_language,
            ),
            default_instructions=_semantic_default_instructions(
                slot_id="final_response",
                ui_language=ui_language,
            ),
            ui_language=ui_language,
        ),
        suffix_slots=(
            (
                _terminal_artifact_slot(
                    slot_ordinal=1,
                    input_source=terminal_input_source,
                    final_output_type=final_output_type,
                    final_output_mode=final_output_mode,
                    ui_language=ui_language,
                ),
            )
            if terminal_artifact_needed
            else ()
        ),
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        semantic_output_policy=(
            "text_for_all_semantic"
            if terminal_artifact_needed
            else "final_output_on_last_semantic"
        ),
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        ui_language=ui_language,
    )


def _terminal_artifact_slot(
    *,
    slot_ordinal: int,
    input_source: InputSource,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    ui_language: str | None,
) -> StepSkeleton:
    output_mode = _final_output_mode(
        input_type=InputType.TEXT,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
    )
    return _backend_fixed_slot(
        slot_ordinal=slot_ordinal,
        chain_token=TERMINAL_ARTIFACT_STEP,
        input_source=input_source,
        input_type=InputType.TEXT,
        output_type=final_output_type,
        output_mode=output_mode,
        document_delivery_mode=_document_delivery_mode_for_output(
            output_type=final_output_type,
            final_output_mode=final_output_mode,
        ),
        default_name=default_final_step_name(
            final_output_type,
            ui_language=ui_language,
        ),
        default_instructions=(
            default_render_step_instructions(
                final_output_type,
                ui_language=ui_language,
            )
            if output_mode == OutputMode.RENDER_VERBATIM
            else default_final_step_instructions(ui_language=ui_language)
        ),
        ui_language=ui_language,
    )


def _backend_fixed_slot(
    *,
    slot_ordinal: int,
    chain_token: ChainStepToken,
    input_source: InputSource,
    input_type: InputType,
    output_type: OutputType,
    output_mode: OutputMode,
    document_delivery_mode: DocumentDeliveryMode,
    runtime_required: bool = False,
    runtime_max_files: int | None = None,
    output_fields: tuple[StructuredFieldDraft, ...] = (),
    default_name: str | None = None,
    default_instructions: str | None = None,
    ui_language: str | None = None,
) -> StepSkeleton:
    template = _compiled_chain_step_template(chain_token, ui_language=ui_language)
    owns_runtime_input = _owns_runtime_input_constraints(
        slot_ordinal=slot_ordinal,
        input_type=input_type,
    )
    return StepSkeleton(
        slot_ordinal=slot_ordinal,
        slot_id=chain_token,
        role="backend_fixed",
        mechanics_policy="locked",
        semantic_policy="backend_default",
        chain_token=chain_token,
        default_name=default_name or template.name,
        default_instructions=default_instructions or template.instructions,
        input_source=input_source,
        input_type=input_type,
        output_type=output_type,
        output_mode=output_mode,
        document_delivery_mode=document_delivery_mode,
        runtime_required=owns_runtime_input and runtime_required,
        runtime_max_files=runtime_max_files if owns_runtime_input else None,
        output_fields=output_fields,
    )


def _semantic_required_slot(
    *,
    slot_ordinal: int,
    slot_id: str,
    input_source: InputSource,
    input_type: InputType,
    output_type: OutputType,
    output_mode: OutputMode,
    document_delivery_mode: DocumentDeliveryMode,
    runtime_required: bool = False,
    runtime_max_files: int | None = None,
    default_name: str | None = None,
    default_instructions: str | None = None,
    ui_language: str | None = None,
) -> StepSkeleton:
    owns_runtime_input = _owns_runtime_input_constraints(
        slot_ordinal=slot_ordinal,
        input_type=input_type,
    )
    return StepSkeleton(
        slot_ordinal=slot_ordinal,
        slot_id=slot_id,
        role="semantic_required",
        mechanics_policy="fill_missing",
        semantic_policy="required_from_intent",
        chain_token=None,
        default_name=default_name
        or default_final_step_name(output_type, ui_language=ui_language),
        default_instructions=default_instructions
        or default_final_step_instructions(ui_language=ui_language),
        input_source=input_source,
        input_type=input_type,
        output_type=output_type,
        output_mode=output_mode,
        document_delivery_mode=document_delivery_mode,
        runtime_required=owns_runtime_input and runtime_required,
        runtime_max_files=runtime_max_files if owns_runtime_input else None,
    )


def _skeleton_plan(
    *,
    prefix_slots: tuple[StepSkeleton, ...],
    semantic_slot: StepSkeleton,
    suffix_slots: tuple[StepSkeleton, ...],
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    semantic_output_policy: SemanticOutputPolicy,
    fan_in_policy: SemanticFanInPolicy = "none",
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
) -> StepSkeletonPlan:
    return StepSkeletonPlan(
        prefix_slots=prefix_slots,
        semantic_slot=semantic_slot,
        suffix_slots=suffix_slots,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        semantic_output_policy=semantic_output_policy,
        fan_in_policy=fan_in_policy,
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        ui_language=ui_language,
    )


def _renumber_slots(
    slots: tuple[StepSkeleton, ...],
    *,
    runtime_required: bool,
    runtime_max_files: int | None,
) -> tuple[StepSkeleton, ...]:
    return tuple(
        _slot_with_ordinal(
            slot=slot,
            slot_ordinal=slot_ordinal,
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
        )
        for slot_ordinal, slot in enumerate(slots)
    )


def _slot_with_ordinal(
    *,
    slot: StepSkeleton,
    slot_ordinal: int,
    runtime_required: bool,
    runtime_max_files: int | None,
) -> StepSkeleton:
    owns_runtime_input = _owns_runtime_input_constraints(
        slot_ordinal=slot_ordinal,
        input_type=slot.input_type,
    )
    return replace(
        slot,
        slot_ordinal=slot_ordinal,
        runtime_required=owns_runtime_input and runtime_required,
        runtime_max_files=runtime_max_files if owns_runtime_input else None,
    )


def _owns_runtime_input_constraints(
    *,
    slot_ordinal: int,
    input_type: InputType,
) -> bool:
    return slot_ordinal == 0 and input_type in _FILE_INPUT_TYPES


def _final_output_mode(
    *,
    input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
) -> OutputMode:
    return derive_output_mode(
        input_type=input_type,
        output_type=final_output_type,
        document_delivery_mode=_document_delivery_mode_for_output(
            output_type=final_output_type,
            final_output_mode=final_output_mode,
        ),
    )


def _document_delivery_mode_for_output(
    *,
    output_type: OutputType,
    final_output_mode: OutputMode | None,
) -> DocumentDeliveryMode:
    if output_type == OutputType.DOCX and final_output_mode == OutputMode.TEMPLATE_FILL:
        return "template_fill"
    if output_type in _DOCUMENT_OUTPUT_TYPES:
        return "generated"
    return "not_applicable"


def _chain_requests_docx_template_fill(
    *,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
) -> bool:
    return (
        _DOCX_TEMPLATE_PATTERN_ID in pattern_ids
        and TEMPLATE_FILL_DOCX_STEP in chain_steps
    )


def _chain_requests_audio_artifact(
    *,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
) -> bool:
    return (
        _AUDIO_ARTIFACT_PATTERN_ID in pattern_ids
        or FLOW_INPUT_AUDIO_TRANSCRIPTION in chain_steps
    )
