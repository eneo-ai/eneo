"""What each step kind does at run time.

A runner has two halves so the executor can keep transactions short:
``prepare`` reads the database (models, files, knowledge) inside a session
scope and returns plain data; ``invoke`` does the provider I/O with no
transaction open. ``review`` is not a runner: the executor pauses the run
itself. ``document`` and ``transcribe`` fail the run until their runners
ship, so a published flow never reaches a step that cannot execute.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, cast
from uuid import UUID

import jsonschema

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.references import EmbedMethod
from eneo.flows.definition import (
    ComposeStep,
    DocumentStep,
    LlmStep,
    Step,
    TranscribeStep,
)
from eneo.flows.flow_repo import RunFileRow
from eneo.flows.templating import TemplateContext, TemplateError, render_template
from eneo.main.exceptions import NotFoundException
from eneo.tokens.token_utils import count_tokens

if TYPE_CHECKING:
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModel as AICompletionModel,
    )
    from eneo.assistants.references import ReferencesService
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from eneo.files.file_models import File
    from eneo.files.file_service import FileService
    from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore
    from eneo.spaces.space import Space
    from eneo.spaces.space_repo import SpaceRepository

# Error codes a step can fail with; the run API exposes them unchanged.
STEP_KIND_UNAVAILABLE = "flow_step_kind_unavailable"
STEP_TEMPLATE_ERROR = "flow_step_template_error"
STEP_MODEL_UNAVAILABLE = "flow_step_model_unavailable"
STEP_INPUT_TOO_LARGE = "flow_step_input_exceeds_model_window"
STEP_OUTPUT_INVALID_JSON = "flow_step_output_invalid_json"
STEP_FAILED = "flow_step_failed"
STEP_TIMEOUT = "flow_step_timeout"

JSON_INSTRUCTION = (
    "\n\nRespond with one JSON document only, no prose and no code fences. "
    "It must satisfy this JSON Schema:\n{schema}"
)
JSON_RETRY_INPUT = (
    "{input}\n\nYour previous answer was not valid for the required JSON "
    "Schema ({error}). Return only a corrected JSON document."
)
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class FlowStepError(Exception):
    """A step cannot produce its output; the run fails with ``code``."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class RunContext:
    """Plain data about the run, safe to hold across session scopes."""

    run_id: UUID
    flow_id: UUID
    space_id: UUID
    tenant_id: UUID
    principal_user_id: Optional[UUID]
    form_values: dict[str, Any]
    input_files: list[RunFileRow]

    def file_ids_for(self, field_key: str) -> list[UUID]:
        return [
            row.file_id
            for row in self.input_files
            if row.role == "input" and row.field_key == field_key
        ]


def _no_files() -> list[File]:
    return []


def _no_chunks() -> list[InfoBlobChunkInDBWithScore]:
    return []


@dataclass
class PreparedStep:
    """Everything ``invoke`` needs, resolved while a session was open."""

    input_payload: dict[str, Any]
    output_payload: Optional[dict[str, Any]] = None  # set when no I/O is needed
    text_input: str = ""
    prompt: str = ""
    model: Optional[CompletionModel] = None
    model_kwargs: Optional[ModelKwargs] = None
    files: list[File] = field(default_factory=_no_files)
    chunks: list[InfoBlobChunkInDBWithScore] = field(default_factory=_no_chunks)
    json_schema: Optional[dict[str, Any]] = None


@dataclass
class StepOutcome:
    output_payload: dict[str, Any]
    num_tokens_input: Optional[int] = None
    num_tokens_output: Optional[int] = None
    output_file_ids: list[UUID] = field(default_factory=list[UUID])


def _strip_fences(text: str) -> str:
    return _FENCE.sub("", text).strip()


def parse_json_output(text: str, schema: dict[str, Any]) -> Any:
    """Parse and schema-check a model's JSON answer; ValueError on failure."""
    try:
        value = json.loads(_strip_fences(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    try:
        jsonschema.validate(value, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"schema violation: {exc.message}") from exc
    except jsonschema.SchemaError as exc:
        raise ValueError(f"invalid schema: {exc.message}") from exc
    return value


class StepRunners:
    def __init__(
        self,
        completion_service: CompletionService,
        references_service: ReferencesService,
        file_service: FileService,
        space_repo: SpaceRepository,
    ):
        self.completion_service = completion_service
        self.references_service = references_service
        self.file_service = file_service
        self.space_repo = space_repo
        self._space: Optional[Space] = None

    async def _space_for(self, ctx: RunContext) -> Space:
        if self._space is None or self._space.id != ctx.space_id:
            self._space = await self.space_repo.one(ctx.space_id)
        return self._space

    # --- prepare (inside a session scope) ---

    async def prepare(
        self, step: Step, ctx: RunContext, template_context: TemplateContext
    ) -> PreparedStep:
        if isinstance(step, ComposeStep):
            return self._prepare_compose(step, template_context)
        if isinstance(step, LlmStep):
            return await self._prepare_llm(step, ctx, template_context)
        if isinstance(step, (DocumentStep, TranscribeStep)):
            raise FlowStepError(
                STEP_KIND_UNAVAILABLE,
                f"Step '{step.name}' has kind '{step.kind}', which this version "
                "of Eneo cannot run yet.",
            )
        raise FlowStepError(STEP_FAILED, f"Step '{step.name}' has no runner.")

    @staticmethod
    def _render(label: str, template: str, context: TemplateContext) -> str:
        try:
            return render_template(template, context)
        except TemplateError as exc:
            raise FlowStepError(STEP_TEMPLATE_ERROR, f"{label}: {exc}") from exc

    def _prepare_compose(
        self, step: ComposeStep, context: TemplateContext
    ) -> PreparedStep:
        text = self._render(f"step '{step.key}' template", step.template, context)
        return PreparedStep(
            input_payload={"template": step.template},
            output_payload={"text": text, "value": None},
        )

    async def _prepare_llm(
        self, step: LlmStep, ctx: RunContext, context: TemplateContext
    ) -> PreparedStep:
        space = await self._space_for(ctx)
        text_input = self._render(f"step '{step.key}' input", step.input, context)
        prompt = self._render(f"step '{step.key}' prompt", step.prompt, context)

        if step.model_id is not None:
            try:
                model = space.get_completion_model(step.model_id)
            except NotFoundException as exc:
                raise FlowStepError(
                    STEP_MODEL_UNAVAILABLE,
                    f"Step '{step.name}' uses a model that is no longer available "
                    "in this space.",
                ) from exc
        else:
            default = space.get_default_completion_model()
            if default is None:
                raise FlowStepError(
                    STEP_MODEL_UNAVAILABLE,
                    f"Step '{step.name}' needs the space default model, but the "
                    "space has none.",
                )
            model = default
        if not model.can_access:
            raise FlowStepError(
                STEP_MODEL_UNAVAILABLE,
                f"Step '{step.name}' uses model '{model.name}', which cannot be "
                "accessed any more.",
            )

        file_ids = [
            file_id for key in step.files_from for file_id in ctx.file_ids_for(key)
        ]
        files = (
            await self.file_service.get_files_by_ids(
                file_ids, include_transcription=True
            )
            if file_ids
            else []
        )

        chunks: list[InfoBlobChunkInDBWithScore] = []
        if not step.knowledge.is_empty():
            collections = [
                space.get_collection(cid) for cid in step.knowledge.collection_ids
            ]
            websites = [space.get_website(wid) for wid in step.knowledge.website_ids]
            result = await self.references_service.get_references(
                question=text_input,
                collections=collections,
                websites=websites,
                embed_method=EmbedMethod.LAST_QUESTION,
                context_window_tokens=model.token_limit,
            )
            chunks = list(result.chunks)

        json_schema: Optional[dict[str, Any]] = None
        if step.output.type == "json":
            json_schema = step.output.schema_
            prompt = prompt + JSON_INSTRUCTION.format(
                schema=json.dumps(json_schema, ensure_ascii=False)
            )

        packaged = prompt + text_input
        for file in files:
            packaged += file.text or file.transcription or ""
        packaged_tokens = count_tokens(packaged, model.name)
        if packaged_tokens > model.token_limit:
            raise FlowStepError(
                STEP_INPUT_TOO_LARGE,
                f"Step '{step.name}' packages about {packaged_tokens} tokens but "
                f"the model window is {model.token_limit} tokens.",
            )

        model_kwargs = (
            ModelKwargs.model_validate(step.model_kwargs)
            if step.model_kwargs is not None
            else None
        )
        return PreparedStep(
            input_payload={
                "text": text_input,
                "prompt": prompt,
                "model_id": str(model.id),
                "file_ids": [str(file.id) for file in files],
                "knowledge_chunks": len(chunks),
            },
            text_input=text_input,
            prompt=prompt,
            model=model,
            model_kwargs=model_kwargs,
            files=files,
            chunks=chunks,
            json_schema=json_schema,
        )

    # --- invoke (provider I/O) ---

    async def invoke(self, step: Step, prepared: PreparedStep) -> StepOutcome:
        if prepared.output_payload is not None:
            return StepOutcome(output_payload=prepared.output_payload)
        assert isinstance(step, LlmStep) and prepared.model is not None
        text, tokens_in, tokens_out = await self._complete(
            prepared, prepared.text_input
        )
        if prepared.json_schema is None:
            return StepOutcome(
                output_payload={"text": text, "value": None},
                num_tokens_input=tokens_in,
                num_tokens_output=tokens_out,
            )
        try:
            value = parse_json_output(text, prepared.json_schema)
        except ValueError as first_error:
            retry_input = JSON_RETRY_INPUT.format(
                input=prepared.text_input, error=first_error
            )
            text, more_in, more_out = await self._complete(prepared, retry_input)
            tokens_in = (tokens_in or 0) + (more_in or 0)
            tokens_out = (tokens_out or 0) + (more_out or 0)
            try:
                value = parse_json_output(text, prepared.json_schema)
            except ValueError as exc:
                raise FlowStepError(
                    STEP_OUTPUT_INVALID_JSON,
                    f"Step '{step.name}' declared JSON output but produced "
                    f"{exc} after one retry.",
                ) from exc
        return StepOutcome(
            output_payload={"text": text, "value": value},
            num_tokens_input=tokens_in,
            num_tokens_output=tokens_out,
        )

    async def _complete(
        self, prepared: PreparedStep, text_input: str
    ) -> tuple[str, Optional[int], Optional[int]]:
        assert prepared.model is not None
        response = await self.completion_service.get_response(
            # The completion service takes the domain model at run time (the
            # assistant ask path passes the same object); the adapter-facing
            # class is only a typing boundary.
            model=cast("AICompletionModel", prepared.model),
            text_input=text_input,
            prompt=prepared.prompt,
            files=prepared.files,
            info_blob_chunks=prepared.chunks,
            model_kwargs=prepared.model_kwargs,
            mcp_servers=[],
            stream=False,
        )
        # A non-streaming completion is a Completion whose answer is `.text`
        # (the app-run path reads it the same way); a plain string is also
        # accepted so a fake service in tests can return one.
        completion = response.completion
        if isinstance(completion, str):
            text = completion
        else:
            text = getattr(completion, "text", None) or ""
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else response.total_token_count
        tokens_out = usage.completion_tokens if usage else None
        return text, tokens_in, tokens_out
