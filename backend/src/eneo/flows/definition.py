"""The flow definition: run inputs plus an ordered list of typed steps.

This is the document the model writes through the ``flows`` MCP tools, the
document the panel renders, and the document a published version freezes.
The step ``kind`` is a Pydantic discriminator, so the JSON schema of
:class:`FlowDefinitionInput` is exactly what the model is told it may send.

Execution is deterministic: each kind maps to one runner in
:mod:`eneo.flows.step_runners`. A step never decides at run time whether it
runs or whether a document is produced.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.templating import (
    KEY_PATTERN,
    Reference,
    TemplateError,
    extract_references,
)

MAX_STEPS = 64
MAX_FORM_FIELDS = 32
MAX_TEXT_LENGTH = 65_536
MAX_NAME_LENGTH = 200

KeyStr = Annotated[str, Field(pattern=KEY_PATTERN.pattern, max_length=64)]
NameStr = Annotated[str, Field(min_length=1, max_length=MAX_NAME_LENGTH)]
TextStr = Annotated[str, Field(max_length=MAX_TEXT_LENGTH)]


class FormFieldType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    SELECT = "select"
    FILE = "file"
    AUDIO = "audio"


FILE_FIELD_TYPES = (FormFieldType.FILE, FormFieldType.AUDIO)


class FormField(BaseModel):
    """One run input the user (or API caller) provides when starting a run."""

    model_config = ConfigDict(extra="forbid")

    key: KeyStr = Field(description="Identifier used in templates as {{form.<key>}}.")
    label: NameStr = Field(description="Shown to the person starting a run.")
    type: FormFieldType = Field(
        description=(
            "text, number or select take a value; file and audio take uploads "
            "(audio is what a transcribe step reads)."
        )
    )
    required: bool = True
    description: TextStr | None = None
    options: list[str] | None = Field(
        default=None, description="Allowed values for a select field."
    )


class StepKind(StrEnum):
    LLM = "llm"
    COMPOSE = "compose"
    DOCUMENT = "document"
    REVIEW = "review"
    TRANSCRIBE = "transcribe"


class _StepBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: KeyStr = Field(
        description=(
            "Stable identifier other steps use to read this step's output "
            "({{steps.<key>}}). Keep it when editing the flow."
        )
    )
    id: UUID | None = Field(
        default=None,
        description="Assigned by Eneo; omit when creating, keep when updating.",
    )
    name: NameStr = Field(description="Short title shown to the user.")
    description: TextStr | None = None


class TextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text"] = "text"


class JsonOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["json"] = "json"
    schema_: dict[str, Any] = Field(
        alias="schema",
        description="JSON Schema the step's output must satisfy.",
    )


LlmOutput = Annotated[Union[TextOutput, JsonOutput], Field(discriminator="type")]


class StepKnowledge(BaseModel):
    """Knowledge sources whose matching passages are injected into the prompt."""

    model_config = ConfigDict(extra="forbid")

    collection_ids: list[UUID] = Field(default_factory=list[UUID])
    website_ids: list[UUID] = Field(default_factory=list[UUID])

    def is_empty(self) -> bool:
        return not self.collection_ids and not self.website_ids


class LlmStep(_StepBase):
    """One completion with a fixed prompt. Produces text or schema-checked JSON."""

    kind: Literal["llm"] = "llm"
    prompt: TextStr = Field(
        description="The instructions. Fixed at authoring time, never rewritten."
    )
    input: TextStr = Field(
        default="{{previous}}",
        description=(
            "What the model reads, as a template over run inputs and earlier "
            "steps. Defaults to the previous step's output."
        ),
    )
    model_id: UUID | None = Field(
        default=None, description="Completion model; null means the space default."
    )
    model_kwargs: dict[str, Any] | None = None
    files_from: list[KeyStr] = Field(
        default_factory=list[str],
        description="File or audio form fields whose files the model also sees.",
    )
    knowledge: StepKnowledge = Field(default_factory=StepKnowledge)
    output: LlmOutput = Field(default_factory=TextOutput)


class ComposeStep(_StepBase):
    """Deterministic text assembled from a template. No model call."""

    kind: Literal["compose"] = "compose"
    template: TextStr


class DocumentFormat(StrEnum):
    DOCX = "docx"
    PDF = "pdf"


class DocumentStep(_StepBase):
    """A document produced by Eneo's tool runtime, always, with bound values."""

    kind: Literal["document"] = "document"
    format: DocumentFormat = DocumentFormat.DOCX
    template_file_id: UUID | None = Field(
        default=None,
        description="A Word template file to fill; null means compose from content.",
    )
    title: TextStr | None = None
    filename: TextStr | None = Field(
        default=None, description="Template; the extension is added."
    )
    content: TextStr | None = Field(
        default=None,
        description="Markdown template for the document body when no template file.",
    )
    values: dict[str, TextStr] = Field(
        default_factory=dict,
        description="Template field name to template text, for a template file.",
    )


class ReviewMode(StrEnum):
    VIEW = "view"
    EDIT = "edit"


class ReviewStep(_StepBase):
    """Pause the run until a person approves (or edits) an earlier output."""

    kind: Literal["review"] = "review"
    mode: ReviewMode = ReviewMode.EDIT
    of: KeyStr | None = Field(
        default=None, description="Step whose output is reviewed; default previous."
    )
    expires_after_seconds: int | None = Field(default=None, ge=60)


class SpeakerMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participants_field: KeyStr | None = None
    infer_names: bool = True
    model_id: UUID | None = None


class TranscribeStep(_StepBase):
    """Transcribe an audio input with a transcription model."""

    kind: Literal["transcribe"] = "transcribe"
    source: KeyStr = Field(description="The audio (or file) form field to transcribe.")
    transcription_model_id: UUID | None = None
    language: str | None = None
    speaker_labels: bool = False
    max_speakers: int | None = Field(default=None, ge=1, le=32)
    speaker_mapping: SpeakerMapping | None = None


Step = Annotated[
    Union[LlmStep, ComposeStep, DocumentStep, ReviewStep, TranscribeStep],
    Field(discriminator="kind"),
]


class FlowDefinition(BaseModel):
    """The whole definition. ``schema_version`` lets later shapes migrate."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    form_fields: list[FormField] = Field(
        default_factory=list[FormField], max_length=MAX_FORM_FIELDS
    )
    steps: list[Step] = Field(default_factory=list[Step], max_length=MAX_STEPS)

    def step_by_key(self, key: str) -> Step | None:
        return next((step for step in self.steps if step.key == key), None)

    def step_by_id(self, step_id: UUID) -> Step | None:
        return next((step for step in self.steps if step.id == step_id), None)

    def has_review(self) -> bool:
        return any(step.kind == StepKind.REVIEW for step in self.steps)

    def file_fields(self) -> list[FormField]:
        return [field for field in self.form_fields if field.type in FILE_FIELD_TYPES]


class FlowDefinitionError(ValueError):
    """The definition is well-formed JSON but not a runnable flow."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _templates_of(step: Step) -> list[tuple[str, str]]:
    """(label, template text) pairs a step reads at run time."""
    if isinstance(step, LlmStep):
        return [("input", step.input), ("prompt", step.prompt)]
    if isinstance(step, ComposeStep):
        return [("template", step.template)]
    if isinstance(step, DocumentStep):
        templates: list[tuple[str, str]] = []
        if step.content is not None:
            templates.append(("content", step.content))
        if step.title is not None:
            templates.append(("title", step.title))
        if step.filename is not None:
            templates.append(("filename", step.filename))
        templates.extend((f"values.{name}", text) for name, text in step.values.items())
        return templates
    return []


def _check_reference(
    reference: Reference,
    *,
    step_index: int,
    steps: list[Step],
    form_keys: set[str],
) -> str | None:
    if reference.source == "previous":
        return None if step_index > 0 else "{{previous}} has no previous step"
    if reference.source == "form":
        assert reference.key is not None
        if reference.key not in form_keys:
            return f"{{{{form.{reference.key}}}}} names no form field"
        return None
    assert reference.key is not None
    earlier = {step.key: step for step in steps[:step_index]}
    target = earlier.get(reference.key)
    if target is None:
        return f"{{{{{reference.raw}}}}} must name an earlier step"
    if reference.wants_json and not (
        isinstance(target, LlmStep) and target.output.type == "json"
    ):
        return f"{{{{{reference.raw}}}}} reads JSON from a step that produces text"
    return None


def validate_definition(definition: FlowDefinition) -> None:
    """Raise :class:`FlowDefinitionError` listing every structural problem.

    Space-dependent checks (does the model exist, may the space use this
    collection) live in the service; this is the shape-only pass the MCP
    tools and the REST layer share.
    """
    errors: list[str] = []
    form_keys: list[str] = [field.key for field in definition.form_fields]
    duplicates = {key for key in form_keys if form_keys.count(key) > 1}
    for key in sorted(duplicates):
        errors.append(f"form field key '{key}' is used more than once")
    form_by_key = {field.key: field for field in definition.form_fields}
    for field in definition.form_fields:
        if field.type == FormFieldType.SELECT and not field.options:
            errors.append(f"select field '{field.key}' needs options")

    if not definition.steps:
        errors.append("a flow needs at least one step")
    step_keys = [step.key for step in definition.steps]
    for key in sorted({key for key in step_keys if step_keys.count(key) > 1}):
        errors.append(f"step key '{key}' is used more than once")

    steps = list(definition.steps)
    for index, step in enumerate(steps):
        where = f"step '{step.key}'"
        for label, template in _templates_of(step):
            try:
                references = extract_references(template)
            except TemplateError as exc:
                errors.append(f"{where} {label}: {exc}")
                continue
            for reference in references:
                problem = _check_reference(
                    reference, step_index=index, steps=steps, form_keys=set(form_keys)
                )
                if problem:
                    errors.append(f"{where} {label}: {problem}")

        if isinstance(step, LlmStep):
            for key in step.files_from:
                field = form_by_key.get(key)
                if field is None:
                    errors.append(f"{where} files_from names no form field '{key}'")
                elif field.type not in FILE_FIELD_TYPES:
                    errors.append(f"{where} files_from '{key}' is not a file field")
            if step.output.type == "json" and not step.output.schema_:
                errors.append(f"{where} json output needs a schema object")
        elif isinstance(step, DocumentStep):
            if (step.template_file_id is None) == (step.content is None):
                errors.append(
                    f"{where} needs exactly one of template_file_id or content"
                )
            if step.template_file_id is None and step.values:
                errors.append(f"{where} values only apply with a template file")
        elif isinstance(step, ReviewStep):
            if index == 0:
                errors.append(f"{where} cannot be the first step")
            target_key = step.of
            if target_key is None and index > 0:
                target_key = steps[index - 1].key
            target = next((s for s in steps[:index] if s.key == target_key), None)
            if target_key is not None and target is None:
                errors.append(f"{where} reviews '{target_key}', which is not earlier")
            elif isinstance(target, ReviewStep):
                errors.append(f"{where} cannot review another review step")
        elif isinstance(step, TranscribeStep):
            field = form_by_key.get(step.source)
            if field is None:
                errors.append(f"{where} source names no form field '{step.source}'")
            elif field.type not in FILE_FIELD_TYPES:
                errors.append(f"{where} source '{step.source}' is not a file field")
            if step.speaker_mapping and step.speaker_mapping.participants_field:
                pf = form_by_key.get(step.speaker_mapping.participants_field)
                if pf is None or pf.type in FILE_FIELD_TYPES:
                    errors.append(
                        f"{where} speaker_mapping.participants_field must be a text field"
                    )

    if errors:
        raise FlowDefinitionError(errors)


def assign_step_ids(
    definition: FlowDefinition, previous: FlowDefinition | None = None
) -> FlowDefinition:
    """Give every step a stable id.

    A step keeps the id it had in ``previous`` when its key matches, so a
    run's step results and review checkpoints keep pointing at the same step
    across edits. New keys get fresh ids; ids the model sent for unknown keys
    are replaced, since only Eneo assigns them.
    """
    previous_ids = {step.key: step.id for step in (previous.steps if previous else [])}
    steps: list[Any] = []
    for step in definition.steps:
        kept = previous_ids.get(step.key)
        steps.append(step.model_copy(update={"id": kept or uuid4()}))
    return definition.model_copy(update={"steps": steps})


def review_target_key(definition: FlowDefinition, review: ReviewStep) -> str | None:
    """The key of the step a review step pauses on."""
    if review.of is not None:
        return review.of
    index = next(
        (i for i, step in enumerate(definition.steps) if step.key == review.key), None
    )
    if index is None or index == 0:
        return None
    return definition.steps[index - 1].key


def definition_summary(definition: FlowDefinition) -> str:
    """One line per step, the shape the model gets back after a save."""
    lines: list[str] = []
    for index, step in enumerate(definition.steps, start=1):
        lines.append(f"{index}. [{step.kind}] {step.name} (key: {step.key})")
    return "\n".join(lines)
