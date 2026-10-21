"""What each step kind does at run time.

A runner has two halves so the executor can keep transactions short:
``prepare`` reads the database (models, files, knowledge) inside a session
scope and returns plain data; ``invoke`` does the provider I/O with no
transaction open. ``review`` is not a runner: the executor pauses the run
itself. ``document`` and ``function`` call the provider that serves the
space's hidden flows assistant for a capability (the bundled tool runtime,
a web search or image provider) with arguments rendered from the
definition, and hand the files back for the executor to store through the
file service. ``transcribe`` runs the space's transcription model over the
audio of a form field, labels speakers through the configured speaker
service when asked, and names them with one fixed-prompt completion.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from copy import copy
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Optional, cast
from uuid import UUID

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.references import EmbedMethod
from eneo.authentication.signed_urls import (
    build_signed_original_download_url,
    redact_reference_tokens,
)
from eneo.completion_models.application.map_reduce import Usage
from eneo.document_templates.service import resolve_document_template
from eneo.files.file_models import FileOriginalNotFoundError
from eneo.files.file_reference import file_reference_base_url
from eneo.files.generated_documents import (
    GeneratedDocumentRejected,
    validate_generated_document,
)
from eneo.files.transcript import TranscriptSegment
from eneo.flows.definition import (
    ComposeStep,
    DocumentStep,
    FunctionStep,
    LlmStep,
    Step,
    TranscribeStep,
)
from eneo.flows.flow_repo import RunFileRow
from eneo.flows.long_input import (
    LongInputError,
    LongPlan,
    Source,
    prepare_long_input,
    process_long_input,
)
from eneo.flows.schema_validation import validate_value
from eneo.flows.speaker_labels import (
    SpeakerMappingInvalid,
    build_opening_excerpt,
    build_speaker_inventory,
    build_speaker_mapping_question,
    parse_participants,
    parse_speaker_mapping,
    render_segments,
    renumber_segment_speakers,
    speaker_mapping_instructions,
)
from eneo.flows.speaker_service import (
    SpeakerService,
    SpeakerServiceError,
    configured_speaker_service,
)
from eneo.flows.templating import TemplateContext, TemplateError, render_template
from eneo.main.config import get_settings
from eneo.main.exceptions import NotFoundException
from eneo.main.logging import get_logger
from eneo.mcp_servers.domain.entities.mcp_server import (
    DOCX_MIME_TYPE,
    GENERATED_FILE_TYPES_BY_PURPOSE,
    MARKDOWN_MIME_TYPE,
    PDF_MIME_TYPE,
    TXT_MIME_TYPE,
)
from eneo.mcp_servers.infrastructure.identity_headers import build_identity_headers
from eneo.tokens.token_utils import count_tokens

if TYPE_CHECKING:
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModel as AICompletionModel,
    )
    from eneo.assistants.assistant_service import AssistantService
    from eneo.assistants.references import ReferencesService
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from eneo.document_templates.domain import DocumentTemplateReference
    from eneo.files.file_models import File
    from eneo.files.file_service import FileService
    from eneo.files.transcriber import Transcriber
    from eneo.flows.flow_repo import FlowRepository
    from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
        MCPProxySessionFactory,
    )
    from eneo.spaces.space import Space
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )
    from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
        LiteLLMTranscriptionAdapter,
    )
    from eneo.users.user import UserInDB

logger = get_logger(__name__)

# Error codes a step can fail with; the run API exposes them unchanged.
STEP_KIND_UNAVAILABLE = "flow_step_kind_unavailable"
STEP_TEMPLATE_ERROR = "flow_step_template_error"
STEP_MODEL_UNAVAILABLE = "flow_step_model_unavailable"
STEP_INPUT_TOO_LARGE = "flow_step_input_exceeds_model_window"
STEP_OUTPUT_INVALID_JSON = "flow_step_output_invalid_json"
STEP_FAILED = "flow_step_failed"
STEP_TIMEOUT = "flow_step_timeout"
STEP_DOCUMENT_UNAVAILABLE = "flow_step_document_provider_unavailable"
STEP_DOCUMENT_FAILED = "flow_step_document_failed"
STEP_TEMPLATE_FILE_UNAVAILABLE = "flow_step_template_file_unavailable"
STEP_FUNCTION_UNAVAILABLE = "flow_step_function_unavailable"
STEP_FUNCTION_FAILED = "flow_step_function_failed"
STEP_TRANSCRIPTION_MODEL_UNAVAILABLE = "flow_step_transcription_model_unavailable"
STEP_AUDIO_UNAVAILABLE = "flow_step_audio_unavailable"
STEP_SPEAKER_SERVICE_UNAVAILABLE = "flow_step_speaker_service_unavailable"
STEP_SPEAKER_MAPPING_FAILED = "flow_step_speaker_mapping_failed"

# The capability whose provider renders documents, and the tools it does so with.
DOCUMENT_PURPOSE = "file_creation"
CREATE_DOCUMENT_TOOL = "create_document"
FILL_TEMPLATE_TOOL = "fill_template"
FLOWS_ASSISTANT_PURPOSE = "flows"
DOCUMENT_LANGUAGE = "sv"
# What a filled template comes back as, by the template's extension.
TEMPLATE_MIME_TYPES = {
    "docx": DOCX_MIME_TYPE,
    "txt": TXT_MIME_TYPE,
    "md": MARKDOWN_MIME_TYPE,
}
FORMAT_MIME_TYPES = {"docx": DOCX_MIME_TYPE, "pdf": PDF_MIME_TYPE}

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
    runtime_bindings: dict[str, Any] = field(default_factory=dict[str, Any])

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


@dataclass(frozen=True)
class GeneratedDocument:
    """Bytes a document step produced, before the file service stores them."""

    data: bytes
    filename: str
    mime_type: str


@dataclass
class DocumentCall:
    """One call to a capability provider's tool, ready to send."""

    server: MCPServer
    tool_name: str
    arguments: dict[str, Any]
    # Signed links the call may hand the provider (template, input files).
    reference_urls: dict[UUID, str] = field(default_factory=dict[UUID, str])
    # The organisation's document template a content render uses.
    document_template: Optional[DocumentTemplateReference] = None


@dataclass
class AudioInput:
    file_id: UUID
    name: str
    mimetype: str
    data: bytes


@dataclass
class TranscribeCall:
    """One transcription of the audio of a form field, resolved while a session was open."""

    adapter: LiteLLMTranscriptionAdapter
    model_id: UUID
    model_name: str
    language: Optional[str]
    audio: list[AudioInput]
    speaker_labels: bool
    max_speakers: Optional[int]
    speaker_service: Optional[SpeakerService]
    # Speaker naming: participants from the form, or inference, with a model.
    participants: list[str]
    infer_names: bool
    mapping_model: Optional[CompletionModel]


def _no_documents() -> list[GeneratedDocument]:
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
    long_plan: LongPlan | None = None
    run_context: RunContext | None = None
    document: Optional[DocumentCall] = None
    transcribe: Optional[TranscribeCall] = None
    # Whether ``invoke`` resolves anything from the database (a completion
    # looks its provider adapter up); a document call runs with no session.
    io_needs_session: bool = True


@dataclass
class StepOutcome:
    output_payload: dict[str, Any]
    num_tokens_input: Optional[int] = None
    num_tokens_output: Optional[int] = None
    output_file_ids: list[UUID] = field(default_factory=list[UUID])
    # Produced bytes the executor stores (``store_documents``) before persisting.
    documents: list[GeneratedDocument] = field(default_factory=_no_documents)
    # Transcripts to keep on their audio files (``store_transcriptions``).
    transcriptions: list[tuple[UUID, str]] = field(
        default_factory=list[tuple[UUID, str]]
    )
    # What a transcribe step records with its input (``transcription`` key).
    transcription: Optional[dict[str, Any]] = None


def _strip_fences(text: str) -> str:
    return _FENCE.sub("", text).strip()


async def parse_json_output(text: str, schema: dict[str, Any]) -> Any:
    """Parse and schema-check a model's JSON answer; ValueError on failure."""
    try:
        value = json.loads(_strip_fences(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    await validate_value(value, schema)
    return value


def _render_or_error(label: str, template: str, context: TemplateContext) -> str:
    try:
        return render_template(template, context)
    except TemplateError as exc:
        raise FlowStepError(STEP_TEMPLATE_ERROR, f"{label}: {exc}") from exc


def document_tool_arguments(
    step: DocumentStep,
    context: TemplateContext,
    *,
    template: Optional[tuple[str, str]] = None,
) -> tuple[str, dict[str, Any]]:
    """The provider tool and its arguments for a document step (pure).

    ``template`` is the signed ``(url, filename)`` of the step's template
    file; with one the step fills that form (``fill_template``), without one
    it renders ``content`` into a new document (``create_document``). Every
    text the definition holds is rendered against the run first.
    """
    where = f"step '{step.key}'"
    arguments: dict[str, Any] = {}
    if step.filename:
        arguments["filename"] = _render_or_error(
            f"{where} filename", step.filename, context
        )
    if template is not None:
        url, filename = template
        arguments["template"] = {"url": url, "filename": filename}
        arguments["values"] = {
            name: _render_or_error(f"{where} values.{name}", text, context)
            for name, text in step.values.items()
        }
        return FILL_TEMPLATE_TOOL, arguments
    title = (
        _render_or_error(f"{where} title", step.title, context)
        if step.title is not None
        else ""
    )
    arguments["title"] = title.strip() or step.name
    arguments["format"] = step.format.value
    arguments["content"] = _render_or_error(
        f"{where} content", step.content or "", context
    )
    arguments["language"] = DOCUMENT_LANGUAGE
    return CREATE_DOCUMENT_TOOL, arguments


def expected_document_mime_types(
    step: DocumentStep, template_filename: Optional[str]
) -> frozenset[str]:
    """The file types a document step's call is expected to come back as."""
    if template_filename is not None:
        extension = template_filename.rsplit(".", 1)[-1].lower()
        mime_type = TEMPLATE_MIME_TYPES.get(extension)
        return frozenset({mime_type}) if mime_type else frozenset()
    return frozenset({FORMAT_MIME_TYPES[step.format.value]})


def _result_text(result: dict[str, Any]) -> str:
    blocks = cast(list[dict[str, Any]], result.get("content") or [])
    texts = [
        str(block.get("text") or "") for block in blocks if block.get("type") == "text"
    ]
    return " ".join(text for text in texts if text).strip()


def document_from_result(
    result: dict[str, Any],
    *,
    step: DocumentStep,
    expected_mime_types: frozenset[str],
) -> GeneratedDocument:
    """The file the provider returned, checked (pure).

    Only a file block the proxy admitted for the file-creation purpose
    counts, in one of the expected types; its bytes must pass the generated
    document checks before they are stored.
    """
    blocks = cast(list[dict[str, Any]], result.get("content") or [])
    allowed = GENERATED_FILE_TYPES_BY_PURPOSE.get(DOCUMENT_PURPOSE, frozenset())
    candidates = [
        block
        for block in blocks
        if block.get("type") == "file"
        and str(block.get("mime_type") or "") in allowed
        and (not expected_mime_types or block.get("mime_type") in expected_mime_types)
    ]
    if result.get("is_error") or not candidates:
        detail = _result_text(result)
        raise FlowStepError(
            STEP_DOCUMENT_FAILED,
            f"Step '{step.name}' produced no document"
            + (f": {detail[:500]}" if detail else "."),
        )
    block = candidates[0]
    mime_type = str(block.get("mime_type"))
    try:
        data = base64.b64decode(str(block.get("data") or ""), validate=True)
        validate_generated_document(data, mime_type)
    except (binascii.Error, GeneratedDocumentRejected) as exc:
        raise FlowStepError(
            STEP_DOCUMENT_FAILED,
            f"Step '{step.name}' produced a document Eneo cannot keep: {exc}",
        ) from exc
    filename = str(block.get("filename") or "") or f"{step.name}.{step.format.value}"
    return GeneratedDocument(data=data, filename=filename, mime_type=mime_type)


class StepRunners:
    def __init__(
        self,
        completion_service: CompletionService,
        references_service: ReferencesService,
        file_service: FileService,
        space_repo: SpaceRepository,
        flow_repo: FlowRepository,
        assistant_service: AssistantService,
        proxy_factory: MCPProxySessionFactory,
        user: UserInDB,
        transcriber: Transcriber,
    ):
        self.completion_service = completion_service
        self.references_service = references_service
        self.file_service = file_service
        self.space_repo = space_repo
        self.flow_repo = flow_repo
        self.assistant_service = assistant_service
        self.proxy_factory = proxy_factory
        self.user = user
        self.transcriber = transcriber
        self._space: Optional[Space] = None

    async def _space_for(self, ctx: RunContext) -> Space:
        if self._space is None or self._space.id != ctx.space_id:
            self._space = await self.space_repo.one(ctx.space_id)
        return self._space

    # --- prepare (inside a session scope) ---

    async def prepare(
        self, step: Step, ctx: RunContext, template_context: TemplateContext
    ) -> PreparedStep:
        if ctx.runtime_bindings:
            from eneo.flows.definition import FlowDefinition
            from eneo.flows.execution_bindings import bind_execution

            self._space = await self.space_repo.one(ctx.space_id)
            expected: dict[str, Any] = {"version": 1, "steps": {}}
            binding = ctx.runtime_bindings.get("steps", {}).get(step.key)
            if binding is not None:
                expected["steps"][step.key] = binding
            try:
                await bind_execution(
                    FlowDefinition(steps=[step]),
                    self._space,
                    self.assistant_service,
                    expected,
                )
            except Exception as exc:
                raise FlowStepError(
                    "flow_execution_dependency_changed",
                    "The published execution dependency is unavailable or changed; review and republish the flow.",
                ) from exc
        if isinstance(step, ComposeStep):
            return self._prepare_compose(step, template_context)
        if isinstance(step, LlmStep):
            return await self._prepare_llm(step, ctx, template_context)
        if isinstance(step, DocumentStep):
            return await self._prepare_document(step, ctx, template_context)
        if isinstance(step, FunctionStep):
            return await self._prepare_function(step, ctx, template_context)
        if isinstance(step, TranscribeStep):
            return await self._prepare_transcribe(step, ctx, template_context)
        raise FlowStepError(STEP_FAILED, f"Step '{step.name}' has no runner.")

    # --- shared: the provider serving a capability of the flows assistant ---

    async def _capability_server(
        self, ctx: RunContext, step: Step, purpose: str
    ) -> tuple[MCPServer, UUID]:
        space = await self._space_for(ctx)
        assistant = next(
            (
                candidate
                for candidate in space.purpose_assistants
                if candidate.purpose == FLOWS_ASSISTANT_PURPOSE
            ),
            None,
        )
        if assistant is None:
            raise FlowStepError(
                STEP_DOCUMENT_UNAVAILABLE,
                f"Step '{step.name}' needs the space's flows assistant, which "
                "does not exist; open the flow's chat once to create it.",
            )
        server = await self.assistant_service.capability_server(
            assistant_id=assistant.id, purpose=purpose
        )
        if server is None:
            raise FlowStepError(
                STEP_DOCUMENT_UNAVAILABLE
                if purpose == DOCUMENT_PURPOSE
                else STEP_FUNCTION_UNAVAILABLE,
                f"Step '{step.name}' needs the {purpose} function, but no provider "
                "for it is available in this space.",
            )
        return server, assistant.id

    async def _signed_file_url(
        self, ctx: RunContext, step: Step, file_id: UUID
    ) -> tuple[str, str]:
        """A signed link to a run file and its name; checks the original is kept."""
        try:
            metadata = await self.file_service.ensure_original_available(
                file_id, require_owner=False
            )
        except (NotFoundException, FileOriginalNotFoundError) as exc:
            raise FlowStepError(
                STEP_TEMPLATE_FILE_UNAVAILABLE,
                f"Step '{step.name}' names a file whose original is no longer stored.",
            ) from exc
        base_url = file_reference_base_url()
        if not base_url:
            raise FlowStepError(
                STEP_DOCUMENT_UNAVAILABLE,
                "No FILE_REFERENCE_BASE_URL or PUBLIC_ORIGIN is configured, so a "
                "provider cannot be handed a file.",
            )
        url = build_signed_original_download_url(
            file_id=file_id,
            base_url=base_url,
            expires_in=get_settings().file_reference_url_expiry_seconds,
            tenant_id=ctx.tenant_id,
        )
        return url, metadata.name

    async def _file_links(
        self,
        ctx: RunContext,
        step: Step,
        field_keys: list[str],
        context: TemplateContext,
    ) -> dict[UUID, str]:
        """Signed links to the files of the given form fields, also placed in
        the template context so ``{{files.<key>}}`` renders them."""
        urls: dict[UUID, str] = {}
        for key in field_keys:
            links: list[str] = []
            for file_id in ctx.file_ids_for(key):
                url, _ = await self._signed_file_url(ctx, step, file_id)
                urls[file_id] = url
                links.append(url)
            context.files[key] = links
        return urls

    @staticmethod
    def _render(label: str, template: str, context: TemplateContext) -> str:
        return _render_or_error(label, template, context)

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

        pinned = ctx.runtime_bindings.get("steps", {}).get(step.key, {}).get("model_id")
        model_id = UUID(pinned) if pinned else step.model_id
        if model_id is not None:
            try:
                model = space.get_completion_model(model_id)
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

        if step.processing:
            if any(
                file.mimetype
                in {
                    "text/csv",
                    "text/tab-separated-values",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/vnd.ms-excel",
                }
                or file.name.lower().endswith(
                    (".csv", ".tsv", ".xlsx", ".xls", ".ods", ".parquet")
                )
                for file in files
            ):
                raise FlowStepError(
                    STEP_INPUT_TOO_LARGE,
                    "Tables must be read with a file-analysis function step, not summarized from extracted text.",
                )
            context_text = text_input if files else ""
            sources = (
                [
                    Source(
                        f"D{index + 1}", file.name, file.inline_text or "", str(file.id)
                    )
                    for index, file in enumerate(files)
                ]
                if files
                else [Source("D1", "Input", text_input)]
            )
            summary_prompt = (
                self._render(
                    f"step '{step.key}' processing.summary_prompt",
                    step.processing.summary_prompt,
                    context,
                )
                if step.processing.mode == "summarize"
                and step.processing.summary_prompt
                else None
            )
            try:
                plan = prepare_long_input(
                    sources,
                    mode=step.processing.mode,
                    section_tokens=step.processing.section_tokens,
                    window=model.token_limit,
                    output_tokens=model.max_output_tokens,
                    tokens=lambda text: count_tokens(text, model.name),
                    prompt=prompt,
                    context=context_text,
                    summary_prompt=summary_prompt,
                )
            except LongInputError as exc:
                raise FlowStepError(STEP_INPUT_TOO_LARGE, str(exc)) from exc
            return PreparedStep(
                input_payload={
                    "text": text_input,
                    "prompt": prompt,
                    "model_id": str(model.id),
                    "file_ids": [str(file.id) for file in files],
                    "processing": step.processing.model_dump(),
                    "sections": sum(group.total_segments for group in plan.plans),
                },
                prompt=prompt,
                text_input=context_text,
                model=model,
                model_kwargs=ModelKwargs.model_validate(step.model_kwargs)
                if step.model_kwargs is not None
                else None,
                long_plan=plan,
                run_context=ctx,
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

    async def _prepare_document(
        self, step: DocumentStep, ctx: RunContext, context: TemplateContext
    ) -> PreparedStep:
        server, assistant_id = await self._capability_server(
            ctx, step, DOCUMENT_PURPOSE
        )

        template: Optional[tuple[str, str]] = None
        reference_urls: dict[UUID, str] = {}
        if step.template_file_id is not None:
            file_id = step.template_file_id
            pinned = await self.flow_repo.get_flow_file(
                ctx.flow_id, file_id, role="template"
            )
            if pinned is None:
                raise FlowStepError(
                    STEP_TEMPLATE_FILE_UNAVAILABLE,
                    f"Step '{step.name}' names a template file that does not "
                    "belong to this flow.",
                )
            url, name = await self._signed_file_url(ctx, step, file_id)
            reference_urls[file_id] = url
            template = (url, name)

        tool_name, arguments = document_tool_arguments(step, context, template=template)
        document_template: Optional[DocumentTemplateReference] = None
        if tool_name == CREATE_DOCUMENT_TOOL:
            document_template = await resolve_document_template(
                self.flow_repo.session,
                tenant_id=ctx.tenant_id,
                assistant_id=assistant_id,
            )
        return PreparedStep(
            input_payload={
                "tool": tool_name,
                # Stored with the run: signed links are credentials and stay out.
                "arguments": redact_reference_tokens(arguments),
                "template_file_id": (
                    str(step.template_file_id) if step.template_file_id else None
                ),
            },
            document=DocumentCall(
                server=server,
                tool_name=tool_name,
                arguments=arguments,
                reference_urls=reference_urls,
                document_template=document_template,
            ),
            io_needs_session=False,
        )

    # --- invoke (provider I/O) ---

    async def invoke(self, step: Step, prepared: PreparedStep) -> StepOutcome:
        if prepared.output_payload is not None:
            return StepOutcome(output_payload=prepared.output_payload)
        if prepared.document is not None and isinstance(step, DocumentStep):
            return await self._invoke_document(step, prepared.document)
        if prepared.document is not None and isinstance(step, FunctionStep):
            return await self._invoke_function(step, prepared.document)
        if prepared.transcribe is not None and isinstance(step, TranscribeStep):
            return await self._invoke_transcribe(step, prepared.transcribe)
        assert isinstance(step, LlmStep) and prepared.model is not None
        if prepared.long_plan is not None:
            return await self._invoke_long_input(prepared)
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
            value = await parse_json_output(text, prepared.json_schema)
        except ValueError as first_error:
            retry_input = JSON_RETRY_INPUT.format(
                input=prepared.text_input, error=first_error
            )
            text, more_in, more_out = await self._complete(prepared, retry_input)
            tokens_in = (tokens_in or 0) + (more_in or 0)
            tokens_out = (tokens_out or 0) + (more_out or 0)
            try:
                value = await parse_json_output(text, prepared.json_schema)
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

    async def _invoke_long_input(self, prepared: PreparedStep) -> StepOutcome:
        assert prepared.model is not None and prepared.run_context is not None
        assert prepared.long_plan is not None
        ctx = prepared.run_context
        model = prepared.model

        async def should_stop() -> bool:
            return not await self.flow_repo.run_can_continue(ctx.run_id, ctx.tenant_id)

        async def complete(
            prompt: str, text: str, max_tokens: int, final: bool
        ) -> tuple[str, Usage]:
            if count_tokens(prompt + text, model.name) + max_tokens > model.token_limit:
                raise LongInputError(
                    "A digest call exceeds the pinned model's context window."
                )
            kwargs = prepared.model_kwargs or ModelKwargs()
            changes: dict[str, Any] = {"response_format": None}
            if not final and model.get_supported_model_kwargs().temperature.accepts(
                0.0
            ):
                changes["temperature"] = 0.0
            call_model = copy(model)
            call_model.max_output_tokens = min(model.max_output_tokens, max_tokens)
            call = replace(
                prepared,
                prompt=prompt,
                model=call_model,
                model_kwargs=kwargs.model_copy(update=changes),
            )
            return await self._complete_with_usage(call, text)

        try:
            payload, incoming, outgoing = await process_long_input(
                prepared.long_plan,
                complete=complete,
                should_stop=should_stop,
                tokens=lambda text: count_tokens(text, model.name),
            )
        except LongInputError as exc:
            raise FlowStepError(STEP_INPUT_TOO_LARGE, str(exc)) from exc
        return StepOutcome(
            output_payload=payload,
            num_tokens_input=incoming,
            num_tokens_output=outgoing,
        )

    async def _complete(
        self, prepared: PreparedStep, text_input: str
    ) -> tuple[str, Optional[int], Optional[int]]:
        text, usage = await self._complete_with_usage(prepared, text_input)
        return text, usage.input_tokens, usage.output_tokens

    async def _complete_with_usage(
        self, prepared: PreparedStep, text_input: str
    ) -> tuple[str, Usage]:
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
        if getattr(completion, "error", None):
            raise FlowStepError(
                STEP_FAILED, "The completion provider could not finish the call."
            )
        if isinstance(completion, str):
            text = completion
        else:
            text = getattr(completion, "text", None) or ""
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else response.total_token_count
        tokens_out = usage.completion_tokens if usage else None
        return text, Usage(
            tokens_in or 0,
            tokens_out or 0,
            length_stopped=getattr(completion, "stop", True) is False,
        )

    async def _invoke_document(
        self, step: DocumentStep, call: DocumentCall
    ) -> StepOutcome:
        """One provider call through the proxy, exactly as a turn would make it.

        The proxy admits the file block because the provider serves the
        file-creation purpose; the bytes are checked here and stored by
        :meth:`store_documents` once a session is open again.
        """
        template_filename = (
            str(call.arguments["template"]["filename"])
            if isinstance(call.arguments.get("template"), dict)
            else None
        )
        proxy = self.proxy_factory.create(
            [call.server], identity_headers=build_identity_headers(self.user, None)
        )
        try:
            if call.reference_urls:
                # The provider is handed only the links this call minted.
                proxy.allow_file_references(call.reference_urls)
            if call.document_template is not None:
                proxy.set_document_template(call.document_template)
            await proxy.prepare_tools_for_context()
            tool = proxy.prefixed_tool_name(call.server.id, call.tool_name)
            if tool is None:
                raise FlowStepError(
                    STEP_DOCUMENT_UNAVAILABLE,
                    f"Step '{step.name}' needs the {call.tool_name} tool, which "
                    f"the document provider '{call.server.name}' does not offer.",
                )
            result = (await proxy.call_tools_parallel([(tool, call.arguments)]))[0]
        finally:
            await proxy.close()
        document = document_from_result(
            result,
            step=step,
            expected_mime_types=expected_document_mime_types(step, template_filename),
        )
        return StepOutcome(
            output_payload={"text": document.filename, "value": None},
            documents=[document],
        )

    # --- store (inside a session scope) ---

    async def store_documents(self, documents: list[GeneratedDocument]) -> list[UUID]:
        """Keep produced documents as files of the run's principal.

        They go through the file service like any generated document, so
        signed downloads, previews and the platform's file lifecycle apply.
        """
        file_ids: list[UUID] = []
        for document in documents:
            if document.mime_type in ("image/png", "image/jpeg"):
                file = await self.file_service.save_image_from_bytes(
                    document.data, name=document.filename, mimetype=document.mime_type
                )
            else:
                file = await self.file_service.save_generated_document(
                    document.data, name=document.filename, mimetype=document.mime_type
                )
            file_ids.append(file.id)
        return file_ids

    # --- function steps (any capability's tool with bound arguments) ---

    async def _prepare_function(
        self, step: FunctionStep, ctx: RunContext, context: TemplateContext
    ) -> PreparedStep:
        server, _ = await self._capability_server(ctx, step, step.purpose)
        tool = next((entry for entry in server.tools if entry.name == step.tool), None)
        if tool is None:
            names = ", ".join(entry.name for entry in server.tools) or "none"
            raise FlowStepError(
                STEP_FUNCTION_UNAVAILABLE,
                f"Step '{step.name}' calls '{step.tool}', which the {step.purpose} "
                f"provider does not offer (it offers: {names}).",
            )
        reference_urls = await self._file_links(ctx, step, step.files_from, context)
        arguments = cast(
            dict[str, Any],
            render_arguments(step, step.arguments, context),
        )
        schema = getattr(tool, "input_schema", None)
        if isinstance(schema, dict):
            try:
                await validate_value(
                    arguments, cast(dict[str, Any], schema), authored=False
                )
            except ValueError as exc:
                raise FlowStepError(
                    STEP_FUNCTION_FAILED,
                    f"Step '{step.name}' has arguments '{step.tool}' does not "
                    f"accept: {exc}",
                ) from exc
        return PreparedStep(
            input_payload={
                "tool": step.tool,
                "purpose": step.purpose,
                "arguments": redact_reference_tokens(arguments),
            },
            document=DocumentCall(
                server=server,
                tool_name=step.tool,
                arguments=arguments,
                reference_urls=reference_urls,
            ),
            io_needs_session=False,
        )

    async def _invoke_function(
        self, step: FunctionStep, call: DocumentCall
    ) -> StepOutcome:
        result = await self._call_tool(step, call)
        return function_outcome(result, step=step)

    async def _call_tool(self, step: Step, call: DocumentCall) -> dict[str, Any]:
        """One provider call through the proxy, exactly as a turn would make it."""
        proxy = self.proxy_factory.create(
            [call.server], identity_headers=build_identity_headers(self.user, None)
        )
        try:
            if call.reference_urls:
                proxy.allow_file_references(call.reference_urls)
            if call.document_template is not None:
                proxy.set_document_template(call.document_template)
            await proxy.prepare_tools_for_context()
            tool = proxy.prefixed_tool_name(call.server.id, call.tool_name)
            if tool is None:
                raise FlowStepError(
                    STEP_FUNCTION_UNAVAILABLE,
                    f"Step '{step.name}' needs the {call.tool_name} tool, which "
                    f"the provider '{call.server.name}' does not offer.",
                )
            return (await proxy.call_tools_parallel([(tool, call.arguments)]))[0]
        finally:
            await proxy.close()

    # --- transcribe steps ---

    async def _prepare_transcribe(
        self, step: TranscribeStep, ctx: RunContext, context: TemplateContext
    ) -> PreparedStep:
        space = await self._space_for(ctx)
        model: Optional[TranscriptionModel]
        pinned = ctx.runtime_bindings.get("steps", {}).get(step.key, {}).get("model_id")
        model_id = UUID(pinned) if pinned else step.transcription_model_id
        if model_id is not None:
            try:
                model = space.get_transcription_model(model_id)
            except NotFoundException:
                model = None
        else:
            model = space.get_default_transcription_model()
        if model is None:
            raise FlowStepError(
                STEP_TRANSCRIPTION_MODEL_UNAVAILABLE,
                f"Step '{step.name}' has no transcription model available in this "
                "space.",
            )
        file_ids = ctx.file_ids_for(step.source)
        if not file_ids:
            raise FlowStepError(
                STEP_AUDIO_UNAVAILABLE,
                f"Step '{step.name}' got no audio: form field '{step.source}' "
                "has no file.",
            )
        audio: list[AudioInput] = []
        for file_id in file_ids:
            try:
                file = await self.file_service.get_file_content(file_id)
            except NotFoundException as exc:
                raise FlowStepError(
                    STEP_AUDIO_UNAVAILABLE,
                    f"Step '{step.name}' cannot read file {file_id}.",
                ) from exc
            if file.blob is None:
                raise FlowStepError(
                    STEP_AUDIO_UNAVAILABLE,
                    f"Step '{step.name}' cannot read the audio of '{file.name}'.",
                )
            audio.append(
                AudioInput(
                    file_id=file.id,
                    name=file.name,
                    mimetype=file.mimetype or "application/octet-stream",
                    data=file.blob,
                )
            )
        adapter = await self.transcriber.prepare_transcription(model)
        speaker_service: Optional[SpeakerService] = None
        if step.speaker_labels:
            config = configured_speaker_service()
            if config is None:
                raise FlowStepError(
                    STEP_SPEAKER_SERVICE_UNAVAILABLE,
                    f"Step '{step.name}' asks for speaker labels, but no speaker "
                    "service is configured (FLOW_SPEAKER_SERVICE_URL).",
                )
            speaker_service = SpeakerService(config)
        participants: list[str] = []
        infer_names = False
        mapping_model: Optional[CompletionModel] = None
        if step.speaker_labels and step.speaker_mapping is not None:
            mapping = step.speaker_mapping
            if mapping.participants_field:
                participants = parse_participants(
                    ctx.form_values.get(mapping.participants_field)
                )
            infer_names = mapping.infer_names
            if participants or infer_names:
                pinned_mapping = (
                    ctx.runtime_bindings.get("steps", {})
                    .get(step.key, {})
                    .get("speaker_model", {})
                    .get("model_id")
                )
                mapping_id = (
                    UUID(pinned_mapping) if pinned_mapping else mapping.model_id
                )
                mapping_model = (
                    space.get_completion_model(mapping_id)
                    if mapping_id is not None
                    else space.get_default_completion_model()
                )
                if mapping_model is None or not mapping_model.can_access:
                    raise FlowStepError(
                        STEP_MODEL_UNAVAILABLE,
                        f"Step '{step.name}' needs a completion model to name "
                        "speakers, but none is available.",
                    )
        return PreparedStep(
            input_payload={
                "source": step.source,
                "file_ids": [str(item.file_id) for item in audio],
                "model_id": str(model.id),
                "language": step.language,
                "speaker_labels": step.speaker_labels,
            },
            transcribe=TranscribeCall(
                adapter=adapter,
                model_id=model.id,
                model_name=model.name,
                language=step.language,
                audio=audio,
                speaker_labels=step.speaker_labels,
                max_speakers=step.max_speakers,
                speaker_service=speaker_service,
                participants=participants,
                infer_names=infer_names,
                mapping_model=mapping_model,
            ),
        )

    async def _invoke_transcribe(
        self, step: TranscribeStep, call: TranscribeCall
    ) -> StepOutcome:
        serialized: list[dict[str, Any]] = []
        transcriptions: list[tuple[UUID, str]] = []
        label_offset = 0
        audio_seconds = 0.0
        for index, item in enumerate(call.audio):
            try:
                transcribed = await self.transcriber.transcribe_prepared_bytes(
                    item.data, adapter=call.adapter, language=call.language
                )
            except Exception as exc:
                raise FlowStepError(
                    STEP_FAILED,
                    f"Step '{step.name}' could not transcribe '{item.name}': "
                    f"{type(exc).__name__}: {exc}",
                ) from exc
            segments: list[TranscriptSegment] = list(transcribed.segments)
            if segments:
                audio_seconds += max(segment.end for segment in segments)
            if call.speaker_service is not None and segments:
                try:
                    labelled = await call.speaker_service.label_speakers(
                        item.data,
                        filename=item.name,
                        mimetype=item.mimetype,
                        segments=segments,
                        model_name=call.model_name,
                        language=call.language,
                        max_speakers=call.max_speakers,
                    )
                except SpeakerServiceError as exc:
                    raise FlowStepError(
                        exc.code, f"Step '{step.name}': {exc.message}"
                    ) from exc
                segments, count = renumber_segment_speakers(labelled, label_offset)
                label_offset += count
            transcriptions.append((item.file_id, transcribed.text))
            serialized.extend(segment.as_json(file_index=index) for segment in segments)

        speaker_names: dict[str, Optional[str]] = {}
        inventory = build_speaker_inventory(serialized)
        if call.mapping_model is not None and inventory:
            speaker_names = await self._map_speakers(step, call, serialized, inventory)

        text = (
            render_segments(serialized, speaker_names)
            if call.speaker_labels
            else "\n\n".join(text for _, text in transcriptions)
        )
        return StepOutcome(
            output_payload={"text": text, "value": None},
            transcriptions=transcriptions,
            transcription={
                "model": call.model_name,
                "model_id": str(call.model_id),
                "language": call.language,
                "file_ids": [str(item.file_id) for item in call.audio],
                "files_count": len(call.audio),
                "audio_seconds": round(audio_seconds, 1),
                "speaker_labels": call.speaker_labels,
                "speakers": inventory,
                "speaker_names": speaker_names,
                "segments": serialized,
            },
        )

    async def _map_speakers(
        self,
        step: TranscribeStep,
        call: TranscribeCall,
        segments: list[dict[str, Any]],
        inventory: list[dict[str, Any]],
    ) -> dict[str, Optional[str]]:
        assert call.mapping_model is not None
        opening = build_opening_excerpt(segments) if call.infer_names else None
        question = build_speaker_mapping_question(
            inventory=inventory, participants=call.participants, opening=opening
        )
        prompt = speaker_mapping_instructions(infer_names=call.infer_names)
        prepared = PreparedStep(
            input_payload={},
            prompt=prompt,
            model=call.mapping_model,
            text_input=question,
        )
        try:
            answer, _, _ = await self._complete(prepared, question)
            return parse_speaker_mapping(
                answer,
                inventory=inventory,
                participants=call.participants,
                allow_free_text=call.infer_names or not call.participants,
            )
        except SpeakerMappingInvalid as exc:
            raise FlowStepError(
                STEP_SPEAKER_MAPPING_FAILED,
                f"Step '{step.name}' could not name the speakers: {exc}",
            ) from exc

    # --- store (inside a session scope) ---

    async def store_transcriptions(self, items: list[tuple[UUID, str]]) -> None:
        """Keep each transcript on its audio file, so a later llm step that
        reads the field (files_from) sees the text."""
        for file_id, text in items:
            try:
                await self.file_service.save_transcription(file_id, text)
            except Exception as exc:  # the transcript is kept with the step anyway
                logger.warning(
                    "Could not keep the transcript on file %s: %s", file_id, exc
                )


def signed_links_for(tenant_id: Optional[UUID], file_ids: list[UUID]) -> list[str]:
    """Signed links to run files, for ``{{steps.<key>.file}}``; empty when no
    file reference base URL is configured (no tool could be handed them)."""
    base_url = file_reference_base_url()
    if not base_url or tenant_id is None or not file_ids:
        return []
    expires_in = get_settings().file_reference_url_expiry_seconds
    return [
        build_signed_original_download_url(
            file_id=file_id,
            base_url=base_url,
            expires_in=expires_in,
            tenant_id=tenant_id,
        )
        for file_id in file_ids
    ]


def render_arguments(step: FunctionStep, value: Any, context: TemplateContext) -> Any:
    """``value`` with every string inside rendered as a template (pure)."""
    if isinstance(value, str):
        from eneo.flows.templating import render_argument

        try:
            return render_argument(value, context)
        except TemplateError as exc:
            raise FlowStepError(
                STEP_TEMPLATE_ERROR, f"step '{step.key}' arguments: {exc}"
            ) from exc
    if isinstance(value, dict):
        return {
            key: render_arguments(step, item, context)
            for key, item in cast(dict[str, Any], value).items()
        }
    if isinstance(value, list):
        return [
            render_arguments(step, item, context) for item in cast(list[Any], value)
        ]
    return value


def function_outcome(result: dict[str, Any], *, step: FunctionStep) -> StepOutcome:
    """A tool result as a step outcome (pure): its text, structured value
    and the files or images it produced, which the executor stores."""
    blocks = cast(list[dict[str, Any]], result.get("content") or [])
    texts = [
        str(block.get("text") or "") for block in blocks if block.get("type") == "text"
    ]
    text = "\n\n".join(text for text in texts if text).strip()
    if result.get("is_error"):
        raise FlowStepError(
            STEP_FUNCTION_FAILED,
            f"Step '{step.name}' failed in '{step.tool}'"
            + (f": {text[:500]}" if text else "."),
        )
    documents: list[GeneratedDocument] = []
    for index, block in enumerate(blocks):
        kind = block.get("type")
        if kind not in ("file", "image"):
            continue
        mime_type = str(block.get("mime_type") or block.get("mimeType") or "")
        try:
            data = base64.b64decode(str(block.get("data") or ""), validate=True)
        except binascii.Error:
            continue
        if kind == "file":
            try:
                validate_generated_document(data, mime_type)
            except GeneratedDocumentRejected:
                continue
            filename = str(block.get("filename") or "") or f"{step.key}-{index}"
        else:
            if mime_type not in ("image/png", "image/jpeg"):
                continue
            extension = "png" if mime_type == "image/png" else "jpg"
            filename = f"{step.key}-{index}.{extension}"
        documents.append(
            GeneratedDocument(data=data, filename=filename, mime_type=mime_type)
        )
    value: Any = result.get("structured_content") or result.get("structuredContent")
    if value is None and text:
        try:
            parsed: Any = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            value = cast(Any, parsed)
    return StepOutcome(
        output_payload={
            "text": text or ", ".join(d.filename for d in documents),
            "value": value,
        },
        documents=documents,
    )
