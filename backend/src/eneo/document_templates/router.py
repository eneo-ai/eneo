"""The document template library (admin) and the signed download the runtime uses."""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import require_user_for_creation
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    authenticates,
    endpoint_access,
)
from eneo.authentication.signed_urls import verify_document_template_download_token
from eneo.document_templates import runtime_client
from eneo.document_templates.domain import DocumentTemplate
from eneo.document_templates.models import (
    DocumentTemplateList,
    DocumentTemplateOptionPublic,
    DocumentTemplateOptions,
    DocumentTemplatePublic,
    DocumentTemplateUpdate,
)
from eneo.document_templates.repo import DocumentTemplateRepository
from eneo.document_templates.validation import MAX_TEMPLATE_BYTES
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    AuthenticationException,
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.mcp_servers.domain.entities.mcp_server import DOCX_MIME_TYPE
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.server.protocol.downloads import content_disposition_header

router = APIRouter()
download_router = APIRouter()

_ADMIN_REASON = "Document templates are organisation-wide configuration."
_WITH_USER = Depends(get_container(with_user=True))


async def _read_upload(upload: UploadFile) -> tuple[str, bytes]:
    content = await upload.read(MAX_TEMPLATE_BYTES + 1)
    if len(content) > MAX_TEMPLATE_BYTES:
        raise BadRequestException("A document template may be at most 5 MiB.")
    return upload.filename or "", content


async def _audit(
    container: Container,
    action: ActionType,
    template: DocumentTemplate,
    description: str,
    *,
    changes: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=action,
        entity_type=EntityType.DOCUMENT_TEMPLATE,
        entity_id=template.id,
        description=description,
        metadata=AuditMetadata.standard(
            actor=user,
            target=template,
            changes=changes,
            extra={"name": template.name, "sha256": template.sha256, **(extra or {})},
        ),
    )


@router.get(
    "/",
    response_model=DocumentTemplateList,
    responses=responses.get_responses([403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ADMIN_REASON,
)
async def list_document_templates(container: Container = _WITH_USER):
    service = container.document_template_service()
    return DocumentTemplateList(
        items=[DocumentTemplatePublic.from_domain(t) for t in await service.list()],
        runtime_configured=runtime_client.configured(),
    )


@router.get(
    "/available/",
    response_model=DocumentTemplateOptions,
    responses=responses.get_responses([403]),
    description="The organisation's templates by name, for choosing one on an assistant.",
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Template names are organisation-wide; the files stay with administrators.",
)
async def list_available_document_templates(container: Container = _WITH_USER):
    user = container.user()
    repo = DocumentTemplateRepository(cast(AsyncSession, container.session()))
    return DocumentTemplateOptions(
        items=[
            DocumentTemplateOptionPublic(id=t.id, name=t.name, is_default=t.is_default)
            for t in await repo.list(user.tenant_id)
        ]
    )


@router.post(
    "/",
    response_model=DocumentTemplatePublic,
    status_code=201,
    responses=responses.get_responses([400, 403, 413, 415]),
    description=(
        "Upload a Word (.docx) template. The tool runtime reads its fields and "
        "styles; the result is stored with the template."
    ),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ADMIN_REASON,
)
async def upload_document_template(
    file: UploadFile,
    name: Annotated[str, Form(min_length=1, max_length=120)],
    is_default: Annotated[bool, Form()] = False,
    container: Container = _WITH_USER,
    _user_for_creation: None = Depends(require_user_for_creation),
):
    filename, content = await _read_upload(file)
    service = container.document_template_service()
    template = await service.upload(
        name=name, filename=filename, content=content, is_default=is_default
    )
    await _audit(
        container,
        ActionType.DOCUMENT_TEMPLATE_CREATED,
        template,
        f"Uploaded document template '{template.name}'",
        extra={"is_default": template.is_default, "status": template.status},
    )
    return DocumentTemplatePublic.from_domain(template)


@router.get(
    "/builtin/",
    response_class=Response,
    responses=responses.get_responses([400, 403]),
    description="Eneo's built-in document template, to adapt in Word.",
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ADMIN_REASON,
)
async def download_builtin_document_template(
    language: Annotated[Literal["sv", "en"], Query()] = "sv",
    container: Container = _WITH_USER,
):
    service = container.document_template_service()
    content = await service.builtin(language)
    return Response(
        content=content,
        media_type=DOCX_MIME_TYPE,
        headers={
            "Content-Disposition": content_disposition_header(
                "attachment", f"eneo-dokumentmall-{language}.docx"
            ),
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{id}/",
    response_model=DocumentTemplatePublic,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ADMIN_REASON,
)
async def get_document_template(id: UUID, container: Container = _WITH_USER):
    service = container.document_template_service()
    return DocumentTemplatePublic.from_domain(await service.get(id))


@router.patch(
    "/{id}/",
    response_model=DocumentTemplatePublic,
    responses=responses.get_responses([400, 403, 404]),
    description="Rename a template or make it the organisation's default.",
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ADMIN_REASON,
)
async def update_document_template(
    id: UUID, data: DocumentTemplateUpdate, container: Container = _WITH_USER
):
    service = container.document_template_service()
    before = await service.get(id)
    template = await service.update(id, name=data.name, is_default=data.is_default)
    changes: dict[str, Any] = {}
    if before.name != template.name:
        changes["name"] = {"old": before.name, "new": template.name}
    if before.is_default != template.is_default:
        changes["is_default"] = {"old": before.is_default, "new": template.is_default}
    if template.is_default and not before.is_default:
        await _audit(
            container,
            ActionType.DOCUMENT_TEMPLATE_DEFAULT_SET,
            template,
            f"Made '{template.name}' the organisation's document template",
            changes=changes,
        )
    elif changes:
        await _audit(
            container,
            ActionType.DOCUMENT_TEMPLATE_UPDATED,
            template,
            f"Updated document template '{template.name}'",
            changes=changes,
        )
    return DocumentTemplatePublic.from_domain(template)


@router.put(
    "/{id}/content/",
    response_model=DocumentTemplatePublic,
    responses=responses.get_responses([400, 403, 404, 413, 415]),
    description="Replace the template's Word file; the template keeps its id.",
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ADMIN_REASON,
)
async def replace_document_template_content(
    id: UUID, file: UploadFile, container: Container = _WITH_USER
):
    filename, content = await _read_upload(file)
    service = container.document_template_service()
    before = await service.get(id)
    template = await service.replace_content(id, filename=filename, content=content)
    await _audit(
        container,
        ActionType.DOCUMENT_TEMPLATE_UPDATED,
        template,
        f"Replaced the file of document template '{template.name}'",
        changes={
            "filename": {"old": before.filename, "new": template.filename},
            "sha256": {"old": before.sha256, "new": template.sha256},
        },
        extra={"status": template.status},
    )
    return DocumentTemplatePublic.from_domain(template)


@router.get(
    "/{id}/content/",
    response_class=Response,
    responses=responses.get_responses([403, 404]),
    description="Download the template's Word file.",
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ADMIN_REASON,
)
async def download_document_template(id: UUID, container: Container = _WITH_USER):
    service = container.document_template_service()
    template, content = await service.content(id)
    return Response(
        content=content,
        media_type=DOCX_MIME_TYPE,
        headers={
            "Content-Disposition": content_disposition_header(
                "attachment", template.filename
            ),
            "Cache-Control": "no-store",
        },
    )


@router.delete(
    "/{id}/",
    status_code=204,
    response_class=Response,
    responses=responses.get_responses([403, 404]),
    description=(
        "Remove a template. Assistants that selected it fall back to the "
        "organisation's default."
    ),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason=_ADMIN_REASON,
)
async def delete_document_template(id: UUID, container: Container = _WITH_USER):
    service = container.document_template_service()
    template = await service.delete(id)
    await _audit(
        container,
        ActionType.DOCUMENT_TEMPLATE_DELETED,
        template,
        f"Removed document template '{template.name}'",
        extra={"selected_by": template.selected_by},
    )
    return Response(status_code=204)


@authenticates(Authentication.SIGNED_URL)
def authorize_document_template_token(
    id: UUID,
    token: Annotated[str, Query(description="The signed template-download token")],
) -> UUID:
    """The tenant claim of a valid token for this template."""
    payload = verify_document_template_download_token(token)
    if not payload:
        raise AuthenticationException("Invalid or expired token")
    if str(id) != payload.get("template_id"):
        raise UnauthorizedException("Token not valid for this template")
    try:
        return UUID(str(payload["tenant_id"]))
    except (KeyError, ValueError):
        raise AuthenticationException("Invalid token claims") from None


@download_router.get(
    "/{id}/original/download/",
    response_class=Response,
    response_model=None,
    summary="Download a document template through a signed link",
    responses=responses.get_responses([401, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.SIGNED_URL,
    authorization=Authorization.SIGNED_URL,
    reason="A signed token grants access only to its template and tenant.",
)
async def download_document_template_signed(
    id: UUID,
    tenant_id: Annotated[UUID, Depends(authorize_document_template_token)],
    container: Annotated[Container, Depends(get_container(with_transaction=False))],
) -> Response:
    session = cast(AsyncSession, container.session())
    async with session.begin():
        found = await DocumentTemplateRepository(session).get_content(tenant_id, id)
    if found is None:
        raise NotFoundException("Document template not found")
    template, content = found
    etag = f'"{template.sha256}"'
    return Response(
        content=content,
        media_type=DOCX_MIME_TYPE,
        headers={
            "Content-Disposition": content_disposition_header(
                "attachment", template.filename
            ),
            "ETag": etag,
            "Cache-Control": "private, no-cache",
        },
    )
