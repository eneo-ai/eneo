from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel

from eneo.flows.api.flow_template_asset_models import (
    FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE,
    FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE,
    FlowTemplateAssetPublic,
    FlowTemplateInspectionPublic,
    FlowTemplatePlaceholderPublic,
)
from eneo.flows.domain.flow import FlowTemplateAsset


def _assert_example_keys_belong_to_model(
    *, model: type[BaseModel], example: dict[str, object]
) -> None:
    assert set(example) <= set(model.model_fields)


def test_flow_template_inspection_example_matches_public_model() -> None:
    _assert_example_keys_belong_to_model(
        model=FlowTemplateInspectionPublic,
        example=FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE,
    )
    for placeholder in FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE["placeholders"]:
        _assert_example_keys_belong_to_model(
            model=FlowTemplatePlaceholderPublic,
            example=placeholder,
        )

    parsed = FlowTemplateInspectionPublic.model_validate(
        FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE
    )

    assert parsed.file_name == FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE["file_name"]


def test_flow_template_asset_example_matches_public_model() -> None:
    _assert_example_keys_belong_to_model(
        model=FlowTemplateAssetPublic,
        example=FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE,
    )

    parsed = FlowTemplateAssetPublic.model_validate(FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE)

    assert str(parsed.file_id) == FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE["file_id"]


def test_flow_template_asset_domain_does_not_carry_public_capabilities() -> None:
    assert {
        "can_edit",
        "can_download",
        "can_select",
        "can_inspect",
    }.isdisjoint(FlowTemplateAsset.model_fields)


def test_flow_template_asset_public_projects_editor_capabilities() -> None:
    now = datetime.now(timezone.utc)
    asset = FlowTemplateAsset(
        id=uuid4(),
        flow_id=uuid4(),
        space_id=uuid4(),
        tenant_id=uuid4(),
        file_id=uuid4(),
        name="template.docx",
        checksum="checksum",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        placeholders=["summary"],
        status="ready",
        last_updated_by_name="User",
        created_at=now,
        updated_at=now,
    )

    public = FlowTemplateAssetPublic.for_editor(asset)

    assert public.id == asset.id
    assert public.file_id == asset.file_id
    assert public.status == asset.status
    assert public.can_edit is True
    assert public.can_download is True
    assert public.can_select is True
    assert public.can_inspect is True
