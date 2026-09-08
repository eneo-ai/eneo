from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.config import JsonDict

from eneo.flows.domain.flow import FlowTemplateAsset
from eneo.flows.enums import FlowTemplateAssetStatus

FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE: JsonDict = {
    "asset_id": "00000000-0000-0000-0000-000000000601",
    "file_id": "00000000-0000-0000-0000-000000000602",
    "file_name": "ibic-template.docx",
    "placeholders": [
        {
            "name": "sammanfattning",
            "label": "Sammanfattning",
            "kind": "rich",
            "hint": "Sammanfatta ärendet i två till fyra stycken.",
            "location": "body",
        },
        {
            "name": "handlaggare",
            "label": "Handläggare",
            "kind": "text",
            "hint": "Namn och titel",
            "location": "body",
        },
    ],
    "extracted_text_preview": "IBIC plan template with content controls.",
    "status": "ready",
}

FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE: JsonDict = {
    "id": "00000000-0000-0000-0000-000000000601",
    "flow_id": "00000000-0000-0000-0000-000000000001",
    "file_id": "00000000-0000-0000-0000-000000000602",
    "name": "ibic-template.docx",
    "checksum": "sha256:abc123",
    "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "placeholders": ["sammanfattning", "handlaggare"],
    "status": "ready",
    "last_updated_by_name": "Case Worker Admin",
    "can_edit": True,
    "can_download": True,
    "can_select": True,
    "can_inspect": True,
    "created_at": "2026-03-17T09:40:00Z",
    "updated_at": "2026-03-17T09:45:00Z",
}


class FlowTemplatePlaceholderPublic(BaseModel):
    """One fill target of a DOCX template: a Word content control.

    ``name`` is the control's tag (what bindings address), ``label`` its
    title, ``kind`` whether it takes a whole section (``rich``: paragraphs,
    lists, tables) or one line of text (``text``), and ``hint`` the
    placeholder text the author wrote, which the AI Builder reads as the
    instruction for that target.
    """

    name: str
    label: str
    kind: Literal["rich", "text"]
    hint: str | None = None
    location: str


class FlowTemplateInspectionPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE}
    )

    asset_id: UUID | None = None
    file_id: UUID
    file_name: str
    placeholders: list[FlowTemplatePlaceholderPublic]
    extracted_text_preview: str | None = None
    status: FlowTemplateAssetStatus | None = None


class FlowTemplateAssetPublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE},
    )

    id: UUID
    flow_id: UUID
    file_id: UUID
    name: str
    checksum: str
    mimetype: str | None = None
    placeholders: list[str] = Field(default_factory=list)
    status: FlowTemplateAssetStatus
    last_updated_by_name: str | None = None
    can_edit: bool = False
    can_download: bool = False
    can_select: bool = False
    can_inspect: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def for_editor(cls, asset: FlowTemplateAsset) -> Self:
        return cls(
            id=asset.id,
            flow_id=asset.flow_id,
            file_id=asset.file_id,
            name=asset.name,
            checksum=asset.checksum,
            mimetype=asset.mimetype,
            placeholders=asset.placeholders,
            status=asset.status,
            last_updated_by_name=asset.last_updated_by_name,
            can_edit=True,
            can_download=True,
            can_select=True,
            can_inspect=True,
            created_at=asset.created_at,
            updated_at=asset.updated_at,
        )
