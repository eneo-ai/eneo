from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import UploadFile

from intric.files.file_models import File
from intric.files.file_repo import FileRepository
from intric.files.file_service import FileService
from intric.flows.domain.flow import FlowTemplateAsset
from intric.flows.enums import FlowTemplateAssetStatus
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.flow_template_asset_repo import FlowTemplateAssetRepository
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
from intric.flows.runtime.docx_template_runtime import (
    extract_docx_template_text_preview,
    inspect_docx_template_bytes,
)
from intric.main.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from intric.users.user import UserInDB


class FlowTemplateAssetService:
    def __init__(
        self,
        *,
        user: UserInDB,
        flow_repo: FlowRepository,
        file_repo: FileRepository,
        file_service: FileService,
        template_asset_repo: FlowTemplateAssetRepository,
        flow_version_repo: FlowVersionRepository,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.file_repo = file_repo
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
        document_file = await self.file_service.document_from_upload(upload_file)
        if document_file.blob is None:
            raise BadRequestException(
                "The uploaded DOCX template could not be saved with file content.",
                code=FlowApiErrorCode.TEMPLATE_MISSING_CONTENT.value,
            )
        placeholders = inspect_docx_template_bytes(
            document_file.blob,
            filename=document_file.name,
        )
        saved_file = await self.file_service.save_file_content(document_file)
        asset = await self.template_asset_repo.create(
            flow_id=persisted_flow_id,
            space_id=flow.space_id,
            tenant_id=self.user.tenant_id,
            file_id=saved_file.id,
            name=saved_file.name,
            checksum=saved_file.checksum,
            mimetype=saved_file.mimetype,
            placeholders=_unique_placeholder_names(placeholders),
            created_by_user_id=self.user.id,
            updated_by_user_id=self.user.id,
            status=FlowTemplateAssetStatus.READY.value,
        )
        return asset

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
        file = await self.file_repo.get_by_id(file_id=asset.file_id)
        if file.tenant_id != self.user.tenant_id:
            raise NotFoundException("Flow template asset file not found.")
        return asset, file


def _unique_placeholder_names(placeholders: list[dict[str, str | None]]) -> list[str]:
    names: list[str] = []
    for item in placeholders:
        name = str(item.get("name", "")).strip()
        if name and name not in names:
            names.append(name)
    return names
