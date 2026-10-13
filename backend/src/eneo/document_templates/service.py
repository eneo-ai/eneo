"""The tenant's document template library, and which template a turn renders with."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eneo.authentication.signed_urls import build_signed_document_template_url
from eneo.document_templates import runtime_client
from eneo.document_templates.domain import (
    BUILTIN_REFERENCE,
    DocumentTemplate,
    DocumentTemplateChoice,
    DocumentTemplateReference,
    TemplateInspection,
)
from eneo.document_templates.repo import DocumentTemplateRepository
from eneo.document_templates.validation import (
    validate_template_archive,
    validate_template_filename,
)
from eneo.files.file_reference import file_reference_base_url
from eneo.main.config import get_settings
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.users.user import UserInDB

logger = get_logger(__name__)

_NOT_FOUND = "Document template not found"


def _inspection_columns(
    inspection: TemplateInspection | None,
) -> tuple[Any, list[dict[str, Any]], dict[str, Any], Any]:
    if inspection is None:
        return "unknown", [], {}, "unchecked"
    failed = [name for name, check in inspection.checks.items() if not check.get("ok")]
    # A template that cannot take a document at all is kept, but flagged.
    status = (
        "invalid"
        if "content_placeholder" in failed
        and not any(p.get("supported") for p in inspection.placeholders)
        else "ready"
    )
    return inspection.syntax, inspection.placeholders, inspection.checks, status


class DocumentTemplateService:
    """Administration of the library; the router checks the admin permission."""

    def __init__(self, user: "UserInDB", repo: DocumentTemplateRepository):
        self.user = user
        self.repo = repo

    async def list(self) -> list[DocumentTemplate]:
        return await self.repo.list(self.user.tenant_id)

    async def get(self, template_id: UUID) -> DocumentTemplate:
        template = await self.repo.get(self.user.tenant_id, template_id)
        if template is None:
            raise NotFoundException(_NOT_FOUND)
        return template

    async def content(self, template_id: UUID) -> tuple[DocumentTemplate, bytes]:
        found = await self.repo.get_content(self.user.tenant_id, template_id)
        if found is None:
            raise NotFoundException(_NOT_FOUND)
        return found

    async def _check(
        self, filename: str, content: bytes
    ) -> tuple[str, TemplateInspection | None]:
        name = validate_template_filename(filename)
        validate_template_archive(content)
        try:
            inspection = await runtime_client.inspect_template(content)
        except runtime_client.RuntimeUnavailable:
            # The library works without the runtime; the checks show "not checked".
            inspection = None
        return name, inspection

    async def upload(
        self, *, name: str, filename: str, content: bytes, is_default: bool
    ) -> DocumentTemplate:
        name = name.strip()
        if not name or len(name) > 120:
            raise BadRequestException(
                "Give the template a name of at most 120 characters."
            )
        if await self.repo.name_taken(self.user.tenant_id, name, None):
            raise BadRequestException(
                "A document template with that name already exists."
            )
        stored_name, inspection = await self._check(filename, content)
        syntax, placeholders, checks, status = _inspection_columns(inspection)
        return await self.repo.create(
            tenant_id=self.user.tenant_id,
            name=name,
            filename=stored_name,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            syntax=syntax,
            placeholders=placeholders,
            checks=checks,
            status=status,
            is_default=is_default,
            user_id=self.user.id,
        )

    async def replace_content(
        self, template_id: UUID, *, filename: str, content: bytes
    ) -> DocumentTemplate:
        await self.get(template_id)
        stored_name, inspection = await self._check(filename, content)
        updated = await self.repo.update(
            self.user.tenant_id,
            template_id,
            user_id=self.user.id,
            content=(stored_name, content, hashlib.sha256(content).hexdigest()),
            inspection=_inspection_columns(inspection),
        )
        assert updated is not None
        return updated

    async def update(
        self, template_id: UUID, *, name: str | None, is_default: bool | None
    ) -> DocumentTemplate:
        await self.get(template_id)
        if name is not None:
            name = name.strip()
            if not name or len(name) > 120:
                raise BadRequestException(
                    "Give the template a name of at most 120 characters."
                )
            if await self.repo.name_taken(self.user.tenant_id, name, template_id):
                raise BadRequestException(
                    "A document template with that name already exists."
                )
        updated = await self.repo.update(
            self.user.tenant_id,
            template_id,
            user_id=self.user.id,
            name=name,
            is_default=is_default,
        )
        assert updated is not None
        return updated

    async def delete(self, template_id: UUID) -> DocumentTemplate:
        deleted = await self.repo.soft_delete(
            self.user.tenant_id, template_id, user_id=self.user.id
        )
        if deleted is None:
            raise NotFoundException(_NOT_FOUND)
        return deleted

    async def builtin(self, language: str) -> bytes:
        try:
            return await runtime_client.builtin_template(language)
        except runtime_client.RuntimeUnavailable:
            raise BadRequestException(
                "The tool runtime is not available, so the built-in template cannot be fetched."
            ) from None

    async def validate_choice(self, choice: DocumentTemplateChoice) -> None:
        """An assistant may select only a live template of its tenant."""
        if choice.mode != "selected":
            return
        assert choice.template_id is not None
        if await self.repo.get(self.user.tenant_id, choice.template_id) is None:
            raise BadRequestException("The selected document template does not exist.")


def document_template_resolver(
    session: "AsyncSession", tenant_id: UUID
) -> "Callable[[UUID], Awaitable[DocumentTemplateReference]]":
    """A resolver bound to one session and tenant, for the document export."""

    async def resolve(assistant_id: UUID) -> DocumentTemplateReference:
        return await resolve_document_template(
            session, tenant_id=tenant_id, assistant_id=assistant_id
        )

    return resolve


async def resolve_document_template(
    session: "AsyncSession",
    *,
    tenant_id: UUID,
    assistant_id: UUID | None,
    choice: DocumentTemplateChoice | None = None,
) -> DocumentTemplateReference:
    """The template an assistant's documents render with, as a signed reference.

    The assistant's choice (given, or read from its capability row) wins; the
    tenant default follows; Eneo's built-in template is what remains. A
    selected template that no longer exists falls back like a default would.
    """
    repo = DocumentTemplateRepository(session)
    if choice is None:
        choice = (
            await repo.choice_for_assistant(assistant_id)
            if assistant_id is not None
            else DocumentTemplateChoice()
        )
    if choice.mode == "builtin":
        return BUILTIN_REFERENCE
    template = None
    source: str = "tenant"
    if choice.mode == "selected" and choice.template_id is not None:
        template = await repo.get(tenant_id, choice.template_id)
        source = "assistant"
    if template is None:
        template = await repo.get_default(tenant_id)
        source = "tenant"
    if template is None:
        return BUILTIN_REFERENCE
    base_url = file_reference_base_url()
    if not base_url:
        logger.warning(
            "Document template '%s' cannot be referenced: no FILE_REFERENCE_BASE_URL "
            "or PUBLIC_ORIGIN is configured; the built-in template applies",
            template.name,
        )
        return BUILTIN_REFERENCE
    settings = get_settings()
    return DocumentTemplateReference(
        name=template.name,
        source="assistant" if source == "assistant" else "tenant",
        template_id=template.id,
        url=build_signed_document_template_url(
            template.id,
            base_url=base_url,
            expires_in=settings.file_reference_url_expiry_seconds,
            tenant_id=tenant_id,
        ),
        filename=template.filename,
    )
