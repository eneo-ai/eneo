from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import UploadFile

from intric.files.file_models import File
from intric.files.file_service import FileService
from intric.files.file_repo import FileRepository
from intric.flows.flow import FlowTemplateAsset, FlowTemplateAssetStatus
from intric.flows.flow_repo import FlowRepository
from intric.flows.flow_template_asset_repo import FlowTemplateAssetRepository
from intric.flows.runtime.docx_template_runtime import (
    extract_docx_template_text_preview,
    inspect_docx_template_bytes,
)
from intric.main.exceptions import BadRequestException, NotFoundException
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
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.file_repo = file_repo
        self.file_service = file_service
        self.template_asset_repo = template_asset_repo

    async def list_assets(
        self,
        *,
        flow_id: UUID,
        can_edit: bool,
        can_download: bool,
    ) -> list[FlowTemplateAsset]:
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        assets = await self.template_asset_repo.list_for_flow(
            flow_id=flow.id,
            tenant_id=self.user.tenant_id,
        )
        return [
            self._with_capabilities(
                asset,
                can_edit=can_edit,
                can_download=can_download,
            )
            for asset in assets
        ]

    async def upload_asset(
        self,
        *,
        flow_id: UUID,
        upload_file: UploadFile,
    ) -> FlowTemplateAsset:
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        saved_file = await self.file_service.save_docx_template(upload_file)
        placeholders = inspect_docx_template_bytes(
            saved_file.blob or b"",
            filename=saved_file.name,
        )
        asset = await self.template_asset_repo.create(
            flow_id=flow.id,
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
        return self._with_capabilities(asset, can_edit=True, can_download=True)

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
                code="flow_template_missing_content",
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

    async def get_asset_with_file(
        self,
        *,
        flow_id: UUID,
        asset_id: UUID,
    ) -> tuple[FlowTemplateAsset, File]:
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        asset = await self.template_asset_repo.get(asset_id=asset_id, tenant_id=self.user.tenant_id)
        if asset.flow_id != flow.id:
            raise NotFoundException("Flow template asset not found.")
        file = await self.file_repo.get_by_id(file_id=asset.file_id)
        if file.tenant_id != self.user.tenant_id:
            raise NotFoundException("Flow template asset file not found.")
        return asset, file

    async def get_published_template_file(
        self,
        *,
        tenant_id: UUID,
        asset_id: UUID,
        expected_checksum: str | None,
    ) -> tuple[FlowTemplateAsset, File]:
        asset = await self.template_asset_repo.get(asset_id=asset_id, tenant_id=tenant_id)
        file = await self.file_repo.get_by_id(file_id=asset.file_id)
        if file.tenant_id != tenant_id:
            raise NotFoundException("Flow template asset file not found.")
        if file.blob is None:
            raise BadRequestException(
                "The published DOCX template could not be read because the saved file content is missing.",
                code="flow_template_missing_content",
            )
        if expected_checksum is not None and file.checksum != expected_checksum:
            raise BadRequestException(
                "The published DOCX template checksum no longer matches the selected asset.",
                code="flow_template_not_accessible",
            )
        return asset, file

    @staticmethod
    def _with_capabilities(
        asset: FlowTemplateAsset,
        *,
        can_edit: bool,
        can_download: bool,
    ) -> FlowTemplateAsset:
        return asset.model_copy(
            update={
                "can_edit": can_edit,
                "can_download": can_download,
                "can_select": can_edit,
                "can_inspect": True,
                "status": (
                    FlowTemplateAssetStatus.READ_ONLY
                    if not can_edit and asset.status == FlowTemplateAssetStatus.READY
                    else asset.status
                ),
            },
            deep=True,
        )


def _unique_placeholder_names(placeholders: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in placeholders:
        name = str(item.get("name", "")).strip()
        if name and name not in names:
            names.append(name)
    return names
