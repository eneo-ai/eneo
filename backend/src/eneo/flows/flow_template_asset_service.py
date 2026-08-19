from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import UploadFile

from eneo.files.file_content_loader import FileContentLoader
from eneo.files.file_models import File, FileContentVariant
from eneo.files.file_repo import FileRepository
from eneo.files.file_service import FileService
from eneo.flows.domain.flow import FlowTemplateAsset
from eneo.flows.enums import FlowTemplateAssetStatus
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_template_asset_repo import FlowTemplateAssetRepository
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.runtime.docx_template_runtime import (
    docx_template_placeholder_names,
    extract_docx_template_text_preview,
    inspect_docx_template_bytes,
)
from eneo.main.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from eneo.object_content.content import (
    ObjectContentStateError,
    ObjectContentUnavailableError,
)
from eneo.users.user import UserInDB


class AttachedTemplateFileUnavailableError(Exception):
    """The selected Builder File disappeared before its retention fence."""


class FlowTemplateAssetService:
    def __init__(
        self,
        *,
        user: UserInDB,
        flow_repo: FlowRepository,
        file_repo: FileRepository,
        file_content_loader: FileContentLoader,
        file_service: FileService,
        template_asset_repo: FlowTemplateAssetRepository,
        flow_version_repo: FlowVersionRepository,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.file_repo = file_repo
        self.file_content_loader = file_content_loader
        self.file_service = file_service
        self.template_asset_repo = template_asset_repo
        self.flow_version_repo = flow_version_repo

    async def list_assets(
        self,
        *,
        flow_id: UUID,
    ) -> list[FlowTemplateAsset]:
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        persisted_flow_id = flow.require_persisted_id()
        return await self.template_asset_repo.list_for_flow(
            flow_id=persisted_flow_id,
            tenant_id=self.user.tenant_id,
        )

    async def upload_asset(
        self,
        *,
        flow_id: UUID,
        upload_file: UploadFile,
    ) -> FlowTemplateAsset:
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        persisted_flow_id = flow.require_persisted_id()
        async with self.file_service.prepare_document_upload(upload_file) as prepared:
            original = next(
                content
                for content in prepared.contents
                if content.variant is FileContentVariant.ORIGINAL
            )
            document_bytes = b"".join([chunk async for chunk in original.chunks])
            placeholders = docx_template_placeholder_names(
                document_bytes,
                filename=prepared.name,
            )
            saved_file = await self.file_service.save_prepared_file(prepared)
        asset = await self.template_asset_repo.create(
            flow_id=persisted_flow_id,
            space_id=flow.space_id,
            tenant_id=self.user.tenant_id,
            file_id=saved_file.id,
            name=saved_file.name,
            checksum=saved_file.checksum,
            mimetype=saved_file.mimetype,
            placeholders=list(placeholders),
            created_by_user_id=self.user.id,
            updated_by_user_id=self.user.id,
            status=FlowTemplateAssetStatus.READY.value,
        )
        return asset

    async def create_from_existing_attached_file(
        self,
        *,
        flow_id: UUID,
        file_id: UUID,
    ) -> FlowTemplateAsset:
        """Promote an authorized existing File into a Flow template asset.

        Builder attachments already own a durable File row. Reusing that row
        keeps the asset foreign key as the retention boundary and avoids a
        second copy whose lifecycle could drift from the selected attachment.
        Session-membership validation remains the Builder lifecycle's concern.
        """

        flow = await self.flow_repo.get(
            flow_id=flow_id,
            tenant_id=self.user.tenant_id,
        )
        persisted_flow_id = flow.require_persisted_id()
        try:
            file = await self.file_service.get_owned_file_for_key_share(
                file_id,
                include_text_original_bytes=True,
            )
        except NotFoundException as exc:
            raise AttachedTemplateFileUnavailableError from exc
        if file.blob is None:
            raise BadRequestException(
                "The selected DOCX template could not be read because the file content is missing.",
                code=FlowApiErrorCode.TEMPLATE_MISSING_CONTENT.value,
            )
        placeholders = docx_template_placeholder_names(file.blob, filename=file.name)
        reusable = await self.template_asset_repo.find_ready_for_file(
            flow_id=persisted_flow_id,
            tenant_id=self.user.tenant_id,
            file_id=file.id,
            checksum=file.checksum,
        )
        if reusable is not None:
            return reusable
        return await self.template_asset_repo.create(
            flow_id=persisted_flow_id,
            space_id=flow.space_id,
            tenant_id=self.user.tenant_id,
            file_id=file.id,
            name=file.name,
            checksum=file.checksum,
            mimetype=file.mimetype,
            placeholders=list(placeholders),
            created_by_user_id=self.user.id,
            updated_by_user_id=self.user.id,
            status=FlowTemplateAssetStatus.READY.value,
        )

    async def inspect_asset(
        self,
        *,
        flow_id: UUID,
        asset_id: UUID,
    ) -> dict[str, Any]:
        asset, file = await self.get_asset_with_file(flow_id=flow_id, asset_id=asset_id)
        if file.blob is None:
            raise BadRequestException(
                "The selected DOCX template could not be read because the file content is missing.",
                code=FlowApiErrorCode.TEMPLATE_MISSING_CONTENT.value,
            )
        return {
            "asset_id": asset.id,
            "file_id": file.id,
            "file_name": file.name,
            "template_name": asset.name,
            "placeholders": inspect_docx_template_bytes(file.blob, filename=file.name),
            "extracted_text_preview": extract_docx_template_text_preview(file.blob),
            "status": asset.status,
        }

    async def delete_asset(
        self,
        *,
        flow_id: UUID,
        asset_id: UUID,
    ) -> FlowTemplateAsset:
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        persisted_flow_id = flow.require_persisted_id()
        asset = await self.template_asset_repo.get(
            asset_id=asset_id,
            tenant_id=self.user.tenant_id,
        )
        if asset.flow_id != persisted_flow_id:
            raise NotFoundException("Flow template asset not found.")

        if await self.flow_version_repo.has_template_asset_reference(
            flow_id=persisted_flow_id,
            tenant_id=self.user.tenant_id,
            template_asset_id=asset.id,
            template_file_id=asset.file_id,
        ):
            raise ConflictException(
                "The DOCX template is used by a published flow definition and cannot be deleted.",
                code=FlowApiErrorCode.TEMPLATE_IN_USE.value,
                context={
                    "flow_id": str(persisted_flow_id),
                    "template_asset_id": str(asset.id),
                    "template_file_id": str(asset.file_id),
                },
            )

        await self.template_asset_repo.soft_delete(
            asset_id=asset.id,
            tenant_id=self.user.tenant_id,
            updated_by_user_id=self.user.id,
        )
        return asset

    async def get_asset_with_file(
        self,
        *,
        flow_id: UUID,
        asset_id: UUID,
    ) -> tuple[FlowTemplateAsset, File]:
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        persisted_flow_id = flow.require_persisted_id()
        asset = await self.template_asset_repo.get(
            asset_id=asset_id, tenant_id=self.user.tenant_id
        )
        if asset.flow_id != persisted_flow_id:
            raise NotFoundException("Flow template asset not found.")
        try:
            metadata = await self.file_repo.get_by_id(
                file_id=asset.file_id,
                tenant_id=self.user.tenant_id,
            )
            file = (
                await self.file_content_loader.load(
                    [metadata],
                    include_text_original_bytes=True,
                )
            )[metadata.id]
        except (
            NotFoundException,
            ObjectContentStateError,
            ObjectContentUnavailableError,
        ) as exc:
            raise BadRequestException(
                "The selected DOCX template could not be read because the file content is missing. Upload the template again or choose another DOCX file.",
                code=FlowApiErrorCode.TEMPLATE_MISSING_CONTENT.value,
            ) from exc
        return asset, file
