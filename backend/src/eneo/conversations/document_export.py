"""A Markdown document of a conversation, handed over as Word or PDF.

The assistant writes documents as Markdown, which is read in Eneo. A reader
who needs the document elsewhere exports it: the provider that serves the
assistant's file-creation capability renders the document's own text in the
other format. The bytes go back to the reader as a download and are not
stored; a Word file that should live in the conversation is asked for there.

A document shows an image as a line naming a file by its handle
(``![alt](eneo-file:...)``). The export hands the provider a signed link for
each such file the conversation holds, so the image is embedded in the file
that leaves Eneo.
"""

import base64
import binascii
import re
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel

from eneo.authentication.signed_urls import build_signed_original_download_url
from eneo.document_templates.models import DocumentTemplateReferencePublic
from eneo.files.file_reference import (
    file_reference_base_url,
    image_reference_file_ids,
)
from eneo.files.generated_documents import (
    GeneratedDocumentRejected,
    validate_generated_document,
)
from eneo.files.model_file_references import HANDLE_PATTERN, HANDLE_PREFIX
from eneo.main.config import get_settings
from eneo.main.exceptions import NotFoundException
from eneo.main.logging import get_logger
from eneo.mcp_servers.domain.entities.mcp_server import (
    DOCX_MIME_TYPE,
    MARKDOWN_MIME_TYPE,
    PDF_MIME_TYPE,
)

if TYPE_CHECKING:
    from jsonschema.protocols import Validator

    from eneo.assistants.assistant_service import AssistantService
    from eneo.document_templates.domain import DocumentTemplateReference
    from eneo.files.file_models import File
    from eneo.files.file_service import FileService
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
        MCPProxySessionFactory,
    )
    from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession
    from eneo.sessions.session import SessionInDB

logger = get_logger(__name__)

ExportFormat = Literal["docx", "pdf"]
# Gives the template an assistant's documents render with (document_templates.service).
TemplateResolver = Callable[[UUID], Awaitable["DocumentTemplateReference"]]
EXPORT_MIME_TYPES: dict[str, str] = {"docx": DOCX_MIME_TYPE, "pdf": PDF_MIME_TYPE}
# The capability whose provider renders documents, and the tool it does so with.
EXPORT_PURPOSE = "file_creation"
EXPORT_TOOL = "create_document"

_NOT_FOUND = "Document not found in this conversation"

# An image of a Markdown document: alt text, the file's handle, perhaps a caption.
_IMAGE = re.compile(
    r"!\[(?P<alt>[^\]\n]*)\]\((?P<handle>" + HANDLE_PATTERN + r")(?:[ \t][^)\n]*)?\)"
)
# What the renderer is told the image is; it checks the bytes itself.
_IMAGE_FILENAMES = {"image/png": "image.png", "image/jpeg": "image.jpg"}


ExportUnavailableReason = Literal[
    "provider_unavailable",
    "tool_unavailable",
    "incompatible_tool",
    "format_unsupported",
    "document_unsupported",
]


class DocumentExportFormatAvailability(BaseModel):
    available: bool
    reason: ExportUnavailableReason | None = None


class DocumentExportAvailability(BaseModel):
    docx: DocumentExportFormatAvailability
    pdf: DocumentExportFormatAvailability
    template: DocumentTemplateReferencePublic | None = None


def export_compatibility(
    schema: dict[str, Any] | None, arguments: dict[str, Any]
) -> DocumentExportFormatAvailability:
    """Check our exact request against the approved native export contract.

    Never resolve schema references over the network. Discovery proves input
    compatibility, not that the remote implementation will successfully render.
    """

    def unavailable(reason: ExportUnavailableReason):
        return DocumentExportFormatAvailability(available=False, reason=reason)

    def references(value: Any) -> bool:
        if isinstance(value, dict):
            return any(
                key in value for key in ("$ref", "$dynamicRef", "$recursiveRef")
            ) or any(
                references(child) for child in cast(dict[str, Any], value).values()
            )
        return isinstance(value, list) and any(
            references(child) for child in cast(list[Any], value)
        )

    if (
        not isinstance(schema, dict)
        or schema.get("type") != "object"
        or references(schema)
    ):
        return unavailable("incompatible_tool")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return unavailable("incompatible_tool")
    properties = cast(dict[str, Any], properties)
    for name, value in arguments.items():
        field = properties.get(name)
        # The document's images go as a list; everything else is text.
        expected = "array" if isinstance(value, list) else "string"
        if (
            not isinstance(field, dict)
            or cast(dict[str, Any], field).get("type") != expected
        ):
            return unavailable("incompatible_tool")
    formats = properties["format"].get("enum")
    required = schema.get("required", [])
    if (
        not isinstance(formats, list)
        or not formats
        or not all(isinstance(value, str) for value in cast(list[Any], formats))
        or not isinstance(required, list)
        or any(
            not isinstance(name, str) or name not in arguments
            for name in cast(list[Any], required)
        )
        or any(key in schema for key in ("allOf", "anyOf", "oneOf", "if", "not"))
    ):
        return unavailable("incompatible_tool")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        return unavailable("incompatible_tool")
    if arguments["format"] not in formats:
        return unavailable("format_unsupported")
    validator = cast("Validator", Draft202012Validator(schema))
    if not validator.is_valid(arguments):
        return unavailable("document_unsupported")
    return DocumentExportFormatAvailability(available=True)


class DocumentExportUnavailable(Exception):
    """The assistant has no compatible provider for this document and format."""

    def __init__(self, reason: ExportUnavailableReason = "provider_unavailable"):
        self.reason = reason
        super().__init__(reason)


class DocumentExportFailed(Exception):
    """The provider did not return the document in the format asked for."""


@dataclass(frozen=True)
class ExportedDocument:
    filename: str
    mime_type: str
    data: bytes
    mcp_server_id: UUID


def _stem(filename: str) -> str:
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def conversation_document(
    conversation: "SessionInDB", file_id: UUID
) -> "tuple[UUID | None, File] | None":
    """The Markdown document the assistant made in this conversation, and its assistant."""
    for question in conversation.questions or []:
        for file in question.generated_files or []:
            if file.id == file_id and file.mimetype == MARKDOWN_MIME_TYPE:
                return question.assistant_id, file
    return None


def _with_images(
    content: str, conversation: "SessionInDB"
) -> tuple[str, dict[UUID, dict[str, str]]]:
    """The document's text and its images, by file, as the renderer takes them.

    An image is signed only when the conversation itself holds the file
    (attached to or generated in one of its turns); what the document says is
    the model's writing and never on its own a reason to sign a link. Any other
    image is left as its alt text, so the rest of the document still exports.
    """
    if HANDLE_PREFIX not in content:
        return content, {}
    held: "dict[UUID, File]" = {
        file.id: file
        for question in conversation.questions or []
        for file in [
            *getattr(question, "files", []),
            *getattr(question, "generated_files", []),
        ]
    }
    base_url = file_reference_base_url()
    expires_in = get_settings().file_reference_url_expiry_seconds
    images: dict[UUID, dict[str, str]] = {}

    def place(match: re.Match[str]) -> str:
        file_id = UUID(hex=match["handle"][len(HANDLE_PREFIX) :])
        file = held.get(file_id)
        filename = _IMAGE_FILENAMES.get((file.mimetype if file else None) or "")
        if (
            file is None
            or filename is None
            or not base_url
            or file_id not in image_reference_file_ids([file])
        ):
            return match["alt"]
        if file_id not in images:
            images[file_id] = {
                "url": build_signed_original_download_url(
                    file_id=file_id,
                    base_url=base_url,
                    expires_in=expires_in,
                    tenant_id=file.tenant_id,
                ),
                "filename": filename,
            }
        return match[0]

    content = _IMAGE.sub(place, content)
    return content, images


@asynccontextmanager
async def _export_context(
    *,
    conversation: "SessionInDB",
    file_id: UUID,
    assistant_service: "AssistantService",
    file_service: "FileService",
    proxy_factory: "MCPProxySessionFactory",
    identity_headers: dict[str, str],
    template_resolver: "TemplateResolver | None" = None,
) -> AsyncGenerator[
    tuple[
        "MCPServer | None",
        "MCPProxySession | None",
        str | None,
        dict[str, Any],
        DocumentExportAvailability,
    ]
]:
    found = conversation_document(conversation, file_id)
    if found is None:
        raise NotFoundException(_NOT_FOUND)
    assistant_id, document = found
    if assistant_id is None and conversation.assistant is not None:
        assistant_id = conversation.assistant.id
    if assistant_id is None:
        raise NotFoundException(_NOT_FOUND)
    content = (await file_service.get_file_content(file_id)).text
    if not content:
        raise NotFoundException(_NOT_FOUND)
    name = _stem(document.name)
    content, images = _with_images(content, conversation)
    arguments: dict[str, Any] = {"title": name, "content": content, "filename": name}
    if images:
        arguments["images"] = list(images.values())
    server = await assistant_service.capability_server(
        assistant_id=assistant_id, purpose=EXPORT_PURPOSE
    )
    unavailable = DocumentExportFormatAvailability(
        available=False, reason="provider_unavailable"
    )
    if server is None:
        yield (
            None,
            None,
            None,
            arguments,
            DocumentExportAvailability(docx=unavailable, pdf=unavailable),
        )
        return
    proxy = proxy_factory.create([server], identity_headers=identity_headers)
    try:
        if images:
            # The proxy passes on only the signed links it was told of.
            proxy.allow_file_references(
                {file_id: image["url"] for file_id, image in images.items()}
            )
        # The export renders with the same template as the assistant's own calls.
        template = None
        if template_resolver is not None:
            reference = await template_resolver(assistant_id)
            if reference.argument is not None:
                proxy.set_document_template(reference)
            template = DocumentTemplateReferencePublic(
                name=reference.name,
                source=reference.source,
                template_id=reference.template_id,
            )
        await proxy.prepare_tools_for_context()
        tool = proxy.prefixed_tool_name(server.id, EXPORT_TOOL)
        approved = next(
            (entry for entry in server.tools if entry.name == EXPORT_TOOL), None
        )
        states: dict[str, DocumentExportFormatAvailability] = {}
        for format in EXPORT_MIME_TYPES:
            states[format] = (
                export_compatibility(
                    approved.input_schema, {**arguments, "format": format}
                )
                if tool is not None and approved is not None
                else DocumentExportFormatAvailability(
                    available=False, reason="tool_unavailable"
                )
            )
        yield (
            server,
            proxy,
            tool,
            arguments,
            DocumentExportAvailability(**states, template=template),
        )
    finally:
        await proxy.close()


async def document_export_availability(
    *,
    conversation: "SessionInDB",
    file_id: UUID,
    assistant_service: "AssistantService",
    file_service: "FileService",
    proxy_factory: "MCPProxySessionFactory",
    identity_headers: dict[str, str],
    template_resolver: "TemplateResolver | None" = None,
) -> DocumentExportAvailability:
    """Read the current contract without rendering or storing a document."""
    async with _export_context(
        conversation=conversation,
        file_id=file_id,
        assistant_service=assistant_service,
        file_service=file_service,
        proxy_factory=proxy_factory,
        identity_headers=identity_headers,
        template_resolver=template_resolver,
    ) as (_, _, _, _, availability):
        return availability


async def export_document(
    *,
    conversation: "SessionInDB",
    file_id: UUID,
    format: ExportFormat,
    assistant_service: "AssistantService",
    file_service: "FileService",
    proxy_factory: "MCPProxySessionFactory",
    identity_headers: dict[str, str],
    template_resolver: "TemplateResolver | None" = None,
) -> ExportedDocument:
    """Re-resolve permissions and the contract for every rendering attempt."""
    mime_type = EXPORT_MIME_TYPES[format]
    async with _export_context(
        conversation=conversation,
        file_id=file_id,
        assistant_service=assistant_service,
        file_service=file_service,
        proxy_factory=proxy_factory,
        identity_headers=identity_headers,
        template_resolver=template_resolver,
    ) as (server, proxy, tool, arguments, availability):
        if (
            not getattr(availability, format).available
            or server is None
            or proxy is None
            or tool is None
        ):
            raise DocumentExportUnavailable(
                getattr(availability, format).reason or "tool_unavailable"
            )
        name = arguments["filename"]
        result = (
            await proxy.call_tools_parallel([(tool, {**arguments, "format": format})])
        )[0]

    blocks = cast(list[dict[str, Any]], result.get("content") or [])
    # Only a file the proxy admitted for this capability, in the format asked for.
    block = next(
        (
            block
            for block in blocks
            if block.get("type") == "file" and block.get("mime_type") == mime_type
        ),
        None,
    )
    if result.get("is_error") or block is None:
        logger.warning(
            "Document export as %s returned no file from '%s'", format, server.name
        )
        raise DocumentExportFailed()
    try:
        data = base64.b64decode(str(block.get("data") or ""), validate=True)
        validate_generated_document(data, mime_type)
    except (binascii.Error, GeneratedDocumentRejected) as exc:
        logger.warning(
            "Document export as %s from '%s' was rejected: %s",
            format,
            server.name,
            exc,
        )
        raise DocumentExportFailed() from exc
    return ExportedDocument(
        filename=f"{name}.{format}",
        mime_type=mime_type,
        data=data,
        mcp_server_id=server.id,
    )
