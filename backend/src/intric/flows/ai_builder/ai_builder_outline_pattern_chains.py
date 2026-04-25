from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, TypeVar, cast

from intric.flows.ai_builder.ai_builder_models import InputType, OutputType
from intric.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from intric.flows.ai_builder.pattern_registry import (
    ANALYSIS_OR_QUALITY_REVIEW_STEP,
    EXTRACT_TEMPLATE_VARIABLES_STEP,
    FLOW_INPUT_AUDIO_TRANSCRIPTION,
    STRUCTURED_EXTRACTION_STEP,
    TEMPLATE_FILL_DOCX_STEP,
    TERMINAL_ARTIFACT_STEP,
    compiled_chain_pattern_ids,
)

StepT = TypeVar("StepT", bound="OutlineStepLike")
StepFactory = Callable[
    [str, str, str | None, list[StructuredFieldDraft] | None],
    StepT,
]


@dataclass(frozen=True, slots=True)
class CompiledChainStepTemplate:
    """Compiler-owned default step text for backend-added chain steps."""

    name: str
    task: str


_COMPILED_CHAIN_STEP_TEMPLATES = MappingProxyType(
    {
        FLOW_INPUT_AUDIO_TRANSCRIPTION: CompiledChainStepTemplate(
            name="Transcribe audio",
            task=(
                "Transcribe the uploaded audio into text before downstream "
                "analysis or artifact generation."
            ),
        ),
        EXTRACT_TEMPLATE_VARIABLES_STEP: CompiledChainStepTemplate(
            name="Extract template variables",
            task=(
                "Extract the stable fields and source facts needed before "
                "filling the DOCX template."
            ),
        ),
        STRUCTURED_EXTRACTION_STEP: CompiledChainStepTemplate(
            name="Extract structured foundation",
            task=(
                "Extract source facts, key points, and uncertainties needed "
                "for the downstream analysis."
            ),
        ),
        ANALYSIS_OR_QUALITY_REVIEW_STEP: CompiledChainStepTemplate(
            name="Review quality and gaps",
            task=(
                "Review the analysis for missing information, uncertainty, "
                "and quality issues before the final output is created."
            ),
        ),
        TEMPLATE_FILL_DOCX_STEP: CompiledChainStepTemplate(
            name="Fill DOCX template",
            task=(
                "Fill the DOCX template from the prepared content. Preserve "
                "the user's requested scope and terminology."
            ),
        ),
        TERMINAL_ARTIFACT_STEP: CompiledChainStepTemplate(
            name="Create final output",
            task=(
                "Create the final output from the reviewed analysis. Preserve "
                "the user's requested scope, ordering, and constraints."
            ),
        ),
    }
)


class OutlineStepLike(Protocol):
    """Structural surface needed to rewrite semantic outline steps.

    The Pydantic outline model lives in `ai_builder_create_outline.py`; this
    module stays independent of that model so chain templates can evolve
    without making the parser depend on the compiler registry.
    """

    @property
    def output_type(self) -> str | None: ...

    @property
    def output_fields(self) -> object | None: ...

    def model_copy(self, *, update: dict[str, Any]) -> Any: ...


@dataclass(frozen=True, slots=True)
class ChainRealizationRequest:
    steps: list[OutlineStepLike]
    runtime_input_type: InputType
    final_output_type: OutputType
    pattern_ids: tuple[str, ...]
    chain_steps: tuple[str, ...]
    make_step: StepFactory[Any]

    @property
    def pattern_id_set(self) -> frozenset[str]:
        return frozenset(self.pattern_ids)

    @property
    def token_set(self) -> frozenset[str]:
        return frozenset(self.chain_steps)


@dataclass(frozen=True, slots=True)
class ChainRealizer:
    """Declarative bridge from registry chain tokens to Flow-ready outline steps."""

    name: str
    required_tokens: frozenset[str]
    applies: Callable[[ChainRealizationRequest], bool]
    build: Callable[[ChainRealizationRequest], list[OutlineStepLike]]

    def try_build(
        self,
        request: ChainRealizationRequest,
    ) -> list[OutlineStepLike] | None:
        if not self.required_tokens <= request.token_set:
            return None
        if not self.applies(request):
            return None
        return self.build(request)


def realize_outline_pattern_chain(
    *,
    steps: list[StepT],
    runtime_input_type: InputType,
    final_output_type: OutputType,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
    make_step: StepFactory[StepT],
) -> list[StepT]:
    """Expand server-owned pattern chains into concrete semantic steps.

    The model submits a small semantic outline. Pattern registry tokens tell
    the backend when a known Flow capability requires mechanical scaffolding,
    such as transcription before artifact generation or template extraction
    before DOCX fill. This keeps those mechanics out of the LLM contract.
    """

    request = ChainRealizationRequest(
        steps=cast(list[OutlineStepLike], steps),
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        pattern_ids=pattern_ids,
        chain_steps=chain_steps,
        make_step=make_step,
    )
    compiled_pattern_ids = compiled_chain_pattern_ids(request.pattern_ids)
    if len(compiled_pattern_ids) > 1:
        raise ValueError(
            "Only one compiler-backed pattern chain can be realized at a time; "
            f"got {sorted(compiled_pattern_ids)}"
        )
    if compiled_pattern_ids:
        pattern_id = next(iter(compiled_pattern_ids))
        realizer = _CHAIN_REALIZER_BY_PATTERN_ID.get(pattern_id)
        if realizer is None:
            raise ValueError(
                "Compiler-backed pattern chain has no registered realizer: "
                f"{pattern_id!r}"
            )
        realized = realizer.try_build(request)
        if realized is not None:
            return cast(list[StepT], realized)
    return steps


def chain_requests_docx_template_fill(
    *,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
) -> bool:
    return (
        "document_to_docx_template" in pattern_ids
        and TEMPLATE_FILL_DOCX_STEP in chain_steps
    )


def compiled_chain_realizer_ids() -> frozenset[str]:
    """Pattern ids that have concrete backend chain realization logic."""

    return frozenset(_CHAIN_REALIZER_BY_PATTERN_ID)


def _docx_template_applies(request: ChainRealizationRequest) -> bool:
    if request.runtime_input_type not in {InputType.DOCUMENT, InputType.FILE}:
        return False
    return request.final_output_type == OutputType.DOCX


def _build_docx_template_chain(
    request: ChainRealizationRequest,
) -> list[OutlineStepLike]:
    semantic_steps = _semantic_steps_or_default(
        request,
        name="Prepare template content",
        task="Prepare the content that should be placed in the DOCX template.",
    )
    return [
        _make_compiled_chain_step(
            request,
            token=EXTRACT_TEMPLATE_VARIABLES_STEP,
            output_fields=_default_structured_output_fields(),
        ),
        *[_as_text_step(step) for step in semantic_steps],
        _make_compiled_chain_step(
            request,
            token=TEMPLATE_FILL_DOCX_STEP,
            output_type=OutputType.DOCX.value,
        ),
    ]


def _structured_quality_applies(request: ChainRealizationRequest) -> bool:
    return request.runtime_input_type in {InputType.DOCUMENT, InputType.FILE}


def _build_structured_quality_chain(
    request: ChainRealizationRequest,
) -> list[OutlineStepLike]:
    semantic_steps = _semantic_steps_or_default(
        request,
        name="Analyze structured material",
        task="Analyze the structured source material according to the request.",
    )
    return [
        _make_compiled_chain_step(
            request,
            token=STRUCTURED_EXTRACTION_STEP,
            output_fields=_default_structured_output_fields(),
        ),
        *[_as_text_step(step) for step in semantic_steps],
        _make_compiled_chain_step(
            request,
            token=ANALYSIS_OR_QUALITY_REVIEW_STEP,
            output_type=OutputType.TEXT.value,
        ),
        _make_compiled_chain_step(
            request,
            token=TERMINAL_ARTIFACT_STEP,
            output_type=request.final_output_type.value,
        ),
    ]


def _audio_transcription_applies(request: ChainRealizationRequest) -> bool:
    if request.runtime_input_type != InputType.AUDIO:
        return False
    if not request.steps:
        return False
    if _chain_explicitly_requests_audio_transcription(request):
        return not _outline_already_starts_with_transcribed_text(request)
    if _single_text_output_can_use_audio_step_directly(request):
        return False
    if _first_step_already_produces_text(request):
        return False
    return _downstream_audio_work_needs_transcript(request)


def _single_text_output_can_use_audio_step_directly(
    request: ChainRealizationRequest,
) -> bool:
    return request.final_output_type == OutputType.TEXT and len(request.steps) == 1


def _first_step_already_produces_text(request: ChainRealizationRequest) -> bool:
    return request.steps[0].output_type == OutputType.TEXT.value


def _outline_already_starts_with_transcribed_text(
    request: ChainRealizationRequest,
) -> bool:
    return len(request.steps) > 1 and _first_step_already_produces_text(request)


def _chain_explicitly_requests_audio_transcription(
    request: ChainRealizationRequest,
) -> bool:
    return FLOW_INPUT_AUDIO_TRANSCRIPTION in request.token_set


def _downstream_audio_work_needs_transcript(
    request: ChainRealizationRequest,
) -> bool:
    return request.final_output_type != OutputType.TEXT or bool(
        request.steps[0].output_fields
    )


def _build_audio_transcription_chain(
    request: ChainRealizationRequest,
) -> list[OutlineStepLike]:
    return [
        _make_compiled_chain_step(
            request,
            token=FLOW_INPUT_AUDIO_TRANSCRIPTION,
            output_type=OutputType.TEXT.value,
        ),
        *request.steps,
    ]


def _semantic_steps_or_default(
    request: ChainRealizationRequest,
    *,
    name: str,
    task: str,
) -> list[OutlineStepLike]:
    if request.steps:
        return request.steps
    return [_make_step(request, name=name, task=task)]


def _as_text_step(step: OutlineStepLike) -> OutlineStepLike:
    return cast(
        OutlineStepLike,
        step.model_copy(update={"output_type": OutputType.TEXT.value}),
    )


def _make_step(
    request: ChainRealizationRequest,
    *,
    name: str,
    task: str,
    output_type: str | None = None,
    output_fields: list[StructuredFieldDraft] | None = None,
) -> OutlineStepLike:
    return cast(
        OutlineStepLike,
        request.make_step(name, task, output_type, output_fields),
    )


def _make_compiled_chain_step(
    request: ChainRealizationRequest,
    *,
    token: str,
    output_type: str | None = None,
    output_fields: list[StructuredFieldDraft] | None = None,
) -> OutlineStepLike:
    template = _COMPILED_CHAIN_STEP_TEMPLATES[token]
    return _make_step(
        request,
        name=template.name,
        task=template.task,
        output_type=output_type,
        output_fields=output_fields,
    )


def _default_structured_output_fields() -> list[StructuredFieldDraft]:
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


_CHAIN_REALIZER_BY_PATTERN_ID = MappingProxyType(
    {
        "document_to_docx_template": ChainRealizer(
            name="document_to_docx_template",
            required_tokens=frozenset(
                {
                    EXTRACT_TEMPLATE_VARIABLES_STEP,
                    TEMPLATE_FILL_DOCX_STEP,
                }
            ),
            applies=_docx_template_applies,
            build=_build_docx_template_chain,
        ),
        "multi_step_quality_chain": ChainRealizer(
            name="multi_step_quality_chain",
            required_tokens=frozenset(
                {
                    STRUCTURED_EXTRACTION_STEP,
                    ANALYSIS_OR_QUALITY_REVIEW_STEP,
                }
            ),
            applies=_structured_quality_applies,
            build=_build_structured_quality_chain,
        ),
        "audio_to_artifact_report": ChainRealizer(
            name="audio_to_artifact_report",
            required_tokens=frozenset({FLOW_INPUT_AUDIO_TRANSCRIPTION}),
            applies=_audio_transcription_applies,
            build=_build_audio_transcription_chain,
        ),
    }
)
